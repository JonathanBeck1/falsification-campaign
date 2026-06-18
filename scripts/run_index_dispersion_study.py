#!/usr/bin/env python
"""End-to-end runner for T22 — index dispersion / correlation risk premium.

Pre-registration: research/index_dispersion_preregistration.md (FIXED design).

For the FROZEN universe (QQQ index + 27 fully-collected mega-cap constituents),
this:

1. Loads the EOD option lake (parity-anchored spot, two-sided quotes), and on a
   shared monthly (21-trading-day) rebalance grid marks the ~30d ATM straddle for
   the index and every constituent: mid value, vega, and the REALIZED quoted
   half-spread (the friction).
2. Holds HOLD_DAYS (~10 trading days) and reprices the SAME contracts at exit
   from the actual exit quotes (BS fallback at the residual tenor where a contract
   is no longer two-sided), so the realized move + IV change + theta all flow
   through honestly.
3. Builds the pre-registered, **vega-neutral** dispersion book — SHORT 1 index
   straddle, LONG an equal-weighted, vega-matched basket of single-name straddles
   — and its decomposed control legs (short-index-only, long-basket-only).
4. Reports the mechanism (implied vs realized average correlation) and applies the
   FULL brain/30 gate: N, after-cost t, OOS sign stability, the KEY controls
   (incremental alpha over short-index-vol; crash-compensation regression on the
   index move), sign-flip placebo, too-good tripwire, and the tail / max-drawdown.

Run from the worktree root:
  .venv/bin/python scripts/run_index_dispersion_study.py
Flags:
  --quick      6 names + QQQ, 8 rebalances (smoke test)
  --out PATH   results text file (default data/index_dispersion_results.txt)
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

from trader.catalysts import index_dispersion as idp  # noqa: E402
from trader.catalysts import vol_surface_data as v  # noqa: E402

INDEX = "QQQ"
CONSTITUENTS = [
    "AAPL", "ADBE", "AMAT", "AMD", "AMZN", "AVGO", "BKNG", "COST", "CSCO",
    "GOOGL", "HON", "INTU", "ISRG", "LIN", "LRCX", "META", "MU", "NFLX",
    "NVDA", "PEP", "QCOM", "REGN", "TMUS", "TSLA", "TXN", "VRTX",
]  # GOOG dropped (GOOGL kept) so the dual-class share class is not double-counted
START = date(2022, 1, 1)
END = date(2026, 6, 13)


# --------------------------------------------------------------------------- #
# ATM straddle mark from an enriched (IV-bearing) one-name frame
# --------------------------------------------------------------------------- #
def atm_straddle_mark(
    enriched: pd.DataFrame,
    trade_date: pd.Timestamp,
    *,
    target_days: float = idp.ATM_TARGET_DAYS,
) -> idp.StraddleMark | None:
    """The single nearest-ATM straddle at the tenor nearest ``target_days``.

    Immune to the atm_iv() wing-average fallback: we pick the ONE strike closest
    to spot and use its matched call+put (not a moneyness-window average), then
    take that straddle's mid value, quoted half-spread, and BS vega at the
    call/put average IV. Returns None if no priceable ATM straddle exists.
    """

    day = enriched[enriched["trade_date"].dt.normalize() == pd.Timestamp(trade_date).normalize()]
    day = day[np.isfinite(day["iv"])]
    if day.empty:
        return None
    spot = float(day["underlying"].iloc[0])
    if not np.isfinite(spot) or spot <= 0:
        return None

    # Expiration nearest target among those carrying both a call and put.
    tenors = day.assign(days=day["tau"] * v.DAYS_PER_YEAR)
    exp_days = tenors.groupby("expiration")["days"].first()
    both = tenors.groupby("expiration")["right"].apply(lambda s: {"C", "P"}.issubset(set(s)))
    cand = exp_days[both[both].index]
    if cand.empty:
        return None
    chosen_exp = (cand - target_days).abs().idxmin()
    leg = tenors[tenors["expiration"] == chosen_exp]

    calls = leg[leg["right"] == "C"]
    puts = leg[leg["right"] == "P"]
    if calls.empty or puts.empty:
        return None
    # The one strike nearest spot that has BOTH a call and a put.
    common = sorted(set(calls["strike"]).intersection(set(puts["strike"])))
    if not common:
        return None
    k = min(common, key=lambda s: abs(s - spot))
    crow = calls[calls["strike"] == k].iloc[0]
    prow = puts[puts["strike"] == k].iloc[0]

    value = float(crow["mid"] + prow["mid"])
    half_spread = 0.5 * float((crow["ask"] - crow["bid"]) + (prow["ask"] - prow["bid"]))
    iv = float(np.nanmean([crow["iv"], prow["iv"]]))
    tenor_days = float(leg["days"].iloc[0])
    vega = idp.straddle_vega(spot, tenor_days, iv, strike=k)
    if not (np.isfinite(value) and np.isfinite(vega) and vega > 0):
        return None
    return idp.StraddleMark(
        value=value,
        vega=vega,
        half_spread=max(half_spread, 0.0),
        spot=spot,
        strike=float(k),
        tenor_days=tenor_days,
        iv=iv,
        expiration=pd.Timestamp(chosen_exp),
    )


def exit_mark(
    enriched_exit: pd.DataFrame,
    entry: idp.StraddleMark,
    exit_date: pd.Timestamp,
) -> tuple[float, float]:
    """(value, half_spread) of the SAME (expiration, strike) straddle at exit.

    Prefers the actual exit quotes for the entry contracts; falls back to a BS
    reprice at the residual tenor and the exit ATM IV when a leg is no longer
    two-sided. Returns (NaN, NaN) if the contract cannot be marked at all.
    """

    day = enriched_exit[enriched_exit["trade_date"].dt.normalize() == pd.Timestamp(exit_date).normalize()]
    if day.empty:
        return float("nan"), float("nan")
    same = day[(day["expiration"] == entry.expiration) & (np.isclose(day["strike"], entry.strike))]
    crow = same[same["right"] == "C"]
    prow = same[same["right"] == "P"]
    if not crow.empty and not prow.empty:
        value = float(crow["mid"].iloc[0] + prow["mid"].iloc[0])
        hs = 0.5 * float(
            (crow["ask"].iloc[0] - crow["bid"].iloc[0]) + (prow["ask"].iloc[0] - prow["bid"].iloc[0])
        )
        if np.isfinite(value) and value > 0:
            return value, max(hs, 0.0)

    # BS fallback: reprice the entry strike at the residual tenor + exit ATM IV.
    spot_exit = float(day["underlying"].iloc[0]) if np.isfinite(day["underlying"].iloc[0]) else float("nan")
    residual_days = (pd.Timestamp(entry.expiration) - pd.Timestamp(exit_date)).days
    exit_iv = v.atm_iv(enriched_exit, exit_date, target_days=max(residual_days, 2.0))
    if not (np.isfinite(spot_exit) and spot_exit > 0 and np.isfinite(exit_iv) and residual_days > 0):
        return float("nan"), float("nan")
    value = idp.straddle_value(spot_exit, residual_days, exit_iv, strike=entry.strike)
    # No quote -> charge the entry half-spread again as the exit-cross proxy.
    return value, entry.half_spread


# --------------------------------------------------------------------------- #
# Panel construction
# --------------------------------------------------------------------------- #
def load_name(ticker: str) -> tuple[pd.DataFrame, list[pd.Timestamp], dict[pd.Timestamp, float]]:
    """(quotes, sorted dates, date->parity-spot map) for one name."""

    quotes = v.load_option_quotes(ticker, START, END)
    if quotes.empty:
        return pd.DataFrame(), [], {}
    dates = sorted(pd.Timestamp(d) for d in quotes["trade_date"].dt.normalize().unique())
    spot_map = (
        quotes.assign(d=quotes["trade_date"].dt.normalize())
        .groupby("d")["underlying"]
        .first()
        .to_dict()
    )
    return quotes, dates, spot_map


def rebalance_pairs(all_dates: list[list[pd.Timestamp]]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Master (entry, exit) grid on the UNION trading calendar."""

    master = sorted(set().union(*all_dates)) if all_dates else []
    if len(master) < idp.HOLD_DAYS + 2:
        return []
    idxs = range(0, len(master) - idp.HOLD_DAYS, idp.REBALANCE_STEP)
    return [(master[i], master[i + idp.HOLD_DAYS]) for i in idxs]


