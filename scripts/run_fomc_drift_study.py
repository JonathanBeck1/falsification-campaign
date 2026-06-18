"""Run the pre-registered FOMC pre-announcement drift study (T47) end to end.

Downloads SPY daily (yfinance, auto-adjusted), computes each scheduled FOMC
event's pre-FOMC (D-1) return, builds the pooled non-event baseline, applies the
2 bps after-cost gate, splits IS (2015-2020) vs OOS (2021-2025), and runs a
Monte-Carlo placebo (random pseudo-event pre-days drift ~0). Honestly counts
events dropped for incomplete windows.

Usage:
    .venv/bin/python scripts/run_fomc_drift_study.py
    .venv/bin/python scripts/run_fomc_drift_study.py --placebo 5000 --seed 7
"""

from __future__ import annotations

import argparse
import contextlib
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import structlog
import yfinance as yf

from trader.catalysts.fomc_drift import (
    ROUND_TRIP_COST,
    EventReturn,
    abnormal_pre_fomc,
    compute_event_return,
    evaluate_gate,
    non_event_baseline_mean,
    summarize,
)

warnings.filterwarnings("ignore")
log = structlog.get_logger("fomc_drift.runner")

OUT_DIR = Path(__file__).resolve().parents[1] / "data"
CACHE = OUT_DIR / "fomc_spy.pkl"
RESULTS_TXT = OUT_DIR / "fomc_drift_results.txt"

_LINES: list[str] = []

# Scheduled FOMC announcement (2nd/decision) days, hardcoded from the Fed
# calendar (pre-reg §10). The Mar 2020 scheduled meeting was cancelled (emergency
# Mar 15 action) and is intentionally omitted. Knowable ex-ante.
FOMC_DATES: list[date] = [
    # 2015
    date(2015, 1, 28), date(2015, 3, 18), date(2015, 4, 29), date(2015, 6, 17),
    date(2015, 7, 29), date(2015, 9, 17), date(2015, 10, 28), date(2015, 12, 16),
    # 2016
    date(2016, 1, 27), date(2016, 3, 16), date(2016, 4, 27), date(2016, 6, 15),
    date(2016, 7, 27), date(2016, 9, 21), date(2016, 11, 2), date(2016, 12, 14),
    # 2017
    date(2017, 2, 1), date(2017, 3, 15), date(2017, 5, 3), date(2017, 6, 14),
    date(2017, 7, 26), date(2017, 9, 20), date(2017, 11, 1), date(2017, 12, 13),
    # 2018
    date(2018, 1, 31), date(2018, 3, 21), date(2018, 5, 2), date(2018, 6, 13),
    date(2018, 8, 1), date(2018, 9, 26), date(2018, 11, 8), date(2018, 12, 19),
    # 2019
    date(2019, 1, 30), date(2019, 3, 20), date(2019, 5, 1), date(2019, 6, 19),
    date(2019, 7, 31), date(2019, 9, 18), date(2019, 10, 30), date(2019, 12, 11),
    # 2020 (Mar 18 cancelled -> emergency Mar 15; omitted)
    date(2020, 1, 29), date(2020, 4, 29), date(2020, 6, 10), date(2020, 7, 29),
    date(2020, 9, 16), date(2020, 11, 5), date(2020, 12, 16),
    # 2021
    date(2021, 1, 27), date(2021, 3, 17), date(2021, 4, 28), date(2021, 6, 16),
    date(2021, 7, 28), date(2021, 9, 22), date(2021, 11, 3), date(2021, 12, 15),
    # 2022
    date(2022, 1, 26), date(2022, 3, 16), date(2022, 5, 4), date(2022, 6, 15),
    date(2022, 7, 27), date(2022, 9, 21), date(2022, 11, 2), date(2022, 12, 14),
    # 2023
    date(2023, 2, 1), date(2023, 3, 22), date(2023, 5, 3), date(2023, 6, 14),
    date(2023, 7, 26), date(2023, 9, 20), date(2023, 11, 1), date(2023, 12, 13),
    # 2024
    date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1), date(2024, 6, 12),
    date(2024, 7, 31), date(2024, 9, 18), date(2024, 11, 7), date(2024, 12, 18),
    # 2025
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7), date(2025, 6, 18),
    date(2025, 7, 30), date(2025, 9, 17), date(2025, 10, 29), date(2025, 12, 10),
]


