#!/usr/bin/env python
"""Run the pre-registered T43 earnings-announcement premium study (end-to-end).

Pre-registration: research/earnings_premium_preregistration.md. Falsify-first.

Free data only: yfinance earnings dates (get_earnings_dates, <=100 rows/ticker)
and yfinance daily adjusted closes. Network-bound; the pure core lives in
trader.catalysts.earnings_premium and is unit-tested without I/O.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalysts.earnings_premium import (  # noqa: E402
    EVENT_WINDOWS,
    PRIMARY_WINDOW,
    ROUND_TRIP_COST,
    EarningsEvent,
    abnormal_returns,
    aggregate,
    compute_event,
    evaluate_gate,
    is_amc,
    jump_risk_correlation,
    mean,
    premium_vs_baseline,
    resolve_t0_index,
    sample_non_earnings_cars,
    t_stat_one_sample,
)
from trader.catalysts.prices import fetch_daily  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))
log = structlog.get_logger()

# --- Pre-registered universe (hardcoded BEFORE results; see pre-reg sec.3) ----
# 10 catalog single-name mega-caps (the catalog's 12 minus QQQ/SPY ETFs) ...
MEGA = ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "BRK-B", "JPM"]
# ... plus a fixed large/mid-cap list with reliable yfinance earnings dates.
LARGE_MID = [
    "AMD", "ORCL", "CRM", "COST", "NFLX", "ADBE", "INTC", "QCOM", "JNJ", "PFE",
    "MRK", "LLY", "ABBV", "UNH", "HD", "LOW", "WMT", "DIS", "NKE", "MCD",
    "KO", "PEP", "XOM", "CVX", "BA", "V", "MA", "BAC", "WFC", "GS",
    "MS", "CAT", "GE", "HON", "IBM", "CSCO", "TXN", "T", "VZ",
]
TICKERS = MEGA + LARGE_MID

SINCE = date(2015, 1, 1)
UNTIL = date(2025, 12, 31)
OOS_SPLIT_YEAR = 2020  # IS: event year <= 2020 ; OOS: >= 2021
N_PLACEBO_PER_TICKER = 60  # non-earnings windows sampled per ticker
SEED = 43

OUT_DIR = ROOT / "output" / "catalysts"
REPORT_PATH = ROOT / "research" / "earnings_premium_report.md"
RESULTS_PATH = ROOT / "data" / "earnings_premium_results.txt"
JSON_PATH = OUT_DIR / "earnings_premium_study.json"


def _fetch_earnings_with_amc(ticker: str) -> tuple[list[tuple[date, bool]], int]:
    """Return [(announcement_date, amc?), ...] in span, and the raw count seen.

    AMC inferred from the timestamp hour (US/Eastern); missing time -> AMC.
    """

    import yfinance as yf

    try:
        frame = yf.Ticker(ticker).get_earnings_dates(limit=100)
    except Exception as exc:  # pragma: no cover - network path
        log.warning("earn_dates_failed", ticker=ticker, error=str(exc))
        return [], 0
    if frame is None or frame.empty:
        return [], 0

    today = date.today()
    seen: dict[date, bool] = {}
    raw = 0
    for ts in frame.index:
        stamp = pd.Timestamp(ts)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        et = stamp.tz_convert("US/Eastern")
        d = et.date()
        if not (SINCE <= d <= UNTIL) or d >= today:
            continue
        raw += 1
        # Heuristic: if the hour is exactly midnight ET, yfinance likely had no
        # intraday time -> treat as missing (-> AMC).
        hour = None if (et.hour == 0 and et.minute == 0) else et.hour
        seen[d] = is_amc(hour)  # dedupe by date; last wins
    return sorted(seen.items()), raw


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    spy = fetch_daily("SPY", SINCE - timedelta(days=40), UNTIL + timedelta(days=40))
    if spy is None:
        print("ERROR: could not fetch SPY benchmark", file=sys.stderr)
        return 2
    spy_close, _ = spy

    events: list[EarningsEvent] = []
    placebo_cars: list[float] = []
    warnings: list[str] = []
    raw_dates = 0
    used_tickers = 0
    incomplete = 0

    for ticker in TICKERS:
        ann_list, raw = _fetch_earnings_with_amc(ticker)
        raw_dates += raw
        if not ann_list:
            warnings.append(f"{ticker}: no usable earnings dates in span")
            continue
        lo = min(d for d, _ in ann_list) - timedelta(days=20)
        hi = max(d for d, _ in ann_list) + timedelta(days=20)
        prices = fetch_daily(ticker, lo, hi)
        if prices is None:
            warnings.append(f"{ticker}: price history unavailable")
            continue
        close, _ = prices
        abn = abnormal_returns(close, spy_close)
        index = pd.DatetimeIndex(abn.index)

        ticker_events: list[EarningsEvent] = []
        t0_positions: list[int] = []
        for ann_date, amc in ann_list:
            ev = compute_event(abn, ann_date, ticker, amc=amc)
            if ev is None:
                incomplete += 1
                continue
            ticker_events.append(ev)
            t0 = resolve_t0_index(index, ann_date, amc=amc)
            if t0 is not None:
                t0_positions.append(t0)
        if not ticker_events:
            warnings.append(f"{ticker}: no complete event windows")
            continue
        used_tickers += 1
        events.extend(ticker_events)

        # Same-stock non-earnings placebo windows (the matched baseline).
        placebo_cars.extend(
            sample_non_earnings_cars(
                abn, t0_positions, n_samples=N_PLACEBO_PER_TICKER, rng=rng
            )
        )

    # ----- aggregate (PRIMARY window) -----
    primary_cars = [e.cars[PRIMARY_WINDOW] for e in events]
    stats = aggregate(primary_cars, label="announcement")
    placebo_stats = aggregate(placebo_cars, label="placebo")

    premium, premium_t = premium_vs_baseline(primary_cars, placebo_cars)

    # IS / OOS split on event year.
    is_cars = [e.cars[PRIMARY_WINDOW] for e in events if e.t0_date.year <= OOS_SPLIT_YEAR]
    oos_cars = [e.cars[PRIMARY_WINDOW] for e in events if e.t0_date.year > OOS_SPLIT_YEAR]
    is_after = [c - ROUND_TRIP_COST for c in is_cars]
    oos_after = [c - ROUND_TRIP_COST for c in oos_cars]

    # Jump-risk vs alpha.
    jr_corr = jump_risk_correlation(events)

    gate = evaluate_gate(
        n_events=len(events),
        after_cost_mean=stats.after_cost_mean,
        after_cost_t=stats.t_stat,
        is_mean=mean(is_after),
        is_n=len(is_cars),
        oos_mean=mean(oos_after),
        oos_n=len(oos_cars),
        placebo_mean=placebo_stats.gross_mean,
        placebo_t=placebo_stats.t_stat,
        premium_vs_base=premium,
    )

    # ----- secondary windows (reported, non-gating) -----
    secondary = {}
    for name in EVENT_WINDOWS:
        if name == PRIMARY_WINDOW:
            continue
        sc = aggregate([e.cars[name] for e in events], label=name)
        secondary[name] = sc

    # Top-5 contributor inspection (too-good tripwire hygiene).
    ranked = sorted(events, key=lambda e: e.cars[PRIMARY_WINDOW], reverse=True)
    top5 = ranked[:5]
    mean_ex_top5 = mean(
        [e.cars[PRIMARY_WINDOW] for e in ranked[5:]]
    ) if len(ranked) > 5 else float("nan")

    run_at = datetime.now(UTC).isoformat()
    warning_lines = [f"- {w}" for w in warnings] or ["- None"]

    lines = [
        "# T43 — Earnings-Announcement Premium Study Result",
        "",
        "Pre-registration: `research/earnings_premium_preregistration.md`.",
        "",
        "## Run metadata",
        f"- Run at: {run_at}",
        f"- Span: {SINCE} .. {UNTIL}",
        f"- Universe: {len(TICKERS)} tickers ({used_tickers} contributed events)",
        "- Benchmark: SPY; abnormal return = stock - SPY (beta=1)",
        f"- PRIMARY window: {PRIMARY_WINDOW} = {EVENT_WINDOWS[PRIMARY_WINDOW]} (event-day)",
        f"- Round-trip cost: {ROUND_TRIP_COST * 1e4:.0f} bps/event",
        f"- IS = year <= {OOS_SPLIT_YEAR}, OOS = year > {OOS_SPLIT_YEAR}",
        "",
        "## Sample accounting",
        f"- Raw earnings dates in span: {raw_dates}",
        f"- Complete-window events: {len(events)}",
        f"- Events dropped (incomplete/glitch window): {incomplete}",
        f"- Placebo (non-earnings) windows: {len(placebo_cars)}",
        "",
        "## Announcement-window premium (PRIMARY car_m1_p1)",
        f"- N events: {stats.n}",
        f"- Gross mean abnormal return: {stats.gross_mean * 100:+.3f}%",
        f"- After-cost mean: {stats.after_cost_mean * 100:+.3f}%",
        f"- After-cost t-stat: {stats.t_stat:+.2f}",
        f"- Median: {stats.median * 100:+.3f}%",
        f"- Win rate: {stats.win_rate * 100:.1f}%",
        f"- Event-window Sharpe (mean/std of CARs): {stats.sharpe:+.3f}",
        "",
        "## Same-stock non-earnings baseline (placebo)",
        f"- N windows: {placebo_stats.n}",
        f"- Mean abnormal return: {placebo_stats.gross_mean * 100:+.3f}%",
        f"- t-stat: {placebo_stats.t_stat:+.2f}",
        "",
        "## Premium net of baseline (the true announcement premium)",
        f"- Premium (event mean - non-earnings mean): {premium * 100:+.3f}%",
        f"- Welch t: {premium_t:+.2f}",
        "",
        "## IS / OOS (decay check)",
        f"- IS  (<= {OOS_SPLIT_YEAR}) after-cost mean: {mean(is_after) * 100:+.3f}% "
        f"(n={len(is_cars)}, t={t_stat_one_sample(is_after):+.2f})",
        f"- OOS (>  {OOS_SPLIT_YEAR}) after-cost mean: {mean(oos_after) * 100:+.3f}% "
        f"(n={len(oos_cars)}, t={t_stat_one_sample(oos_after):+.2f})",
        "",
        "## Jump-risk vs alpha",
        f"- Corr(|window CAR|, window vol): {jr_corr:+.3f}",
        "  (high positive => premium tracks jump-risk magnitude = compensated"
        " variance, not alpha)",
        "",
        "## Secondary windows (non-gating)",
        *[
            f"- {name}: gross {sc.gross_mean * 100:+.3f}% after-cost "
            f"{sc.after_cost_mean * 100:+.3f}% t={sc.t_stat:+.2f} (n={sc.n})"
            for name, sc in secondary.items()
        ],
        "",
        "## Too-good tripwire / top-5 contributor inspection",
        "- Top-5 event CARs: "
        + ", ".join(f"{e.ticker} {e.t0_date} {e.cars[PRIMARY_WINDOW] * 100:+.1f}%" for e in top5),
        f"- Mean ex-top-5: {mean_ex_top5 * 100:+.3f}% (vs full {stats.gross_mean * 100:+.3f}%)",
        "",
        "## Pre-registered gate verdict",
        f"### {'PASS' if gate.passed else 'FAIL'}",
        *[f"- {r}" for r in gate.reasons],
        "",
        "## Coverage warnings",
        *warning_lines,
        "",
    ]

    text = "\n".join(lines)
    try:
        REPORT_PATH.write_text(text)
        RESULTS_PATH.write_text(text)
        JSON_PATH.write_text(
            json.dumps(
                {
                    "run_at": run_at,
                    "n_events": len(events),
                    "n_placebo": len(placebo_cars),
                    "primary_gross_mean": stats.gross_mean,
                    "primary_after_cost_mean": stats.after_cost_mean,
                    "primary_after_cost_t": stats.t_stat,
                    "premium_net_of_baseline": premium,
                    "premium_t": premium_t,
                    "placebo_mean": placebo_stats.gross_mean,
                    "placebo_t": placebo_stats.t_stat,
                    "is_mean": mean(is_after),
                    "is_n": len(is_cars),
                    "oos_mean": mean(oos_after),
                    "oos_n": len(oos_cars),
                    "jump_risk_corr": jr_corr,
                    "gate_passed": gate.passed,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    except OSError as exc:
        print(f"ERROR: could not write outputs: {exc}", file=sys.stderr)
        return 3

    print(text)
    print(f"Report written: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
