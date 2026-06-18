"""Run the pre-registered day-of-week & pre-holiday study (T50) end to end.

Downloads SPY daily (yfinance, auto-adjusted, full ~1993-2025 history), computes
close-to-close returns, labels each by weekday and by pre-holiday status (the last
session before a calendar-gap market holiday), reports each weekday's mean/t, the
PRIMARY Monday-vs-rest and pre-holiday-vs-rest abnormal returns GROSS and AFTER a
2 bps round trip, splits IS (early half) vs OOS (late half), and runs a
Monte-Carlo placebo (random pseudo-effect days abnormal ~0) per effect.

Honest framing: a day-of-week / pre-holiday timing rule trades essentially daily,
so costs dominate. Gross and after-cost are both reported prominently.

Usage:
    .venv/bin/python scripts/run_day_of_week_study.py
    .venv/bin/python scripts/run_day_of_week_study.py --placebo 5000 --seed 7
"""

from __future__ import annotations

import argparse
import contextlib
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import structlog
import yfinance as yf

from trader.catalysts.day_of_week import (
    MONDAY,
    ROUND_TRIP_COST,
    WEEKDAY_NAMES,
    AbnormalResult,
    daily_returns,
    evaluate_gate,
    monday_abnormal,
    pre_holiday_abnormal,
    pre_holiday_mask,
    split_is_oos,
    summarize,
    weekday_cohorts,
)

warnings.filterwarnings("ignore")
log = structlog.get_logger("day_of_week.runner")

OUT_DIR = Path(__file__).resolve().parents[1] / "data"
CACHE = OUT_DIR / "dow_spy.pkl"
RESULTS_TXT = OUT_DIR / "day_of_week_results.txt"

_LINES: list[str] = []


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
    df = yf.download("SPY", start="1993-01-01", end="2026-01-01", progress=False, auto_adjust=True)
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


def _placebo_abnormal_t95(
    returns: pd.Series, cohort_n: int, *, n_iter: int, seed: int
) -> tuple[float, float]:
    """Monte-Carlo placebo: draw ``cohort_n`` random days, compute the abnormal
    mean (vs the complementary pool) and its Welch |t| each iteration. Return
    (placebo mean of abnormal means, 95th-pct |t|). Pure-ish (numpy RNG only).
    """

    vals = returns.to_numpy(dtype=float)
    n = len(vals)
    rng = np.random.default_rng(seed)
    abn_means: list[float] = []
    abn_ts: list[float] = []
    for _ in range(n_iter):
        pick = rng.choice(n, size=cohort_n, replace=False)
        mask = np.zeros(n, dtype=bool)
        mask[pick] = True
        a = vals[mask]
        b = vals[~mask]
        ma, mb = float(a.mean()), float(b.mean())
        va = float(a.var(ddof=1)) / len(a) if len(a) > 1 else 0.0
        vb = float(b.var(ddof=1)) / len(b) if len(b) > 1 else 0.0
        denom = (va + vb) ** 0.5
        t = (ma - mb) / denom if denom else 0.0
        abn_means.append(ma - mb)
        abn_ts.append(abs(t))
    return float(np.mean(abn_means)), float(np.percentile(abn_ts, 95))


def _report_abnormal(res: AbnormalResult, *, sign: int, name: str) -> None:
    want = "+" if sign > 0 else "-"
    emit(f"\n=== {name} ABNORMAL RETURN (primary; hypothesised sign {want}) ===")
    emit(f"cohort mean (gross)  : {res.cohort_mean:+.6f}  (N={res.n}, %pos={res.pct_positive:.2f})")
    emit(f"baseline mean (pool) : {res.baseline_mean:+.6f}")
    emit(f"abnormal (gross)     : {res.abnormal_mean:+.6f}  Welch |t|={abs(res.abnormal_t):.2f}")
    emit(f"AFTER-COST ({ROUND_TRIP_COST*1e4:.0f}bps) mean : {res.after_cost_mean:+.6f}")
    emit(f"AFTER-COST abnormal  : {res.after_cost_abnormal:+.6f}")
    emit(f"cohort one-sample t  : {res.cohort_t:+.2f}")


