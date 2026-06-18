#!/usr/bin/env python
"""Run the pre-registered large-cap post-earnings drift study."""

from __future__ import annotations

import json
import math
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalysts.event_driven import (  # noqa: E402
    CAR_WINDOWS,
    CohortStats,
    PeadEvent,
    aggregate_cohort,
    compute_pead_event,
)
from trader.catalysts.prices import fetch_daily  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
log = structlog.get_logger()

# Pre-registered parameters.
TICKERS = [
    "NVDA", "AVGO", "AMD", "ORCL", "CRM", "COST", "AAPL", "MSFT", "GOOGL", "META",
    "AMZN", "TSLA", "NFLX", "ADBE", "INTC", "QCOM", "MU", "AMAT", "LRCX", "KLAC",
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "PYPL", "AXP", "BLK",
    "JNJ", "PFE", "MRK", "LLY", "ABBV", "UNH", "CVS", "HD", "LOW", "WMT",
    "TGT", "DIS", "NKE", "MCD", "SBUX", "KO", "PEP", "XOM", "CVX", "BA",
]
SINCE = date(2020, 1, 1)
UNTIL = date(2025, 12, 31)
OOS_SPLIT_YEAR = 2022

OUT_DIR = ROOT / "output" / "catalysts"
REPORT_PATH = ROOT / "research" / "pead_report.md"
JSON_PATH = OUT_DIR / "pead_study.json"


def _fetch_earnings_dates(ticker: str) -> list[date]:
    import yfinance as yf

    frame = yf.Ticker(ticker).earnings_dates
    if frame is None or frame.empty:
        return []
    timestamps = pd.to_datetime(frame.index, errors="coerce", utc=True)
    today = date.today()
    dates = {
        timestamp.date()
        for timestamp in timestamps
        if not pd.isna(timestamp) and SINCE <= timestamp.date() <= UNTIL and timestamp.date() < today
    }
    return sorted(dates)


def _metric_values(events: list[PeadEvent], metric: str) -> list[float]:
    return [float(getattr(event, metric)) for event in events]


def _welch_t(left: list[float], right: list[float]) -> float:
    if len(left) < 2 or len(right) < 2:
        return 0.0
    left_series = pd.Series(left)
    right_series = pd.Series(right)
    denominator = math.sqrt(
        float(left_series.var(ddof=1)) / len(left)
        + float(right_series.var(ddof=1)) / len(right)
    )
    if denominator == 0 or denominator != denominator:
        return 0.0
    return float((left_series.mean() - right_series.mean()) / denominator)


def _cohort_diff(events: list[PeadEvent]) -> tuple[float, float]:
    positive = [event for event in events if event.prev_day_reaction > 0]
    negative = [event for event in events if event.prev_day_reaction < 0]
    pos_values = _metric_values(positive, "car_0_p21")
    neg_values = _metric_values(negative, "car_0_p21")
    if not pos_values or not neg_values:
        return float("nan"), 0.0
    difference = float(pd.Series(pos_values).mean() - pd.Series(neg_values).mean())
    return difference, _welch_t(pos_values, neg_values)


