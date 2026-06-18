"""Data coverage diagnostics for options research datasets."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from trader.options.models import OptionQuote

if TYPE_CHECKING:
    from trader.options.sources import QuoteSource


@dataclass(frozen=True)
class OptionCoverageSummary:
    ticker: str
    start: date | None
    end: date | None
    trade_dates: int
    option_rows: int
    expirations: int
    missing_bid_ask_rows: int
    missing_delta_rows: int
    min_rows_per_date: int
    max_rows_per_date: int
    average_rows_per_date: float
    warnings: tuple[str, ...] = field(default_factory=tuple)


def summarize_option_coverage(
    quotes: list[OptionQuote],
    *,
    ticker: str,
    min_rows_per_date_warning: int = 50,
) -> OptionCoverageSummary:
    symbol = ticker.strip().upper()
    selected = [quote for quote in quotes if quote.ticker == symbol]
    dates = sorted({quote.trade_date for quote in selected})
    expirations = {quote.expiration for quote in selected}
    rows_by_date = Counter(quote.trade_date for quote in selected)
    counts = list(rows_by_date.values())
    missing_bid_ask = sum(1 for quote in selected if not quote.has_executable_quote)
    missing_delta = sum(1 for quote in selected if quote.delta is None)
    warnings: list[str] = []
    if not selected:
        warnings.append("no_option_rows")
    if counts and min(counts) < min_rows_per_date_warning:
        warnings.append("low_contract_depth")
    if missing_bid_ask:
        warnings.append("missing_bid_ask")
    if missing_delta:
        warnings.append("missing_delta")

    return OptionCoverageSummary(
        ticker=symbol,
        start=dates[0] if dates else None,
        end=dates[-1] if dates else None,
        trade_dates=len(dates),
        option_rows=len(selected),
        expirations=len(expirations),
        missing_bid_ask_rows=missing_bid_ask,
        missing_delta_rows=missing_delta,
        min_rows_per_date=min(counts) if counts else 0,
        max_rows_per_date=max(counts) if counts else 0,
        average_rows_per_date=round(sum(counts) / len(counts), 2) if counts else 0.0,
        warnings=tuple(warnings),
    )


def format_option_coverage_report(summary: OptionCoverageSummary) -> str:
    warnings = ", ".join(summary.warnings) if summary.warnings else "none"
    return "\n".join(
        [
            f"# {summary.ticker} Options Coverage",
            "",
            "- dataset: option_chain_eod",
            f"- start: {summary.start}",
            f"- end: {summary.end}",
            f"- trade_dates: {summary.trade_dates}",
            f"- option_rows: {summary.option_rows}",
            f"- expirations: {summary.expirations}",
            f"- missing_bid_ask_rows: {summary.missing_bid_ask_rows}",
            f"- missing_delta_rows: {summary.missing_delta_rows}",
            f"- min_rows_per_date: {summary.min_rows_per_date}",
            f"- max_rows_per_date: {summary.max_rows_per_date}",
            f"- average_rows_per_date: {summary.average_rows_per_date:.2f}",
            f"- warnings: {warnings}",
            "",
        ]
    )


@dataclass(frozen=True)
class IntradayQuoteCoverage:
    ticker: str
    since: str | None
    until: str | None
    covered_days: int
    expected_trading_days: int | None
    missing_days: tuple[str, ...]
    option_rows: int
    rows_missing_spot: int
    min_rows_per_day: int
    max_rows_per_day: int
    avg_rows_per_day: float
    avg_expirations_per_day: float
    warnings: tuple[str, ...] = field(default_factory=tuple)


def summarize_intraday_quote_coverage(
    store,
    *,
    ticker: str,
    since: str | None = None,
    until: str | None = None,
    min_rows_per_day_warning: int = 5_000,
) -> IntradayQuoteCoverage:
    """Coverage over option_quote_bars_1m, with calendar gap detection when bounded."""
    symbol = ticker.strip().upper()
    coverage = store.intraday_quote_coverage(symbol, since=since, until=until)
    by_date = coverage["by_date"]
    counts = [int(row["rows"]) for row in by_date]
    expirations = [int(row["expirations"]) for row in by_date]
    covered = {row["trade_date"] for row in by_date}

    expected_days: int | None = None
    missing: tuple[str, ...] = ()
    if since is not None and until is not None:
        from trader.options.calendar import trading_days

        sessions = trading_days(date.fromisoformat(since), date.fromisoformat(until))
        expected_days = len(sessions)
        missing = tuple(day.isoformat() for day in sessions if day.isoformat() not in covered)

    warnings: list[str] = []
    if not by_date:
        warnings.append("no_intraday_rows")
    if missing:
        warnings.append("missing_trading_days")
    if counts and min(counts) < min_rows_per_day_warning:
        warnings.append("low_coverage_days")
    if coverage["rows_missing_spot"]:
        warnings.append("rows_missing_underlying_price")

    return IntradayQuoteCoverage(
        ticker=symbol,
        since=since,
        until=until,
        covered_days=len(by_date),
        expected_trading_days=expected_days,
        missing_days=missing,
        option_rows=sum(counts),
        rows_missing_spot=coverage["rows_missing_spot"],
        min_rows_per_day=min(counts) if counts else 0,
        max_rows_per_day=max(counts) if counts else 0,
        avg_rows_per_day=round(sum(counts) / len(counts), 2) if counts else 0.0,
        avg_expirations_per_day=round(sum(expirations) / len(expirations), 2) if expirations else 0.0,
        warnings=tuple(warnings),
    )


def format_intraday_quote_coverage_report(coverage: IntradayQuoteCoverage) -> str:
    warnings = ", ".join(coverage.warnings) if coverage.warnings else "none"
    lines = [
        f"# {coverage.ticker} Intraday Quote Coverage",
        "",
        "- dataset: option_quote_bars_1m",
        f"- since: {coverage.since}",
        f"- until: {coverage.until}",
        f"- covered_days: {coverage.covered_days}",
        f"- expected_trading_days: {coverage.expected_trading_days}",
        f"- missing_days: {len(coverage.missing_days)}",
        f"- option_rows: {coverage.option_rows}",
        f"- rows_missing_underlying_price: {coverage.rows_missing_spot}",
        f"- min_rows_per_day: {coverage.min_rows_per_day}",
        f"- max_rows_per_day: {coverage.max_rows_per_day}",
        f"- avg_rows_per_day: {coverage.avg_rows_per_day:.2f}",
        f"- avg_expirations_per_day: {coverage.avg_expirations_per_day:.2f}",
        f"- warnings: {warnings}",
    ]
    if coverage.missing_days:
        preview = ", ".join(coverage.missing_days[:10])
        suffix = " ..." if len(coverage.missing_days) > 10 else ""
        lines.append(f"- missing_days_sample: {preview}{suffix}")
    lines.append("")
    return "\n".join(lines)


# ── NBBO quote-quality report (streaming, one trade-date at a time) ──────────


@dataclass(frozen=True)
class NbboQualityReport:
    ticker: str
    start: date | None
    end: date | None
    days: int
    total_rows: int
    crossed_quotes: int
    locked_quotes: int
    nonpositive_size_rows: int
    absurd_spread_rows: int
    missing_quote_rows: int
    expirations: int
    expirations_with_gaps: int
    min_minutes_per_day: int
    max_minutes_per_day: int
    avg_minutes_per_day: float
    worst_examples: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


def summarize_nbbo_quality(
    source: QuoteSource,
    *,
    ticker: str,
    start: date,
    end: date,
    max_reasonable_spread_pct: float = 0.5,
    max_examples: int = 10,
) -> NbboQualityReport:
    """Stream one trade-date at a time and flag NBBO data-quality problems.

    Memory-safe: only one day of bars is held at a time. Flags:
    - crossed quotes (bid > ask),
    - locked quotes (bid == ask > 0),
    - non-positive bid/ask sizes,
    - absurd spreads (spread / mid > ``max_reasonable_spread_pct``),
    - missing bid or ask,
    - per-expiration coverage gaps (an expiration absent on some covered days),
    - minutes-present per day (distinct timestamps).
    """
    symbol = ticker.strip().upper()
    days = 0
    total_rows = 0
    crossed = locked = bad_size = absurd = missing = 0
    minutes_per_day: list[int] = []
    expiration_day_counts: Counter[date] = Counter()
    examples: list[str] = []

    for _trade_date, day_bars in source.iter_days(symbol, start, end):
        days += 1
        minutes: set = set()
        expirations_today: set[date] = set()
        for bar in day_bars:
            total_rows += 1
            minutes.add(bar.timestamp)
            expirations_today.add(bar.expiration)
            if bar.bid is None or bar.ask is None:
                missing += 1
                continue
            if bar.bid > bar.ask:
                crossed += 1
                if len(examples) < max_examples:
                    examples.append(f"crossed {bar.timestamp.isoformat()} {bar.strike}{bar.call_put} bid {bar.bid} > ask {bar.ask}")
            elif bar.bid == bar.ask and bar.bid > 0:
                locked += 1
            if (bar.bid_size is not None and bar.bid_size <= 0) or (bar.ask_size is not None and bar.ask_size <= 0):
                bad_size += 1
            mid = bar.mid
            if mid is not None and mid > 0 and bar.ask >= bar.bid and (bar.ask - bar.bid) / mid > max_reasonable_spread_pct:
                absurd += 1
                if len(examples) < max_examples:
                    examples.append(
                        f"wide {bar.timestamp.isoformat()} {bar.strike}{bar.call_put} "
                        f"spread {round((bar.ask - bar.bid) / mid, 3)}"
                    )
        minutes_per_day.append(len(minutes))
        for expiration in expirations_today:
            expiration_day_counts[expiration] += 1

    expirations = len(expiration_day_counts)
    expirations_with_gaps = sum(1 for count in expiration_day_counts.values() if days and count < days)

    warnings: list[str] = []
    if days == 0:
        warnings.append("no_intraday_rows")
    if crossed:
        warnings.append("crossed_quotes")
    if locked:
        warnings.append("locked_quotes")
    if bad_size:
        warnings.append("nonpositive_sizes")
    if absurd:
        warnings.append("absurd_spreads")
    if missing:
        warnings.append("missing_quotes")
    if expirations_with_gaps:
        warnings.append("expiration_coverage_gaps")

    return NbboQualityReport(
        ticker=symbol,
        start=start,
        end=end,
        days=days,
        total_rows=total_rows,
        crossed_quotes=crossed,
        locked_quotes=locked,
        nonpositive_size_rows=bad_size,
        absurd_spread_rows=absurd,
        missing_quote_rows=missing,
        expirations=expirations,
        expirations_with_gaps=expirations_with_gaps,
        min_minutes_per_day=min(minutes_per_day) if minutes_per_day else 0,
        max_minutes_per_day=max(minutes_per_day) if minutes_per_day else 0,
        avg_minutes_per_day=round(sum(minutes_per_day) / len(minutes_per_day), 2) if minutes_per_day else 0.0,
        worst_examples=tuple(examples),
        warnings=tuple(warnings),
    )


def format_nbbo_quality_report(report: NbboQualityReport) -> str:
    warnings = ", ".join(report.warnings) if report.warnings else "none"
    lines = [
        f"# {report.ticker} NBBO Quote Quality",
        "",
        "Research data-quality diagnostic over option_quote_bars_1m (streamed day-by-day).",
        "",
        f"- start: {report.start}",
        f"- end: {report.end}",
        f"- days: {report.days}",
        f"- total_rows: {report.total_rows}",
        f"- crossed_quotes: {report.crossed_quotes}",
        f"- locked_quotes: {report.locked_quotes}",
        f"- nonpositive_size_rows: {report.nonpositive_size_rows}",
        f"- absurd_spread_rows: {report.absurd_spread_rows}",
        f"- missing_quote_rows: {report.missing_quote_rows}",
        f"- expirations: {report.expirations}",
        f"- expirations_with_gaps: {report.expirations_with_gaps}",
        f"- min_minutes_per_day: {report.min_minutes_per_day}",
        f"- max_minutes_per_day: {report.max_minutes_per_day}",
        f"- avg_minutes_per_day: {report.avg_minutes_per_day:.2f}",
        f"- warnings: {warnings}",
    ]
    if report.worst_examples:
        lines.append("")
        lines.append("## Flagged examples")
        lines += [f"- {example}" for example in report.worst_examples]
    lines.append("")
    return "\n".join(lines)