def emit(line: str = "") -> None:
    print(line, flush=True)
    _LINES.append(line)


def _load_spy() -> pd.Series:
    if CACHE.exists():
        with contextlib.suppress(Exception):
            s = pd.read_pickle(CACHE)
            if isinstance(s, pd.Series) and len(s) > 100:
                log.info("spy_cache.loaded", n=len(s))
                return s
    df = yf.download("SPY", start="2014-06-01", end="2026-01-01", progress=False, auto_adjust=True)
    if df is None or df.empty or "Close" not in df:
        raise SystemExit("FATAL: could not download SPY.")
    s = df["Close"]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    s.name = "SPY"
    OUT_DIR.mkdir(exist_ok=True)
    with contextlib.suppress(Exception):
        pd.to_pickle(s, CACHE)
    return s


def _collect(close: pd.Series, dates: list[date]) -> tuple[list[EventReturn], int]:
    events: list[EventReturn] = []
    dropped = 0
    for d in dates:
        ev = compute_event_return(close, d)
        if ev is None:
            dropped += 1
            continue
        events.append(ev)
    return events, dropped


def _placebo(close: pd.Series, real_events: list[EventReturn], baseline_mean: float,
             *, n_iter: int, seed: int) -> tuple[float, float]:
    """Monte-Carlo placebo: draw len(events) random non-event pre-days, compute the
    abnormal pre-day mean and its |t| each iteration. Return (placebo mean of
    abnormal means, 95th-pct |t|). Pseudo-events avoid the real event neighborhood.
    """

    close = close.dropna().sort_index()
    ret = close.pct_change()
    dates = close.index
    n = len(dates)
    rng = np.random.default_rng(seed)
    # eligible "pre-day" indices: not within 3 trading days of a real event,
    # and have a valid return.
    excluded: set[int] = set()
    for ev in real_events:
        pos = int(dates.searchsorted(pd.Timestamp(ev.d_date), side="left"))
        for k in range(pos - 3, pos + 4):
            if 0 <= k < n:
                excluded.add(k)
    eligible = [
        i for i in range(1, n)
        if i not in excluded and ret.iloc[i] == ret.iloc[i]
        and abs(float(ret.iloc[i])) <= 0.30
    ]
    k = len(real_events)
    abn_means: list[float] = []
    abn_ts: list[float] = []
    for _ in range(n_iter):
        pick = rng.choice(eligible, size=k, replace=False)
        vals = [float(ret.iloc[i]) for i in pick]
        st = summarize(vals, label="placebo")
        abn_means.append(st.mean - baseline_mean)
        abn_ts.append(abs(st.t_stat))
    return float(np.mean(abn_means)), float(np.percentile(abn_ts, 95))