def window_dates(master: list[pd.Timestamp], entry: pd.Timestamp, exit_: pd.Timestamp) -> list[pd.Timestamp]:
    i, j = master.index(entry), master.index(exit_)
    return master[i : j + 1]


def build_period_marks(
    universe: list[str],
    quick_periods: int | None,
) -> dict:
    """Mark the index + every constituent on the shared grid; return per-period dicts."""

    loaded = {tk: load_name(tk) for tk in universe}
    all_dates = [d for (_, d, _) in loaded.values() if d]
    master = sorted(set().union(*all_dates))
    pairs = rebalance_pairs(all_dates)
    if quick_periods is not None:
        pairs = pairs[:quick_periods]
    print(f"  master grid: {len(master)} dates, {len(pairs)} rebalance periods")

    # Enrich every name ONCE on the union of all entry/exit dates (big speedup).
    needed = sorted({d for pair in pairs for d in pair})
    enriched: dict[str, pd.DataFrame] = {}
    for tk, (quotes, _, _) in loaded.items():
        if quotes.empty:
            continue
        sub = quotes[quotes["trade_date"].dt.normalize().isin(needed)]
        enriched[tk] = v.compute_implied_vols(sub)
        print(f"  {tk}: enriched {sub['trade_date'].dt.normalize().nunique()} dates")

    spot_maps = {tk: sm for tk, (_, _, sm) in loaded.items()}
    periods = []
    split_drops = 0
    for entry, exit_ in pairs:
        if INDEX not in enriched:
            continue
        idx_entry = atm_straddle_mark(enriched[INDEX], entry)
        if idx_entry is None:
            continue
        idx_exit_val, idx_exit_hs = exit_mark(enriched[INDEX], idx_entry, exit_)
        if not np.isfinite(idx_exit_val):
            continue

        legs: list[idp.DispersionLeg] = []
        cons_ivs, cons_names = [], []
        for tk in CONSTITUENTS:
            if tk not in enriched:
                continue
            em = atm_straddle_mark(enriched[tk], entry)
            if em is None:
                continue
            # Split guard: entry->exit parity-spot return blows up across a split.
            sm = spot_maps.get(tk, {})
            s0, s1 = sm.get(entry), sm.get(exit_)
            if (
                s0 and s1 and np.isfinite(s0) and np.isfinite(s1) and s0 > 0
                and abs(s1 / s0 - 1.0) > idp.SPLIT_RETURN_GUARD
            ):
                split_drops += 1
                continue
            ev, ehs = exit_mark(enriched[tk], em, exit_)
            if not np.isfinite(ev):
                continue
            legs.append(idp.DispersionLeg(name=tk, entry=em, exit_value=ev, exit_half_spread=ehs, weight=1.0))
            cons_ivs.append(em.iv)
            cons_names.append(tk)

        if len(legs) < idp.MIN_BASKET_NAMES:
            continue

        # Mechanism: implied avg correlation (equal weights).
        w = np.ones(len(cons_ivs))
        rho_imp = idp.implied_correlation(idx_entry.iv, np.array(cons_ivs), w)
        # Realized avg correlation over the window from daily parity-spot returns.
        rho_real = realized_corr_window(master, entry, exit_, spot_maps, cons_names)

        periods.append(
            {
                "entry": entry,
                "exit": exit_,
                "index_entry": idx_entry,
                "index_exit_val": idx_exit_val,
                "index_exit_hs": idx_exit_hs,
                "legs": legs,
                "rho_imp": rho_imp,
                "rho_real": rho_real,
                "index_iv": idx_entry.iv,
                "index_move": (idx_entry.spot and _ret(spot_maps.get(INDEX, {}), entry, exit_)),
            }
        )
    print(f"  built {len(periods)} priceable periods; split-guard drops: {split_drops}")
    return {"periods": periods, "master": master}


