#!/usr/bin/env python
"""End-to-end runner: does following Saba's 13D into CEFs pay a follower?

Pre-registration: research/cef_activist_study_preregistration.md.
Run from the worktree root:
  TRADER_SEC_USER_AGENT="name email" .venv/bin/python scripts/run_cef_study.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalysts.cef_events import fetch_saba_cef_campaigns  # noqa: E402
from trader.catalysts.cef_study import (  # noqa: E402
    CefEventMetrics,
    aggregate,
    compute_cef_event,
    evaluate_gate,
)
from trader.catalysts.prices import fetch_daily  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
log = structlog.get_logger()

SINCE = date(2022, 1, 1)
UNTIL = date(2025, 6, 30)
BENCHMARK = "PCEF"
OOS_SPLIT_YEAR = 2023  # campaign year <= 2023 early, else late

OUT_DIR = ROOT / "output" / "catalysts"
REPORT_PATH = ROOT / "research" / "cef_activist_study_report.md"

_METRICS = ["exc_pre", "exc_ann", "exc_1m", "exc_3m", "exc_6m", "exc_12m"]
_LABELS = {
    "exc_pre": "pre-runup [-126,-1] (NOT capturable)",
    "exc_ann": "announcement [-1,+1]",
    "exc_1m": "capturable +1m",
    "exc_3m": "capturable +3m",
    "exc_6m": "capturable +6m (PRIMARY)",
    "exc_12m": "capturable +12m",
}


def _table(result) -> str:
    rows = ["| window | n | mean % | median % | % pos | t-stat |", "|---|---|---|---|---|---|"]
    for m in _METRICS:
        w = result.stats[m]
        rows.append(
            f"| {_LABELS[m]} | {w.n} | {w.mean * 100:+.2f} | {w.median * 100:+.2f} | "
            f"{w.pct_positive:.0%} | {w.t_stat:+.2f} |"
        )
    return "\n".join(rows)


def main() -> int:
    identity = os.getenv("TRADER_SEC_USER_AGENT")
    if not identity:
        print("ERROR: set TRADER_SEC_USER_AGENT", file=sys.stderr)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    log.info("stage_events_start")
    campaigns = fetch_saba_cef_campaigns(SINCE, UNTIL, identity=identity)
    pd.DataFrame([c.__dict__ for c in campaigns]).to_csv(OUT_DIR / "saba_cef_campaigns.csv", index=False)
    log.info("stage_events_done", campaigns=len(campaigns))

    bench = fetch_daily(BENCHMARK, date(2021, 1, 1), date(2026, 6, 9))
    if bench is None:
        print(f"ERROR: could not fetch benchmark {BENCHMARK}", file=sys.stderr)
        return 3
    bench_close, _ = bench

    real: list[CefEventMetrics] = []
    n_no_price = n_no_window = 0
    for i, c in enumerate(campaigns):
        if i % 20 == 0:
            log.info("stage_prices_progress", done=i, total=len(campaigns), real=len(real))
        px = fetch_daily(c.ticker, c.filing_date - timedelta(days=250), c.filing_date + timedelta(days=420))
        if px is None:
            n_no_price += 1
            continue
        close, _vol = px
        m = compute_cef_event(close, bench_close, c.filing_date)
        if m is None:
            n_no_window += 1
            continue
        real.append(m)

    log.info("stage_metrics_done", real=len(real), no_price=n_no_price, no_window=n_no_window)

    early = [m for m in real if m.t0_date.year <= OOS_SPLIT_YEAR]
    late = [m for m in real if m.t0_date.year > OOS_SPLIT_YEAR]
    res_real = aggregate(real, label="real")
    res_early = aggregate(early, label=f"oos<= {OOS_SPLIT_YEAR}")
    res_late = aggregate(late, label=f"oos> {OOS_SPLIT_YEAR}")
    verdict = evaluate_gate(res_real, res_early, res_late)

    lines = [
        "# Following Saba's 13D into CEFs — Event Study Result",
        "",
        "Pre-registration: `research/cef_activist_study_preregistration.md`.",
        "NAV-free: excess return = target CEF total return minus PCEF (broad-CEF ETF).",
        "Follower entry = the trading day AFTER the 13D is public (t0+1).",
        "",
        "## Run metadata",
        f"- Saba initial SC 13D window: {SINCE} .. {UNTIL}",
        f"- Benchmark: {BENCHMARK} (broad closed-end-fund ETF)",
        f"- OOS split: campaign year <= {OOS_SPLIT_YEAR} (early) vs > {OOS_SPLIT_YEAR} (late)",
        "",
        "## Sample accounting",
        f"- Saba CEF campaigns (initial 13D): {len(campaigns)}",
        f"- With >=6mo price history (study N): {len(real)}  | no price: {n_no_price}  | short window: {n_no_window}",
        f"- OOS early: {len(early)}  | OOS late: {len(late)}",
        "",
        "## Excess return vs PCEF, by window",
        _table(res_real),
        "",
        "## Pre-registered gate verdict",
        "",
        f"### {'✅ PASS' if verdict.passed else '❌ FAIL'}",
        "",
    ]
    lines += [f"- {r}" for r in verdict.reasons]
    lines += [
        "",
        "## How to read this",
        "",
        "The decomposition is the point: if the excess return sits in **pre-runup**",
        "and **announcement** but the **capturable +6m** drift (entering the day after",
        "the public filing) is flat, the activist edge is real but **priced by",
        "disclosure** — you'd have to BE the activist, not follow one. A positive,",
        "significant capturable +6m that exceeds the pre-runup is the rare good case.",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[-(len(verdict.reasons) + 14):]))
    print(f"\nReport: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
