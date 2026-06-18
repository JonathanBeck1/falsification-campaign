#!/usr/bin/env python
"""Run T25 — single-name 25-delta skew dynamics — end to end (LIVE).

Pre-registration: ``research/vol_skew_preregistration.md``.

Pipeline (owned EOD option lake + yfinance spot; no paid API):

  1. For each of the 24 fully-collected single names, load the EOD option chain
     from the lake, compute Black-Scholes IVs (the audited
     ``vol_surface_data`` foundation), and read the 30-day 25-delta skew
     (``risk_reversal_25d``) and ATM IV (``atm_iv``) once per WEEKLY snapshot
     date (every 5th trade-day).
  2. Attach the realized forward 21-trading-day stock return measured strictly
     AFTER the snapshot (yfinance daily close; the same source the foundation
     uses for the underlying). Build the frozen panel.
  3. SIGNAL (PRIMARY): cross-sectional tertile long-short (long low-skew, short
     high-skew), market-neutral by demeaning each date; after 10 bps cost and a
     2x stress; IS/OOS split; within-date skew-shuffle placebo; up/down
     symmetry; full brain/30 gate.
  4. PREMIUM (SECONDARY): short-25d-put proxy P&L with the TAIL (worst, maxdd,
     drop-worst-month) and the KEY disguise control (regress on short-ATM-vol +
     short-delta beta -> residual alpha is the only claimable skew premium).
  5. Write raw output to ``data/vol_skew_results.txt``.

Usage:
    .venv/bin/python scripts/run_vol_skew_study.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import structlog

from trader.catalysts import vol_skew as vk
from trader.catalysts import vol_surface_data as vs

log = structlog.get_logger()

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "vol_skew_results.txt"

# The 24 fully-collected single names (pre-reg §0). AAPL/AMZN/NVDA EXCLUDED.
UNIVERSE = [
    "ADBE", "AMAT", "AMD", "AVGO", "BKNG", "COST", "CSCO", "GOOG", "GOOGL",
    "HON", "INTU", "ISRG", "LIN", "LRCX", "META", "MU", "NFLX", "PEP",
    "QCOM", "REGN", "TMUS", "TSLA", "TXN", "VRTX",
]

LAKE_START = date(2022, 1, 1)
LAKE_END = date(2026, 6, 12)


def _fmt(s: vk.SeriesStats) -> str:
    return (f"mean={s.mean:+.5f} t={s.t:+.2f} sharpe={s.sharpe:+.2f} "
            f"win={s.win:.1%} worst={s.worst:+.4f} maxdd={s.maxdd:+.4f} "
            f"median={s.median:+.5f} n={s.n}")


def _spot_series(ticker: str) -> pd.Series:
    """Daily close series (Timestamp-indexed) for forward-return measurement."""

    m = vs.yfinance_daily_close(ticker, LAKE_START, LAKE_END)
    if not m:
        return pd.Series(dtype=float)
    s = pd.Series(m)
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _forward_return(spot: pd.Series, snap: pd.Timestamp, horizon: int) -> float:
    """Close-to-close return from the FIRST trading day strictly after ``snap`` to +horizon.

    t0 = first spot date > snap (act at t+1, no same-bar leak); end = t0 shifted
    ``horizon`` trading days forward. NaN if either endpoint is unavailable.
    """

    after = spot.index[spot.index > snap]
    if len(after) < horizon + 1:
        return float("nan")
    p0 = float(spot.loc[after[0]])
    p1 = float(spot.loc[after[horizon]])
    if p0 <= 0:
        return float("nan")
    return p1 / p0 - 1.0


def build_panel() -> pd.DataFrame:
    """Construct the frozen (name, weekly-snapshot) skew/atm/fwd_ret panel from the lake."""

    rows: list[dict] = []
    spots: dict[str, pd.Series] = {}
    for ticker in UNIVERSE:
        print(f"[{ticker}] loading option lake + computing IVs...", flush=True)
        quotes = vs.load_option_quotes(ticker, LAKE_START, LAKE_END)
        if quotes.empty:
            print(f"  WALL: no quotes for {ticker}", flush=True)
            continue
        enriched = vs.compute_implied_vols(quotes)
        spot = _spot_series(ticker)
        spots[ticker] = spot

        dates = sorted(enriched["trade_date"].dt.normalize().unique())
        weekly = dates[::vk.SAMPLE_EVERY]  # every 5th trade-day
        n_ok = 0
        for snap in weekly:
            snap_ts = pd.Timestamp(snap)
            skew = vs.risk_reversal_25d(
                enriched, snap_ts, target_days=vk.TARGET_DAYS, target_delta=vk.TARGET_DELTA,
            )
            atm = vs.atm_iv(enriched, snap_ts, target_days=vk.TARGET_DAYS)
            fwd = _forward_return(spot, snap_ts, vk.FWD_TRADING_DAYS)
            if not (np.isfinite(skew) and np.isfinite(fwd)):
                continue
            rows.append({
                "ticker": ticker,
                "snapshot_date": snap_ts,
                "skew": float(skew),
                "atm_iv": float(atm) if np.isfinite(atm) else np.nan,
                "fwd_ret": float(fwd),
            })
            n_ok += 1
        print(f"  {ticker}: {n_ok} usable weekly snapshots", flush=True)

    panel = pd.DataFrame(rows)
    # Attach the equal-weight universe forward return per date (pooled baseline).
    if not panel.empty:
        mkt = panel.groupby("snapshot_date")["fwd_ret"].mean().rename("mkt_fwd_ret")
        panel = panel.merge(mkt, on="snapshot_date", how="left")
    return panel


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def emit(s: str = "") -> None:
        print(s, flush=True)
        lines.append(s)

    panel = build_panel()
    if panel.empty:
        emit("PANEL EMPTY — data wall.")
        OUT.write_text("\n".join(lines) + "\n")
        return 1

    n_dates = panel["snapshot_date"].nunique()
    n_names = panel["ticker"].nunique()
    emit("=" * 78)
    emit("T25 — SINGLE-NAME 25-DELTA SKEW DYNAMICS (vol_skew)")
    emit("=" * 78)
    emit(f"universe: {n_names} names {sorted(panel['ticker'].unique())}")
    emit(f"panel: {len(panel)} (name,weekly-date) rows over {n_dates} snapshot dates")
    emit(f"span: {panel['snapshot_date'].min().date()} .. {panel['snapshot_date'].max().date()}")
    emit(f"skew (25d put - 25d call IV): mean={panel['skew'].mean():+.4f} "
         f"median={panel['skew'].median():+.4f} "
         f"frac_positive={(panel['skew'] > 0).mean():.1%}  (normal equity skew is +)")
    emit("")

    # --- SIGNAL framing (PRIMARY) -------------------------------------------
    emit("-" * 78)
    emit("SIGNAL (PRIMARY): tertile long-short  LONG low-skew / SHORT high-skew")
    emit("  (cross-sectionally demeaned => market-neutral; nets the universe baseline)")
    emit("-" * 78)

    ls = vk.signal_long_short(panel, cost_bps=vk.EQUITY_ROUND_TRIP_BPS)
    ls2x = vk.signal_long_short(panel, cost_bps=vk.EQUITY_ROUND_TRIP_2X_BPS)
    gross_s = vk.summarize(ls["gross"].to_numpy())
    net_s = vk.summarize(ls["net"].to_numpy())
    net2x_s = vk.summarize(ls2x["net"].to_numpy())
    emit(f"N long-short obs (weekly): {len(ls)}")
    emit(f"  gross         : {_fmt(gross_s)}")
    emit(f"  net (10bps)   : {_fmt(net_s)}")
    emit(f"  net (20bps 2x): {_fmt(net2x_s)}")

    splits = vk.is_oos_split(ls, value_col="net")
    emit(f"  IS  (<2024-04): {_fmt(splits['is'])}")
    emit(f"  OOS (>=2024-04): {_fmt(splits['oos'])}")

    placebo = vk.placebo_long_short(panel, n_perm=vk.N_PERMUTATIONS)
    emit(f"  placebo (within-date skew-shuffle, {placebo['n_perm']} perms): "
         f"obs_mean={placebo['obs_mean']:+.5f} perm_mean={placebo['perm_mean']:+.5f} "
         f"p={placebo['p_value']:.3f}")

    sym = vk.up_down_symmetry(panel)
    emit(f"  up/down symmetry: forward={sym['forward_mean']:+.5f} "
         f"reversed={sym['reversed_mean']:+.5f} sum={sym['sum']:+.5f} "
         f"(antisymmetric by construction => baseline already netted)")

    gate = vk.evaluate_signal_gate(ls, placebo, value_col="net")
    emit("")
    emit(f"  SIGNAL GATE: {'PASS' if gate.passed else 'FAIL'}")
    for r in gate.reasons:
        emit(f"    - FAIL: {r}")

    # Change-variant (SECONDARY) — Δ20-day skew sort.
    emit("")
    emit("  [secondary] Δ20d-skew sort:")
    chg = _change_panel(panel)
    if not chg.empty:
        ls_chg = vk.signal_long_short(chg, cost_bps=vk.EQUITY_ROUND_TRIP_BPS)
        emit(f"    net (10bps): {_fmt(vk.summarize(ls_chg['net'].to_numpy()))}")
    else:
        emit("    (insufficient history for Δ20d sort)")

    # --- PREMIUM framing (SECONDARY) + KEY control --------------------------
    emit("")
    emit("-" * 78)
    emit("PREMIUM (SECONDARY): short-25d-put proxy P&L (vol-pts) + TAIL + disguise control")
    emit("-" * 78)
    prem = vk.short_put_premium_pnl(panel, cost_volpts=vk.PREMIUM_COST_VOLPTS)
    prem2x = vk.short_put_premium_pnl(panel, cost_volpts=vk.PREMIUM_COST_VOLPTS_2X)
    prem_s = vk.summarize(prem["pnl"].to_numpy())
    prem2x_s = vk.summarize(prem2x["pnl"].to_numpy())
    emit(f"  short-put premium net (2 vol-pts): {_fmt(prem_s)}")
    emit(f"  short-put premium net (4 vol-pts): {_fmt(prem2x_s)}")
    emit(f"  TAIL: worst single payout={prem['pnl'].min():+.4f}  "
         f"maxdd(cum)={prem_s.maxdd:+.4f}")
    dwm = vk.drop_worst_month(prem)
    emit(f"  drop-worst-month: full mean={dwm['full_mean']:+.5f} (t={dwm['full_t']:+.2f}) "
         f"-> drop {dwm['worst_month']}: mean={dwm['drop_mean']:+.5f} (t={dwm['drop_t']:+.2f})")

    short_vol_leg = vk.short_vol_control_pnl(panel)
    beta_leg = vk.market_beta_control_pnl(panel)
    reg = vk.disguise_regression(prem["pnl"].to_numpy(), short_vol_leg, beta_leg)
    emit("  KEY CONTROL — premium ~ const + short-ATM-vol + short-delta-beta:")
    emit(f"    residual alpha={reg['alpha']:+.5f} t={reg['alpha_t']:+.2f}  "
         f"beta_vol={reg['beta_vol']:+.3f} beta_mkt={reg['beta_mkt']:+.3f} "
         f"R^2={reg['r2']:.3f} n={reg['n']}")
    disguised = not (np.isfinite(reg["alpha_t"]) and abs(reg["alpha_t"]) >= 2.0
                     and reg["alpha"] > 0)
    emit(f"    => {'DISGUISED short-vol+short-delta beta (no distinct skew premium)' if disguised else 'residual alpha survives'}")

    emit("")
    emit("=" * 78)
    emit("VERDICT INPUTS:")
    emit(f"  PRIMARY signal after-cost: mean={net_s.mean:+.5f} t={net_s.t:+.2f} "
         f"(need |t|>=2); OOS sign stable={np.sign(splits['is'].mean)==np.sign(splits['oos'].mean)}; "
         f"placebo p={placebo['p_value']:.3f}")
    emit(f"  PREMIUM residual alpha t={reg['alpha_t']:+.2f} (disguise control); "
         f"tail worst={prem['pnl'].min():+.4f}")
    emit("=" * 78)

    OUT.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {OUT}")
    return 0


def _change_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Replace ``skew`` with the per-name Δ over SKEW_CHANGE_LOOKBACK trade-days.

    Weekly cadence -> SKEW_CHANGE_LOOKBACK/SAMPLE_EVERY weekly steps back. PURE-ish
    (reads the already-built panel). Drops the first lookback rows per name.
    """

    steps = max(1, vk.SKEW_CHANGE_LOOKBACK // vk.SAMPLE_EVERY)
    out = panel.sort_values(["ticker", "snapshot_date"]).copy()
    out["skew"] = out.groupby("ticker")["skew"].diff(steps)
    return out.dropna(subset=["skew", "fwd_ret"]).reset_index(drop=True)


if __name__ == "__main__":
    sys.exit(main())