def _effect_block(
    returns: pd.Series,
    res: AbnormalResult,
    cohort_mask,
    *,
    sign: int,
    name: str,
    n_placebo: int,
    seed: int,
) -> None:
    _report_abnormal(res, sign=sign, name=name)

    # IS / OOS on the cohort returns
    is_r, oos_r = split_is_oos(returns)
    is_coh = summarize([float(v) for v in is_r[cohort_mask(is_r)].tolist()], label="IS")
    oos_coh = summarize([float(v) for v in oos_r[cohort_mask(oos_r)].tolist()], label="OOS")
    emit(f"\n--- {name}: IS (early half) vs OOS (late half), cohort returns ---")
    emit(f"IS  N={is_coh.n} mean={is_coh.mean:+.6f} t={is_coh.t_stat:+.2f} %pos={is_coh.pct_positive:.2f}")
    emit(f"OOS N={oos_coh.n} mean={oos_coh.mean:+.6f} t={oos_coh.t_stat:+.2f} %pos={oos_coh.pct_positive:.2f}")
    if is_coh.mean == is_coh.mean and oos_coh.mean == oos_coh.mean:
        flip = "SIGN FLIP" if (is_coh.mean * oos_coh.mean) < 0 else "same sign"
        shrink = "decayed (|OOS|<|IS|)" if abs(oos_coh.mean) < abs(is_coh.mean) else "persisted/grew"
        emit(f"persistence: {flip}; {shrink}")

    # Placebo
    placebo_mean, placebo_t95 = _placebo_abnormal_t95(
        returns, res.n, n_iter=n_placebo, seed=seed
    )
    emit(f"\n--- {name}: PLACEBO ({n_placebo} random draws, seed={seed}) ---")
    emit(f"placebo abnormal mean: {placebo_mean:+.6f} (expect ~0)")
    emit(f"placebo 95th-pct |t| : {placebo_t95:.2f}   real abnormal |t|: {abs(res.abnormal_t):.2f}")

    # Too-good tripwire
    if abs(res.pct_positive - 0.5) > 0.35 or (res.cohort_mean and abs(res.cohort_mean) > 0.02):
        emit(f"[TRIPWIRE] {name}: %pos={res.pct_positive:.2f} mean={res.cohort_mean:+.4f} -> inspect")

    emit(f"\n--- {name}: PRE-REGISTERED GATE ---")
    gate = evaluate_gate(res, is_coh, oos_coh, placebo_t95, hypothesis_sign=sign)
    for r in gate.reasons:
        emit(f"  {r}")
    emit(f"{name} GATE: {'PASS' if gate.passed else 'FAIL — effect killed / null'}")


def run(n_placebo: int, seed: int) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    close = _load_spy()
    emit(f"SPY loaded: {len(close)} bars, {close.index.min().date()}..{close.index.max().date()}")

    returns = daily_returns(close)
    emit("\n--- DATA WALL (count, don't hide) ---")
    emit(f"close-to-close returns: {len(returns)}; span "
         f"{returns.index.min().date()}..{returns.index.max().date()}")
    mask = pre_holiday_mask(returns.index).reindex(returns.index).fillna(False)
    emit(f"pre-holiday days flagged (calendar-gap): {int(mask.sum())}")

    # Full weekday table
    emit("\n=== WEEKDAY MEAN RETURNS (one-sample t vs 0) ===")
    emit(f"{'weekday':<10}{'N':>7}{'mean':>12}{'after-cost':>13}{'median':>12}{'%pos':>8}{'t':>8}")
    coh = weekday_cohorts(returns)
    for w in range(5):
        c = coh[w]
        ac = c.mean - ROUND_TRIP_COST
        emit(f"{WEEKDAY_NAMES[w]:<10}{c.n:>7}{c.mean:>+12.6f}{ac:>+13.6f}"
             f"{c.median:>+12.6f}{c.pct_positive:>8.2f}{c.t_stat:>+8.2f}")

    # (a) Monday effect
    mon_res = monday_abnormal(returns)
    _effect_block(
        returns, mon_res,
        cohort_mask=lambda r: (r.index.weekday == MONDAY),
        sign=-1, name="MONDAY", n_placebo=n_placebo, seed=seed,
    )

    # (b) Pre-holiday drift
    ph_res = pre_holiday_abnormal(returns)

    def _ph_mask(r: pd.Series):
        m = pre_holiday_mask(r.index).reindex(r.index).fillna(False)
        return m.to_numpy()

    _effect_block(
        returns, ph_res,
        cohort_mask=_ph_mask,
        sign=+1, name="PRE-HOLIDAY", n_placebo=n_placebo, seed=seed + 1,
    )

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
