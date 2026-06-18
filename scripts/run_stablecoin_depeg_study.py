#!/usr/bin/env python
"""Run T34 — stablecoin depeg mean-reversion — end to end (free data).

Pre-registration: ``research/stablecoin_depeg_preregistration.md``.

The headline number is the after-cost mean forward return **WITH vs WITHOUT the
dead coins** (UST/USTC). If including the corpses flips a survivor-only positive
to <= 0, the strategy is a survivorship artifact — the pre-registered kill.

Pipeline (all free, no API key; reads Binance's public ``data.binance.vision``
SPOT archive, which RETAINS delisted symbols — so UST's collapse is in-sample):

  1. Fetch daily SPOT klines for the pre-registered stablecoin universe (incl.
     the DEAD ones — UST/USTC are mandatory).
  2. Detect depeg events (first close < $0.98, re-armed) per symbol.
  3. Build forward returns (7d / 30d / to-peg), marking a terminated series to
     its last close (UST's death is REALIZED as a loss, not dropped).
  4. Survivorship split (with vs without dead coins), tail/skew distribution,
     drop-worst, placebo, IS/OOS, and the pre-registered gate.
  5. Write raw output to ``data/stablecoin_depeg_results.txt``.

Usage:
    .venv/bin/python scripts/run_stablecoin_depeg_study.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import structlog

from trader.catalysts import crypto_data as cd
from trader.catalysts.stablecoin_depeg import (
    build_events,
    drop_worst,
    evaluate_gate,
    is_oos_split,
    placebo_stats,
    survivorship_split,
)

log = structlog.get_logger()

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "stablecoin_depeg_results.txt"

STUDY_START = date(2018, 1, 1)
STUDY_END = date(2026, 5, 31)

# Pre-registered universe. ``dead`` is the externally-known classification
# (UST collapsed to ~0; USTC is the post-collapse Terra Classic USD that never
# re-pegged). UST is MANDATORY — it is the steamroller the test must include.
UNIVERSE: list[tuple[str, bool]] = [
    ("USTUSDT", True),    # TerraUST — DEAD (archive ends 2022-05, the collapse)
    ("USTCUSDT", True),   # Terra Classic USD — never re-pegged
    ("USDCUSDT", False),  # survived Mar-2023 SVB depeg to ~$0.88
    ("DAIUSDT", False),   # survived (sparse on Binance spot)
    ("BUSDUSDT", False),  # wound down but re-pegged
    ("TUSDUSDT", False),  # survived; minor depegs
    ("USDPUSDT", False),  # Pax USD — survived
    ("FDUSDUSDT", False), # survived; Feb-2025 minor depeg
    ("USDDUSDT", True),   # algorithmic (Tron) — depegged hard; treat as a tail/death
    ("SUSDUSDT", False),  # sUSD — include if served
    ("GUSDUSDT", False),  # Gemini USD — include if served
]


def _fmt(d: dict) -> str:
    if not d or d.get("n", 0) == 0:
        return "  (no events)"
    return (
        f"  n={int(d['n'])}  mean={d['mean']:+.4%}  median={d['median']:+.4%}  "
        f"t={d['t_stat']:+.2f}\n"
        f"  min={d['min']:+.4%}  p5={d['p5']:+.4%}  max={d['max']:+.4%}  "
        f"win={d['win_rate']:.1%}  skew={d['skew']:+.2f}  "
        f"worst_share={d.get('worst_contribution', float('nan')):.2f}"
    )


def main() -> int:
    lines: list[str] = []

    def emit(s: str = "") -> None:
        print(s)
        lines.append(s)

    emit("=" * 72)
    emit("T34 — STABLECOIN DEPEG MEAN-REVERSION (survivorship/tail test)")
    emit("Pre-reg: research/stablecoin_depeg_preregistration.md")
    emit("Source: data.binance.vision SPOT daily klines (free, append-only)")
    emit("=" * 72)

    all_events = []
    coverage: list[str] = []
    close_by_symbol: dict = {}
    for sym, dead in UNIVERSE:
        df = cd.fetch_spot_kline_history(sym, STUDY_START, STUDY_END, interval="1d")
        if df is None or df.empty:
            coverage.append(f"  {sym:10s} NO DATA SERVED (skipped)")
            continue
        close = df["close"]
        close_by_symbol[sym] = close
        span = f"{close.index[0].date()}..{close.index[-1].date()}"
        evs = build_events(close, sym, is_dead_coin=dead)
        all_events.extend(evs)
        tag = "DEAD" if dead else "live"
        term = sum(1 for e in evs if e.terminal)
        coverage.append(
            f"  {sym:10s} [{tag}]  {span}  bars={len(close):4d}  "
            f"depegs={len(evs)}  terminal={term}  lo={close.min():.4f}"
        )

    emit("\n--- UNIVERSE COVERAGE (corpses must be present) ---")
    for c in coverage:
        emit(c)

    n = len(all_events)
    emit(f"\nTotal depeg events (all symbols): N = {n}")
    if n == 0:
        emit("No events — cannot evaluate.")
        OUT.write_text("\n".join(lines) + "\n")
        return 1

    emit("\n--- EVENT LEDGER (every event, incl. the deaths) ---")
    for e in sorted(all_events, key=lambda x: x.ret_30d):
        flag = " <-- DEAD/TERMINAL" if (e.is_dead_coin or e.terminal) else ""
        emit(
            f"  {e.symbol:10s} t0={e.t0}  entry={e.entry:.4f}  "
            f"ret30d={e.ret_30d:+.2%}  to_peg={e.ret_to_peg:+.2%}  "
            f"recovered={e.recovered}{flag}"
        )

    # ---- THE HEADLINE: survivorship split (PRIMARY = ret_30d) ----
    emit("\n" + "=" * 72)
    emit("HEADLINE — after-cost mean forward return, PRIMARY = ret_30d")
    emit("=" * 72)
    split = survivorship_split(all_events, window="ret_30d")
    emit(f"\nWITH dead coins (the honest, full sample):\n{_fmt(split['with_dead'])}")
    emit(f"\nSURVIVOR-ONLY (dead coins removed — the survivorship illusion):\n"
         f"{_fmt(split['survivor_only'])}")
    emit(f"\n  dead-coin events removed: {int(split['n_dead_events'])}   "
         f"terminal (series-died) events: {int(split['n_terminal_events'])}")
    delta = split["with_dead"].get("mean", 0) - split["survivor_only"].get("mean", 0)
    emit(f"  SURVIVORSHIP EFFECT (with - without) = {delta:+.4%}  "
         f"(negative => corpses drag the mean down)")

    # ---- tail domination: drop the single worst event ----
    dropped = drop_worst(all_events, window="ret_30d")
    g = np.array([e.ret_30d for e in dropped]) - 0.0020
    emit("\n--- TAIL DOMINATION (drop the single worst event) ---")
    emit(f"  with-worst mean = {split['with_dead']['mean']:+.4%}")
    emit(f"  drop-worst mean = {g.mean():+.4%}  "
         f"(sign flip => one event dominates the result)")

    # ---- placebo ----
    emit("\n--- PLACEBO (random non-event entries, same symbols) ---")
    placebo = placebo_stats(close_by_symbol, n_per_symbol=50)
    emit(_fmt(placebo))

    # ---- IS / OOS ----
    emit("\n--- IS / OOS (split at 2023-01-01) ---")
    io = is_oos_split(all_events, window="ret_30d")
    emit(f"IS (pre-2023):\n{_fmt(io['is'])}")
    emit(f"OOS (2023+):\n{_fmt(io['oos'])}")

    # ---- secondary windows for context ----
    emit("\n--- SECONDARY WINDOWS (with dead coins) ---")
    for w in ("ret_7d", "ret_to_peg"):
        s = survivorship_split(all_events, window=w)
        emit(f"{w}:\n{_fmt(s['with_dead'])}")

    # ---- GATE ----
    emit("\n" + "=" * 72)
    emit("PRE-REGISTERED GATE (PRIMARY = ret_30d, WITH dead coins)")
    emit("=" * 72)
    gate = evaluate_gate(all_events, window="ret_30d")
    emit(f"  N = {gate['n']}  (need >= 30) -> {'PASS' if gate['n_ok'] else 'FAIL'}")
    emit(f"  after-cost mean WITH dead = {gate['with_dead_mean']:+.4%}  "
         f"t = {gate['with_dead_t']:+.2f}  (need >0 & |t|>=2) -> "
         f"{'PASS' if gate['signal_ok'] else 'FAIL'}")
    emit(f"  survivor-only mean = {gate['survivor_only_mean']:+.4%}  "
         f"-> corpses-flip-sign check {'PASS' if gate['survivorship_ok'] else 'FAIL (artifact)'}")
    emit(f"  drop-worst mean = {gate['drop_worst_mean']:+.4%}  -> tail check "
         f"{'PASS' if gate['tail_ok'] else 'FAIL (tail dominates)'}")
    emit(f"\n  VERDICT: {'SURVIVES' if gate['survives'] else 'KILL'}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    emit(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
