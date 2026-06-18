"""Network-free tests for the turn-of-month effect study (T48).

Covers: the calendar TOM mask (last-trading-day + first three trading days, no
look-ahead), the TOM/ROM split + Welch difference with an injected TOM bump, the
glitch guard, the after-cost arithmetic, the placebo distribution, and the gate.
No I/O — everything runs on synthetic in-memory daily-return series.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from trader.catalysts.turn_of_month import (
    TomResult,
    WindowStats,
    compute_tom,
    evaluate_gate,
    placebo_diffs,
    summarize,
    turn_of_month_mask,
)


def _bdays(start: date, n: int) -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


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
# calendar mask
# --------------------------------------------------------------------------- #
def test_mask_marks_last_and_first_three_trading_days():
    # A full single month (Jan 2021) plus a few days into Feb so Jan's LDOM is the
    # last Jan bday and Feb's first three bdays are flagged.
    idx = pd.bdate_range(date(2021, 1, 1), date(2021, 2, 10))
    mask = turn_of_month_mask(idx)
    jan = idx[idx.month == 1]
    feb = idx[idx.month == 2]
    # Jan LDOM = last Jan business day -> True; Jan day 5..(n-1) -> False.
    assert mask.loc[jan[-1]]  # LDOM Jan
    assert mask.loc[jan[0]]   # first trading day Jan (+1)
    assert mask.loc[jan[1]]   # +2
    assert mask.loc[jan[2]]   # +3
    assert not mask.loc[jan[3]]   # +4 -> ROM
    assert not mask.loc[jan[10]]  # mid-month -> ROM
    # Feb first three -> True.
    assert mask.loc[feb[0]] and mask.loc[feb[1]] and mask.loc[feb[2]]


def test_mask_count_is_four_per_full_month_turn():
    idx = pd.bdate_range(date(2021, 3, 1), date(2021, 3, 31))
    mask = turn_of_month_mask(idx)
    # Within a single fully-present month, TOM days = first 3 + LDOM = 4.
    assert int(mask.sum()) == 4


def test_mask_uses_only_calendar_not_returns():
    # The mask takes only an index; identical indices give identical masks
    # regardless of any return values -> structurally cannot peek at returns.
    idx = _bdays(date(2021, 1, 4), 60)
    m1 = turn_of_month_mask(idx)
    m2 = turn_of_month_mask(idx)
    assert m1.equals(m2)


# --------------------------------------------------------------------------- #
# compute_tom split + injected bump
# --------------------------------------------------------------------------- #
def _flat_returns(idx: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(np.zeros(len(idx)), index=idx, name="r")


def test_compute_tom_zero_diff_when_flat():
    idx = pd.bdate_range(date(2010, 1, 1), date(2012, 12, 31))
    res = compute_tom(_flat_returns(idx))
    assert res.tom.n > 0 and res.rom.n > 0
    assert abs(res.diff) < 1e-12


def test_compute_tom_recovers_injected_tom_bump():
    idx = pd.bdate_range(date(2005, 1, 1), date(2015, 12, 31))
    r = _flat_returns(idx)
    mask = turn_of_month_mask(idx).reindex(idx).fillna(False)
    bump = 0.002  # +20 bps on every TOM day
    r[mask.to_numpy()] = bump
    res = compute_tom(r, cost=0.0)
    assert abs(res.tom.mean - bump) < 1e-9
    assert abs(res.rom.mean) < 1e-12
    assert abs(res.diff - bump) < 1e-9
    assert res.welch_t > 5  # large, many TOM days, zero ROM variance-ish


def test_compute_tom_after_cost_subtracts_per_day():
    idx = pd.bdate_range(date(2005, 1, 1), date(2010, 12, 31))
    r = _flat_returns(idx)
    mask = turn_of_month_mask(idx).reindex(idx).fillna(False)
    r[mask.to_numpy()] = 0.001
    res = compute_tom(r, cost=0.00005)
    assert abs(res.after_cost_diff - (res.diff - 0.00005)) < 1e-12


def test_compute_tom_drops_glitch_returns():
    idx = pd.bdate_range(date(2010, 1, 1), date(2011, 12, 31))
    r = _flat_returns(idx)
    r.iloc[20] = 5.0  # +500% glitch -> dropped by MAX_ABS_DAILY_RET
    res = compute_tom(r)
    # glitch excluded -> all-zero populations -> zero diff, finite stats
    assert abs(res.diff) < 1e-12
    assert res.tom.n + res.rom.n == len(idx) - 1


# --------------------------------------------------------------------------- #
# placebo
# --------------------------------------------------------------------------- #
def test_placebo_centers_near_zero_on_flat_noise():
    rng = np.random.default_rng(7)
    idx = pd.bdate_range(date(2000, 1, 1), date(2015, 12, 31))
    r = pd.Series(rng.normal(0, 0.01, len(idx)), index=idx, name="r")
    ts = placebo_diffs(r, n_trials=50, seed=1)
    assert len(ts) == 50
    # random pseudo-windows on noise -> mean |t| small, 95th pct modest
    assert abs(float(np.mean(ts))) < 1.0
    assert float(np.percentile(np.abs(ts), 95)) < 3.0


def test_placebo_below_real_when_true_tom_bump_present():
    idx = pd.bdate_range(date(1995, 1, 1), date(2015, 12, 31))
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0, 0.005, len(idx)), index=idx, name="r")
    mask = turn_of_month_mask(idx).reindex(idx).fillna(False)
    r[mask.to_numpy()] += 0.003  # strong real TOM bump
    res = compute_tom(r, cost=0.0)
    placebo_95 = float(np.percentile(np.abs(placebo_diffs(r, n_trials=100, seed=2)), 95))
    assert abs(res.welch_t) > placebo_95


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #
def _res(diff: float, welch_t: float, tom_n: int, *, cost: float = 0.00005) -> TomResult:
    tom = WindowStats("tom", tom_n, diff, diff, 0.01, 0.55, 2.0)
    rom = WindowStats("rom", 3000, 0.0, 0.0, 0.01, 0.5, 0.0)
    return TomResult(tom=tom, rom=rom, diff=diff, after_cost_diff=diff - cost, welch_t=welch_t)


def test_gate_passes_on_strong_consistent_signal():
    full = _res(0.0008, 3.0, 800)
    is_r = _res(0.0009, 2.5, 400)
    oos_r = _res(0.0007, 2.2, 400)
    v = evaluate_gate(full, is_r, oos_r, placebo_abs_t_95=1.8)
    assert v.passed is True


def test_gate_fails_on_low_half_n():
    full = _res(0.0008, 3.0, 800)
    is_r = _res(0.0009, 2.5, 50)  # IS TOM N too small
    oos_r = _res(0.0007, 2.2, 400)
    v = evaluate_gate(full, is_r, oos_r, placebo_abs_t_95=1.8)
    assert v.passed is False
    assert any("TOM N" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_on_weak_after_cost_tstat():
    full = _res(0.00006, 0.6, 800)  # net barely positive, t small
    is_r = _res(0.0001, 0.8, 400)
    oos_r = _res(0.00002, 0.2, 400)
    v = evaluate_gate(full, is_r, oos_r, placebo_abs_t_95=1.8)
    assert v.passed is False


def test_gate_fails_on_oos_sign_flip():
    full = _res(0.0008, 3.0, 800)
    is_r = _res(0.0012, 3.0, 400)
    oos_r = _res(-0.0003, -1.0, 400)  # decayed / flipped
    v = evaluate_gate(full, is_r, oos_r, placebo_abs_t_95=1.8)
    assert v.passed is False
    assert any("OOS sign" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_when_placebo_matches_real():
    full = _res(0.0008, 2.2, 800)
    is_r = _res(0.0009, 2.0, 400)
    oos_r = _res(0.0007, 1.9, 400)
    v = evaluate_gate(full, is_r, oos_r, placebo_abs_t_95=2.5)  # placebo as wide as real
    assert v.passed is False
    assert any("placebo" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_when_negative_after_cost():
    full = _res(0.00003, 2.5, 800)  # significant but net-negative after 0.5bp cost
    is_r = _res(0.00008, 2.0, 400)
    oos_r = _res(0.00002, 1.5, 400)
    v = evaluate_gate(full, is_r, oos_r, placebo_abs_t_95=1.8)
    assert v.passed is False
