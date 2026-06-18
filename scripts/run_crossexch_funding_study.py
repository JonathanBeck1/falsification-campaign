#!/usr/bin/env python
"""Run T31 — cross-exchange perp funding dispersion — end to end (free data).

Pre-registration: ``research/crossexch_funding_preregistration.md``.

Hypothesis: the SAME perp carries DIFFERENT realized funding on Binance vs OKX at
the same 8h timestamp; a market-neutral book (long the LOW-funding venue, short
the HIGH-funding venue) harvests the DIFFERENCE with no net price exposure.

Pipeline (all free, no API key):
  1. For each fixed candidate base (pre-reg §3), fetch Binance funding
     (``data.binance.vision`` archive) and OKX public funding history.
  2. Build the survivorship-honest (both-venues-alive) dispersion panel, aligning
     on the 8h grid after flooring Binance's sub-second jitter.
  3. Aggregate the harvest gross + after TWO-VENUE round-trip cost.
  4. Decisive control: mean |dispersion| vs round-trip cost / break-even hold.
  5. IS/OOS split, venue-shuffle placebo, the pre-registered gate.
  6. Write raw output to ``data/crossexch_funding_results.txt``.

Usage:
    .venv/bin/python scripts/run_crossexch_funding_study.py

DATA WALL: OKX's public funding-rate-history serves only ~3 months, which bounds
the overlap window (Binance has 2020+). Bybit is geoblocked (HTTP 403) from this
environment, so OKX is venue B. Documented, not faked.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import structlog

from trader.catalysts import crypto_data as cd
from trader.catalysts.crossexch_funding import (
    CANDIDATE_BASES,
    binance_symbol,
    build_dispersion_panel,
    evaluate_gate,
    fetch_okx_funding_history,
    harvest_stats,
    split_is_oos,
    venue_shuffle_signed_mean,
)

log = structlog.get_logger()

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "crossexch_funding_results.txt"

# Binance fetch span: a generous superset of the OKX overlap (OKX bounds it).
BIN_START = date(2026, 1, 1)
BIN_END = date(2026, 12, 31)
LEG_FEE_BPS = 5.0          # base-case taker fee per leg
LEG_FEE_BPS_STRESS = 10.0  # stress-case
HOLD_INTERVALS = 21        # ~1 week of 8h intervals for cost amortization
PLACEBO_SEED = 20260614


def main() -> None:
    print(f"[1/5] Fetching OKX + Binance funding for {len(CANDIDATE_BASES)} candidate bases...")
    okx_funding: dict = {}
    bin_funding: dict = {}

    def _fetch_okx(base: str):
        return base, fetch_okx_funding_history(base)

    def _fetch_bin(base: str):
        return base, cd.fetch_funding_history(binance_symbol(base), BIN_START, BIN_END)

    with ThreadPoolExecutor(max_workers=8) as ex:
        for fut in as_completed([ex.submit(_fetch_okx, b) for b in CANDIDATE_BASES]):
            base, s = fut.result()
            if s is not None and not s.empty:
                okx_funding[binance_symbol(base)] = s
    with ThreadPoolExecutor(max_workers=8) as ex:
        for fut in as_completed([ex.submit(_fetch_bin, b) for b in CANDIDATE_BASES]):
            base, s = fut.result()
            if s is not None and not s.empty:
                bin_funding[binance_symbol(base)] = s

    print(f"      OKX returned funding for {len(okx_funding)} bases; "
          f"Binance for {len(bin_funding)}.")
    if not okx_funding:
        print("FATAL: OKX funding unreachable (geoblock?). Documented wall — see report.")
        sys.exit(1)

    print("[2/5] Building cross-venue dispersion panel (8h-aligned, both-venues-alive)...")
    panel = build_dispersion_panel(bin_funding, okx_funding, venue_a="binance", venue_b="okx")
    if panel.n_obs == 0:
        print("FATAL: no overlapping (symbol, timestamp) rows.")
        sys.exit(1)
    ts_min = panel.long_format["ts"].min()
    ts_max = panel.long_format["ts"].max()
    print(f"      panel: {panel.n_obs} obs, {panel.n_symbols} symbols, "
          f"{panel.n_timestamps} timestamps ({ts_min.date()}..{ts_max.date()})")

    # IS/OOS split at the overlap midpoint.
    mid = ts_min + (ts_max - ts_min) / 2
    oos_start = mid.normalize().strftime("%Y-%m-%d")

    print("[3/5] Aggregating harvest (gross + two-venue round-trip cost)...")
    full = harvest_stats(panel, leg_fee_bps=LEG_FEE_BPS, hold_intervals=HOLD_INTERVALS)
    full_stress = harvest_stats(panel, leg_fee_bps=LEG_FEE_BPS_STRESS, hold_intervals=HOLD_INTERVALS)

    is_p, oos_p = split_is_oos(panel, oos_start)
    is_s = harvest_stats(is_p, leg_fee_bps=LEG_FEE_BPS, hold_intervals=HOLD_INTERVALS)
    oos_s = harvest_stats(oos_p, leg_fee_bps=LEG_FEE_BPS, hold_intervals=HOLD_INTERVALS)

    print("[4/5] Placebo (venue-label shuffle) + gate...")
    placebo_signed = venue_shuffle_signed_mean(panel, seed=PLACEBO_SEED)
    gate = evaluate_gate(full, is_s, oos_s, placebo_signed,
                         max_breakeven_intervals=float(HOLD_INTERVALS))

    # Per-symbol mean |dispersion| (bps) for the contributor table.
    per_sym = (
        panel.long_format.groupby("symbol")["abs_diff"].agg(["mean", "count"])
        .sort_values("mean", ascending=False)
    )

    def bps(x: float) -> str:
        return f"{x * 1e4:+.3f}bps"

    print("[5/5] Writing report...")
    lines = [
        "T31 — CROSS-EXCHANGE PERP FUNDING DISPERSION — RAW RESULTS",
        "Pre-reg: research/crossexch_funding_preregistration.md",
        "Venues: A=Binance (data.binance.vision archive) B=OKX (public funding-rate-history).",
        f"Run {cd.utc_today()}. Survivorship: both-venues-alive intersection. NO look-ahead.",
        "",
        "=== DATA WALL ===",
        "Bybit: HTTP 403 (CloudFront geoblock from this environment) -> OKX used as venue B.",
        f"OKX public funding history depth bounds the overlap window: "
        f"{ts_min.date()}..{ts_max.date()} (~3 months).",
        "",
        "=== PANEL (both-venues-alive) ===",
        f"OKX bases fetched      : {len(okx_funding)}",
        f"Binance bases fetched  : {len(bin_funding)}",
        f"matched symbols        : {panel.n_symbols}",
        f"matched 8h timestamps  : {panel.n_timestamps}",
        f"total matched obs      : {panel.n_obs}",
        f"overlap window         : {ts_min} .. {ts_max}",
        "",
        "=== DISPERSION (per 8h interval) ===",
        f"mean signed diff (A-B) : {bps(full.mean_signed_diff)}",
        f"mean |diff| (harvest)  : {bps(full.mean_abs_diff)}",
        f"gross t-stat (|d|)     : {full.t_gross:+.2f}",
        "",
        "=== DECISIVE CONTROL: dispersion vs TWO-VENUE round-trip cost ===",
        f"leg taker fee (base)   : {LEG_FEE_BPS:.1f} bps/leg",
        f"round-trip cost        : {full.rt_cost * 1e4:.1f} bps  (2 venues x open+close = 4 fills)",
        f"mean |dispersion|      : {full.mean_abs_diff * 1e4:.3f} bps / interval",
        f"break-even hold        : {full.break_even_intervals:.1f} intervals "
        f"({full.break_even_intervals / 3:.1f} days at 3 funding/day)",
        f"=> dispersion {'EXCEEDS' if full.mean_abs_diff > full.rt_cost else 'is FAR BELOW'} "
        f"a single round trip; "
        f"{'capturable' if full.break_even_intervals <= HOLD_INTERVALS else 'DEAD ON ARRIVAL after two-venue fees'}",
        "",
        f"=== AFTER-COST HARVEST (cost amortized over {HOLD_INTERVALS} intervals) ===",
        f"base  (5bps/leg) : mean={bps(full.after_cost_mean)}/interval  t={full.t_after_cost:+.2f}  "
        f"win={full.win_rate:.2f}",
        f"stress(10bps/leg): mean={bps(full_stress.after_cost_mean)}/interval  t={full_stress.t_after_cost:+.2f}  "
        f"win={full_stress.win_rate:.2f}",
        "",
        "=== IS / OOS (signed dispersion sign stability) ===",
        f"IS  (< {oos_start}): signed={bps(is_s.mean_signed_diff)} |d|={bps(is_s.mean_abs_diff)} "
        f"n={is_s.n_timestamps}",
        f"OOS (>= {oos_start}): signed={bps(oos_s.mean_signed_diff)} |d|={bps(oos_s.mean_abs_diff)} "
        f"n={oos_s.n_timestamps}",
        "",
        "=== PLACEBO (venue-label shuffle, signed) ===",
        f"real signed mean    : {bps(full.mean_signed_diff)}",
        f"shuffled signed mean: {bps(placebo_signed)}",
        "",
        "=== PER-SYMBOL mean |dispersion| (top contributors) ===",
        *[f"  {sym:12s} {bps(row['mean'])}  (n={int(row['count'])})"
          for sym, row in per_sym.head(20).iterrows()],
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
