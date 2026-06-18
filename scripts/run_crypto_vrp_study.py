#!/usr/bin/env python
"""Run T32 — crypto Volatility Risk Premium (Deribit DVOL) — end to end.

Pre-registration: ``research/crypto_vrp_preregistration.md``.

Pipeline (all free, no API key):

  1. Fetch the DVOL implied-vol index (Deribit public REST, paginated) for BTC
     and ETH — history begins 2021-03-24 (the verified data wall).
  2. Fetch BTC/ETH daily spot closes (Binance ``data.binance.vision`` archive,
     via ``crypto_data.py``) over the same span.
  3. Build the IV-RV spread (the *existence* measurement of the premium).
  4. Build the daily short-vol proxy book (variance-swap-replication accrual,
     vega units) after cost — the tradeable claim that actually eats the tail.
  5. Apply the pre-registered gate on the PRIMARY (full-sample, TAIL-INCLUSIVE):
     after-cost |t|≥2, OOS sign stability, MECHANISM corr≥0.10 + monotone
     quartile gradient, TAIL survival (verdict must not hinge on dropping the
     worst month), placebo. Also the long-vol and random-entry placebos and the
     2x cost stress.
  6. Write raw output to ``data/crypto_vrp_results.txt``.

Usage:
    .venv/bin/python scripts/run_crypto_vrp_study.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import structlog

from trader.catalysts import crypto_data as cd
from trader.catalysts import crypto_vrp as vrp
from trader.catalysts import crypto_vrp_data as dv

log = structlog.get_logger()

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "crypto_vrp_results.txt"

STUDY_START = date(2021, 3, 24)   # DVOL inception (the data wall)
SPOT_START = date(2021, 2, 1)     # a little earlier so RV windows are full at the edge
OOS_START = vrp.OOS_START          # 2024-01-01


def _fmt(st: dict) -> str:
    return (f"mean={st['mean']:+.5f}/d t={st['t']:+.2f} ann={st['ann_ret']:+.3f} "
            f"sharpe={st['sharpe']:+.2f} win={st['win']:.1%} "
            f"worst={st['worst']:+.4f} maxdd={st['maxdd']:+.3f} n={st['n']}")


def _run_currency(cur: str, end: date) -> dict | None:
    print(f"\n[{cur}] fetching DVOL (Deribit, paginated)...")
    dvol = dv.fetch_dvol_history(cur, STUDY_START, end)
    if dvol is None or dvol.empty:
        print(f"  WALL: DVOL not fetchable for {cur}.")
        return None
    print(f"  DVOL: {len(dvol)} days {dvol.index.min().date()}..{dvol.index.max().date()}")

    print(f"[{cur}] fetching spot daily klines (Binance archive)...")
    sym = f"{cur}USDT"
    klines = cd.fetch_kline_history(sym, SPOT_START, end)
    if klines is None or klines.empty:
        print(f"  WALL: spot klines not fetchable for {sym}.")
        return None
    close = klines["close"]
    print(f"  spot: {len(close)} days {close.index.min().date()}..{close.index.max().date()}")

    iv = vrp.dvol_to_fraction(dvol)
    panel = vrp.iv_rv_spread(iv, close)  # existence measurement (IV - fwd RV)

    short = vrp.short_vol_book(iv, close, friction_vol_pts=vrp.FRICTION_VOL_PTS, sign=+1)
    short_2x = vrp.short_vol_book(iv, close, friction_vol_pts=2 * vrp.FRICTION_VOL_PTS, sign=+1)
    placebo_long = vrp.short_vol_book(iv, close, friction_vol_pts=vrp.FRICTION_VOL_PTS, sign=-1)
    placebo_rand = vrp.short_vol_book(iv, close, friction_vol_pts=vrp.FRICTION_VOL_PTS,
                                      sign=+1, random_entry_seed=vrp.PLACEBO_SEED)

    gate = vrp.evaluate_gate(short, placebo_long, placebo_rand, oos_start=OOS_START)

    full = vrp.book_stats(short.book_ret)
    gross = vrp.book_stats(short.gross_ret)
    is_, oos = vrp.split_is_oos(short.book_ret, OOS_START)
    s_is, s_oos = vrp.book_stats(is_), vrp.book_stats(oos)
    corr = vrp.mechanism_corr(short.entry_spread, short.book_ret)
    grad = vrp.spread_quartile_gradient(short.entry_spread, short.book_ret)
    kept, worst_m = vrp.drop_worst_month(short.book_ret)
    k_st = vrp.book_stats(kept)
    p2 = vrp.book_stats(short_2x.book_ret)
    pl_long = vrp.book_stats(placebo_long.book_ret)
    pl_rand = vrp.book_stats(placebo_rand.book_ret)

    mean_spread = float(panel["vrp"].mean()) if not panel.empty else float("nan")
    spread_pos_frac = float((panel["vrp"] > 0).mean()) if not panel.empty else float("nan")

    return {
        "cur": cur, "dvol": dvol, "close": close, "panel": panel,
        "gate": gate, "full": full, "gross": gross,
        "s_is": s_is, "s_oos": s_oos, "corr": corr, "grad": grad,
        "worst_m": worst_m, "k_st": k_st, "p2": p2,
        "pl_long": pl_long, "pl_rand": pl_rand,
        "mean_spread": mean_spread, "spread_pos_frac": spread_pos_frac,
    }


def _report_block(r: dict) -> list[str]:
    cur = r["cur"]
    lines = [
        f"========================= {cur} =========================",
        f"DVOL span: {r['dvol'].index.min().date()}..{r['dvol'].index.max().date()} "
        f"({len(r['dvol'])} days)",
        "",
        "--- EXISTENCE: IV - forward-30d-RV spread (vol fraction) ---",
        f"mean IV-RV spread : {r['mean_spread']:+.4f}  "
        f"(IV>RV on {r['spread_pos_frac']:.1%} of days)  "
        f"[positive ⇒ IV richer than realized, the premium]",
        "",
        "--- PRIMARY: short-vol proxy daily P&L (vega units), after 2 vol-pt cost ---",
        f"gross : {_fmt(r['gross'])}",
        f"net   : {_fmt(r['full'])}",
        "",
        "--- *** MECHANISM (THE KEY TEST) *** ---",
        f"corr(entry IV-RV spread, short-vol P&L) = {r['corr']:+.3f}  "
        f"(need ≥ +{vrp.MECH_MIN_CORR:.2f}; ~0 ⇒ short-gamma BETA, not VRP)",
        f"spread-quartile P&L gradient Q1..Q4 = {[round(g, 5) for g in r['grad']]}  "
        f"(need monotone increasing)",
        "",
        "--- IS / OOS (after cost) ---",
        f"IS  (..{OOS_START}): {_fmt(r['s_is'])}",
        f"OOS ({OOS_START}..): {_fmt(r['s_oos'])}",
        f"sign stable & IS>0 : "
        f"{bool(r['s_is']['mean'] > 0 and r['s_oos']['mean'] > 0)}",
        "",
        "--- *** TAIL (crypto catastrophe control) *** ---",
        f"worst single day   : {r['full']['worst']:+.4f} vol-pts P&L",
        f"max drawdown       : {r['full']['maxdd']:+.4f} (cumulative vol-pts)",
        f"worst month        : {r['worst_m']} — remove it ⇒ {_fmt(r['k_st'])}",
        f"verdict hinges on dropping the tail? "
        f"{bool(r['full']['mean'] <= 0 and r['k_st']['mean'] > 0)} (True ⇒ KILL)",
        "",
        "--- PLACEBO + 2x COST STRESS ---",
        f"long-vol (sign-flip): {_fmt(r['pl_long'])}",
        f"random-entry        : {_fmt(r['pl_rand'])}  (must NOT reproduce edge)",
        f"net @2x cost (4vp)  : {_fmt(r['p2'])}",
        "",
        "--- PRE-REGISTERED GATE ---",
        f"VERDICT: {'PASS' if r['gate'].passed else 'FAIL (KILL)'}",
        *[f"  {x}" for x in r["gate"].reasons],
        "",
    ]
    return lines


def main() -> None:
    end = dv.utc_today()
    print("T32 — CRYPTO VOLATILITY RISK PREMIUM (Deribit DVOL)")
    print(f"Span: {STUDY_START}..{end}  |  OOS from {OOS_START}")

    results = []
    for cur in vrp.CURRENCIES:
        r = _run_currency(cur, end)
        if r is not None:
            results.append(r)

    if not results:
        print("\nFATAL: no currency produced data (DVOL + spot both unreachable).")
        print("Document the wall in the decision doc and report.")
        sys.exit(1)

    header = [
        "T32 — CRYPTO VOLATILITY RISK PREMIUM (Deribit DVOL) — RAW RESULTS",
        "Pre-reg: research/crypto_vrp_preregistration.md",
        f"IV source: Deribit DVOL (public REST). Spot RV: Binance archive. Run {end}.",
        f"Friction: {vrp.FRICTION_VOL_PTS:.0f} vol-pts round-trip (Deribit fee+spread+hedge).",
        f"Data wall: DVOL history begins {dv.DVOL_INCEPTION} (2020-03 COVID crash OUT of sample).",
        "Units: short-vol P&L is in vega (vol-point) units per day; a -50% day ⇒ huge loss.",
        "",
    ]
    lines = header[:]
    for r in results:
        lines += _report_block(r)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nRaw results written to {OUT}")


if __name__ == "__main__":
    main()
