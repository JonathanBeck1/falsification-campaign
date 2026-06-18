"""Research-only EOD iron-condor backtester."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from statistics import mean
from uuid import uuid4

from trader.options.iron_condor import (
    IronCondor,
    IronCondorConfig,
    mark_condor_close_debit,
    quote_key,
    select_iron_condor,
)
from trader.options.models import OptionQuote


@dataclass(frozen=True)
class IronCondorBacktestConfig:
    ticker: str = "SPY"
    start: date | None = None
    end: date | None = None
    selector: IronCondorConfig = field(default_factory=IronCondorConfig)
    profit_target_pct: float = 0.50
    stop_loss_credit_multiple: float = 2.0
    exit_dte: int = 21
    max_concurrent_trades: int = 1
    contract_multiplier: int = 100
    # Friction defaults are neutral (0) at the library level so programmatic
    # callers and unit tests see a frictionless baseline; the CLI sets realistic
    # research defaults (commission 0.65, slippage 0.02) -- mirroring intraday.
    commission_per_contract: float = 0.0
    # Option-price points lost to crossing the spread on each of the 4 legs, at
    # both entry and exit.
    slippage_per_contract: float = 0.0


@dataclass(frozen=True)
class IronCondorDailyMark:
    trade_id: str
    mark_date: date
    exit_debit: float
    pnl: float
    dte: int


@dataclass(frozen=True)
class IronCondorTrade:
    trade_id: str
    ticker: str
    entry_date: date
    exit_date: date | None
    expiration: date
    short_put_strike: float
    long_put_strike: float
    short_call_strike: float
    long_call_strike: float
    entry_credit: float
    exit_debit: float | None
    max_risk: float
    pnl: float | None
    exit_reason: str
    holding_days: int
    dte_entry: int
    dte_exit: int | None


@dataclass(frozen=True)
class IronCondorBacktestSummary:
    opened_count: int
    closed_count: int
    unclosed_count: int
    trade_count: int
    win_rate: float
    total_pnl: float
    average_pnl: float
    average_holding_days: float
    max_drawdown: float
    profit_factor: float | None


@dataclass(frozen=True)
class IronCondorBacktestResult:
    run_id: str
    config: IronCondorBacktestConfig
    trades: list[IronCondorTrade]
    marks: list[IronCondorDailyMark]
    summary: IronCondorBacktestSummary


@dataclass(frozen=True)
class _OpenTrade:
    trade_id: str
    condor: IronCondor


def run_iron_condor_backtest(
    quotes: list[OptionQuote],
    config: IronCondorBacktestConfig | None = None,
    *,
    underlying_closes: Mapping[date, float] | None = None,
) -> IronCondorBacktestResult:
    """Run a single-position EOD replay over normalized option quotes.

    ``underlying_closes`` (trade_date -> underlying close) enables the intrinsic
    floor on quote-based marks and intrinsic settlement at expiration when leg
    quotes are missing -- the same semantics as the intraday engine. Without it,
    marks are still wing-capped but breaches hidden behind stale quotes cannot
    be floored to intrinsic.
    """

    config = config or IronCondorBacktestConfig()
    underlying_closes = underlying_closes or {}
    by_date: dict[date, list[OptionQuote]] = defaultdict(list)
    for quote in quotes:
        if quote.ticker != config.ticker.upper():
            continue
        if config.start is not None and quote.trade_date < config.start:
            continue
        if config.end is not None and quote.trade_date > config.end:
            continue
        by_date[quote.trade_date].append(quote)

    open_trades: list[_OpenTrade] = []
    closed_trades: list[IronCondorTrade] = []
    marks: list[IronCondorDailyMark] = []

    replay_dates = sorted(by_date)
    last_replay_date = replay_dates[-1] if replay_dates else None
    for trade_date in replay_dates:
        chain = by_date[trade_date]
        remaining_open: list[_OpenTrade] = []
        for open_trade in open_trades:
            mark = _mark_open_trade(
                open_trade,
                chain,
                trade_date=trade_date,
                multiplier=config.contract_multiplier,
                underlying_price=underlying_closes.get(trade_date),
                slippage_per_contract=config.slippage_per_contract,
            )
            if mark is None:
                remaining_open.append(open_trade)
                continue
            marks.append(mark)
            exit_reason = _exit_reason(
                open_trade.condor,
                mark,
                profit_target_pct=config.profit_target_pct,
                stop_loss_credit_multiple=config.stop_loss_credit_multiple,
                exit_dte=config.exit_dte,
            )
            if exit_reason is None:
                remaining_open.append(open_trade)
                continue
            closed_trades.append(_close_trade(open_trade, mark, exit_reason=exit_reason, friction=_close_friction(config)))
        open_trades = remaining_open

        if trade_date == last_replay_date:
            continue
        if len(open_trades) >= config.max_concurrent_trades:
            continue
        condor = select_iron_condor(chain, config.selector)
        if condor is None:
            continue
        open_trades.append(_OpenTrade(trade_id=str(uuid4()), condor=condor))

    if by_date:
        last_date = max(by_date)
        last_chain = by_date[last_date]
        for open_trade in open_trades:
            mark = _mark_open_trade(
                open_trade,
                last_chain,
                trade_date=last_date,
                multiplier=config.contract_multiplier,
                underlying_price=underlying_closes.get(last_date),
                slippage_per_contract=config.slippage_per_contract,
            )
            if mark is None:
                closed_trades.append(_unclosed_trade(open_trade))
            else:
                if not any(existing.trade_id == mark.trade_id and existing.mark_date == mark.mark_date for existing in marks):
                    marks.append(mark)
                closed_trades.append(_close_trade(open_trade, mark, exit_reason="final_mark", friction=_close_friction(config)))

    return IronCondorBacktestResult(
        run_id=str(uuid4()),
        config=config,
        trades=closed_trades,
        marks=marks,
        summary=_summarize(closed_trades),
    )


def _mark_open_trade(
    open_trade: _OpenTrade,
    chain: list[OptionQuote],
    *,
    trade_date: date,
    multiplier: int,
    underlying_price: float | None = None,
    slippage_per_contract: float = 0.0,
) -> IronCondorDailyMark | None:
    by_key = {quote_key(quote): quote for quote in chain}
    condor = open_trade.condor
    short_put = by_key.get(quote_key(condor.short_put))
    long_put = by_key.get(quote_key(condor.long_put))
    short_call = by_key.get(quote_key(condor.short_call))
    long_call = by_key.get(quote_key(condor.long_call))
    dte = (condor.expiration - trade_date).days
    # Shared marking core (audit A2/B3): bounded debit (intrinsic floor / wing
    # cap), intrinsic settlement from the underlying only at expiration, exit
    # slippage on 4 legs. Mid-life missing quotes -> None (position stays open).
    debit = mark_condor_close_debit(
        condor,
        short_put,
        long_put,
        short_call,
        long_call,
        underlying_price,
        dte=dte,
        slippage_per_contract=slippage_per_contract,
    )
    if debit is None:
        return None
    pnl = round((condor.entry_credit - debit) * multiplier, 2)
    return IronCondorDailyMark(
        trade_id=open_trade.trade_id,
        mark_date=trade_date,
        exit_debit=debit,
        pnl=pnl,
        dte=dte,
    )


def _exit_reason(
    condor: IronCondor,
    mark: IronCondorDailyMark,
    *,
    profit_target_pct: float,
    stop_loss_credit_multiple: float,
    exit_dte: int,
) -> str | None:
    # Expiration must be checked first: with exit_dte >= 0 the time_exit branch
    # would otherwise shadow it (the audit A2 "dead expiration-ordering branch").
    if mark.dte <= 0:
        return "expiration"
    if mark.exit_debit <= condor.entry_credit * (1.0 - profit_target_pct):
        return "profit_target"
    if mark.exit_debit >= condor.entry_credit * stop_loss_credit_multiple:
        return "stop_loss"
    if mark.dte <= exit_dte:
        return "time_exit"
    return None


def _close_friction(config: IronCondorBacktestConfig) -> float:
    """Per-trade friction deducted at close: round-trip commission plus the
    entry-side slippage. Exit-side slippage is already baked into the mark debit,
    so only the entry leg of slippage is added here (mirrors the intraday engine)."""

    commission = config.commission_per_contract * 4 * 2
    entry_slippage = config.slippage_per_contract * 4 * config.contract_multiplier
    return round(commission + entry_slippage, 2)


def _close_trade(open_trade: _OpenTrade, mark: IronCondorDailyMark, *, exit_reason: str, friction: float = 0.0) -> IronCondorTrade:
    condor = open_trade.condor
    return IronCondorTrade(
        trade_id=open_trade.trade_id,
        ticker=condor.ticker,
        entry_date=condor.trade_date,
        exit_date=mark.mark_date,
        expiration=condor.expiration,
        short_put_strike=condor.short_put.strike,
        long_put_strike=condor.long_put.strike,
        short_call_strike=condor.short_call.strike,
        long_call_strike=condor.long_call.strike,
        entry_credit=condor.entry_credit,
        exit_debit=mark.exit_debit,
        max_risk=condor.max_risk,
        pnl=round(mark.pnl - friction, 2),
        exit_reason=exit_reason,
        holding_days=(mark.mark_date - condor.trade_date).days,
        dte_entry=condor.dte,
        dte_exit=mark.dte,
    )


def _unclosed_trade(open_trade: _OpenTrade) -> IronCondorTrade:
    condor = open_trade.condor
    return IronCondorTrade(
        trade_id=open_trade.trade_id,
        ticker=condor.ticker,
        entry_date=condor.trade_date,
        exit_date=None,
        expiration=condor.expiration,
        short_put_strike=condor.short_put.strike,
        long_put_strike=condor.long_put.strike,
        short_call_strike=condor.short_call.strike,
        long_call_strike=condor.long_call.strike,
        entry_credit=condor.entry_credit,
        exit_debit=None,
        max_risk=condor.max_risk,
        pnl=None,
        exit_reason="unclosed_missing_mark",
        holding_days=0,
        dte_entry=condor.dte,
        dte_exit=None,
    )


def _summarize(trades: list[IronCondorTrade]) -> IronCondorBacktestSummary:
    closed = [trade for trade in trades if trade.pnl is not None]
    unclosed = [trade for trade in trades if trade.pnl is None]
    pnls = [float(trade.pnl) for trade in closed]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    total_pnl = round(sum(pnls), 2)
    return IronCondorBacktestSummary(
        opened_count=len(trades),
        closed_count=len(closed),
        unclosed_count=len(unclosed),
        trade_count=len(closed),
        win_rate=(len(wins) / len(closed)) if closed else 0.0,
        total_pnl=total_pnl,
        average_pnl=round(mean(pnls), 2) if pnls else 0.0,
        average_holding_days=round(mean([trade.holding_days for trade in closed]), 2) if closed else 0.0,
        max_drawdown=round(_max_drawdown(pnls), 2),
        profit_factor=(round(sum(wins) / abs(sum(losses)), 4) if losses else None),
    )


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return abs(max_dd)