def _ret(spot_map: dict, entry: pd.Timestamp, exit_: pd.Timestamp) -> float:
    s0, s1 = spot_map.get(entry), spot_map.get(exit_)
    if s0 and s1 and np.isfinite(s0) and np.isfinite(s1) and s0 > 0:
        r = s1 / s0 - 1.0
        return float(r) if abs(r) <= idp.SPLIT_RETURN_GUARD else float("nan")
    return float("nan")


def realized_corr_window(
    master: list[pd.Timestamp],
    entry: pd.Timestamp,
    exit_: pd.Timestamp,
    spot_maps: dict[str, dict],
    names: list[str],
) -> float:
    """Weighted realized avg correlation over [entry, exit] from daily parity spot.

    Split-guarded: any daily return beyond SPLIT_RETURN_GUARD is set NaN (a split
    day, not a real move). Diagnostic only.
    """

    wd = window_dates(master, entry, exit_)
    if len(wd) < 4:
        return float("nan")

    def path_returns(sm: dict) -> np.ndarray:
        spots = np.array([sm.get(d, np.nan) for d in wd], dtype=float)
        rets = spots[1:] / spots[:-1] - 1.0
        rets = np.where(np.abs(rets) > idp.SPLIT_RETURN_GUARD, np.nan, rets)
        return rets

    cols = {tk: path_returns(spot_maps.get(tk, {})) for tk in names}
    rets = pd.DataFrame(cols)
    idx_rets = path_returns(spot_maps.get(INDEX, {}))
    w = np.ones(rets.shape[1])
    return idp.realized_correlation(idx_rets, rets, w)


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #
def evaluate(periods: list[dict]) -> tuple[pd.DataFrame, str]:
    rows = []
    for p in periods:
        pnl = idp.dispersion_period_pnl(
            p["index_entry"], p["index_exit_val"], p["index_exit_hs"], p["legs"], charge_friction=True
        )
        pnl_nocost = idp.dispersion_period_pnl(
            p["index_entry"], p["index_exit_val"], p["index_exit_hs"], p["legs"], charge_friction=False
        )
        rows.append(
            {
                "entry": p["entry"],
                "ret": pnl["ret"],
                "ret_gross": pnl_nocost["ret"],
                "cost": pnl["cost"],
                "short_index_only": pnl["short_index_only"],
                "long_only": pnl["long_only"],
                "rho_imp": p["rho_imp"],
                "rho_real": p["rho_real"],
                "index_move": p["index_move"],
                "n_names": pnl["n_names"],
            }
        )
    df = pd.DataFrame(rows)
    lines = render_gate(df)
    return df, lines