def run(n_placebo: int, seed: int) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    close = _load_spy()
    emit(f"SPY loaded: {len(close)} bars, {close.index.min().date()}..{close.index.max().date()}")

    events, dropped = _collect(close, FOMC_DATES)
    emit("\n--- DATA WALL (count, don't hide) ---")
    emit(f"scheduled FOMC events: {len(FOMC_DATES)}; usable: {len(events)}; "
         f"dropped (incomplete window / glitch): {dropped}")

    baseline = non_event_baseline_mean(close, [e.d_date for e in events])
    emit(f"non-event baseline: mean={baseline.mean:+.6f} (N={baseline.n} days)")

    def windows_block(evs: list[EventReturn], label: str) -> None:
        emit(f"\n=== {label}  (N={len(evs)}) ===")
        emit(f"{'window':<12}{'mean':>12}{'median':>12}{'%pos':>8}{'t-stat':>9}")
        for col in ("pre_fomc", "announce", "pre2"):
            st = summarize([getattr(e, col) for e in evs], label=col)
            emit(f"{col:<12}{st.mean:>+12.6f}{st.median:>+12.6f}{st.pct_positive:>8.2f}{st.t_stat:>+9.2f}")

    windows_block(events, "ALL EVENTS")

    full = abnormal_pre_fomc(events, baseline)
    emit("\n=== PRE-FOMC ABNORMAL RETURN (primary) ===")
    emit(f"cohort pre_fomc mean : {full.cohort_mean:+.6f}")
    emit(f"non-event baseline   : {full.baseline_mean:+.6f}")
    emit(f"abnormal (gross)     : {full.abnormal_mean:+.6f}")
    emit(f"after-cost ({ROUND_TRIP_COST*1e4:.0f}bps) mean: {full.after_cost_mean:+.6f}")
    emit(f"after-cost abnormal  : {full.after_cost_abnormal:+.6f}")
    emit(f"pre_fomc t-stat      : {full.t_stat:+.2f}   %pos: {full.pct_positive:.2f}")

    # IS vs OOS
    is_evs = [e for e in events if e.d_date.year <= 2020]
    oos_evs = [e for e in events if e.d_date.year >= 2021]
    is_pre = summarize([e.pre_fomc for e in is_evs], label="IS")
    oos_pre = summarize([e.pre_fomc for e in oos_evs], label="OOS")
    emit("\n=== IS (2015-2020) vs OOS (2021-2025), pre_fomc ===")
    emit(f"IS  N={is_pre.n} mean={is_pre.mean:+.6f} t={is_pre.t_stat:+.2f} %pos={is_pre.pct_positive:.2f}")
    emit(f"OOS N={oos_pre.n} mean={oos_pre.mean:+.6f} t={oos_pre.t_stat:+.2f} %pos={oos_pre.pct_positive:.2f}")
    if is_pre.mean == is_pre.mean and oos_pre.mean == oos_pre.mean:
        decay = "DECAYED (OOS < IS)" if oos_pre.mean < is_pre.mean else "persisted/grew"
        emit(f"decay: {decay}")

    # Placebo
    placebo_mean, placebo_t95 = _placebo(
        close, events, baseline.mean, n_iter=n_placebo, seed=seed
    )
    emit(f"\n=== PLACEBO ({n_placebo} random pseudo-event draws, seed={seed}) ===")
    emit(f"placebo abnormal mean: {placebo_mean:+.6f} (expect ~0)")
    emit(f"placebo 95th-pct |t| : {placebo_t95:.2f}   real |t|: {abs(full.t_stat):.2f}")

    # Too-good tripwire
    sharpe = (full.cohort_mean / summarize([e.pre_fomc for e in events], label="x").std
              if events else 0.0)
    if abs(sharpe) > 3 or full.pct_positive > 0.85:
        emit(f"\n[TRIPWIRE] per-event Sharpe={sharpe:.2f} %pos={full.pct_positive:.2f} "
             "-> inspect top contributors")
        top = sorted(events, key=lambda e: e.pre_fomc, reverse=True)[:5]
        for e in top:
            emit(f"   {e.d_date} pre_fomc={e.pre_fomc:+.4f}")

    emit("\n=== PRE-REGISTERED GATE ===")
    gate = evaluate_gate(full, is_pre, oos_pre, placebo_t95, full.t_stat)
    for r in gate.reasons:
        emit(f"  {r}")
    emit(f"\nGATE: {'PASS' if gate.passed else 'FAIL — idea killed / null result'}")

    RESULTS_TXT.write_text("\n".join(_LINES) + "\n")
    log.info("results.written", path=str(RESULTS_TXT))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--placebo", type=int, default=2000)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    run(args.placebo, args.seed)


if __name__ == "__main__":
    main()
