#!/usr/bin/env python
"""End-to-end runner for the pre-registered Sell-in-May / Halloween study (T49).

Pipeline:
  1. Fetch full-history SPY daily adjusted close (yfinance).
  2. Resample to month-end returns; split by calendar season (Nov-Apr winter /
     May-Oct summer) -- ex-ante, calendar-defined, no look-ahead.
  3. Build the seasonal allocation (SPY in winter, cash in summer) and the
     buy-and-hold benchmark; compute annualized return, vol, and Sharpe for both,
     after the once-a-year round-trip cost.
  4. Welch t-test on winter vs summer monthly returns; IS/OOS split (early vs
     late half of the monthly series) for both the seasonal difference and the
     Sharpe-vs-B&H verdict.
  5. Apply the pre-registered gate (decisive check: seasonal Sharpe > B&H Sharpe)
     and write a markdown report + raw numbers.

Report under research/ and raw output under data/ are the deliverables. Run from
the worktree root:

  .venv/bin/python scripts/run_sell_in_may_study.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalysts.prices import fetch_daily  # noqa: E402
from trader.catalysts.sell_in_may import (  # noqa: E402
    ROUND_TRIP_COST,
    annualized_sharpe,
    buy_and_hold_returns,
    evaluate_gate,
    mean,
    seasonal_strategy_returns,
    split_by_season,
    std,
    summarize_strategy,
    to_monthly_returns,
    welch_t,
)

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
log = structlog.get_logger()

# Pre-registered parameters.
RF_MONTHLY_PRIMARY = 0.0          # conservative: 0% while in cash (pre-reg sec.3)
RF_MONTHLY_SENSITIVITY = 0.02 / 12  # secondary sensitivity ~2%/yr (NOT the gate)
FETCH_START = date(1990, 1, 1)    # before SPY inception (1993-01-29); yf clips it
FETCH_END = date(2026, 6, 14)

REPORT_PATH = ROOT / "research" / "sell_in_may_decision.md"
RAW_PATH = ROOT / "data" / "sell_in_may_results.txt"


def _strat_streams(monthly: pd.Series, *, rf_monthly: float):
    seasonal = seasonal_strategy_returns(
        monthly, rf_monthly=rf_monthly, round_trip_cost=ROUND_TRIP_COST
    )
    bh = buy_and_hold_returns(monthly)
    time_in_market = sum(1 for ts in monthly.index if ts.month in {11, 12, 1, 2, 3, 4}) / len(monthly)
    s_stats = summarize_strategy(
        seasonal, label="seasonal", rf_monthly=rf_monthly, time_in_market=time_in_market
    )
    b_stats = summarize_strategy(bh, label="buy_and_hold", rf_monthly=rf_monthly, time_in_market=1.0)
    return seasonal, bh, s_stats, b_stats, time_in_market


def main() -> int:
    log.info("fetch_spy_start", start=FETCH_START.isoformat(), end=FETCH_END.isoformat())
    spy = fetch_daily("SPY", FETCH_START, FETCH_END)
    if spy is None:
        print("ERROR: could not fetch SPY from yfinance", file=sys.stderr)
        return 3
    spy_close, _ = spy
    monthly = to_monthly_returns(spy_close)
    if len(monthly) < 60:
        print(f"ERROR: only {len(monthly)} monthly returns; need full history", file=sys.stderr)
        return 4

    first, last = monthly.index[0], monthly.index[-1]
    log.info("monthly_built", n=len(monthly), first=str(first.date()), last=str(last.date()))

    # --- full-sample season split + seasonal difference ----------------------
    split_full = split_by_season(monthly)
    diff_t_full = welch_t(split_full.winter, split_full.summer)
    win_mean, sum_mean = mean(split_full.winter), mean(split_full.summer)

    # --- strategy vs buy-and-hold (PRIMARY: rf=0%) ---------------------------
    _, _, s_stats, b_stats, _ = _strat_streams(monthly, rf_monthly=RF_MONTHLY_PRIMARY)

    # --- sensitivity: rf ~2%/yr in cash --------------------------------------
    _, _, s_stats_rf, _, _ = _strat_streams(monthly, rf_monthly=RF_MONTHLY_SENSITIVITY)
    seasonal_rf_sharpe = annualized_sharpe(
        seasonal_strategy_returns(monthly, rf_monthly=RF_MONTHLY_SENSITIVITY, round_trip_cost=ROUND_TRIP_COST),
        rf_monthly=RF_MONTHLY_SENSITIVITY,
    )

    # --- IS / OOS split (early vs late half of the monthly series) -----------
    mid = len(monthly) // 2
    monthly_is, monthly_oos = monthly.iloc[:mid], monthly.iloc[mid:]
    split_is, split_oos = split_by_season(monthly_is), split_by_season(monthly_oos)

    _, _, sis_stats, bis_stats, _ = _strat_streams(monthly_is, rf_monthly=RF_MONTHLY_PRIMARY)
    _, _, soos_stats, boos_stats, _ = _strat_streams(monthly_oos, rf_monthly=RF_MONTHLY_PRIMARY)

    # --- gate ----------------------------------------------------------------
    verdict = evaluate_gate(
        split_full,
        s_stats,
        b_stats,
        diff_t_full,
        split_is,
        split_oos,
        sis_stats.sharpe,
        bis_stats.sharpe,
        soos_stats.sharpe,
        boos_stats.sharpe,
    )

    # --- raw dump ------------------------------------------------------------
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw_lines = [
        "T49 Sell-in-May / Halloween indicator -- raw run output",
        f"sample: {first.date()} .. {last.date()}  (n_months={len(monthly)})",
        f"IS: {monthly_is.index[0].date()}..{monthly_is.index[-1].date()} (n={len(monthly_is)})",
        f"OOS: {monthly_oos.index[0].date()}..{monthly_oos.index[-1].date()} (n={len(monthly_oos)})",
        "",
        "--- seasonal split (monthly returns) ---",
        f"winter (Nov-Apr): n={split_full.n_winter} mean={win_mean:+.5f} std={std(split_full.winter):.5f}",
        f"summer (May-Oct): n={split_full.n_summer} mean={sum_mean:+.5f} std={std(split_full.summer):.5f}",
        f"winter-summer Welch t = {diff_t_full:+.3f}",
        "",
        "--- seasonal strategy vs buy-and-hold (PRIMARY rf=0%, after cost) ---",
        f"seasonal:     ann_ret={s_stats.ann_return:+.4f} ann_vol={s_stats.ann_vol:.4f} "
        f"Sharpe={s_stats.sharpe:+.3f} time_in_mkt={s_stats.time_in_market:.2%}",
        f"buy_and_hold: ann_ret={b_stats.ann_return:+.4f} ann_vol={b_stats.ann_vol:.4f} "
        f"Sharpe={b_stats.sharpe:+.3f} time_in_mkt={b_stats.time_in_market:.2%}",
        f"Sharpe edge (seasonal - B&H) = {s_stats.sharpe - b_stats.sharpe:+.3f}",
        "",
        "--- sensitivity: cash earns ~2%/yr (NOT the gate) ---",
        f"seasonal Sharpe @rf2% = {seasonal_rf_sharpe:+.3f}  ann_ret={s_stats_rf.ann_return:+.4f}",
        "",
        "--- IS / OOS ---",
        f"IS  winter-summer diff = {mean(split_is.winter) - mean(split_is.summer):+.5f} "
        f"(seasonal Sharpe={sis_stats.sharpe:+.3f} vs B&H={bis_stats.sharpe:+.3f})",
        f"OOS winter-summer diff = {mean(split_oos.winter) - mean(split_oos.summer):+.5f} "
        f"(seasonal Sharpe={soos_stats.sharpe:+.3f} vs B&H={boos_stats.sharpe:+.3f})",
        "",
        "--- gate ---",
        *verdict.reasons,
        "",
        f"PASSED: {verdict.passed}",
    ]
    RAW_PATH.write_text("\n".join(raw_lines) + "\n")

    # --- report --------------------------------------------------------------
    killed = not verdict.passed
    sharpe_edge = s_stats.sharpe - b_stats.sharpe
    exposure_story = sharpe_edge <= 0
    lines = [
        "# Decision: Sell-in-May / Halloween Indicator (T49)",
        "",
        "Pre-registration: `research/sell_in_may_preregistration.md`. Falsify-first.",
        "",
        "## Verdict",
        "",
        (
            "### ❌ KILL — "
            + (
                "seasonal allocation does NOT beat buy-and-hold on Sharpe; the lower "
                "drawdown is reduced market exposure (beta), not alpha."
                if exposure_story
                else "seasonal split real but failed a pre-registered gate (see below)."
            )
            if killed
            else "### ✅ SURVIVES — after-cost seasonal Sharpe exceeds buy-and-hold and is OOS-stable."
        ),
        "",
        "## Numbers (after-cost, full sample, PRIMARY rf=0%)",
        "",
        "| metric | value |",
        "|---|---|",
        f"| sample | {first.date()} .. {last.date()} ({len(monthly)} months) |",
        f"| winter (Nov-Apr) mean monthly | {win_mean:+.4%} (n={split_full.n_winter}) |",
        f"| summer (May-Oct) mean monthly | {sum_mean:+.4%} (n={split_full.n_summer}) |",
        f"| winter-summer Welch t | {diff_t_full:+.2f} |",
        f"| seasonal ann. return | {s_stats.ann_return:+.2%} |",
        f"| buy-and-hold ann. return | {b_stats.ann_return:+.2%} |",
        f"| seasonal ann. vol | {s_stats.ann_vol:.2%} |",
        f"| buy-and-hold ann. vol | {b_stats.ann_vol:.2%} |",
        f"| **seasonal Sharpe** | **{s_stats.sharpe:+.3f}** |",
        f"| **buy-and-hold Sharpe** | **{b_stats.sharpe:+.3f}** |",
        f"| Sharpe edge (seasonal - B&H) | {sharpe_edge:+.3f} |",
        f"| seasonal time-in-market | {s_stats.time_in_market:.1%} |",
        f"| seasonal Sharpe @ cash=2%/yr (sensitivity) | {seasonal_rf_sharpe:+.3f} |",
        "",
        "## IS vs OOS (early half / late half)",
        "",
        "| half | span | winter-summer diff | seasonal Sharpe | B&H Sharpe |",
        "|---|---|---|---|---|",
        f"| IS | {monthly_is.index[0].date()}..{monthly_is.index[-1].date()} | "
        f"{mean(split_is.winter) - mean(split_is.summer):+.4%} | {sis_stats.sharpe:+.3f} | {bis_stats.sharpe:+.3f} |",
        f"| OOS | {monthly_oos.index[0].date()}..{monthly_oos.index[-1].date()} | "
        f"{mean(split_oos.winter) - mean(split_oos.summer):+.4%} | {soos_stats.sharpe:+.3f} | {boos_stats.sharpe:+.3f} |",
        "",
        "## Gate result (each line PASS/FAIL)",
        "",
        *[f"- {r}" for r in verdict.reasons],
        "",
        f"### {'✅ PASS' if verdict.passed else '❌ FAIL'}",
        "",
        "## Friction note",
        "",
        "The seasonal strategy trades ~twice a year (one round trip), so total",
        f"friction is ~{ROUND_TRIP_COST * 1e4:.0f} bps/yr -- immaterial to the verdict. This idea",
        "does not live or die on costs; it lives or dies on whether holding cash",
        "half the year buys *risk-adjusted* return or merely *less risk*.",
        "",
        "## Artifact class (if killed)",
        "",
        (
            "**Decayed / exposure-driven (not alpha).** The winter>summer split can be "
            "statistically real while the seasonal *strategy* offers no Sharpe edge over "
            "buy-and-hold: it simply holds ~half the market exposure, so it shows lower "
            "vol and lower drawdown without higher reward-per-unit-risk. That is risk "
            "reduction, not edge -- the same dollar of risk-budget in B&H sized down "
            "would match it. (brain/30: real-mechanism-but-no-survivable-edge.)"
            if exposure_story
            else "See failing gate line(s) above."
        ),
        "",
        "## Honest verdict",
        "",
        (
            f"Winter monthly returns ({win_mean:+.3%}) are "
            f"{'higher than' if win_mean > sum_mean else 'not higher than'} summer "
            f"({sum_mean:+.3%}) directionally, but the gap is "
            f"{'statistically real' if abs(diff_t_full) >= 2.0 else 'in-noise'} "
            f"(Welch t={diff_t_full:+.2f}). The seasonal "
            f"strategy's Sharpe ({s_stats.sharpe:+.3f}) "
            f"{'does NOT beat' if exposure_story else 'beats'} buy-and-hold's ({b_stats.sharpe:+.3f}). "
            + (
                "The strategy's only genuine benefit is lower volatility/drawdown from being "
                "in cash half the year -- that is reduced exposure, not alpha. A kill here does "
                "NOT prove winter == summer in raw mean; it proves the publicized 'edge' offers "
                "no risk-adjusted advantage net of its lower market participation."
                if exposure_story
                else "The risk-adjusted edge survived the pre-registered gate on this sample."
            )
        ),
        "",
        "## Files",
        "",
        "- `src/trader/catalysts/sell_in_may.py` -- pure core + gate",
        "- `tests/financial/test_sell_in_may.py` -- network-free tests",
        "- `scripts/run_sell_in_may_study.py` -- end-to-end runner",
        "- `data/sell_in_may_results.txt` -- raw run output",
        "",
        "## Registry status update line (paste into brain/34)",
        "",
        f"`- {'❌' if killed else '✅'} **T49** Sell-in-May / Halloween — "
        + (
            f"*KILL: winter>summer directionally but in-noise (t={diff_t_full:+.2f}); seasonal "
            f"Sharpe {s_stats.sharpe:.2f} < B&H {b_stats.sharpe:.2f} — exposure reduction, not alpha.*`"
            if exposure_story
            else "*see decision doc.*`"
        ),
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n")

    print("\n".join(raw_lines))
    print(f"\nReport written: {REPORT_PATH}")
    print(f"Raw output: {RAW_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
