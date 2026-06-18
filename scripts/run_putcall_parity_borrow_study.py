#!/usr/bin/env python
"""Run the pre-registered T26 put-call-parity / implied-borrow study (end-to-end).

Pre-registration: research/putcall_parity_borrow_preregistration.md. Falsify-first.

Reads the owned EOD option lake via the audited vol-surface loader (which fills
the underlying from yfinance), computes a per-(name, date) options-implied borrow
from near-the-money put-call-parity pairs, sorts names cross-sectionally each
month, and tests whether high-implied-borrow names under-perform after costs.
The pure core lives in trader.catalysts.putcall_parity_borrow and is unit-tested
without I/O. Only this runner touches the lake and yfinance.

HONEST PRIOR (pre-registered): our 24 single names are all easy-to-borrow
mega-caps, so implied borrow should be ~0 with no cross-sectional dispersion ->
the most-likely verdict is a DATA_WALL (wrong universe for the HTB effect).
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

from trader.catalysts.prices import fetch_daily  # noqa: E402
from trader.catalysts.putcall_parity_borrow import (  # noqa: E402
    FORWARD_WINDOWS,
    PRIMARY_WINDOW,
    SPREAD_COST,
    aggregate_spreads,
    cross_section_spread,
    evaluate_gate,
    forward_return,
    iqr,
    mean,
    median,
    name_date_borrow,
    t_stat_one_sample,
)
from trader.catalysts.vol_surface_data import load_option_quotes  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))
log = structlog.get_logger()

# --- Pre-registered universe (FIXED before results; see pre-reg sec.3) --------
# 24 fully-collected single names (2022-2026). AAPL/AMZN/NVDA EXCLUDED (still
# collecting). QQQ/SPY indices excluded from the single-name cross-section
# (an index has no borrow signal and SPY is the benchmark).
UNIVERSE = [
    "ADBE", "AMAT", "AMD", "AVGO", "BKNG", "COST", "CSCO", "GOOG", "GOOGL",
    "HON", "INTU", "ISRG", "LIN", "LRCX", "META", "MU", "NFLX", "PEP", "QCOM",
    "REGN", "TMUS", "TSLA", "TXN", "VRTX",
]
BENCH = "SPY"

SINCE = date(2022, 1, 1)
UNTIL = date(2026, 6, 13)
OOS_SPLIT_YEAR = 2023  # IS: trade-date year <= 2023 ; OOS: >= 2024
SEED = 26

OUT_DIR = ROOT / "output" / "catalysts"
REPORT_PATH = ROOT / "research" / "putcall_parity_borrow_report.md"
RESULTS_PATH = ROOT / "data" / "putcall_parity_borrow_results.txt"
JSON_PATH = OUT_DIR / "putcall_parity_borrow_study.json"


def _monthly_rebalance_dates(trade_dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
    """First available trade-date in each (year, month) — the monthly rebalances."""

    seen: dict[tuple[int, int], pd.Timestamp] = {}
    for d in sorted(trade_dates):
        key = (d.year, d.month)
        if key not in seen:
            seen[key] = d
    return [seen[k] for k in sorted(seen)]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    # ---- 1. per-(name, date) implied borrow from the option lake -------------
    # borrow_by_date[trade_date][ticker] = implied_borrow ; pairs_by_date for QA.
    borrow_by_date: dict[pd.Timestamp, dict[str, float]] = {}
    npairs_by_date: dict[pd.Timestamp, dict[str, int]] = {}
    per_name_borrow_samples: dict[str, list[float]] = {t: [] for t in UNIVERSE}
    all_trade_dates: set[pd.Timestamp] = set()
    name_coverage: dict[str, int] = {}

    for ticker in UNIVERSE:
        quotes = load_option_quotes(ticker, SINCE, UNTIL)
        if quotes.empty:
            log.warning("no_quotes", ticker=ticker)
            name_coverage[ticker] = 0
            continue
        days = 0
        for td, day_quotes in quotes.groupby(quotes["trade_date"].dt.normalize()):
            nb = name_date_borrow(day_quotes, ticker, td)
            if nb is None:
                continue
            borrow_by_date.setdefault(td, {})[ticker] = nb.implied_borrow
            npairs_by_date.setdefault(td, {})[ticker] = nb.n_pairs
            per_name_borrow_samples[ticker].append(nb.implied_borrow)
            all_trade_dates.add(td)
            days += 1
        name_coverage[ticker] = days
        log.info("name_done", ticker=ticker, days=days)

    if not borrow_by_date:
        print("ERROR: no implied-borrow observations from the lake", file=sys.stderr)
        return 2

    # ---- 2. forward returns (SPY-adjusted) -----------------------------------
    bench = fetch_daily(BENCH, SINCE - timedelta(days=10), UNTIL + timedelta(days=120))
    if bench is None:
        print("ERROR: could not fetch SPY benchmark", file=sys.stderr)
        return 2
    bench_close, _ = bench
    bench_close = bench_close.dropna().sort_index()

    closes: dict[str, pd.Series] = {}
    for ticker in UNIVERSE:
        px = fetch_daily(ticker, SINCE - timedelta(days=10), UNTIL + timedelta(days=120))
        if px is None:
            log.warning("no_prices", ticker=ticker)
            continue
        closes[ticker] = px[0].dropna().sort_index()

    # ---- 3. monthly cross-sectional spreads ----------------------------------
    rebal_dates = _monthly_rebalance_dates(sorted(all_trade_dates))
    spreads_by_window: dict[str, list[tuple[pd.Timestamp, float]]] = {w: [] for w in FORWARD_WINDOWS}
    dispersions: list[float] = []
    rebalance_records: list[dict] = []

    for td in rebal_dates:
        borrows = list(borrow_by_date.get(td, {}).items())
        if len(borrows) < 3:
            continue
        # Forward abnormal returns per window for the names present this date.
        for wname, horizon in FORWARD_WINDOWS.items():
            bench_fwd = forward_return(bench_close, td, horizon)
            if bench_fwd != bench_fwd:
                continue
            abn: dict[str, float] = {}
            for ticker, _ in borrows:
                if ticker not in closes:
                    continue
                fwd = forward_return(closes[ticker], td, horizon)
                if fwd == fwd:
                    abn[ticker] = fwd - bench_fwd
            rs = cross_section_spread(borrows, abn, td)
            if rs is None:
                continue
            spreads_by_window[wname].append((td, rs.spread))
            if wname == PRIMARY_WINDOW:
                dispersions.append(rs.borrow_dispersion)
                rebalance_records.append(
                    {
                        "date": td.date().isoformat(),
                        "n_names": rs.n_names,
                        "dispersion": rs.borrow_dispersion,
                        "high_borrow_ret": rs.high_borrow_ret,
                        "low_borrow_ret": rs.low_borrow_ret,
                        "spread": rs.spread,
                    }
                )

    primary = spreads_by_window[PRIMARY_WINDOW]
    primary_spreads = [s for _, s in primary]
    stats = aggregate_spreads(primary_spreads, label="primary")

    # IS / OOS split on rebalance date year.
    is_spreads = [s for td, s in primary if td.year <= OOS_SPLIT_YEAR]
    oos_spreads = [s for td, s in primary if td.year > OOS_SPLIT_YEAR]
    is_after = [s - SPREAD_COST for s in is_spreads]
    oos_after = [s - SPREAD_COST for s in oos_spreads]

    # Placebo: shuffle the borrow assignment within each rebalance date and rerun.
    placebo_spreads: list[float] = []
    for td in rebal_dates:
        borrows = list(borrow_by_date.get(td, {}).items())
        if len(borrows) < 3:
            continue
        bench_fwd = forward_return(bench_close, td, FORWARD_WINDOWS[PRIMARY_WINDOW])
        if bench_fwd != bench_fwd:
            continue
        names = [t for t, _ in borrows]
        vals = [b for _, b in borrows]
        shuffled = vals[:]
        rng.shuffle(shuffled)
        shuffled_borrows = list(zip(names, shuffled, strict=True))
        abn = {}
        for ticker in names:
            if ticker not in closes:
                continue
            fwd = forward_return(closes[ticker], td, FORWARD_WINDOWS[PRIMARY_WINDOW])
            if fwd == fwd:
                abn[ticker] = fwd - bench_fwd
        rs = cross_section_spread(shuffled_borrows, abn, td)
        if rs is not None:
            placebo_spreads.append(rs.spread)
    placebo_stats = aggregate_spreads(placebo_spreads, label="placebo")

    median_dispersion = median(dispersions)

    gate = evaluate_gate(
        n_spreads=stats.n,
        after_cost_mean=stats.after_cost_mean,
        after_cost_t=stats.t_stat,
        is_mean=mean(is_after),
        is_n=len(is_spreads),
        oos_mean=mean(oos_after),
        oos_n=len(oos_spreads),
        median_borrow_dispersion=median_dispersion,
        placebo_t=placebo_stats.t_stat,
    )

    # ---- cross-sectional borrow level/dispersion QA (the DATA_WALL evidence) --
    per_name_median_borrow = {
        t: median(s) for t, s in per_name_borrow_samples.items() if s
    }
    pooled_name_medians = [v for v in per_name_median_borrow.values() if v == v]
    cross_name_iqr = iqr(pooled_name_medians)

    # Secondary windows.
    secondary = {}
    for w in FORWARD_WINDOWS:
        if w == PRIMARY_WINDOW:
            continue
        sc = aggregate_spreads([s for _, s in spreads_by_window[w]], label=w)
        secondary[w] = sc

    # Top contributor inspection (too-good hygiene), on the PRIMARY spreads.
    ranked = sorted(rebalance_records, key=lambda r: abs(r["spread"]), reverse=True)
    top5 = ranked[:5]

    run_at = datetime.now(UTC).isoformat()

    lines = [
        "# T26 — Put-Call Parity / Implied Borrow Study Result",
        "",
        "Pre-registration: `research/putcall_parity_borrow_preregistration.md`.",
        "",
        "## Run metadata",
        f"- Run at: {run_at}",
        f"- Span: {SINCE} .. {UNTIL}",
        f"- Universe: {len(UNIVERSE)} single names (AAPL/AMZN/NVDA excluded: collecting)",
        f"- Benchmark: {BENCH}; abnormal fwd return = stock_fwd - SPY_fwd (beta=1)",
        f"- PRIMARY window: {PRIMARY_WINDOW} ({FORWARD_WINDOWS[PRIMARY_WINDOW]} td)",
        "- Rebalance: monthly (first trade-date each month)",
        f"- Round-trip cost: {SPREAD_COST * 1e4:.0f} bps/rebalance (long-short, 2 legs)",
        f"- IS = year <= {OOS_SPLIT_YEAR}, OOS = year > {OOS_SPLIT_YEAR}",
        "",
        "## Implied-borrow level & dispersion (the DATA_WALL evidence)",
        "Per-name median implied carry q* (annualized; ~borrow for these "
        "zero/low-div names):",
        *[
            f"  - {t}: {per_name_median_borrow[t] * 1e4:+8.1f} bps/yr "
            f"(n_days={name_coverage.get(t, 0)})"
            for t in UNIVERSE
            if t in per_name_median_borrow
        ],
        f"- Cross-name pooled median q*: {median(pooled_name_medians) * 1e4:+.1f} bps/yr",
        f"- Cross-name IQR of median q* (the dispersion to sort on): "
        f"{cross_name_iqr * 1e4:+.1f} bps/yr",
        f"- Median per-date top-minus-bottom-tercile borrow dispersion: "
        f"{median_dispersion * 1e4:+.1f} bps/yr",
        "",
        "## Cross-sectional spread (PRIMARY fwd_21d, low-borrow minus high-borrow)",
        f"- N rebalances: {stats.n}",
        f"- Gross mean spread: {stats.gross_mean * 100:+.4f}%",
        f"- After-cost mean spread: {stats.after_cost_mean * 100:+.4f}%",
        f"- After-cost t-stat: {stats.t_stat:+.2f}",
        f"- Median spread: {stats.median * 100:+.4f}%",
        f"- Win rate (spread > 0): {stats.win_rate * 100:.1f}%",
        f"- Spread Sharpe (mean/std): {stats.sharpe:+.3f}",
        "",
        "## IS / OOS (decay check)",
        f"- IS  (<= {OOS_SPLIT_YEAR}) after-cost: {mean(is_after) * 100:+.4f}% "
        f"(n={len(is_spreads)}, t={t_stat_one_sample(is_after):+.2f})",
        f"- OOS (>  {OOS_SPLIT_YEAR}) after-cost: {mean(oos_after) * 100:+.4f}% "
        f"(n={len(oos_spreads)}, t={t_stat_one_sample(oos_after):+.2f})",
        "",
        "## Placebo (shuffled-borrow sort)",
        f"- N: {placebo_stats.n}",
        f"- Mean spread: {placebo_stats.gross_mean * 100:+.4f}%",
        f"- t-stat: {placebo_stats.t_stat:+.2f}",
        "",
        "## Secondary windows (non-gating)",
        *[
            f"- {name}: gross {sc.gross_mean * 100:+.4f}% after-cost "
            f"{sc.after_cost_mean * 100:+.4f}% t={sc.t_stat:+.2f} (n={sc.n})"
            for name, sc in secondary.items()
        ],
        "",
        "## Top-5 |spread| rebalances (contributor inspection)",
        *[
            f"- {r['date']}: spread {r['spread'] * 100:+.2f}% "
            f"(low {r['low_borrow_ret'] * 100:+.2f}% / high {r['high_borrow_ret'] * 100:+.2f}%, "
            f"disp {r['dispersion'] * 1e4:+.0f}bps, n={r['n_names']})"
            for r in top5
        ],
        "",
        "## Pre-registered gate verdict",
        f"### {'DATA_WALL' if gate.data_wall else ('PASS' if gate.passed else 'FAIL')}",
        *[f"- {r}" for r in gate.reasons],
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
                    "n_rebalances": stats.n,
                    "primary_gross_spread": stats.gross_mean,
                    "primary_after_cost_spread": stats.after_cost_mean,
                    "primary_after_cost_t": stats.t_stat,
                    "is_mean": mean(is_after),
                    "is_n": len(is_spreads),
                    "oos_mean": mean(oos_after),
                    "oos_n": len(oos_spreads),
                    "placebo_mean": placebo_stats.gross_mean,
                    "placebo_t": placebo_stats.t_stat,
                    "cross_name_pooled_median_borrow": median(pooled_name_medians),
                    "cross_name_iqr_borrow": cross_name_iqr,
                    "median_tercile_dispersion": median_dispersion,
                    "gate_passed": gate.passed,
                    "data_wall": gate.data_wall,
                    "per_name_median_borrow_bps": {
                        t: per_name_median_borrow[t] * 1e4
                        for t in per_name_median_borrow
                    },
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
