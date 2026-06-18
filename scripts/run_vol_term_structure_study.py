#!/usr/bin/env python
"""End-to-end runner for T24 — single-name IV term-structure carry.

Pre-registration: research/vol_term_structure_preregistration.md (FIXED design).

For each name in the FROZEN universe (24 fully-collected single names + QQQ +
SPY; AAPL/AMZN/NVDA EXCLUDED), this:

1. Loads the EOD option lake, joins the yfinance underlying, and enriches IVs —
   but ONLY on the dates we trade (rebalance dates + their exit dates), so we
   pay the BS solve cost ~50x, not ~1115x, per name.
2. On each monthly (21-trading-day) rebalance date, reads the ATM term-structure
   slope (~30d vs ~90d) and the entry straddle marks; 21 trading days later it
   re-reads the SAME contracts' marks at reduced tenors (the roll-down) for exit.
3. Builds the pre-registered cross-sectional, dollar- & vega-neutral long-short
   calendar book (steep contango short-near/long-far; flat the mirror) and the
   unconditional short-vol control book.
4. Applies the FULL brain/30 gate: N, after-cost t, OOS sign stability,
   incremental-over-short-vol alpha (the KEY control), up/down symmetry, placebo
   permutation, too-good tripwire, and the tail / max-drawdown report.

Run from the worktree root:
  .venv/bin/python scripts/run_vol_term_structure_study.py
Flags:
  --quick   3 names, 8 rebalances (smoke test)
  --out PATH   results text file (default data/vol_term_structure_results.txt)
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalysts import vol_surface_data as v  # noqa: E402
from trader.catalysts import vol_term_structure as vt  # noqa: E402

UNIVERSE = [
    "ADBE", "AMAT", "AMD", "AVGO", "BKNG", "COST", "CSCO", "GOOG", "GOOGL",
    "HON", "INTU", "ISRG", "LIN", "LRCX", "META", "MU", "NFLX", "PEP", "QCOM",
    "REGN", "TMUS", "TSLA", "TXN", "VRTX", "QQQ", "SPY",
]
START = date(2022, 1, 1)
END = date(2026, 6, 13)
PERIODS_PER_YEAR = 252.0 / vt.REBALANCE_STEP  # ~12


def load_name_dates(ticker: str) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    """Return (quotes, sorted unique trade dates) for one name; ([], []) if empty."""

    quotes = v.load_option_quotes(ticker, START, END)
    if quotes.empty:
        return pd.DataFrame(), []
    dates = sorted(pd.Timestamp(d) for d in quotes["trade_date"].dt.normalize().unique())
    return quotes, dates


def shared_rebalance_pairs(all_name_dates: list[list[pd.Timestamp]]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Build ONE master (entry, exit) rebalance grid shared by every name.

    The master trading calendar is the UNION of all names' trade dates (so the
    grid is not hostage to any single short-history name). Every REBALANCE_STEP-th
    master date is an entry; its exit is HOLD_DAYS master-days later. Each name
    then samples its surface on these SAME dates — so the cross-section is
    populated on a common grid and N counts true rebalance periods, not the
    sparse coincidences of per-name indexing.
    """

    master = sorted(set().union(*all_name_dates)) if all_name_dates else []
    if len(master) < vt.HOLD_DAYS + 2:
        return []
    idxs = range(0, len(master) - vt.HOLD_DAYS, vt.REBALANCE_STEP)
    return [(master[i], master[i + vt.HOLD_DAYS]) for i in idxs]


