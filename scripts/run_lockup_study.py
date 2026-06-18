#!/usr/bin/env python
"""End-to-end runner for the pre-registered IPO lock-up event study (v1).

Pipeline:
  1. Build the genuine-IPO universe from SEC EDGAR (424B4/424B1 ∩ recent S-1,
     non-SPAC, no prior periodic report) for the pre-registered window.
  2. Fetch daily adjusted prices (yfinance) for each IPO ticker + SPY.
  3. Compute market-adjusted CARs and the realized-vol ratio around each
     lock-up expiry (real), plus a placebo window 60 trading days earlier.
  4. Apply the pre-registered liquidity filter, split out-of-sample, aggregate,
     and evaluate the gate.
  5. Write a markdown report.

Data artifacts (universe CSV) go under output/ (gitignored). The report under
research/ is the committable deliverable. Run from the worktree root:

  TRADER_SEC_USER_AGENT="name email" .venv/bin/python scripts/run_lockup_study.py
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

from trader.catalysts.ipo_universe import build_ipo_universe  # noqa: E402
from trader.catalysts.lockup_study import (  # noqa: E402
    CAR_WINDOWS,
    EventMetrics,
    aggregate,
    compute_event_metrics,
    evaluate_gate,
)
from trader.catalysts.prices import fetch_daily  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
log = structlog.get_logger()

# Pre-registered parameters.
SINCE = date(2019, 1, 1)
UNTIL = date(2025, 6, 30)
LIQUIDITY_MIN_DOLLAR_VOL = 5_000_000.0
PLACEBO_OFFSET = -60          # trading days (reduced from pre-reg's 90; see report)
OOS_SPLIT_YEAR = 2022         # ipo_date.year <= 2022 -> early; else late

OUT_DIR = ROOT / "output" / "catalysts"
REPORT_PATH = ROOT / "research" / "lockup_study_report.md"


def _fmt_agg_table(result) -> str:
    rows = ["| window | n | mean % | median % | % neg | t-stat |", "|---|---|---|---|---|---|"]
    for name in CAR_WINDOWS:
        w = result.windows[name]
        rows.append(
            f"| {name} | {w.n} | {w.mean * 100:+.2f} | {w.median * 100:+.2f} | "
            f"{w.pct_negative:.0%} | {w.t_stat:+.2f} |"
        )
    v = result.vol_ratio
    rows.append(f"| vol_ratio | {v.n} | {v.mean:.3f} | {v.median:.3f} | — | {v.t_stat:+.2f} |")
    return "\n".join(rows)


def main() -> int:
    identity = os.getenv("TRADER_SEC_USER_AGENT")
    if not identity:
        print("ERROR: set TRADER_SEC_USER_AGENT='name email' for SEC access", file=sys.stderr)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 1. Universe ---------------------------------------------------------
    log.info("stage_universe_start", since=SINCE.isoformat(), until=UNTIL.isoformat())
    events = build_ipo_universe(SINCE, UNTIL, identity=identity)
    universe_df = pd.DataFrame([e.__dict__ for e in events])
    universe_df.to_csv(OUT_DIR / "ipo_universe.csv", index=False)
    with_ticker = [e for e in events if e.ticker]
    log.info("stage_universe_done", ipos=len(events), with_ticker=len(with_ticker))

    # --- 2/3. Prices + metrics ----------------------------------------------
    spy = fetch_daily("SPY", date(2018, 6, 1), date(2026, 6, 9))
    if spy is None:
        print("ERROR: could not fetch SPY", file=sys.stderr)
        return 3
    spy_close, _ = spy

    real: list[EventMetrics] = []
    placebo: list[EventMetrics] = []
    n_no_price = n_no_window = 0
    for i, e in enumerate(with_ticker):
        if i % 50 == 0:
            log.info("stage_prices_progress", done=i, total=len(with_ticker),
                     real=len(real), no_price=n_no_price, no_window=n_no_window)
        px = fetch_daily(e.ticker, e.ipo_date - timedelta(days=5), e.lockup_expiry_date + timedelta(days=95))
        if px is None:
            n_no_price += 1
            continue
        close, volume = px
        m = compute_event_metrics(close, volume, spy_close, e.lockup_expiry_date)
        if m is None:
            n_no_window += 1
            continue
        real.append(m)
        mp = compute_event_metrics(close, volume, spy_close, e.lockup_expiry_date,
                                   offset_trading_days=PLACEBO_OFFSET)
        if mp is not None:
            placebo.append(mp)

    log.info("stage_metrics_done", real=len(real), placebo=len(placebo),
             no_price=n_no_price, no_window=n_no_window)

    # --- 4. Liquidity filter + OOS split + aggregate -------------------------
    liquid = [m for m in real if m.median_dollar_volume >= LIQUIDITY_MIN_DOLLAR_VOL]
    liquid_tickers = {m.ticker for m in liquid}
    liquid_placebo = [m for m in placebo if m.ticker in liquid_tickers]

    early = [m for m in liquid if m.t0_date.year <= OOS_SPLIT_YEAR]
    late = [m for m in liquid if m.t0_date.year > OOS_SPLIT_YEAR]

    res_real = aggregate(liquid, label="real")
    res_plac = aggregate(liquid_placebo, label="placebo")
    res_early = aggregate(early, label=f"oos<= {OOS_SPLIT_YEAR}")
    res_late = aggregate(late, label=f"oos> {OOS_SPLIT_YEAR}")
    verdict = evaluate_gate(res_real, res_plac, res_early, res_late)

    # --- 5. Report -----------------------------------------------------------
    lines = [
        "# IPO Lock-Up Expiry Event Study — v1 Result",
        "",
        "Pre-registration: `research/lockup_expiry_study_preregistration.md`.",
        "This is the underlying-only (v1) test. A pass here would justify the v2",
        "convexity (long-put) test; a fail kills the bucket cheaply.",
        "",
        "## Run metadata",
        f"- IPO pricing window: {SINCE} .. {UNTIL}",
        f"- Liquidity filter: median dollar volume >= ${LIQUIDITY_MIN_DOLLAR_VOL:,.0f} over [-30,-10]",
        f"- Placebo offset: {PLACEBO_OFFSET} trading days (reduced from pre-reg's -90 so the",
        "  placebo baseline stays within post-IPO history; stocks trade ~124 days IPO→lock-up)",
        f"- OOS split: lock-up year <= {OOS_SPLIT_YEAR} (early) vs > {OOS_SPLIT_YEAR} (late)",
        "- Abnormal return = stock return minus SPY return (beta=1, conservative)",
        "",
        "## Sample accounting",
        f"- Genuine IPOs in universe: {len(events)} (with ticker: {len(with_ticker)})",
        f"- Priced + full window (real): {len(real)}  | no price: {n_no_price}  | short window: {n_no_window}",
        f"- **Liquidity-filtered events (the study N): {len(liquid)}**",
        f"- Placebo events (liquid): {len(liquid_placebo)}",
        f"- OOS early (<= {OOS_SPLIT_YEAR}): {len(early)}  | OOS late: {len(late)}",
        "",
        "## Real window (around lock-up expiry)",
        _fmt_agg_table(res_real),
        "",
        "## Placebo window (60 trading days earlier)",
        _fmt_agg_table(res_plac),
        "",
        "## Pre-registered gate verdict",
        "",
        f"### {'✅ PASS' if verdict.passed else '❌ FAIL'}",
        "",
    ]
    lines += [f"- {r}" for r in verdict.reasons]
    lines += [
        "",
        "## Interpretation",
        "",
        "A negative result here is a *correct, cheap kill* of the cleanest catalyst",
        "in the supply thesis — and evidence the dated-supply idea is already",
        "arbitraged. A pass advances to the v2 convexity test (single-name options).",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n")

    print("\n".join(lines[-(len(verdict.reasons) + 12):]))
    print(f"\nReport written: {REPORT_PATH}")
    print(f"Universe CSV: {OUT_DIR / 'ipo_universe.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