def _fmt_cohort_table(stats: CohortStats) -> str:
    rows = [
        "| window | n | mean % | median % | t-stat |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in CAR_WINDOWS:
        rows.append(
            f"| {name} | {stats.n} | {stats.means[name] * 100:+.2f} | "
            f"{stats.medians[name] * 100:+.2f} | {stats.t_stats[name]:+.2f} |"
        )
    return "\n".join(rows)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spy = fetch_daily("SPY", date(2019, 6, 1), date(2026, 6, 9))
    if spy is None:
        print("ERROR: could not fetch SPY", file=sys.stderr)
        return 2
    spy_close, _ = spy

    events: list[PeadEvent] = []
    warnings: list[str] = []
    dates_found = 0
    no_window = 0
    for ticker in TICKERS:
        try:
            earnings_dates = _fetch_earnings_dates(ticker)
        except Exception as exc:
            message = f"{ticker}: earnings dates unavailable ({exc})"
            warnings.append(message)
            log.warning("pead_earnings_failed", ticker=ticker, error=str(exc))
            continue
        dates_found += len(earnings_dates)
        if not earnings_dates:
            warnings.append(f"{ticker}: no earnings dates in study window")
            continue

        start = min(earnings_dates) - timedelta(days=100)
        end = max(earnings_dates) + timedelta(days=100)
        prices = fetch_daily(ticker, start, end)
        if prices is None:
            warnings.append(f"{ticker}: price history unavailable")
            continue
        close, _ = prices
        for earnings_date in earnings_dates:
            event = compute_pead_event(close, spy_close, earnings_date)
            if event is None:
                no_window += 1
                continue
            events.append(event)

    positive = [event for event in events if event.prev_day_reaction > 0]
    negative = [event for event in events if event.prev_day_reaction < 0]
    ties = len(events) - len(positive) - len(negative)
    pos_stats = aggregate_cohort(positive, "positive")
    neg_stats = aggregate_cohort(negative, "negative")
    primary_diff, primary_t = _cohort_diff(events)

    early = [event for event in events if event.event_date.year <= OOS_SPLIT_YEAR]
    late = [event for event in events if event.event_date.year > OOS_SPLIT_YEAR]
    early_diff, early_t = _cohort_diff(early)
    late_diff, late_t = _cohort_diff(late)

    enough_events = len(positive) + len(negative) >= 200
    primary_pass = primary_diff > 0 and primary_t >= 2.0
    oos_pass = early_diff > 0 and late_diff > 0
    gate_passed = enough_events and primary_pass and oos_pass
    reasons = [
        f"{'PASS' if enough_events else 'FAIL'}: N={len(positive) + len(negative)} (need >= 200)",
        f"{'PASS' if primary_pass else 'FAIL'}: positive-minus-negative car_0_p21 "
        f"diff={primary_diff:+.4f}, Welch t={primary_t:+.2f} (need diff > 0 and t >= 2.0)",
        f"{'PASS' if oos_pass else 'FAIL'}: OOS differences early={early_diff:+.4f}, "
        f"late={late_diff:+.4f} (both must be positive)",
    ]

    run_at = datetime.now(UTC).isoformat()
    warning_lines = [f"- {warning}" for warning in warnings] or ["- None"]
    lines = [
        "# PEAD Cohort-Split Event Study Result",
        "",
        "Pre-registration: `research/pead_preregistration.md`.",
        "",
        "## Run metadata",
        f"- Run at: {run_at}",
        f"- Earnings window: {SINCE} .. {UNTIL}",
        f"- Fixed universe: {len(TICKERS)} tickers",
        "- Benchmark: SPY; abnormal return = stock return minus SPY return (beta=1)",
        f"- OOS split: event year <= {OOS_SPLIT_YEAR} vs > {OOS_SPLIT_YEAR}",
        "",
        "## Sample accounting",
        f"- Earnings dates found: {dates_found}",
        f"- Events with complete windows: {len(events)}",
        f"- Positive cohort: {len(positive)}",
        f"- Negative cohort: {len(negative)}",
        f"- Exact-zero ties dropped: {ties}",
        f"- Events dropped for incomplete windows: {no_window}",
        "",
        "## Positive cohort",
        _fmt_cohort_table(pos_stats),
        "",
        "## Negative cohort",
        _fmt_cohort_table(neg_stats),
        "",
        "## Primary comparison",
        f"- Positive-minus-negative mean car_0_p21: {primary_diff:+.4f}",
        f"- Welch t-statistic: {primary_t:+.2f}",
        f"- Early half difference: {early_diff:+.4f} (t={early_t:+.2f})",
        f"- Late half difference: {late_diff:+.4f} (t={late_t:+.2f})",
        "",
        "## Pre-registered gate verdict",
        f"### {'PASS' if gate_passed else 'FAIL'}",
        *[f"- {reason}" for reason in reasons],
        "",
        "## Coverage warnings",
        *warning_lines,
        "",
    ]

    try:
        REPORT_PATH.write_text("\n".join(lines))
        JSON_PATH.write_text(
            json.dumps(
                {
                    "run_at": run_at,
                    "n_events": len(events),
                    "cohort_means": {
                        "pos": pos_stats.means,
                        "neg": neg_stats.means,
                    },
                    "diff_t_stats": {"primary": primary_t},
                    "gate_passed": gate_passed,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    except OSError as exc:
        print(f"ERROR: could not write study outputs: {exc}", file=sys.stderr)
        return 3

    print("\n".join(lines[-min(12, len(lines)) :]))
    print(f"Report written: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
