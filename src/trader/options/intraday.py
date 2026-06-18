"""Intraday quote-based iron-condor research backtester.

This module is intentionally premium-target based. ThetaData Value includes
historical quote data, but not historical Greeks, so this path does not pretend
to run a 16-delta strategy until we compute or buy point-in-time Greeks.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time
from statistics import mean
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from trader.options.greeks import estimate_quote_delta
from trader.options.iron_condor import IronCondor, mark_condor_close_debit, quote_key
from trader.options.models import OptionQuote, OptionQuoteBar

if TYPE_CHECKING:
    from trader.options.sources import QuoteSource

SelectionMode = Literal["premium", "delta"]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntradayIronCondorSelectorConfig:
    min_dte: int = 30
    max_dte: int = 45
    wing_width: float = 5.0
    max_wing_width: float = 20.0
    selection_mode: SelectionMode = "premium"
    target_short_bid: float = 1.0
    target_delta: float = 0.16
    max_delta_deviation: float = 0.08
    min_credit: float = 0.05
    min_credit_to_wing_ratio: float = 0.10
    max_bid_ask_spread_pct: float = 1.0
    risk_free_rate: float = 0.04
    dividend_yield: float = 0.0


@dataclass(frozen=True)
class IntradayIronCondorBacktestConfig:
    ticker: str = "SPY"
    start: date | None = None
    end: date | None = None
    selector: IntradayIronCondorSelectorConfig = field(default_factory=IntradayIronCondorSelectorConfig)
    entry_time: str = "09:45:00"
    profit_target_pct: float = 0.50
    stop_loss_credit_multiple: float = 2.0
    exit_dte: int = 21
    max_concurrent_trades: int = 1
    contract_multiplier: int = 100
    # Friction defaults are neutral (0) at the library level so programmatic
    # callers and unit tests see a frictionless baseline; the CLI sets realistic
    # research defaults (commission 0.65, slippage 0.02, daily exit cadence).
    commission_per_contract: float = 0.0
    # Execution realism. slippage_per_contract is option-price points lost to
    # crossing the spread on each of the 4 legs, at both entry and exit.
    slippage_per_contract: float = 0.0
    # When set (e.g. "15:55:00"), profit-target / stop exits may only be acted on
    # at the first snapshot at/after this time each day -- a once-a-day decision
    # cadence that prevents cherry-picking the single most favorable intraday mark.
    # The decision is causal: it uses ONLY the mark at that snapshot (never the
    # day's range, close, or best minute retroactively). Audit A3 caveat: under
    # this cadence an intraday stop breach that reverts before the decision time
    # is NOT realized as a stop_loss -- reported PnL assumes no intraday risk
    # control between decision points (the breach is visible only in
    # max_adverse_pnl). Empty string evaluates exits every minute, filling at the
    # first threshold crossing.
    exit_decision_time: str = ""


@dataclass(frozen=True)
class IntradayIronCondorMark:
    trade_id: str
    mark_ts: datetime
    exit_debit: float
    pnl: float
    dte: int


@dataclass(frozen=True)
class IntradayIronCondorTrade:
    trade_id: str
    ticker: str
    entry_ts: datetime
    exit_ts: datetime | None
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
    holding_minutes: int
    dte_entry: int
    dte_exit: int | None
    short_put_delta: float | None = None
    short_call_delta: float | None = None
    max_favorable_pnl: float | None = None
    max_adverse_pnl: float | None = None
    mark_count: int = 0


@dataclass(frozen=True)
class IntradayIronCondorBacktestSummary:
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
class IntradayIronCondorBacktestResult:
    run_id: str
    config: IntradayIronCondorBacktestConfig
    trades: list[IntradayIronCondorTrade]
    marks: list[IntradayIronCondorMark]
    summary: IntradayIronCondorBacktestSummary


@dataclass(frozen=True)
class IntradayQuoteReplayData:
    """Timestamp-indexed intraday quote tape reused across parameter sweeps."""

    by_ts: dict[datetime, list[OptionQuoteBar]]
    timestamps: tuple[datetime, ...]


@dataclass(frozen=True)
class _OpenIntradayTrade:
    trade_id: str
    condor: IronCondor
    entry_ts: datetime


def build_intraday_quote_replay_data(
    quote_bars: list[OptionQuoteBar],
    config: IntradayIronCondorBacktestConfig | None = None,
) -> IntradayQuoteReplayData:
    """Filter and group quote bars once so repeated backtests can reuse the tape."""

    config = config or IntradayIronCondorBacktestConfig()
    symbol = config.ticker.strip().upper()
    by_ts: dict[datetime, list[OptionQuoteBar]] = defaultdict(list)
    for quote in quote_bars:
        if quote.ticker != symbol:
            continue
        if config.start is not None and quote.trade_date < config.start:
            continue
        if config.end is not None and quote.trade_date > config.end:
            continue
        by_ts[quote.timestamp].append(quote)
    return IntradayQuoteReplayData(by_ts=dict(by_ts), timestamps=tuple(sorted(by_ts)))


@dataclass
class _StreamState:
    """Mutable carry-over state shared across trade-dates during a streaming run."""

    open_trades: list[_OpenIntradayTrade] = field(default_factory=list)
    closed_trades: list[IntradayIronCondorTrade] = field(default_factory=list)
    marks: list[IntradayIronCondorMark] = field(default_factory=list)
    marks_by_trade_id: dict[str, list[IntradayIronCondorMark]] = field(default_factory=lambda: defaultdict(list))
    entered_dates: set[date] = field(default_factory=set)
    exit_decision_dates: set[date] = field(default_factory=set)
    position_active_dates: set[date] = field(default_factory=set)
    last_ts: datetime | None = None
    last_snapshot: list[OptionQuoteBar] | None = None


def run_intraday_iron_condor_backtest(
    quote_bars: list[OptionQuoteBar]
    | IntradayQuoteReplayData
    | QuoteSource
    | Iterable[tuple[date, list[OptionQuoteBar]]],
    config: IntradayIronCondorBacktestConfig | None = None,
) -> IntradayIronCondorBacktestResult:
    """Replay a single-position intraday iron-condor strategy from 1-minute quote bars.

    Accepts a raw ``list[OptionQuoteBar]`` or a prebuilt ``IntradayQuoteReplayData``
    (both materialized, used by sweeps) or a :class:`~trader.options.sources.QuoteSource`
    (streamed one trade-date at a time). Regardless of input, the engine processes
    one trade-date at a time and never holds more than a single day of quote bars in
    memory. The public result shape is identical across all input types.
    """

    config = config or IntradayIronCondorBacktestConfig()
    day_stream = _coerce_day_stream(quote_bars, config)
    return _run_streaming(day_stream, config)


def _run_streaming(
    day_stream: Iterator[tuple[date, list[OptionQuoteBar]]],
    config: IntradayIronCondorBacktestConfig,
) -> IntradayIronCondorBacktestResult:
    entry_clock = time.fromisoformat(config.entry_time)
    state = _StreamState()

    for _trade_date, day_bars in day_stream:
        by_ts = _group_day_by_ts(day_bars, config)
        for ts in sorted(by_ts):
            snapshot = by_ts[ts]
            _step_timestamp(ts, snapshot, config=config, entry_clock=entry_clock, state=state)
            state.last_ts = ts
            state.last_snapshot = snapshot
        # Release this day's bars before reading the next one.
        del by_ts, day_bars

    _finalize_open_trades(config, state)
    if config.exit_decision_time:
        missed = sorted(state.position_active_dates - state.exit_decision_dates)
        if missed:
            logger.warning(
                "%d trading day(s) had an open position but no snapshot at/after exit_decision_time %s; "
                "profit-target/stop exits could not be evaluated those days (e.g. %s).",
                len(missed),
                config.exit_decision_time,
                ", ".join(d.isoformat() for d in missed[:3]),
            )

    return IntradayIronCondorBacktestResult(
        run_id=str(uuid4()),
        config=config,
        trades=state.closed_trades,
        marks=state.marks,
        summary=_summarize(state.closed_trades),
    )


def _group_day_by_ts(
    day_bars: list[OptionQuoteBar],
    config: IntradayIronCondorBacktestConfig,
) -> dict[datetime, list[OptionQuoteBar]]:
    symbol = config.ticker.strip().upper()
    by_ts: dict[datetime, list[OptionQuoteBar]] = defaultdict(list)
    for quote in day_bars:
        if quote.ticker != symbol:
            continue
        if config.start is not None and quote.trade_date < config.start:
            continue
        if config.end is not None and quote.trade_date > config.end:
            continue
        by_ts[quote.timestamp].append(quote)
    return by_ts


def _is_exit_decision_point(
    ts: datetime,
    config: IntradayIronCondorBacktestConfig,
    state: _StreamState,
) -> bool:
    """Whether a profit-target / stop exit may be acted on at this timestamp.

    With no ``exit_decision_time`` configured, every minute qualifies (legacy
    behavior). Otherwise only the first snapshot at/after the decision time each
    day qualifies, modeling a once-a-day check rather than catching the single
    most favorable intraday mark. Forced exits (expiration / time_exit) are not
    gated by this -- they fire whenever they come due.
    """

    if not config.exit_decision_time:
        return True
    decision_clock = time.fromisoformat(config.exit_decision_time)
    if ts.timetz().replace(tzinfo=None) < decision_clock:
        return False
    if ts.date() in state.exit_decision_dates:
        return False
    state.exit_decision_dates.add(ts.date())
    return True


def _step_timestamp(
    ts: datetime,
    snapshot: list[OptionQuoteBar],
    *,
    config: IntradayIronCondorBacktestConfig,
    entry_clock: time,
    state: _StreamState,
) -> None:
    if state.open_trades:
        state.position_active_dates.add(ts.date())
    decision_point = _is_exit_decision_point(ts, config, state)
    remaining_open: list[_OpenIntradayTrade] = []
    for open_trade in state.open_trades:
        mark = _mark_open_trade(
            open_trade,
            snapshot,
            ts=ts,
            multiplier=config.contract_multiplier,
            slippage_per_contract=config.slippage_per_contract,
        )
        if mark is None:
            remaining_open.append(open_trade)
            continue
        state.marks.append(mark)
        state.marks_by_trade_id[mark.trade_id].append(mark)
        exit_reason = _exit_reason(
            open_trade.condor,
            mark,
            profit_target_pct=config.profit_target_pct,
            stop_loss_credit_multiple=config.stop_loss_credit_multiple,
            exit_dte=config.exit_dte,
        )
        # Intraday-discretionary exits (profit target / stop) can only be acted on
        # at a decision point; forced exits (expiration / time_exit) always fire.
        if exit_reason in ("profit_target", "stop_loss") and not decision_point:
            exit_reason = None
        if exit_reason is None:
            remaining_open.append(open_trade)
            continue
        state.closed_trades.append(
            _close_trade(
                open_trade,
                mark,
                exit_reason=exit_reason,
                trade_marks=state.marks_by_trade_id[mark.trade_id],
                commission=_close_friction(config),
            )
        )
    state.open_trades = remaining_open

    if ts.date() in state.entered_dates:
        return
    if ts.timetz().replace(tzinfo=None) < entry_clock:
        return
    if len(state.open_trades) >= config.max_concurrent_trades:
        return
    condor = select_intraday_iron_condor(snapshot, config.selector)
    if condor is None:
        state.entered_dates.add(ts.date())
        return
    state.open_trades.append(_OpenIntradayTrade(trade_id=str(uuid4()), condor=condor, entry_ts=ts))
    state.entered_dates.add(ts.date())


def _finalize_open_trades(config: IntradayIronCondorBacktestConfig, state: _StreamState) -> None:
    if state.last_ts is None or state.last_snapshot is None:
        return
    last_ts = state.last_ts
    last_snapshot = state.last_snapshot
    for open_trade in state.open_trades:
        mark = _mark_open_trade(
            open_trade,
            last_snapshot,
            ts=last_ts,
            multiplier=config.contract_multiplier,
            slippage_per_contract=config.slippage_per_contract,
        )
        if mark is None:
            state.closed_trades.append(_unclosed_trade(open_trade))
        else:
            if not any(
                existing.trade_id == mark.trade_id and existing.mark_ts == mark.mark_ts for existing in state.marks
            ):
                state.marks.append(mark)
                state.marks_by_trade_id[mark.trade_id].append(mark)
            state.closed_trades.append(
                _close_trade(
                    open_trade,
                    mark,
                    exit_reason="final_mark",
                    trade_marks=state.marks_by_trade_id.get(mark.trade_id, [mark]),
                    commission=_close_friction(config),
                )
            )


def _coerce_day_stream(
    quote_bars: list[OptionQuoteBar]
    | IntradayQuoteReplayData
    | QuoteSource
    | Iterable[tuple[date, list[OptionQuoteBar]]],
    config: IntradayIronCondorBacktestConfig,
) -> Iterator[tuple[date, list[OptionQuoteBar]]]:
    """Normalize any supported input into a chronological day-by-day stream.

    Lists and ``IntradayQuoteReplayData`` are already materialized (used by sweeps);
    they are regrouped by trade-date in memory. A ``QuoteSource`` is streamed via
    ``iter_days`` so only one trade-date is read at a time.
    """

    if isinstance(quote_bars, IntradayQuoteReplayData):
        return _days_from_replay(quote_bars)
    if isinstance(quote_bars, list):
        return _days_from_bars(quote_bars)
    if hasattr(quote_bars, "iter_days"):
        if config.start is None or config.end is None:
            raise ValueError("Streaming from a QuoteSource requires config.start and config.end.")
        return quote_bars.iter_days(config.ticker.strip().upper(), config.start, config.end)
    # Already a chronological iterable of (trade_date, day_bars) tuples.
    return iter(quote_bars)


def _days_from_bars(quote_bars: list[OptionQuoteBar]) -> Iterator[tuple[date, list[OptionQuoteBar]]]:
    by_date: dict[date, list[OptionQuoteBar]] = defaultdict(list)
    for quote in quote_bars:
        by_date[quote.trade_date].append(quote)
    for trade_date in sorted(by_date):
        yield trade_date, by_date[trade_date]


def _days_from_replay(replay_data: IntradayQuoteReplayData) -> Iterator[tuple[date, list[OptionQuoteBar]]]:
    by_date: dict[date, list[OptionQuoteBar]] = defaultdict(list)
    for ts in replay_data.timestamps:
        by_date[ts.date()].extend(replay_data.by_ts[ts])
    for trade_date in sorted(by_date):
        yield trade_date, by_date[trade_date]


def select_intraday_iron_condor(
    snapshot: list[OptionQuoteBar],
    config: IntradayIronCondorSelectorConfig | None = None,
) -> IronCondor | None:
    config = config or IntradayIronCondorSelectorConfig()
    if config.selection_mode == "delta":
        return select_delta_iron_condor(snapshot, config)
    return select_premium_iron_condor(snapshot, config)


def select_premium_iron_condor(
    snapshot: list[OptionQuoteBar],
    config: IntradayIronCondorSelectorConfig | None = None,
) -> IronCondor | None:
    """Select a condor from one timestamp using premium target rather than Greeks."""

    config = config or IntradayIronCondorSelectorConfig()
    eligible = [
        _to_option_quote(quote)
        for quote in snapshot
        if quote.has_executable_quote
        and config.min_dte <= quote.dte <= config.max_dte
        and _spread_ok(quote, config.max_bid_ask_spread_pct)
    ]
    by_expiration: dict[date, list[OptionQuote]] = defaultdict(list)
    for quote in eligible:
        by_expiration[quote.expiration].append(quote)

    target_dte = (config.min_dte + config.max_dte) / 2.0
    for expiration, quotes in sorted(
        by_expiration.items(),
        key=lambda item: abs((item[0] - item[1][0].trade_date).days - target_dte),
    ):
        condor = _select_premium_for_expiration(quotes, config=config, expiration=expiration)
        if condor is not None:
            return condor
    return None


def select_delta_iron_condor(
    snapshot: list[OptionQuoteBar],
    config: IntradayIronCondorSelectorConfig | None = None,
) -> IronCondor | None:
    """Select a condor from one timestamp using approximate Black-Scholes deltas."""

    config = config or IntradayIronCondorSelectorConfig(selection_mode="delta")
    eligible = [
        quote
        for quote in (_to_delta_estimated_option_quote(bar, config) for bar in snapshot)
        if quote is not None
        and quote.has_executable_quote
        and quote.delta is not None
        and config.min_dte <= quote.dte <= config.max_dte
    ]
    by_expiration: dict[date, list[OptionQuote]] = defaultdict(list)
    for quote in eligible:
        by_expiration[quote.expiration].append(quote)

    target_dte = (config.min_dte + config.max_dte) / 2.0
    for expiration, quotes in sorted(
        by_expiration.items(),
        key=lambda item: abs((item[0] - item[1][0].trade_date).days - target_dte),
    ):
        condor = _select_delta_for_expiration(quotes, config=config, expiration=expiration)
        if condor is not None:
            return condor
    return None


def format_intraday_iron_condor_report(result: IntradayIronCondorBacktestResult) -> str:
    """Render a compact markdown report for CLI output."""
    summary = result.summary
    lines = [
        f"# {result.config.ticker} Intraday Iron Condor Backtest",
        "",
        "## Parameters",
        f"- start: {result.config.start}",
        f"- end: {result.config.end}",
        f"- entry_time: {result.config.entry_time}",
        f"- min_dte: {result.config.selector.min_dte}",
        f"- max_dte: {result.config.selector.max_dte}",
        f"- wing_width: {result.config.selector.wing_width}",
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
        "| entry_ts | exit_ts | expiration | strikes | put_delta | call_delta | credit | debit | max_risk | pnl | mae | mfe | marks | reason |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for trade in result.trades:
        lines.append(
            "| "
            f"{trade.entry_ts.isoformat()} | "
            f"{trade.exit_ts.isoformat() if trade.exit_ts else ''} | "
            f"{trade.expiration.isoformat()} | "
            f"{trade.long_put_strike:.2f}/{trade.short_put_strike:.2f}/"
            f"{trade.short_call_strike:.2f}/{trade.long_call_strike:.2f} | "
            f"{_format_optional_float(trade.short_put_delta, precision=3)} | "
            f"{_format_optional_float(trade.short_call_delta, precision=3)} | "
            f"{trade.entry_credit:.2f} | "
            f"{_format_optional_float(trade.exit_debit)} | "
            f"{trade.max_risk:.2f} | "
            f"{_format_optional_float(trade.pnl)} | "
            f"{_format_optional_float(trade.max_adverse_pnl)} | "
            f"{_format_optional_float(trade.max_favorable_pnl)} | "
            f"{trade.mark_count} | "
            f"{trade.exit_reason} |"
        )
    return "\n".join(lines) + "\n"


def _select_premium_for_expiration(
    quotes: list[OptionQuote],
    *,
    config: IntradayIronCondorSelectorConfig,
    expiration: date,
) -> IronCondor | None:
    puts = [quote for quote in quotes if quote.call_put == "Put"]
    calls = [quote for quote in quotes if quote.call_put == "Call"]
    if not puts or not calls:
        return None

    short_puts = sorted(
        [quote for quote in puts if quote.bid is not None],
        key=lambda quote: (abs(float(quote.bid) - config.target_short_bid), -quote.strike),
    )
    short_calls = sorted(
        [quote for quote in calls if quote.bid is not None],
        key=lambda quote: (abs(float(quote.bid) - config.target_short_bid), quote.strike),
    )
    for short_put in short_puts:
        long_put = _find_long_put(puts, short_put, config)
        if long_put is None:
            continue
        for short_call in short_calls:
            long_call = _find_long_call(calls, short_call, config)
            if long_call is None:
                continue
            credit = _entry_credit(short_put, long_put, short_call, long_call)
            if not _meets_credit_floor(credit, short_put, long_put, short_call, long_call, config):
                continue
            return IronCondor(
                ticker=short_put.ticker,
                trade_date=short_put.trade_date,
                expiration=expiration,
                short_put=short_put,
                long_put=long_put,
                short_call=short_call,
                long_call=long_call,
                entry_credit=credit,
            )
    return None


def _select_delta_for_expiration(
    quotes: list[OptionQuote],
    *,
    config: IntradayIronCondorSelectorConfig,
    expiration: date,
) -> IronCondor | None:
    puts = [quote for quote in quotes if quote.call_put == "Put" and quote.delta is not None and quote.delta < 0]
    calls = [quote for quote in quotes if quote.call_put == "Call" and quote.delta is not None and quote.delta > 0]
    if not puts or not calls:
        return None

    short_puts = sorted(
        [
            quote
            for quote in puts
            if quote.delta is not None and abs(abs(float(quote.delta)) - config.target_delta) <= config.max_delta_deviation
        ],
        key=lambda quote: (abs(abs(float(quote.delta)) - config.target_delta), -quote.strike),
    )
    short_calls = sorted(
        [
            quote
            for quote in calls
            if quote.delta is not None and abs(float(quote.delta) - config.target_delta) <= config.max_delta_deviation
        ],
        key=lambda quote: (abs(float(quote.delta) - config.target_delta), quote.strike),
    )
    for short_put in short_puts:
        long_put = _find_long_put(puts, short_put, config)
        if long_put is None:
            continue
        for short_call in short_calls:
            long_call = _find_long_call(calls, short_call, config)
            if long_call is None:
                continue
            credit = _entry_credit(short_put, long_put, short_call, long_call)
            if not _meets_credit_floor(credit, short_put, long_put, short_call, long_call, config):
                continue
            return IronCondor(
                ticker=short_put.ticker,
                trade_date=short_put.trade_date,
                expiration=expiration,
                short_put=short_put,
                long_put=long_put,
                short_call=short_call,
                long_call=long_call,
                entry_credit=credit,
            )
    return None


def _find_long_put(
    puts: list[OptionQuote],
    short_put: OptionQuote,
    config: IntradayIronCondorSelectorConfig,
) -> OptionQuote | None:
    candidates = [
        quote
        for quote in puts
        if quote.strike < short_put.strike
        and config.wing_width <= short_put.strike - quote.strike <= config.max_wing_width
    ]
    return min(candidates, key=lambda quote: abs((short_put.strike - quote.strike) - config.wing_width), default=None)


def _find_long_call(
    calls: list[OptionQuote],
    short_call: OptionQuote,
    config: IntradayIronCondorSelectorConfig,
) -> OptionQuote | None:
    candidates = [
        quote
        for quote in calls
        if quote.strike > short_call.strike
        and config.wing_width <= quote.strike - short_call.strike <= config.max_wing_width
    ]
    return min(candidates, key=lambda quote: abs((quote.strike - short_call.strike) - config.wing_width), default=None)


def _entry_credit(short_put: OptionQuote, long_put: OptionQuote, short_call: OptionQuote, long_call: OptionQuote) -> float:
    if short_put.bid is None or short_call.bid is None or long_put.ask is None or long_call.ask is None:
        return 0.0
    return round(short_put.bid + short_call.bid - long_put.ask - long_call.ask, 4)


def _meets_credit_floor(
    credit: float,
    short_put: OptionQuote,
    long_put: OptionQuote,
    short_call: OptionQuote,
    long_call: OptionQuote,
    config: IntradayIronCondorSelectorConfig,
) -> bool:
    """Reject degenerate entries whose credit is trivially small for the wing.

    A condor opened for a few cents on a multi-dollar wing is a quote artifact, not
    a real trade: it has an absurdly low stop threshold and pollutes results. Require
    the credit to clear both an absolute floor and a fraction of the wing width.
    """

    wing = max(short_put.strike - long_put.strike, long_call.strike - short_call.strike)
    floor = max(config.min_credit, config.min_credit_to_wing_ratio * wing)
    return credit >= floor


def _mark_open_trade(
    open_trade: _OpenIntradayTrade,
    snapshot: list[OptionQuoteBar],
    *,
    ts: datetime,
    multiplier: int,
    slippage_per_contract: float = 0.0,
) -> IntradayIronCondorMark | None:
    by_key = {quote_key(_to_option_quote(quote)): _to_option_quote(quote) for quote in snapshot}
    condor = open_trade.condor
    short_put = by_key.get(quote_key(condor.short_put))
    long_put = by_key.get(quote_key(condor.long_put))
    short_call = by_key.get(quote_key(condor.short_call))
    long_call = by_key.get(quote_key(condor.long_call))
    underlying_price = next(
        (bar.underlying_price for bar in snapshot if bar.underlying_price is not None),
        None,
    )
    dte = (condor.expiration - ts.date()).days
    # All marking/settlement semantics (intrinsic floor, wing cap, expiration-only
    # intrinsic settlement, exit slippage) live in the shared core so the intraday
    # and EOD engines cannot diverge. Mid-life (dte > 0) a missing leg quote means
    # the close price is unknown: the mark is None and the position stays open.
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
    return IntradayIronCondorMark(
        trade_id=open_trade.trade_id,
        mark_ts=ts,
        exit_debit=debit,
        pnl=pnl,
        dte=dte,
    )


def _exit_reason(
    condor: IronCondor,
    mark: IntradayIronCondorMark,
    *,
    profit_target_pct: float,
    stop_loss_credit_multiple: float,
    exit_dte: int,
) -> str | None:
    if mark.dte <= 0:
        return "expiration"
    if mark.exit_debit <= condor.entry_credit * (1.0 - profit_target_pct):
        return "profit_target"
    if mark.exit_debit >= condor.entry_credit * stop_loss_credit_multiple:
        return "stop_loss"
    if mark.dte <= exit_dte:
        return "time_exit"
    return None


def _close_friction(config: IntradayIronCondorBacktestConfig) -> float:
    """Per-trade friction deducted at close: round-trip commission plus the
    entry-side slippage. Exit-side slippage is already baked into the mark debit,
    so only the entry leg of slippage is added here."""

    commission = config.commission_per_contract * 4 * 2
    entry_slippage = config.slippage_per_contract * 4 * config.contract_multiplier
    return round(commission + entry_slippage, 2)


def _close_trade(
    open_trade: _OpenIntradayTrade,
    mark: IntradayIronCondorMark,
    *,
    exit_reason: str,
    trade_marks: list[IntradayIronCondorMark] | None = None,
    commission: float = 0.0,
) -> IntradayIronCondorTrade:
    condor = open_trade.condor
    observed_marks = trade_marks or [mark]
    pnls = [observed_mark.pnl for observed_mark in observed_marks]
    net_pnl = round(mark.pnl - commission, 2)
    return IntradayIronCondorTrade(
        trade_id=open_trade.trade_id,
        ticker=condor.ticker,
        entry_ts=open_trade.entry_ts,
        exit_ts=mark.mark_ts,
        expiration=condor.expiration,
        short_put_strike=condor.short_put.strike,
        long_put_strike=condor.long_put.strike,
        short_call_strike=condor.short_call.strike,
        long_call_strike=condor.long_call.strike,
        entry_credit=condor.entry_credit,
        exit_debit=mark.exit_debit,
        max_risk=condor.max_risk,
        pnl=net_pnl,
        exit_reason=exit_reason,
        holding_minutes=int((mark.mark_ts - open_trade.entry_ts).total_seconds() // 60),
        dte_entry=condor.dte,
        dte_exit=mark.dte,
        short_put_delta=condor.short_put.delta,
        short_call_delta=condor.short_call.delta,
        max_favorable_pnl=max(pnls),
        max_adverse_pnl=min(pnls),
        mark_count=len(observed_marks),
    )


def _unclosed_trade(open_trade: _OpenIntradayTrade) -> IntradayIronCondorTrade:
    condor = open_trade.condor
    return IntradayIronCondorTrade(
        trade_id=open_trade.trade_id,
        ticker=condor.ticker,
        entry_ts=open_trade.entry_ts,
        exit_ts=None,
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
        holding_minutes=0,
        dte_entry=condor.dte,
        dte_exit=None,
        short_put_delta=condor.short_put.delta,
        short_call_delta=condor.short_call.delta,
        max_favorable_pnl=None,
        max_adverse_pnl=None,
        mark_count=0,
    )


def _summarize(trades: list[IntradayIronCondorTrade]) -> IntradayIronCondorBacktestSummary:
    closed = [trade for trade in trades if trade.pnl is not None]
    unclosed = [trade for trade in trades if trade.pnl is None]
    pnls = [float(trade.pnl) for trade in closed]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    return IntradayIronCondorBacktestSummary(
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


def _format_optional_float(value: float | None, *, precision: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{precision}f}"


def _to_option_quote(quote: OptionQuoteBar) -> OptionQuote:
    return OptionQuote(
        trade_date=quote.trade_date,
        ticker=quote.ticker,
        expiration=quote.expiration,
        strike=quote.strike,
        call_put=quote.call_put,
        bid=quote.bid,
        ask=quote.ask,
        implied_vol=None,
        delta=None,
        gamma=None,
        theta=None,
        vega=None,
        rho=None,
    )


def _to_delta_estimated_option_quote(
    quote: OptionQuoteBar,
    config: IntradayIronCondorSelectorConfig,
) -> OptionQuote | None:
    if quote.mid is None or quote.underlying_price is None:
        return None
    years_to_expiration = quote.dte / 365
    delta = estimate_quote_delta(
        option_type=quote.call_put,
        option_mid=quote.mid,
        spot=quote.underlying_price,
        strike=quote.strike,
        years_to_expiration=years_to_expiration,
        risk_free_rate=config.risk_free_rate,
        dividend_yield=config.dividend_yield,
    )
    if delta is None:
        return None
    return OptionQuote(
        trade_date=quote.trade_date,
        ticker=quote.ticker,
        expiration=quote.expiration,
        strike=quote.strike,
        call_put=quote.call_put,
        bid=quote.bid,
        ask=quote.ask,
        implied_vol=None,
        delta=delta,
        gamma=None,
        theta=None,
        vega=None,
        rho=None,
    )


def _spread_ok(quote: OptionQuoteBar, max_spread_pct: float) -> bool:
    mid = quote.mid
    if mid is None or mid <= 0 or quote.bid is None or quote.ask is None:
        return False
    return ((quote.ask - quote.bid) / mid) <= max_spread_pct
