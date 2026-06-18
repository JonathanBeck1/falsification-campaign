#!/usr/bin/env python
"""Run Phase 2 end-to-end on the news catalog.

  1. Load the cleaned catalog (dedup'd to unique events).
  2. Fetch daily prices for each ticker + SPY (yfinance, free).
  3. Per event, compute market-adjusted CAR over [+1,+5], [+1,+21], [+1,+63].
  4. Aggregate per (category, direction) cohort.
  5. Apply pre-registered gate: N>=30, |t|>=2 at +21d, OOS sign stable.
  6. Write phase2_report.md and phase2_results.json.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalog.phase2 import (  # noqa: E402
    aggregate_cohort,
    compute_drift_for_event,
    evaluate_drift_gate,
)

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))
log = structlog.get_logger()

CLEAN_CATALOG = ROOT / "output" / "catalysts" / "news_catalog_clean.parquet"
REPORT = ROOT / "research" / "phase2_report.md"
RESULTS_JSON = ROOT / "output" / "catalysts" / "phase2_results.json"
PRICE_START = "2019-11-01"   # need lookback for ARs
PRICE_END = "2026-06-10"


def fetch_close(ticker: str) -> pd.Series | None:
    import yfinance as yf
    try:
        df = yf.download(ticker, start=PRICE_START, end=PRICE_END,
                         auto_adjust=True, progress=False, threads=False)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(axis=1, level=1)
    s = df["Close"].dropna()
    s.index = pd.DatetimeIndex(s.index)
    return s


def main() -> int:
    catalog = pd.read_parquet(CLEAN_CATALOG)
    catalog["date"] = pd.to_datetime(catalog["date"]).dt.date
    print(f"loaded clean catalog: {len(catalog)} events", flush=True)

    tickers = sorted(catalog.ticker.unique())
    print(f"fetching prices for {len(tickers)} tickers + SPY", flush=True)
    closes: dict[str, pd.Series] = {}
    for t in [*tickers, "SPY"]:
        s = fetch_close(t)
        if s is not None:
            closes[t] = s
        print(f"  {t}: {0 if s is None else len(s)} days", flush=True)
    if "SPY" not in closes:
        print("ERROR: could not fetch SPY", file=sys.stderr)
        return 2
    spy = closes["SPY"]

    # Per-event drift
    print("\ncomputing per-event drift...", flush=True)
    rows = []
    skipped = 0
    for _, ev in catalog.iterrows():
        t = ev["ticker"]
        if t not in closes:
            skipped += 1
            continue
        d = compute_drift_for_event(closes[t], spy, ev["date"])
        if d is None:
            skipped += 1
            continue
        rows.append({
            "ticker": t,
            "date": ev["date"],
            "daily_return": ev["daily_return"],
            "direction": ev["direction"],
            "category": ev["category"],
            "confidence": ev["confidence"],
            **d,
        })
    drift_df = pd.DataFrame(rows)
    print(f"events with drift computed: {len(drift_df)} (skipped {skipped})", flush=True)

    # Aggregate per (category, direction)
    cohort_results = []
    gate_results = []
    categories = sorted(drift_df.category.unique())
    for cat in categories:
        for dirn in ("up", "down"):
            m = aggregate_cohort(drift_df, cat, dirn)
            if m is None:
                continue
            cohort_results.append(asdict(m))
            v = evaluate_drift_gate(m)
            gate_results.append({
                "cohort": v.cohort,
                "passed": v.passed,
                "reasons": v.reasons,
                "metrics": asdict(m),
            })

    # Sort gate results: passes first, then by |t|
    gate_results.sort(key=lambda r: (-int(r["passed"]), -abs(r["metrics"]["t_p1_p21"])))

    # Write JSON
    RESULTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(json.dumps({
        "n_events_classified": len(catalog),
        "n_events_with_drift": len(drift_df),
        "cohorts": gate_results,
    }, indent=2, default=str))

    # Write markdown report
    lines = ["# Phase 2 — Catalyst-Drift Analysis", ""]
    lines.append(f"- Catalog (deduped): **{len(catalog)} unique events**")
    lines.append(f"- Events with computable drift: **{len(drift_df)}**")
    lines.append("- Window: market-adjusted CAR[+1,+21] vs SPY (beta=1)")
    lines.append("- t0 = move date, measurement window EXCLUDES t0 (no look-ahead)")
    lines.append("- Gate: N>=30 AND |t|>=2 AND OOS sign stable (2020-22 vs 2023-26)")
    lines.append("")

    survivors = [r for r in gate_results if r["passed"]]
    lines.append(f"## Verdict: **{len(survivors)} cohort(s) survive** out of {len(gate_results)} tested")
    lines.append("")
    # Honest expected-noise note
    expected_noise = 0.05 * len(gate_results)
    lines.append(f"_Note: at naive p<0.05, you'd expect ~{expected_noise:.1f} winners from pure noise across "
                 f"{len(gate_results)} cohorts. Be skeptical of single-cohort passes._")
    lines.append("")

    if survivors:
        lines.append("### 🟡 Cohorts that passed the gate")
        lines.append("")
        for r in survivors:
            m = r["metrics"]
            lines.append(f"**{r['cohort']}** (N={m['n']}):")
            for reason in r["reasons"]:
                lines.append(f"- {reason}")
            lines.append(f"- median +21d CAR: {m['median_car_p1_p21']*100:+.2f}%, "
                         f"% positive: {m['pct_positive_p21']*100:.0f}%")
            lines.append("")

    lines.append("## Full leaderboard (all cohorts, by |t-stat|)")
    lines.append("")
    lines.append("| cohort | N | CAR+21 mean % | t | % pos | early N | early CAR % | late N | late CAR % | gate |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in gate_results:
        m = r["metrics"]
        lines.append(
            f"| {r['cohort']} | {m['n']} | {m['mean_car_p1_p21']*100:+.2f} | {m['t_p1_p21']:+.2f} | "
            f"{m['pct_positive_p21']*100:.0f}% | {m['n_early']} | {m['mean_early']*100:+.2f} | "
            f"{m['n_late']} | {m['mean_late']*100:+.2f} | {'✅' if r['passed'] else '❌'} |"
        )

    REPORT.write_text("\n".join(lines) + "\n")
    print(f"\nreport: {REPORT}")
    print(f"json:   {RESULTS_JSON}")
    print(f"\nVERDICT: {len(survivors)} survivor cohort(s) out of {len(gate_results)} tested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
