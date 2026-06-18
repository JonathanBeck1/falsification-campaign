#!/usr/bin/env python
"""Run T33 — crypto time-series momentum / trend-following — end to end.

Pre-registration: ``research/crypto_momentum_preregistration.md``.

Pipeline (all free, no API key; reads Binance's public ``data.binance.vision``
archive, which RETAINS delisted symbols — the survivorship correction):

  1. List every USDT perp with a funding dump (LIVE + DELISTED).
  2. For a capped, evenly-strided sample, fetch funding-month spans -> assemble
     the survivorship-aware universe.
  3. Fetch daily klines per symbol over the study span.
  4. Build the daily close + return panels.
  5. For each pre-registered lookback (30, 90): run long-flat + long-short books.
  6. Compute the buy-and-hold benchmarks (BTC, equal-weight universe) — THE KEY
     exposure / beta-timing control.
  7. Apply the pre-registered gate on the PRIMARY (N=90 long-flat); IS/OOS split;
     random-timing placebo; 2x cost stress.
  8. Write raw output to ``data/crypto_momentum_results.txt``.

Usage:
    .venv/bin/python scripts/run_crypto_momentum_study.py [--max-symbols N]

The universe sample is an EVENLY-STRIDED slice of the alphabetical symbol list
(NOT a liquidity/recency filter) so it does not reintroduce survivorship.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import structlog

from trader.catalysts import crypto_data as cd
from trader.catalysts.crypto_momentum import (
    LOOKBACKS,
    PRIMARY_LOOKBACK,
    ROUND_TRIP_COST,
    buy_and_hold,
    daily_close_panel,
    daily_return_panel,
    daily_stats,
    evaluate_gate,
    run_momentum,
    split_is_oos,
)

log = structlog.get_logger()

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "crypto_momentum_results.txt"

STUDY_START = date(2020, 1, 1)
STUDY_END = date(2025, 12, 31)
OOS_START = "2023-01-01"
PLACEBO_SEED = 20260614


def _strided_sample(symbols: list[str], n: int) -> list[str]:
    """Evenly-strided slice (NOT a recency/liquidity filter) of the symbol list."""

    usdt = [s for s in symbols if s.endswith("USDT")]
    if n <= 0 or n >= len(usdt):
        return usdt
    step = len(usdt) / n
    return [usdt[int(i * step)] for i in range(n)]


def _fmt(st: dict) -> str:
    return (f"mean={st['mean']:+.6f}/d t={st['t']:+.2f} ann={st['ann_ret'] * 100:+.1f}% "
            f"sharpe={st['sharpe']:+.3f} win={st['win']:.2%} maxdd={st['maxdd']:+.1%} n={st['n']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-symbols", type=int, default=120,
                    help="cap the universe sample (evenly strided). 0 = all.")
    args = ap.parse_args()

    print("[1/6] Listing perp universe (funding archive, live+delisted)...")
    all_syms = cd.list_perp_symbols()
    if not all_syms:
        print("FATAL: could not list symbols (network / archive unreachable).")
        sys.exit(1)
    sample = _strided_sample(all_syms, args.max_symbols)
    # BTC must be present for the buy-and-hold benchmark even if stride skips it.
    if "BTCUSDT" not in sample:
        sample.append("BTCUSDT")
    print(f"      archive lists {len(all_syms)} symbols; sampling {len(sample)}.")

    print("[2/6] Fetching funding spans -> survivorship-aware universe...")
    spans: list[tuple[str, list[date]]] = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(cd.list_symbol_months, sym): sym for sym in sample}
        for j, fut in enumerate(as_completed(futs)):
            sym = futs[fut]
            months = fut.result()
            if months:
                spans.append((sym, months))
            if (j + 1) % 20 == 0:
                print(f"      ...{j + 1}/{len(sample)} spans")
    frontier = cd.utc_today().replace(day=1)
    universe = cd.assemble_universe(spans, frontier=frontier)
    summ = cd.survivorship_summary(universe)
    print(f"      universe: {summ}")

    print("[3/6] Fetching daily klines per symbol (concurrent, span-bounded)...")
    klines: dict = {}

    def _fetch_one(span):
        lo = max(span.first_month, STUDY_START)
        hi = min(span.last_month, STUDY_END)
        k = cd.fetch_kline_history(span.symbol, lo, hi)
        return span.symbol, (k if k is not None and not k.empty else None)

    done = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(_fetch_one, s): s for s in universe}
        for fut in as_completed(futs):
            sym, k = fut.result()
            if k is not None:
                klines[sym] = k
            done += 1
            if done % 20 == 0:
                print(f"      ...{done}/{len(universe)} (klines={len(klines)})")

    print(f"      fetched klines for {len(klines)} symbols.")
    if len(klines) < 10 or "BTCUSDT" not in klines:
        print("FATAL: too few symbols / no BTC fetched to run the study.")
        sys.exit(1)

    print("[4/6] Building daily panels...")
    close = daily_close_panel(klines)
    ret = daily_return_panel(close)
    # Clip to study span.
    close = close.loc[str(STUDY_START):str(STUDY_END)]
    ret = ret.loc[str(STUDY_START):str(STUDY_END)]
    print(f"      panel: {close.shape[0]} days x {close.shape[1]} symbols "
          f"({close.index.min().date()}..{close.index.max().date()})")

    # Buy-and-hold benchmarks (THE KEY exposure control).
    bh_btc = buy_and_hold(ret["BTCUSDT"]).rename("bh_btc")
    bh_uni = buy_and_hold(ret).rename("bh_universe")

    print("[5/6] Running momentum books for each pre-registered lookback...")
    runs: dict[tuple[int, str], object] = {}
    for lb in LOOKBACKS:
        runs[(lb, "long_flat")] = run_momentum(close, ret, lookback=lb, cost=ROUND_TRIP_COST)
        runs[(lb, "long_short")] = run_momentum(close, ret, lookback=lb, cost=ROUND_TRIP_COST,
                                                long_short=True)

    primary = runs[(PRIMARY_LOOKBACK, "long_flat")]
    primary_2x = run_momentum(close, ret, lookback=PRIMARY_LOOKBACK, cost=2 * ROUND_TRIP_COST)
    placebo = run_momentum(close, ret, lookback=PRIMARY_LOOKBACK, cost=ROUND_TRIP_COST,
                           placebo_seed=PLACEBO_SEED)

    print("[6/6] Gate + IS/OOS + exposure control...")
    gate = evaluate_gate(primary, bh_btc, bh_uni, placebo, oos_start=OOS_START)

    p_full = daily_stats(primary.book_ret)
    p_gross = daily_stats(primary.gross_ret)
    p_is, p_oos = split_is_oos(primary.book_ret, OOS_START)
    s_is, s_oos = daily_stats(p_is), daily_stats(p_oos)
    btc_st = daily_stats(bh_btc)
    uni_st = daily_stats(bh_uni)
    pl_st = daily_stats(placebo.book_ret)
    p2_st = daily_stats(primary_2x.book_ret)
    avg_turn = float(primary.turnover.replace(0.0, float("nan")).dropna().mean())
    fee_drag = float(primary.cost_component.dropna().mean()) * 365

    lines = [
        "T33 — CRYPTO TIME-SERIES MOMENTUM / TREND-FOLLOWING — RAW RESULTS",
        "Pre-reg: research/crypto_momentum_preregistration.md",
        f"Source: data.binance.vision (survivorship-aware; delisted RETAINED). Run {cd.utc_today()}.",
        f"Friction: {ROUND_TRIP_COST * 1e4:.0f} bps round-trip on turnover (~6bps/side taker x2).",
        "",
        "=== UNIVERSE (survivorship) ===",
        f"archive symbols listed : {len(all_syms)}",
        f"sampled (strided)      : {len(sample)}",
        f"with funding span      : {len(universe)}",
        f"fetched klines         : {len(klines)}",
        f"survivorship counts    : {summ}",
        f"frontier (live edge)   : {frontier}",
        f"panel span             : {close.index.min().date()}..{close.index.max().date()} "
        f"({close.shape[0]} days x {close.shape[1]} symbols)",
        "",
        "=== PRIMARY: N=90 LONG-FLAT (after cost) ===",
        f"gross : {_fmt(p_gross)}",
        f"net   : {_fmt(p_full)}",
        f"avg turnover (active days): {avg_turn:.4f}  fee drag: {fee_drag * 100:+.2f}%/yr",
        "",
        "=== *** EXPOSURE / BETA-TIMING CONTROL (THE KEY TEST) *** ===",
        f"momentum N=90 net Sharpe : {p_full['sharpe']:+.3f}  (ann {p_full['ann_ret'] * 100:+.1f}%, "
        f"maxdd {p_full['maxdd']:+.1%})",
        f"buy-and-hold BTC Sharpe  : {btc_st['sharpe']:+.3f}  (ann {btc_st['ann_ret'] * 100:+.1f}%, "
        f"maxdd {btc_st['maxdd']:+.1%})",
        f"buy-and-hold UNIV Sharpe : {uni_st['sharpe']:+.3f}  (ann {uni_st['ann_ret'] * 100:+.1f}%, "
        f"maxdd {uni_st['maxdd']:+.1%})",
        f"=> momentum beats BOTH B&H Sharpes? "
        f"{bool(p_full['sharpe'] > btc_st['sharpe'] and p_full['sharpe'] > uni_st['sharpe'])} "
        f"(if False: beta-timing/exposure, NOT alpha)",
        "",
        "=== IS / OOS (PRIMARY N=90 long-flat, after cost) ===",
        f"IS  ({STUDY_START}..{OOS_START}): {_fmt(s_is)}",
        f"OOS ({OOS_START}..{STUDY_END}): {_fmt(s_oos)}",
        f"sign stable (both +): {bool(s_is['mean'] > 0 and s_oos['mean'] > 0)}",
        "",
        "=== PLACEBO (random entry/exit timing, matched exposure) ===",
        f"placebo: {_fmt(pl_st)}  (need |t|<2)",
        "",
        "=== 2x COST STRESS (24 bps round-trip) ===",
        f"net @2x: {_fmt(p2_st)}",
        "",
        "=== ALL LOOKBACKS x VARIANTS (after cost) — for context ===",
    ]
    for lb in LOOKBACKS:
        for variant in ("long_flat", "long_short"):
            st = daily_stats(runs[(lb, variant)].book_ret)
            tag = "PRIMARY" if (lb == PRIMARY_LOOKBACK and variant == "long_flat") else "       "
            lines.append(f"  [{tag}] N={lb:<3} {variant:<10}: {_fmt(st)}")
    lines += [
        "",
        "=== PRE-REGISTERED GATE ===",
        f"VERDICT: {'PASS' if gate.passed else 'FAIL (KILL)'}",
        *[f"  {r}" for r in gate.reasons],
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nRaw results written to {OUT}")


if __name__ == "__main__":
    main()