def build_name_panel(
    ticker: str,
    pairs: list[tuple[pd.Timestamp, pd.Timestamp]] | None = None,
    quotes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Per-rebalance entry/exit marks for one name on the SHARED rebalance grid.

    ``pairs`` is the master (entry, exit) grid from :func:`shared_rebalance_pairs`;
    when omitted (e.g. a single-name diagnostic) the name's own grid is used.
    A name contributes a row only for the master dates on which it actually has
    both legs priceable — missing dates are simply absent from its cross-section
    that period (handled downstream), never silently realigned.
    """

    if quotes is None:
        quotes, name_dates = load_name_dates(ticker)
    else:
        name_dates = sorted(pd.Timestamp(d) for d in quotes["trade_date"].dt.normalize().unique())
    if quotes.empty:
        return pd.DataFrame()
    if pairs is None:
        pairs = shared_rebalance_pairs([name_dates])
    if not pairs:
        return pd.DataFrame()

    name_date_set = set(name_dates)
    # Only sample on master dates this name actually trades (both entry & exit).
    usable = [(e, x) for (e, x) in pairs if e in name_date_set and x in name_date_set]
    needed = sorted({d for pair in usable for d in pair})

    # Enrich IVs only on the dates we actually mark (massive speedup).
    sub = quotes[quotes["trade_date"].dt.normalize().isin(needed)]
    enriched = v.compute_implied_vols(sub)

    rows = []
    for entry, exit_ in usable:
        ts = v.term_structure(enriched, entry, near_days=vt.NEAR_DAYS, far_days=vt.FAR_DAYS)
        near_iv0, far_iv0, slope = ts["near_iv"], ts["far_iv"], ts["slope"]
        if not (np.isfinite(near_iv0) and np.isfinite(far_iv0)):
            continue

        # Entry spot from the enriched frame (the joined underlying on that date).
        spot0 = _spot_on(enriched, entry)
        spot1 = _spot_on(enriched, exit_)
        if not (np.isfinite(spot0) and np.isfinite(spot1)):
            continue

        hold_cal_days = (pd.Timestamp(exit_) - pd.Timestamp(entry)).days
        # Residual tenor on the SAME contracts at exit. With h=10 trading days
        # (~14 cal days) the near leg keeps ~16d; clamp to a small floor as a
        # defensive guard so a holiday-padded exit never produces a non-positive
        # tenor (the floored case is rare and reported, not silently dropped).
        near_tenor_exit = max(vt.NEAR_DAYS - hold_cal_days, 2.0)
        far_tenor_exit = max(vt.FAR_DAYS - hold_cal_days, 2.0)

        # Roll-down: re-read the curve's ATM IV at the REDUCED tenors on exit date.
        near_iv1 = v.atm_iv(enriched, exit_, target_days=near_tenor_exit)
        far_iv1 = v.atm_iv(enriched, exit_, target_days=far_tenor_exit)
        if not (np.isfinite(near_iv1) and np.isfinite(far_iv1)):
            continue

        rows.append(
            {
                "ticker": ticker,
                "trade_date": pd.Timestamp(entry),
                "exit_date": pd.Timestamp(exit_),
                "slope": slope,
                "spot_entry": spot0,
                "spot_exit": spot1,
                "near_tenor_exit": near_tenor_exit,
                "far_tenor_exit": far_tenor_exit,
                "near_iv_entry": near_iv0,
                "far_iv_entry": far_iv0,
                "near_iv_exit": near_iv1,
                "far_iv_exit": far_iv1,
            }
        )
    return pd.DataFrame(rows)


def _spot_on(enriched: pd.DataFrame, d: pd.Timestamp) -> float:
    day = enriched[enriched["trade_date"].dt.normalize() == pd.Timestamp(d).normalize()]
    if day.empty:
        return float("nan")
    return float(day["underlying"].iloc[0])


def _leg_for(row: pd.Series) -> vt.CalendarLeg:
    return vt.CalendarLeg(
        spot_entry=row["spot_entry"],
        spot_exit=row["spot_exit"],
        near_tenor_entry=vt.NEAR_DAYS,
        far_tenor_entry=vt.FAR_DAYS,
        near_tenor_exit=row["near_tenor_exit"],
        far_tenor_exit=row["far_tenor_exit"],
        near_iv_entry=row["near_iv_entry"],
        far_iv_entry=row["far_iv_entry"],
        near_iv_exit=row["near_iv_exit"],
        far_iv_exit=row["far_iv_exit"],
    )


def build_universe_panel(universe: list[str]) -> pd.DataFrame:
    """Load every name ONCE on the shared rebalance grid. Friction-independent.

    Returns the concatenated per-name panel (entry/exit marks); the friction is
    applied later in :func:`run` so both friction levels reuse this single load.
    """

    loaded = []
    for tk in universe:
        quotes, dates = load_name_dates(tk)
        loaded.append((tk, quotes, dates))
    pairs = shared_rebalance_pairs([d for _, _, d in loaded if d])
    print(f"  master rebalance grid: {len(pairs)} (entry,exit) periods")

    panels = []
    for tk, quotes, _ in loaded:
        p = build_name_panel(tk, pairs=pairs, quotes=quotes)
        if not p.empty:
            panels.append(p)
        print(f"  {tk}: {0 if p.empty else len(p)} rebalances")
    if not panels:
        raise SystemExit("no panel data loaded")
    return pd.concat(panels, ignore_index=True)


def run(panel_in: pd.DataFrame, *, friction: float, max_periods: int | None = None) -> dict:
    panel = panel_in.copy()

    # Per-name calendar + short-vol P&L (friction applied here).
    panel["cal_pnl"] = [
        vt.calendar_pnl(_leg_for(r), direction=+1, friction_vol_points=friction)
        for _, r in panel.iterrows()
    ]
    panel["sv_pnl"] = [
        vt.short_vol_pnl(
            r["spot_entry"], vt.NEAR_DAYS, r["near_iv_entry"],
            r["spot_exit"], r["near_tenor_exit"], r["near_iv_exit"],
            friction_vol_points=friction,
        )
        for _, r in panel.iterrows()
    ]

    # Group by rebalance date -> cross-sectional terciles -> period returns.
    per_period_rows = []
    per_period_legs = []
    reb_dates = sorted(panel["trade_date"].unique())
    if max_periods is not None:
        reb_dates = reb_dates[:max_periods]
    for d in reb_dates:
        block = panel[panel["trade_date"] == d].copy()
        terc = vt.assign_terciles(block.set_index("ticker")["slope"])
        if terc.empty:
            continue
        block = block.set_index("ticker")
        block = block.loc[terc.index]
        block["tercile"] = terc
        legs = block[["tercile", "cal_pnl", "sv_pnl"]].reset_index(drop=True)
        res = vt.period_long_short_return(legs)
        res["trade_date"] = d
        per_period_rows.append(res)
        per_period_legs.append(legs)

    periods = pd.DataFrame(per_period_rows)
    return {"panel": panel, "periods": periods, "per_period_legs": per_period_legs}


def gate(periods: pd.DataFrame, per_period_legs: list[pd.DataFrame]) -> str:
    lines: list[str] = []
    ls = periods.set_index("trade_date")["ls_ret"]
    sv = periods.set_index("trade_date")["sv_ret"]
    long_r = periods.set_index("trade_date")["long_ret"]
    short_r = periods.set_index("trade_date")["short_ret"]

    full = vt.summarize(ls, sv)
    lines.append("=== PRIMARY: dollar-neutral long-short slope book (after-cost) ===")
    lines.append(
        f"N periods = {full.get('n')}  mean/period = {full.get('mean'):+.4f}  "
        f"t = {full.get('t'):+.2f}  win = {full.get('win_rate'):.0%}"
    )
    lines.append(
        f"annualized mean = {vt.annualize_mean(full.get('mean', float('nan')), PERIODS_PER_YEAR):+.4f}  "
        f"Sharpe/period = {full.get('sharpe_per_period', float('nan')):+.2f}"
    )
    lines.append(
        f"TAIL: worst period = {full.get('worst_period'):+.4f}  "
        f"max drawdown (cum) = {full.get('max_drawdown'):+.4f}  "
        f"median = {full.get('median'):+.4f}"
    )

    # IS / OOS split
    is_mask = periods["trade_date"] <= vt.IS_END
    is_ls = periods.loc[is_mask, "ls_ret"]
    oos_ls = periods.loc[~is_mask, "ls_ret"]
    lines.append("")
    lines.append("=== OOS sign stability ===")
    lines.append(
        f"IS  (..{vt.IS_END.date()}): N={is_ls.notna().sum()} mean={is_ls.mean():+.4f} t={vt.tstat(is_ls):+.2f}"
    )
    lines.append(
        f"OOS ({(vt.IS_END + pd.Timedelta(days=1)).date()}..): "
        f"N={oos_ls.notna().sum()} mean={oos_ls.mean():+.4f} t={vt.tstat(oos_ls):+.2f}"
    )
    sign_stable = (np.sign(is_ls.mean()) == np.sign(oos_ls.mean())) and is_ls.notna().sum() >= 10 and oos_ls.notna().sum() >= 10

    # KEY control: incremental over short-vol
    inc = vt.incremental_alpha(ls, sv)
    lines.append("")
    lines.append("=== KEY CONTROL: incremental over unconditional short-vol ===")
    sv_sum = vt.summarize(sv, sv)
    lines.append(f"short-vol book: mean={sv_sum.get('mean'):+.4f} t={sv_sum.get('t'):+.2f}")
    lines.append(
        f"slope book regressed on short-vol: alpha={inc['alpha']:+.4f} "
        f"alpha_t={inc['alpha_t']:+.2f} beta={inc['beta']:+.2f} n={inc['n']}"
    )

    # Up/down symmetry
    lines.append("")
    lines.append("=== Symmetry (level vs slope) ===")
    lines.append(
        f"long tercile (steep contango) mean={long_r.mean():+.4f} t={vt.tstat(long_r):+.2f}"
    )
    lines.append(
        f"short tercile MIRROR mean={short_r.mean():+.4f} t={vt.tstat(short_r):+.2f}"
    )

    # Placebo
    obs = full.get("mean", float("nan"))
    p = vt.placebo_pvalue(per_period_legs, observed_ls_mean=obs, k=500)
    lines.append("")
    lines.append(f"=== Placebo (shuffled terciles, k=500): perm p = {p:.3f} ===")

    # Verdict logic
    primary_pass = np.isfinite(full.get("t", np.nan)) and full.get("t") >= 2.0 and full.get("mean") > 0
    inc_pass = np.isfinite(inc["alpha_t"]) and inc["alpha_t"] >= 2.0 and inc["alpha"] > 0
    placebo_pass = np.isfinite(p) and p < 0.05
    lines.append("")
    lines.append("=== GATE ===")
    lines.append(f"[{'PASS' if full.get('n',0)>=30 else 'FAIL'}] N>=30 ({full.get('n')})")
    lines.append(f"[{'PASS' if primary_pass else 'FAIL'}] after-cost mean>0 & |t|>=2 (t={full.get('t'):+.2f})")
    lines.append(f"[{'PASS' if inc_pass else 'FAIL'}] incremental alpha over short-vol >0 & |t|>=2 (alpha_t={inc['alpha_t']:+.2f})")
    lines.append(f"[{'PASS' if sign_stable else 'FAIL'}] OOS sign stable")
    lines.append(f"[{'PASS' if placebo_pass else 'FAIL'}] placebo beaten (p={p:.3f})")
    too_good = (full.get("sharpe_per_period", 0) or 0) > 3 or (full.get("win_rate", 0) or 0) > 0.85
    lines.append(f"[{'TRIGGERED' if too_good else 'n/a'}] too-good tripwire")

    verdict = "KILL"
    if primary_pass and inc_pass and sign_stable and placebo_pass:
        verdict = "SURVIVES"
    elif primary_pass and not inc_pass:
        verdict = "KILL (short-vol beta, no slope alpha)"
    lines.append("")
    lines.append(f"VERDICT: {verdict}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "data" / "vol_term_structure_results.txt"))
    args = ap.parse_args()

    universe = UNIVERSE[:3] if args.quick else UNIVERSE
    max_periods = 8 if args.quick else None

    out_lines = [f"T24 term-structure carry — universe={len(universe)} names, quick={args.quick}"]
    print(out_lines[0])

    print("\n--- loading panel (shared rebalance grid) ---")
    panel = build_universe_panel(universe)

    blocks = []
    for fric in (vt.FRICTION_VOL_POINTS, 2.0 * vt.FRICTION_VOL_POINTS):
        print(f"\n--- friction = {fric} vol-pt/leg ---")
        res = run(panel, friction=fric, max_periods=max_periods)
        header = f"\n############ FRICTION = {fric} vol-pt/leg ############"
        block = header + "\n" + gate(res["periods"], res["per_period_legs"])
        print(block)
        blocks.append(block)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines) + "\n" + "\n".join(blocks) + "\n")
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
