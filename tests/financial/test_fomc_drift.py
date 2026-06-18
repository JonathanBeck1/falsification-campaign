"""Network-free tests for the FOMC pre-announcement drift study (T47).

Covers: per-event pre-FOMC return extraction with an injected drift, the glitch
guard, t0 resolution, the pooled non-event baseline (with event-neighborhood
exclusion), the abnormal-return + after-cost arithmetic, and the gate logic. No
I/O — everything runs on synthetic in-memory series.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from trader.catalysts.fomc_drift import (
    AbnormalResult,
    CohortStats,
    abnormal_pre_fomc,
    compute_event_return,
    evaluate_gate,
    non_event_baseline_mean,
    summarize,
)


def _flat_close(start: date, n: int, *, level: float = 100.0) -> pd.Series:
    idx = pd.bdate_range(start, periods=n)
    return pd.Series(level * np.ones(n), index=idx, name="SPY")


# --------------------------------------------------------------------------- #
# summarize / t-stat
# --------------------------------------------------------------------------- #
def test_summarize_basic_stats():
    s = summarize([0.01, 0.02, 0.03], label="x")
    assert s.n == 3
    assert abs(s.mean - 0.02) < 1e-12
    assert abs(s.median - 0.02) < 1e-12
    assert s.pct_positive == 1.0
    assert s.t_stat > 0


def test_summarize_empty_is_nan_n0():
    s = summarize([], label="x")
    assert s.n == 0
    assert s.mean != s.mean  # NaN


def test_summarize_ignores_nan_values():
    s = summarize([0.01, float("nan"), 0.03], label="x")
    assert s.n == 2


# --------------------------------------------------------------------------- #
# per-event pre-FOMC return
# --------------------------------------------------------------------------- #
def test_pre_fomc_zero_when_flat():
    close = _flat_close(date(2020, 1, 1), 40)
    ev = compute_event_return(close, date(2020, 2, 1))
    assert ev is not None
    assert abs(ev.pre_fomc) < 1e-12
    assert abs(ev.announce) < 1e-12


def test_pre_fomc_captures_injected_drift_on_day_before():
    idx = pd.bdate_range(date(2020, 1, 1), periods=40)
    px = pd.Series(100.0 * np.ones(40), index=idx, name="SPY")
    d_pos = int(idx.searchsorted(pd.Timestamp(date(2020, 2, 1)), side="left"))
    # +1.5% on the D-1 bar (the pre-FOMC session), nothing else.
    px.iloc[d_pos - 1 :] *= 1.015
    ev = compute_event_return(px, date(2020, 2, 1))
    assert ev is not None
    assert abs(ev.pre_fomc - 0.015) < 1e-6
    assert abs(ev.announce) < 1e-9  # no move on D itself
    assert abs(ev.pre2 - 0.015) < 1e-6  # D-2 flat, D-1 +1.5%


def test_pre_fomc_announce_return_isolated_on_event_day():
    idx = pd.bdate_range(date(2020, 1, 1), periods=40)
    px = pd.Series(100.0 * np.ones(40), index=idx, name="SPY")
    d_pos = int(idx.searchsorted(pd.Timestamp(date(2020, 2, 1)), side="left"))
    px.iloc[d_pos:] *= 1.02  # +2% on the announcement day only
    ev = compute_event_return(px, date(2020, 2, 1))
    assert ev is not None
    assert abs(ev.pre_fomc) < 1e-9  # pre-day flat
    assert abs(ev.announce - 0.02) < 1e-6


def test_pre_fomc_drops_glitch_day():
    idx = pd.bdate_range(date(2020, 1, 1), periods=40)
    px = pd.Series(100.0 * np.ones(40), index=idx, name="SPY")
    d_pos = int(idx.searchsorted(pd.Timestamp(date(2020, 2, 1)), side="left"))
    px.iloc[d_pos - 1] = 200.0  # +100% then back -> giant glitch return on D-1
    px.iloc[d_pos:] = 100.0
    assert compute_event_return(px, date(2020, 2, 1)) is None


def test_pre_fomc_none_when_event_too_early():
    close = _flat_close(date(2020, 1, 1), 40)
    # event before the series has 2 prior bars -> no D-2 return formable
    assert compute_event_return(close, date(2020, 1, 1)) is None


def test_pre_fomc_none_when_event_after_series():
    close = _flat_close(date(2020, 1, 1), 40)
    assert compute_event_return(close, date(2021, 1, 1)) is None


def test_d_resolves_to_first_trading_day_on_or_after():
    close = _flat_close(date(2020, 1, 1), 60)
    # 2020-02-15 is a Saturday; D should resolve to Mon 2020-02-17 (Presidents'
    # Day is a market holiday but bdate_range ignores it — fine for this check).
    ev = compute_event_return(close, date(2020, 2, 15))
    assert ev is not None
    assert ev.d_date >= date(2020, 2, 15)
    assert ev.d_date.weekday() < 5


# --------------------------------------------------------------------------- #
# pooled non-event baseline
# --------------------------------------------------------------------------- #
def test_baseline_excludes_event_neighborhood():
    # Flat everywhere except a +5% spike 1 day before an event day. With the
    # neighborhood excluded, the baseline should NOT see that spike.
    idx = pd.bdate_range(date(2020, 1, 1), periods=60)
    px = pd.Series(100.0 * np.ones(60), index=idx, name="SPY")
    ev_day = date(2020, 2, 3)
    d_pos = int(idx.searchsorted(pd.Timestamp(ev_day), side="left"))
    px.iloc[d_pos - 1 :] *= 1.05  # spike on the pre-event bar
    base = non_event_baseline_mean(px, [ev_day], exclusion=3)
    # all the non-excluded bars are flat -> baseline mean ~0
    assert abs(base.mean) < 1e-9
    assert base.n > 0


def test_baseline_nonzero_when_background_drifts():
    idx = pd.bdate_range(date(2020, 1, 1), periods=60)
    px = pd.Series(100.0 * (1.0 + 0.001) ** np.arange(60), index=idx, name="SPY")
    base = non_event_baseline_mean(px, [date(2020, 2, 3)], exclusion=3)
    assert abs(base.mean - 0.001) < 1e-6


# --------------------------------------------------------------------------- #
# abnormal return + after-cost arithmetic
# --------------------------------------------------------------------------- #
def test_abnormal_subtracts_baseline_and_cost():
    events = [
        compute_event_return(_drift_series(date(2020, 1, 1), 40, 0.01, i), date(2020, 2, 1))
        for i in range(5)
    ]
    events = [e for e in events if e is not None]
    assert len(events) == 5
    baseline = CohortStats("base", 100, 0.001, 0.001, 0.0, 0.5, 0.0)
    res = abnormal_pre_fomc(events, baseline, cost=0.0002)
    assert abs(res.cohort_mean - 0.01) < 1e-6
    assert abs(res.abnormal_mean - (0.01 - 0.001)) < 1e-6
    assert abs(res.after_cost_mean - (0.01 - 0.0002)) < 1e-6
    assert abs(res.after_cost_abnormal - (0.01 - 0.001 - 0.0002)) < 1e-6


def _drift_series(start: date, n: int, pre_drift: float, _seed: int) -> pd.Series:
    idx = pd.bdate_range(start, periods=n)
    px = pd.Series(100.0 * np.ones(n), index=idx, name="SPY")
    d_pos = int(idx.searchsorted(pd.Timestamp(date(2020, 2, 1)), side="left"))
    px.iloc[d_pos - 1 :] *= 1.0 + pre_drift
    return px


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #
def _abn(n: int, after_cost_mean: float, t: float) -> AbnormalResult:
    return AbnormalResult(
        n=n,
        cohort_mean=after_cost_mean + 0.0002,
        baseline_mean=0.0,
        abnormal_mean=after_cost_mean + 0.0002,
        after_cost_mean=after_cost_mean,
        after_cost_abnormal=after_cost_mean,
        t_stat=t,
        pct_positive=0.6,
    )


def _stats(n: int, mean: float) -> CohortStats:
    return CohortStats("x", n, mean, mean, 0.01, 0.6, 2.0)


def test_gate_passes_on_strong_consistent_signal():
    full = _abn(80, 0.003, 3.0)
    v = evaluate_gate(full, _stats(40, 0.004), _stats(40, 0.003), placebo_abnormal_t=1.0, real_t=3.0)
    assert v.passed is True


def test_gate_fails_on_low_n():
    full = _abn(20, 0.003, 3.0)
    v = evaluate_gate(full, _stats(10, 0.004), _stats(10, 0.003), placebo_abnormal_t=1.0, real_t=3.0)
    assert v.passed is False
    assert any("N=20" in r for r in v.reasons)


def test_gate_fails_on_weak_after_cost_tstat():
    full = _abn(80, 0.0005, 0.6)  # decayed/in-noise
    v = evaluate_gate(full, _stats(40, 0.001), _stats(40, 0.0002), placebo_abnormal_t=1.0, real_t=0.6)
    assert v.passed is False


def test_gate_fails_on_oos_sign_flip():
    full = _abn(80, 0.003, 3.0)
    v = evaluate_gate(full, _stats(40, 0.005), _stats(40, -0.002), placebo_abnormal_t=1.0, real_t=3.0)
    assert v.passed is False
    assert any("OOS sign" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_when_negative_after_cost():
    full = _abn(80, -0.0001, 2.5)  # significant but net-negative after cost
    v = evaluate_gate(full, _stats(40, 0.002), _stats(40, 0.001), placebo_abnormal_t=1.0, real_t=2.5)
    assert v.passed is False


def test_gate_fails_when_placebo_matches_real():
    full = _abn(80, 0.003, 2.2)
    # placebo band as wide as the real signal -> not distinguishable
    v = evaluate_gate(full, _stats(40, 0.004), _stats(40, 0.003), placebo_abnormal_t=2.5, real_t=2.2)
    assert v.passed is False
    assert any("placebo" in r and "FAIL" in r for r in v.reasons)