def render_gate(df: pd.DataFrame) -> str:
    L: list[str] = []
    net = df.set_index("entry")["ret"]
    gross = df.set_index("entry")["ret_gross"]
    si = df.set_index("entry")["short_index_only"]

    s_net = idp.summarize(net)
    s_gross = idp.summarize(gross)
    L.append("=== MECHANISM: implied vs realized average correlation ===")
    L.append(
        f"mean implied rho = {df['rho_imp'].mean():+.3f}   "
        f"mean realized rho = {df['rho_real'].mean():+.3f}   "
        f"premium (imp-real) = {(df['rho_imp'].mean() - df['rho_real'].mean()):+.3f}"
    )
    L.append(f"  (rho computed on {df['rho_imp'].notna().sum()} periods; equal-weighted mega-cap subset)")
    L.append("")

    L.append("=== PRIMARY: vega-neutral dispersion book (short index / long basket) ===")
    L.append(
        f"GROSS  N={s_gross.get('n')}  mean/period={s_gross.get('mean'):+.4f}  "
        f"t={s_gross.get('t'):+.2f}  win={s_gross.get('win_rate'):.0%}"
    )
    L.append(
        f"NET    N={s_net.get('n')}  mean/period={s_net.get('mean'):+.4f}  "
        f"t={s_net.get('t'):+.2f}  win={s_net.get('win_rate'):.0%}"
    )
    L.append(
        f"  mean friction/period = {df['cost'].mean():+.4f} "
        f"(= {100 * df['cost'].mean() / max(abs(s_gross.get('mean', float('nan'))), 1e-9):.0f}% of gross edge)"
    )
    L.append(
        f"  annualized NET mean = {idp.annualize_mean(s_net.get('mean', float('nan'))):+.4f}  "
        f"Sharpe/period = {s_net.get('sharpe_per_period', float('nan')):+.2f}"
    )
    L.append(
        f"  TAIL: worst period = {s_net.get('worst_period'):+.4f}  "
        f"max drawdown (cum) = {s_net.get('max_drawdown'):+.4f}  median = {s_net.get('median'):+.4f}"
    )
    L.append("")

    # OOS sign stability (on NET).
    is_mask = df["entry"] <= idp.IS_END
    is_net = df.loc[is_mask, "ret"]
    oos_net = df.loc[~is_mask, "ret"]
    L.append("=== OOS sign stability (NET) ===")
    L.append(f"IS  (..{idp.IS_END.date()}): N={is_net.notna().sum()} mean={is_net.mean():+.4f} t={idp.tstat(is_net):+.2f}")
    L.append(
        f"OOS ({(idp.IS_END + pd.Timedelta(days=1)).date()}..): "
        f"N={oos_net.notna().sum()} mean={oos_net.mean():+.4f} t={idp.tstat(oos_net):+.2f}"
    )
    sign_stable = (
        np.isfinite(is_net.mean())
        and np.isfinite(oos_net.mean())
        and np.sign(is_net.mean()) == np.sign(oos_net.mean())
        and is_net.notna().sum() >= 10
        and oos_net.notna().sum() >= 10
    )
    L.append("")

    # KEY CONTROL 1: incremental alpha over short-index-vol stance.
    inc = idp.incremental_alpha(net, si)
    si_sum = idp.summarize(si)
    L.append("=== KEY CONTROL 1: incremental over short-index-vol ===")
    L.append(f"short-index-vol book: mean={si_sum.get('mean'):+.4f} t={si_sum.get('t'):+.2f}")
    L.append(
        f"dispersion regressed on short-index-vol: alpha={inc['alpha']:+.4f} "
        f"alpha_t={inc['alpha_t']:+.2f} beta={inc['beta']:+.2f} n={inc['n']}"
    )
    L.append("")

    # KEY CONTROL 2: crash compensation — regress NET on |index move|.
    crash = df.set_index("entry")["index_move"].abs()
    inc2 = idp.incremental_alpha(net, crash)
    corr_move = float(pd.DataFrame({"r": net, "m": df.set_index("entry")["index_move"]}).dropna().corr().iloc[0, 1]) if net.notna().sum() > 2 else float("nan")
    L.append("=== KEY CONTROL 2: correlation-crash compensation ===")
    L.append(f"corr(dispersion ret, index move) = {corr_move:+.2f}  (dispersion is short correlation -> expect <0 in crashes)")
    L.append(
        f"dispersion regressed on |index move|: alpha={inc2['alpha']:+.4f} "
        f"alpha_t={inc2['alpha_t']:+.2f} beta={inc2['beta']:+.2f}"
    )
    L.append("")

    # Placebo (sign-flip).
    p = idp.sign_flip_placebo(net, k=5000)
    L.append(f"=== Placebo (sign-flip, k=5000): perm p = {p:.4f} ===")
    L.append("")

    # Verdict logic.
    primary_pass = np.isfinite(s_net.get("t", np.nan)) and s_net.get("t") >= 2.0 and s_net.get("mean") > 0
    inc_pass = np.isfinite(inc["alpha_t"]) and inc["alpha_t"] >= 2.0 and inc["alpha"] > 0
    placebo_pass = np.isfinite(p) and p < 0.05
    too_good = (s_net.get("sharpe_per_period", 0) or 0) > 3 or (s_net.get("win_rate", 0) or 0) > 0.85
    L.append("=== GATE ===")
    L.append(f"[{'PASS' if s_net.get('n', 0) >= 30 else 'FAIL'}] N>=30 ({s_net.get('n')})")
    L.append(f"[{'PASS' if primary_pass else 'FAIL'}] after-cost mean>0 & |t|>=2 (net t={s_net.get('t'):+.2f})")
    L.append(f"[{'PASS' if inc_pass else 'FAIL'}] incremental alpha over short-index-vol >0 & |t|>=2 (alpha_t={inc['alpha_t']:+.2f})")
    L.append(f"[{'PASS' if sign_stable else 'FAIL'}] OOS sign stable")
    L.append(f"[{'PASS' if placebo_pass else 'FAIL'}] placebo beaten (p={p:.4f})")
    L.append(f"[{'TRIGGERED' if too_good else 'n/a'}] too-good tripwire")

    verdict = "KILL"
    if primary_pass and inc_pass and sign_stable and placebo_pass and not too_good:
        verdict = "SURVIVES"
    elif primary_pass and not inc_pass:
        verdict = "KILL (short-index-vol beta / crash compensation, no dispersion alpha)"
    elif not primary_pass and net.mean() > 0:
        verdict = "MARGINAL (premium real but eaten by single-name spreads)"
    L.append("")
    L.append(f"VERDICT: {verdict}")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "data" / "index_dispersion_results.txt"))
    args = ap.parse_args()

    universe = [INDEX] + (CONSTITUENTS[:6] if args.quick else CONSTITUENTS)
    quick_periods = 8 if args.quick else None

    print(f"T22 index dispersion — index={INDEX}, constituents={len(universe) - 1}, quick={args.quick}")
    print("\n--- marking panel (shared rebalance grid) ---")
    built = build_period_marks(universe, quick_periods)
    if not built["periods"]:
        raise SystemExit("no priceable periods")

    df, gate_text = evaluate(built["periods"])
    print("\n" + gate_text)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = f"T22 index dispersion — index={INDEX}, constituents={len(universe) - 1}, quick={args.quick}\n"
    out_path.write_text(header + "\n" + gate_text + "\n")
    df.to_csv(out_path.with_suffix(".csv"), index=False)
    print(f"\nwrote {out_path} and {out_path.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
