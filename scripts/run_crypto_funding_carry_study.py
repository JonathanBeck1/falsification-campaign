#!/usr/bin/env python
"""Run T29 — perp funding-rate carry, cross-sectional alt tail — end to end.

Pre-registration: ``research/crypto_funding_carry_preregistration.md``.

Pipeline (all free, no API key; reads Binance's public ``data.binance.vision``
archive, which RETAINS delisted symbols — the survivorship correction):

  1. List every USDT perp with a funding dump (LIVE + DELISTED).
  2. For a capped sample, fetch funding-month spans -> assemble the survivorship-
     aware universe (delisted flag from "last month lags the frontier").
  3. Fetch funding + daily klines for each symbol over the study span.
  4. Build daily funding / return panels.
  5. Run: cohort (delisted-included), survivor-only, random-decile placebo.
  6. Apply the pre-registered gate; decompose funding vs price; IS/OOS split.
  7. Write raw output to ``data/crypto_funding_carry_results.txt``.

Usage:
    .venv/bin/python scripts/run_crypto_funding_carry_study.py [--max-symbols N]

The archive is geoblock-free where ``fapi.binance.com`` returns 451, so this runs
from restricted regions. Network-heavy (one HTTP per symbol-month); --max-symbols
caps the universe sample for a faster run. The universe sample is taken as an
EVENLY-STRIDED slice of the alphabetical symbol list (NOT a liquidity/recency
filter) so it does not reintroduce survivorship through the back door.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import structlog

from trader.catalysts import crypto_data as cd
from trader.catalysts.crypto_funding_carry import (
    daily_funding_panel,
    daily_return_panel,
    daily_stats,
    evaluate_gate,
    run_carry,
    split_is_oos,
)

log = structlog.get_logger()

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "crypto_funding_carry_results.txt"

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

    print("[3/6] Fetching funding + klines per symbol (concurrent, span-bounded)...")
    funding: dict = {}
    klines: dict = {}

    def _fetch_one(span):
        # Only fetch months WITHIN the symbol's own listing span (from step 2) —
        # avoids thousands of guaranteed-404 month requests for short-lived perps.
        lo = max(span.first_month, STUDY_START)
        hi = min(span.last_month, STUDY_END)
        f = cd.fetch_funding_history(span.symbol, lo, hi)
        if f is None or f.empty:
            return span.symbol, None, None
        k = cd.fetch_kline_history(span.symbol, lo, hi)
        return span.symbol, f, (k if k is not None and not k.empty else None)

    done = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(_fetch_one, s): s for s in universe}
        for fut in as_completed(futs):
            sym, f, k = fut.result()
            if f is not None:
                funding[sym] = f
                if k is not None:
                    klines[sym] = k
            done += 1
            if done % 20 == 0:
                print(f"      ...{done}/{len(universe)} (funding={len(funding)} klines={len(klines)})")

    print(f"      fetched funding for {len(funding)} symbols, klines for {len(klines)}.")
    if len(funding) < 10:
        print("FATAL: too few symbols fetched to run a cross-sectional test.")
        sys.exit(1)

    print("[4/6] Building daily panels...")
    fpanel = daily_funding_panel(funding)
    rpanel = daily_return_panel(klines)
    fpanel = fpanel.reindex(columns=[c for c in fpanel.columns if c in rpanel.columns])
    rpanel = rpanel.reindex(columns=fpanel.columns)
    print(f"      panel: {fpanel.shape[0]} days x {fpanel.shape[1]} symbols "
          f"({fpanel.index.min().date()}..{fpanel.index.max().date()})")

    print("[5/6] Running cohort / survivor-only / placebo...")
    cohort = run_carry(fpanel, rpanel)
    survivors = [s.symbol for s in universe if not s.delisted and s.symbol in fpanel.columns]
    survivor = run_carry(fpanel, rpanel, symbols=survivors)
    placebo = run_carry(fpanel, rpanel, seed=PLACEBO_SEED)

    print("[6/6] Gate + decomposition + IS/OOS...")
    gate = evaluate_gate(cohort, survivor, placebo, oos_start=OOS_START)

    full = daily_stats(cohort.book_ret)
    is_, oos = split_is_oos(cohort.book_ret, OOS_START)
    s_is, s_oos = daily_stats(is_), daily_stats(oos)
    surv_stats = daily_stats(survivor.book_ret)
    pl_stats = daily_stats(placebo.book_ret)
    f_mean = float(cohort.funding_component.dropna().mean())
    p_mean = float(cohort.price_component.dropna().mean())
    c_mean = float(cohort.cost_component.dropna().mean())

    # Alt-tail vs majors split.
    alts = [s.symbol for s in universe if s.is_alt and s.symbol in fpanel.columns]
    alt = run_carry(fpanel.reindex(columns=alts), rpanel.reindex(columns=alts))
    alt_stats = daily_stats(alt.book_ret)

    lines = [
        "T29 — PERP FUNDING-RATE CARRY (cross-sectional alt tail) — RAW RESULTS",
        "Pre-reg: research/crypto_funding_carry_preregistration.md",
        f"Source: data.binance.vision (survivorship-aware; delisted RETAINED). Run {cd.utc_today()}.",
        "",
        "=== UNIVERSE (survivorship) ===",
        f"archive symbols listed : {len(all_syms)}",
        f"sampled (strided)      : {len(sample)}",
        f"with funding span      : {len(universe)}",
        f"fetched funding+klines : {len(klines)}",
        f"survivorship counts    : {summ}",
        f"frontier (live edge)   : {frontier}",
        "",
        "=== COHORT (delisted-INCLUDED) — PRIMARY ===",
        f"N days (>=5 names) : {cohort.n_days}",
        f"after-cost mean/day: {full['mean']:+.6f}",
        f"t-stat            : {full['t']:+.3f}",
        f"annualized ret    : {full['ann_ret']:+.4f} ({full['ann_ret'] * 100:+.2f}%)",
        f"Sharpe (ann)      : {full['sharpe']:+.3f}",
        f"win rate          : {full['win']:.3f}",
        "",
        "=== FUNDING vs PRICE DECOMPOSITION (per day, pre-cost) ===",
        f"funding component : {f_mean:+.6f}/day  ({f_mean * 365 * 100:+.2f}%/yr)",
        f"price   component : {p_mean:+.6f}/day  ({p_mean * 365 * 100:+.2f}%/yr)",
        f"cost    component : {c_mean:+.6f}/day  ({c_mean * 365 * 100:+.2f}%/yr)",
        f"=> {'FUNDING dominates' if f_mean > abs(p_mean) and f_mean > 0 else 'PRICE/cost dominates (NOT carry)'}",
        "",
        "=== IS / OOS ===",
        f"IS  ({STUDY_START}..{OOS_START}): mean={s_is['mean']:+.6f} t={s_is['t']:+.2f} n={s_is['n']}",
        f"OOS ({OOS_START}..{STUDY_END}): mean={s_oos['mean']:+.6f} t={s_oos['t']:+.2f} n={s_oos['n']}",
        f"sign stable: {bool((s_is['mean'] > 0) == (s_oos['mean'] > 0) and s_is['mean'] > 0)}",
        "",
        "=== SURVIVORSHIP CONTROL (survivor-only re-run) ===",
        f"survivor-only mean/day: {surv_stats['mean']:+.6f} t={surv_stats['t']:+.2f} n={surv_stats['n']}",
        f"cohort - survivor gap : {full['mean'] - surv_stats['mean']:+.6f}/day "
        f"(>0 means delisted tokens HELPED carry; <0 means survivors flatter the result)",
        "",
        "=== PLACEBO (random-decile, seed) ===",
        f"placebo mean/day: {pl_stats['mean']:+.6f} t={pl_stats['t']:+.2f} n={pl_stats['n']}",
        "",
        "=== ALT-TAIL ONLY (excl BTC/ETH/BNB) ===",
        f"alt mean/day: {alt_stats['mean']:+.6f} t={alt_stats['t']:+.2f} n={alt_stats['n']} "
        f"sharpe={alt_stats['sharpe']:+.2f}",
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
