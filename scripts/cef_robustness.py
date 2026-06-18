#!/usr/bin/env python
"""Robustness addendum for the CEF activist-follow study.

Two checks the main study left open:
  1. Execution frictions — does the only broad signal (the ~+1m pop) survive
     realistic CEF round-trip costs? (computed on the 62 survivors we have)
  2. Survivorship bound — even crediting the 20 delisted/liquidated funds with a
     generous discount-capture, does the *shape* change (broad edge vs convex
     lottery)? (precise correction needs keyed delisted data; this bounds it)

Run: TRADER_SEC_USER_AGENT="name email" .venv/bin/python scripts/cef_robustness.py
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
from trader.catalysts.cef_study import compute_cef_event  # noqa: E402
from trader.catalysts.prices import fetch_daily  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))  # WARN
REPORT = ROOT / "research" / "cef_activist_study_report.md"


def main() -> int:
    identity = os.getenv("TRADER_SEC_USER_AGENT")
    if not identity:
        print("ERROR: set TRADER_SEC_USER_AGENT", file=sys.stderr)
        return 2

    campaigns = fetch_saba_cef_campaigns(date(2022, 1, 1), date(2025, 6, 30), identity=identity)
    bench_close, _ = fetch_daily("PCEF", date(2021, 1, 1), date(2026, 6, 9))

    e1m, e6m = [], []
    n_drop = 0
    for c in campaigns:
        px = fetch_daily(c.ticker, c.filing_date - timedelta(days=250), c.filing_date + timedelta(days=420))
        if px is None:
            n_drop += 1
            continue
        m = compute_cef_event(px[0], bench_close, c.filing_date)
        if m is None:
            n_drop += 1
            continue
        e1m.append(m.exc_1m)
        e6m.append(m.exc_6m)
    n = len(e1m)
    s1m, s6m = pd.Series(e1m), pd.Series(e6m)

    lines = ["", "---", "", "## Robustness Addendum", "",
             f"Survivors with data: {n} | delisted/resolved (no free price data): {n_drop}", ""]

    # 1) Execution frictions: subtract round-trip cost once from each gross excess.
    lines += ["### 1. Net of CEF execution frictions (round-trip cost)", "",
              "| round-trip cost | +1m net mean % | +1m % funds net>0 | +6m net mean % | +6m % funds net>0 |",
              "|---|---|---|---|---|"]
    for cost in (0.005, 0.010, 0.015):
        n1 = s1m - cost
        n6 = s6m - cost
        lines.append(
            f"| {cost*100:.1f}% | {n1.mean()*100:+.2f} | {(n1>0).mean():.0%} | "
            f"{n6.mean()*100:+.2f} | {(n6>0).mean():.0%} |"
        )
    lines += ["", "CEFs trade with wide spreads/low liquidity; ~1% round-trip is realistic.", ""]

    # 2) Survivorship bound: credit the n_drop resolved funds with assumed excess d.
    lines += ["### 2. Survivorship bound (precise needs keyed delisted data)", "",
              f"Gross +6m mean over survivors = {s6m.mean()*100:+.2f}% (median {s6m.median()*100:+.2f}%).",
              f"Crediting the {n_drop} resolved funds with an assumed excess d, the all-{n+n_drop} mean:", "",
              "| assumed resolved-fund excess d | all-fund +6m mean % |", "|---|---|"]
    for d in (0.0, 0.05, 0.10, 0.15):
        allmean = (n * s6m.mean() + n_drop * d) / (n + n_drop)
        lines.append(f"| {d*100:.0f}% | {allmean*100:+.2f} |")
    lines += ["",
              "Even at a generous d=15% (full discount capture on every resolved fund), the "
              "all-fund mean only reaches the mid-single digits, and the **survivor median "
              "stays ~0** — the profile is a convex/lottery (few big wins on resolution, most "
              "funds nothing), not a broad edge.", ""]

    with REPORT.open("a") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nAppended to {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
