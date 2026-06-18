"""Cash-secured short-put intraday backtester (research-only).

A second strategy built on the same memory-safe foundations as the intraday iron
condor: it consumes a :class:`~trader.options.sources.QuoteSource` (or a raw list
/ replay tape) and processes **one trade-date at a time**, never materializing
more than a single day of quote bars.

Strategy, in plain terms:

- **Entry** (once per day, at/after ``entry_time``): sell one cash-secured put.
  In ``premium`` mode pick the put whose bid is closest to ``target_short_bid``;
  in ``delta`` mode estimate Black-Scholes delta from the quote mid and pick the
  put whose |delta| is closest to ``target_delta`` (within ``max_delta_deviation``).
  Only puts with ``min_dte <= dte <= max_dte``, an executable quote, and an
  acceptable spread are eligible. Credit = the put's bid.
- **Mark / exit**: each minute we value the position at the cost to buy the put
  back (its ask). Exit on profit target (debit <= credit*(1-pt)), stop
  (debit >= credit*stop_multiple), time exit (dte <= exit_dte), or expiration
  (dte <= 0). Any position still open at the last observed bar is closed at the
  final mark.
- **Cash-secured risk** = (strike - credit) * multiplier.

This is premium/credit based, like the iron condor path: ThetaData Value has
historical quotes but not historical Greeks, so delta selection is an estimate.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time
from statistics import mean
from typing import TYPE_CHECKING
from uuid import uuid4

from trader.options.intraday import (
    IntradayQuoteReplayData,
    SelectionMode,
    _coerce_day_stream,
    _group_day_by_ts,
    _spread_ok,
    _to_delta_estimated_option_quote,
    _to_option_quote,
)
from trader.options.iron_condor import quote_key
from trader.options.models import OptionQuote, OptionQuoteBar

if TYPE_CHECKING:
    from trader.options.sources import QuoteSource


@dataclass(frozen=True)
class ShortPutSelectorConfig:
    min_dte: int = 30
    max_dte: int = 45
    selection_mode: SelectionMode = "premium"
    target_short_bid: float = 1.0
    target_delta: float = 0.16
    max_delta_deviation: float = 0.08
    min_credit: float = 0.05
    max_bid_ask_spread_pct: float = 1.0
    risk_free_rate: float = 0.04
    dividend_yield: float = 0.0


@dataclass(frozen=True)
class ShortPutBacktestConfig:
    ticker: str = "SPY"
    start: date | None = None
    end: date | None = None
    selector: ShortPutSelectorConfig = field(default_factory=ShortPutSelectorConfig)
    entry_time: str = "09:45:00"
    profit_target_pct: float = 0.50
    stop_loss_credit_multiple: float = 2.0
    exit_dte: int = 21
    max_concurrent_trades: int = 1
    contract_multiplier: int = 100


@dataclass(frozen=True)
class ShortPutMark:
    trade_id: str
    mark_ts: datetime
    exit_debit: float
    pnl: float
    dte: int


@dataclass(frozen=True)
class ShortPutTrade:
    trade_id: str
    ticker: str
    entry_ts: datetime
    exit_ts: datetime | None
    expiration: date
    strike: float
    entry_credit: float
    exit_debit: float | None
    max_risk: float
    pnl: float | None
    exit_reason: str
    holding_minutes: int
    dte_entry: int
    dte_exit: int | None
    short_put_delta: float | None = None
    max_favorable_pnl: float | None = None
    max_adverse_pnl: float | None = None
    mark_count: int = 0


@dataclass(frozen=True)
class ShortPutBacktestSummary:
    opened_count: int
    closed_count: int
    unclosed_count: int
    trade_count: int
    win_rate: float
    total_pnl: float
    average_pnl: float
    average_holding_minutes: float
    max_drawdown: float
    profit_factor: float | None


@dataclass(frozen=True)
class ShortPutBacktestResult:
    run_id: str
    config: ShortPutBacktestConfig
    trades: list[ShortPutTrade]
    marks: list[ShortPutMark]
    summary: ShortPutBacktestSummary


@dataclass(frozen=True)
class _OpenShortPut:
    trade_id: str
    quote: OptionQuote
    entry_credit: float
    entry_ts: datetime


@dataclass
class _ShortPutState:
    open_trades: list[_OpenShortPut] = field(default_factory=list)
    closed_trades: list[ShortPutTrade] = field(default_factory=list)
    marks: list[ShortPutMark] = field(default_factory=list)
    marks_by_trade_id: dict[str, list[ShortPutMark]] = field(default_factory=dict)
    entered_dates: set[date] = field(default_factory=set)
    last_ts: datetime | None = None
    last_snapshot: list[OptionQuoteBar] | None = None


def run_short_put_backtest(
    quote_bars: list[OptionQuoteBar]
    | IntradayQuoteReplayData
    | QuoteSource
    | Iterable[tuple[date, list[OptionQuoteBar]]],
    config: ShortPutBacktestConfig | None = None,
) -> ShortPutBacktestResult:
    """Replay a single-position cash-secured short-put strategy, streaming by day."""

    config = config or ShortPutBacktestConfig()
    # Reuse the iron-condor day-stream coercion so list/replay/QuoteSource all
    # stream one trade-date at a time with identical filtering semantics.
    intraday_like = _ShortPutConfigShim(config)
    day_stream = _coerce_day_stream(quote_bars, intraday_like)  # type: ignore[arg-type]
    return _run_streaming(day_stream, config)


def _run_streaming(
    day_stream: Iterator[tuple[date, list[OptionQuoteBar]]],
    config: ShortPutBacktestConfig,
) -> ShortPutBacktestResult:
    entry_clock = time.fromisoformat(config.entry_time)
    shim = _ShortPutConfigShim(config)
    state = _ShortPutState()

    for _trade_date, day_bars in day_stream:
        by_ts = _group_day_by_ts(day_bars, shim)  # type: ignore[arg-type]
        for ts in sorted(by_ts):
            snapshot = by_ts[ts]
            _step_timestamp(ts, snapshot, config=config, entry_clock=entry_clock, state=state)
            state.last_ts = ts
            state.last_snapshot = snapshot
        del by_ts, day_bars

    _finalize_open_trades(config, state)

    return ShortPutBacktestResult(
        run_id=str(uuid4()),
        config=config,
        trades=state.closed_trades,
        marks=state.marks,
        summary=_summarize(state.closed_trades),
    )


def _step_timestamp(
    ts: datetime,
    snapshot: list[OptionQuoteBar],
    *,
    config: ShortPutBacktestConfig,
    entry_clock: time,
    state: _ShortPutState,
) -> None:
    remaining_open: list[_OpenShortPut] = []
    for open_trade in state.open_trades:
        mark = _mark_open_trade(open_trade, snapshot, ts=ts, multiplier=config.contract_multiplier)
        if mark is None:
            remaining_open.append(open_trade)
            continue
        state.marks.append(mark)
        state.marks_by_trade_id.setdefault(mark.trade_id, []).append(mark)
        exit_reason = _exit_reason(
            open_trade,
            mark,
            profit_target_pct=config.profit_target_pct,
            stop_loss_credit_multiple=config.stop_loss_credit_multiple,
            exit_dte=config.exit_dte,
        )
        if exit_reason is None:
            remaining_open.append(open_trade)
            continue
        state.closed_trades.append(
            _close_trade(open_trade, mark, exit_reason=exit_reason, trade_marks=state.marks_by_trade_id[mark.trade_id])
        )
    state.open_trades = remaining_open

    if ts.date() in state.entered_dates:
        return
    if ts.timetz().replace(tzinfo=None) < entry_clock:
        return
    if len(state.open_trades) >= config.max_concurrent_trades:
        return
    selection = select_short_put(snapshot, config.selector)
    if selection is None:
        state.entered_dates.add(ts.date())
        return
    quote, credit = selection
    state.open_trades.append(
        _OpenShortPut(trade_id=str(uuid4()), quote=quote, entry_credit=credit, entry_ts=ts)
    )
    state.entered_dates.add(ts.date())


def _finalize_open_trades(config: ShortPutBacktestConfig, state: _ShortPutState) -> None:
    if state.last_ts is None or state.last_snapshot is None:
        return
    for open_trade in state.open_trades:
        mark = _mark_open_trade(open_trade, state.last_snapshot, ts=state.last_ts, multiplier=config.contract_multiplier)
        if mark is None:
            state.closed_trades.append(_unclosed_trade(open_trade))
        else:
            if not any(
                existing.trade_id == mark.trade_id and existing.mark_ts == mark.mark_ts for existing in state.marks
            ):
                state.marks.append(mark)
                state.marks_by_trade_id.setdefault(mark.trade_id, []).append(mark)
            state.closed_trades.append(
                _close_trade(
                    open_trade,
                    mark,
                    exit_reason="final_mark",
                    trade_marks=state.marks_by_trade_id.get(mark.trade_id, [mark]),
                )
            )


def select_short_put(
    snapshot: list[OptionQuoteBar],
    config: ShortPutSelectorConfig | None = None,
) -> tuple[OptionQuote, float] | None:
    """Pick one short put + its credit from a single timestamp snapshot."""

    config = config or ShortPutSelectorConfig()
    if config.selection_mode == "delta":
        candidates = [
            quote
            for quote in (_to_delta_estimated_option_quote(bar, _selector_shim(config)) for bar in snapshot)
            if quote is not None
            and quote.call_put == "Put"
            and quote.has_executable_quote
            and quote.delta is not None
            and quote.delta < 0
            and config.min_dte <= quote.dte <= config.max_dte
            and abs(abs(float(quote.delta)) - config.target_delta) <= config.max_delta_deviation
        ]
        candidates.sort(key=lambda quote: (abs(abs(float(quote.delta)) - config.target_delta), -quote.strike))
    else:
        candidates = [
            _to_option_quote(bar)
            for bar in snapshot
            if bar.call_put == "Put"
            and bar.has_executable_quote
            and config.min_dte <= bar.dte <= config.max_dte
            and _spread_ok(bar, config.max_bid_ask_spread_pct)
        ]
        candidates.sort(key=lambda quote: (abs(float(quote.bid) - config.target_short_bid), -quote.strike))

    for quote in candidates:
        if quote.bid is None:
            continue
        credit = round(float(quote.bid), 4)
        if credit < config.min_credit:
            continue
        return quote, credit
    return None


def format_short_put_report(result: ShortPutBacktestResult) -> str:
    """Compact markdown report (mirrors the intraday iron-condor report shape)."""
    summary = result.summary
    lines = [
        f"# {result.config.ticker} Cash-Secured Short Put Backtest",
        "",
        "Research-only quote replay. Not live-trading evidence.",
        "",
        "## Parameters",
        f"- start: {result.config.start}",
        f"- end: {result.config.end}",
        f"- entry_time: {result.config.entry_time}",
        f"- selection_mode: {result.config.selector.selection_mode}",
        f"- target_short_bid: {result.config.selector.target_short_bid}",
        f"- target_delta: {result.config.selector.target_delta}",
        f"- profit_target_pct: {result.config.profit_target_pct}",
        f"- stop_loss_credit_multiple: {result.config.stop_loss_credit_multiple}",
        "",
        "## Summary",
        f"- opened_count: {summary.opened_count}",
        f"- closed_count: {summary.closed_count}",
        f"- unclosed_count: {summary.unclosed_count}",
        f"- trade_count: {summary.trade_count}",
        f"- win_rate: {round(summary.win_rate, 4)}",
        f"- total_pnl: {summary.total_pnl}",
        f"- average_pnl: {summary.average_pnl}",
        f"- average_holding_minutes: {summary.average_holding_minutes}",
        f"- max_drawdown: {summary.max_drawdown}",
        f"- profit_factor: {summary.profit_factor}",
        "",
        "## Trades",
        "| entry_ts | exit_ts | expiration | strike | delta | credit | debit | max_risk | pnl | reason |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for trade in result.trades:
        delta = f"{trade.short_put_delta:.3f}" if trade.short_put_delta is not None else ""
        debit = f"{trade.exit_debit:.2f}" if trade.exit_debit is not None else ""
        pnl = f"{trade.pnl:.2f}" if trade.pnl is not None else ""
        lines.append(
            f"| {trade.entry_ts.isoformat()} | "
            f"{trade.exit_ts.isoformat() if trade.exit_ts else ''} | "
            f"{trade.expiration.isoformat()} | {trade.strike:.2f} | {delta} | "
            f"{trade.entry_credit:.2f} | {debit} | {trade.max_risk:.2f} | {pnl} | {trade.exit_reason} |"
        )
    return "\n".join(lines) + "\n"


def _mark_open_trade(
    open_trade: _OpenShortPut,
    snapshot: list[OptionQuoteBar],
    *,
    ts: datetime,
    multiplier: int,
) -> ShortPutMark | None:
    target = quote_key(open_trade.quote)
    match = next((bar for bar in snapshot if quote_key(_to_option_quote(bar)) == target), None)
    if match is None or match.ask is None:
        return None
    debit = round(max(float(match.ask), 0.0), 4)
    pnl = round((open_trade.entry_credit - debit) * multiplier, 2)
    return ShortPutMark(
        trade_id=open_trade.trade_id,
        mark_ts=ts,
        exit_debit=debit,
        pnl=pnl,
        dte=(open_trade.quote.expiration - ts.date()).days,
    )


def _exit_reason(
    open_trade: _OpenShortPut,
    mark: ShortPutMark,
    *,
    profit_target_pct: float,
    stop_loss_credit_multiple: float,
    exit_dte: int,
) -> str | None:
    if mark.dte <= 0:
        return "expiration"
    if mark.exit_debit <= open_trade.entry_credit * (1.0 - profit_target_pct):
        return "profit_target"
    if mark.exit_debit >= open_trade.entry_credit * stop_loss_credit_multiple:
        return "stop_loss"
    if mark.dte <= exit_dte:
        return "time_exit"
    return None


def _close_trade(
    open_trade: _OpenShortPut,
    mark: ShortPutMark,
    *,
    exit_reason: str,
    trade_marks: list[ShortPutMark] | None = None,
) -> ShortPutTrade:
    observed = trade_marks or [mark]
    pnls = [observed_mark.pnl for observed_mark in observed]
    return ShortPutTrade(
        trade_id=open_trade.trade_id,
        ticker=open_trade.quote.ticker,
        entry_ts=open_trade.entry_ts,
        exit_ts=mark.mark_ts,
        expiration=open_trade.quote.expiration,
        strike=open_trade.quote.strike,
        entry_credit=open_trade.entry_credit,
        exit_debit=mark.exit_debit,
        max_risk=round((open_trade.quote.strike - open_trade.entry_credit) * 100, 2),
        pnl=mark.pnl,
        exit_reason=exit_reason,
        holding_minutes=int((mark.mark_ts - open_trade.entry_ts).total_seconds() // 60),
        dte_entry=(open_trade.quote.expiration - open_trade.entry_ts.date()).days,
        dte_exit=mark.dte,
        short_put_delta=open_trade.quote.delta,
        max_favorable_pnl=max(pnls),
        max_adverse_pnl=min(pnls),
        mark_count=len(observed),
    )


def _unclosed_trade(open_trade: _OpenShortPut) -> ShortPutTrade:
    return ShortPutTrade(
        trade_id=open_trade.trade_id,
        ticker=open_trade.quote.ticker,
        entry_ts=open_trade.entry_ts,
        exit_ts=None,
        expiration=open_trade.quote.expiration,
        strike=open_trade.quote.strike,
        entry_credit=open_trade.entry_credit,
        exit_debit=None,
        max_risk=round((open_trade.quote.strike - open_trade.entry_credit) * 100, 2),
        pnl=None,
        exit_reason="unclosed_missing_mark",
        holding_minutes=0,
        dte_entry=(open_trade.quote.expiration - open_trade.entry_ts.date()).days,
        dte_exit=None,
        short_put_delta=open_trade.quote.delta,
        max_favorable_pnl=None,
        max_adverse_pnl=None,
        mark_count=0,
    )


def _summarize(trades: list[ShortPutTrade]) -> ShortPutBacktestSummary:
    closed = [trade for trade in trades if trade.pnl is not None]
    unclosed = [trade for trade in trades if trade.pnl is None]
    pnls = [float(trade.pnl) for trade in closed]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    return ShortPutBacktestSummary(
        opened_count=len(trades),
        closed_count=len(closed),
        unclosed_count=len(unclosed),
        trade_count=len(closed),
        win_rate=(len(wins) / len(closed)) if closed else 0.0,
        total_pnl=round(sum(pnls), 2),
        average_pnl=round(mean(pnls), 2) if pnls else 0.0,
        average_holding_minutes=round(mean([trade.holding_minutes for trade in closed]), 2) if closed else 0.0,
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


@dataclass(frozen=True)
class _ShortPutConfigShim:
    """Adapt a ShortPutBacktestConfig to the (ticker, start, end) shape that the
    intraday day-stream coercion / day-grouping helpers read."""

    _config: ShortPutBacktestConfig

    @property
    def ticker(self) -> str:
        return self._config.ticker

    @property
    def start(self) -> date | None:
        return self._config.start

    @property
    def end(self) -> date | None:
        return self._config.end


@dataclass(frozen=True)
class _SelectorShim:
    """Adapt ShortPutSelectorConfig to the attributes _to_delta_estimated_option_quote reads."""

    risk_free_rate: float
    dividend_yield: float


def _selector_shim(config: ShortPutSelectorConfig) -> _SelectorShim:
    return _SelectorShim(risk_free_rate=config.risk_free_rate, dividend_yield=config.dividend_yield)
