"""Diagnostics for intraday iron-condor entry selection."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from trader.options.intraday import (
    IntradayIronCondorSelectorConfig,
    _entry_credit,
    _find_long_call,
    _find_long_put,
    _select_premium_for_expiration,
    _to_delta_estimated_option_quote,
)
from trader.options.models import OptionQuote, OptionQuoteBar

if TYPE_CHECKING:
    from trader.options.sources import QuoteSource


@dataclass(frozen=True)
class IntradaySelectionDiagnostics:
    ticker: str
    start: date
    end: date
    entry_time: str
    selection_mode: str
    quote_rows: int
    entry_snapshots: int
    executable_rows: int
    underlying_price_rows: int
    delta_estimated_rows: int
    candidate_short_puts: int
    candidate_short_calls: int
    valid_condors: int
    reason_counts: dict[str, int]


def diagnose_intraday_selection(
    quote_bars: list[OptionQuoteBar],
    *,
    ticker: str,
    start: date,
    end: date,
    entry_time: str,
    selector: IntradayIronCondorSelectorConfig,
) -> IntradaySelectionDiagnostics:
    """Explain why entry snapshots did or did not produce an iron condor."""

    symbol = ticker.strip().upper()
    filtered = [
        quote
        for quote in quote_bars
        if quote.ticker == symbol
        and start <= quote.trade_date <= end
        and selector.min_dte <= quote.dte <= selector.max_dte
    ]
    snapshots = _entry_snapshots(filtered, entry_clock=time.fromisoformat(entry_time))
    reasons: Counter[str] = Counter()
    executable_rows = 0
    underlying_rows = 0
    delta_rows = 0
    put_candidates = 0
    call_candidates = 0
    valid_condors = 0

    if filtered and not snapshots:
        reasons["no_entry_snapshot"] += 1

    for snapshot in snapshots:
        executable = [
            quote for quote in snapshot if quote.has_executable_quote and _spread_ok(quote, selector.max_bid_ask_spread_pct)
        ]
        executable_rows += len(executable)
        underlying_rows += sum(1 for quote in executable if quote.underlying_price is not None)
        if not executable:
            reasons["no_executable_quotes"] += 1
            continue

        if selector.selection_mode == "delta":
            estimated = [
                quote
                for quote in (_to_delta_estimated_option_quote(bar, selector) for bar in executable)
                if quote is not None and quote.delta is not None
            ]
            delta_rows += len(estimated)
            if not any(bar.underlying_price is not None for bar in executable):
                reasons["missing_underlying_price"] += 1
                continue
            if not estimated:
                reasons["no_delta_estimates"] += 1
                continue
            reason, counts = _diagnose_delta_snapshot(estimated, selector)
            put_candidates += counts[0]
            call_candidates += counts[1]
        else:
            reason, counts = _diagnose_premium_snapshot(
                [_to_quote_without_greeks(bar) for bar in executable],
                selector,
            )
            put_candidates += counts[0]
            call_candidates += counts[1]

        if reason == "valid_condor":
            valid_condors += 1
        else:
            reasons[reason] += 1

    return IntradaySelectionDiagnostics(
        ticker=symbol,
        start=start,
        end=end,
        entry_time=entry_time,
        selection_mode=selector.selection_mode,
        quote_rows=len(filtered),
        entry_snapshots=len(snapshots),
        executable_rows=executable_rows,
        underlying_price_rows=underlying_rows,
        delta_estimated_rows=delta_rows,
        candidate_short_puts=put_candidates,
        candidate_short_calls=call_candidates,
        valid_condors=valid_condors,
        reason_counts=dict(sorted(reasons.items())),
    )


def diagnose_intraday_selection_streaming(
    source: QuoteSource,
    *,
    ticker: str,
    start: date,
    end: date,
    entry_time: str,
    selector: IntradayIronCondorSelectorConfig,
) -> IntradaySelectionDiagnostics:
    """Memory-safe diagnostics: stream one trade-date at a time and aggregate counts.

    Entry snapshots are per-day independent and every diagnostic field is additive
    across days, so per-day aggregation is identical to running the full window at
    once -- without ever holding more than a single trade-date in memory.
    """

    symbol = ticker.strip().upper()
    quote_rows = 0
    entry_snapshots = 0
    executable_rows = 0
    underlying_rows = 0
    delta_rows = 0
    put_candidates = 0
    call_candidates = 0
    valid_condors = 0
    reasons: Counter[str] = Counter()

    for trade_date, day_bars in source.iter_days(symbol, start, end):
        day = diagnose_intraday_selection(
            day_bars,
            ticker=symbol,
            start=trade_date,
            end=trade_date,
            entry_time=entry_time,
            selector=selector,
        )
        quote_rows += day.quote_rows
        entry_snapshots += day.entry_snapshots
        executable_rows += day.executable_rows
        underlying_rows += day.underlying_price_rows
        delta_rows += day.delta_estimated_rows
        put_candidates += day.candidate_short_puts
        call_candidates += day.candidate_short_calls
        valid_condors += day.valid_condors
        reasons.update(day.reason_counts)

    return IntradaySelectionDiagnostics(
        ticker=symbol,
        start=start,
        end=end,
        entry_time=entry_time,
        selection_mode=selector.selection_mode,
        quote_rows=quote_rows,
        entry_snapshots=entry_snapshots,
        executable_rows=executable_rows,
        underlying_price_rows=underlying_rows,
        delta_estimated_rows=delta_rows,
        candidate_short_puts=put_candidates,
        candidate_short_calls=call_candidates,
        valid_condors=valid_condors,
        reason_counts=dict(sorted(reasons.items())),
    )


def format_intraday_selection_report(diagnostics: IntradaySelectionDiagnostics) -> str:
    lines = [
        f"# {diagnostics.ticker} Intraday Selection Diagnostics",
        "",
        "## Window",
        f"- start: {diagnostics.start}",
        f"- end: {diagnostics.end}",
        f"- entry_time: {diagnostics.entry_time}",
        f"- selection_mode: {diagnostics.selection_mode}",
        "",
        "## Counts",
        f"- quote_rows: {diagnostics.quote_rows}",
        f"- entry_snapshots: {diagnostics.entry_snapshots}",
        f"- executable_rows: {diagnostics.executable_rows}",
        f"- underlying_price_rows: {diagnostics.underlying_price_rows}",
        f"- delta_estimated_rows: {diagnostics.delta_estimated_rows}",
        f"- candidate_short_puts: {diagnostics.candidate_short_puts}",
        f"- candidate_short_calls: {diagnostics.candidate_short_calls}",
        f"- valid_condors: {diagnostics.valid_condors}",
        "",
        "## Skip Reasons",
        "| reason | count |",
        "|---|---:|",
    ]
    if diagnostics.reason_counts:
        for reason, count in diagnostics.reason_counts.items():
            lines.append(f"| {reason} | {count} |")
    else:
        lines.append("| none | 0 |")
    return "\n".join(lines) + "\n"


def _entry_snapshots(quote_bars: list[OptionQuoteBar], *, entry_clock: time) -> list[list[OptionQuoteBar]]:
    by_date_ts: dict[date, dict[datetime, list[OptionQuoteBar]]] = defaultdict(lambda: defaultdict(list))
    for quote in quote_bars:
        by_date_ts[quote.trade_date][quote.timestamp].append(quote)

    snapshots: list[list[OptionQuoteBar]] = []
    for trade_date in sorted(by_date_ts):
        eligible_ts = [
            timestamp
            for timestamp in sorted(by_date_ts[trade_date])
            if timestamp.timetz().replace(tzinfo=None) >= entry_clock
        ]
        if eligible_ts:
            snapshots.append(by_date_ts[trade_date][eligible_ts[0]])
    return snapshots


def _diagnose_delta_snapshot(
    quotes: list[OptionQuote],
    selector: IntradayIronCondorSelectorConfig,
) -> tuple[str, tuple[int, int]]:
    puts = [quote for quote in quotes if quote.call_put == "Put" and quote.delta is not None and quote.delta < 0]
    calls = [quote for quote in quotes if quote.call_put == "Call" and quote.delta is not None and quote.delta > 0]
    short_puts = [
        quote for quote in puts if quote.delta is not None and abs(abs(float(quote.delta)) - selector.target_delta) <= selector.max_delta_deviation
    ]
    short_calls = [
        quote for quote in calls if quote.delta is not None and abs(float(quote.delta) - selector.target_delta) <= selector.max_delta_deviation
    ]
    if not short_puts:
        return "no_target_put", (0, len(short_calls))
    if not short_calls:
        return "no_target_call", (len(short_puts), 0)
    return _diagnose_wings_and_credit(puts, calls, short_puts, short_calls, selector), (len(short_puts), len(short_calls))


def _diagnose_premium_snapshot(
    quotes: list[OptionQuote],
    selector: IntradayIronCondorSelectorConfig,
) -> tuple[str, tuple[int, int]]:
    by_expiration: dict[date, list[OptionQuote]] = defaultdict(list)
    for quote in quotes:
        by_expiration[quote.expiration].append(quote)
    for expiration, expiration_quotes in by_expiration.items():
        if _select_premium_for_expiration(expiration_quotes, config=selector, expiration=expiration) is not None:
            return "valid_condor", (1, 1)
    puts = [quote for quote in quotes if quote.call_put == "Put"]
    calls = [quote for quote in quotes if quote.call_put == "Call"]
    short_puts = [quote for quote in puts if quote.bid is not None]
    short_calls = [quote for quote in calls if quote.bid is not None]
    if not short_puts:
        return "no_put_quotes", (0, len(short_calls))
    if not short_calls:
        return "no_call_quotes", (len(short_puts), 0)
    return _diagnose_wings_and_credit(puts, calls, short_puts, short_calls, selector), (len(short_puts), len(short_calls))


def _diagnose_wings_and_credit(
    puts: list[OptionQuote],
    calls: list[OptionQuote],
    short_puts: list[OptionQuote],
    short_calls: list[OptionQuote],
    selector: IntradayIronCondorSelectorConfig,
) -> str:
    saw_put_wing = False
    saw_call_wing = False
    saw_credit = False
    for short_put in short_puts:
        long_put = _find_long_put(puts, short_put, selector)
        if long_put is None:
            continue
        saw_put_wing = True
        for short_call in short_calls:
            long_call = _find_long_call(calls, short_call, selector)
            if long_call is None:
                continue
            saw_call_wing = True
            credit = _entry_credit(short_put, long_put, short_call, long_call)
            if credit >= selector.min_credit:
                return "valid_condor"
            saw_credit = True
    if not saw_put_wing:
        return "missing_put_wing"
    if not saw_call_wing:
        return "missing_call_wing"
    if saw_credit:
        return "below_min_credit"
    return "no_complete_condor"


def _to_quote_without_greeks(quote: OptionQuoteBar) -> OptionQuote:
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


def _spread_ok(quote: OptionQuoteBar, max_spread_pct: float) -> bool:
    mid = quote.mid
    if quote.bid is None or quote.ask is None or mid is None or mid <= 0:
        return False
    return ((quote.ask - quote.bid) / mid) <= max_spread_pct
