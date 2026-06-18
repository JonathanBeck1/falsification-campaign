"""Network-free tests for the day-of-week & pre-holiday study (T50).

Covers: close-to-close return construction with the glitch guard; weekday
labeling and cohort aggregation; the calendar-gap pre-holiday mask (weekend gaps
are NOT pre-holiday, mid-week holiday gaps ARE); Monday and pre-holiday abnormal
+ after-cost arithmetic; the IS/OOS split; and the per-effect gate logic with an
injected effect. No I/O — everything runs on synthetic in-memory series.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from trader.catalysts.day_of_week import (
    MAX_ABS_DAILY_RET,
    ROUND_TRIP_COST,
    AbnormalResult,
    CohortStats,
    daily_returns,
    evaluate_gate,
    monday_abnormal,
    pre_holiday_abnormal,
    pre_holiday_mask,
    split_is_oos,
    summarize,
    weekday_cohorts,
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
# daily returns + glitch guard
# --------------------------------------------------------------------------- #
def test_daily_returns_basic():
    idx = _bdays(date(2020, 1, 1), 4)
    close = pd.Series([100.0, 101.0, 102.0, 103.0], index=idx)
    r = daily_returns(close)
    assert len(r) == 3
    assert abs(r.iloc[0] - 0.01) < 1e-9


def test_daily_returns_drops_glitch():
    idx = _bdays(date(2020, 1, 1), 4)
    # 100 -> 200 is a +100% print (split-like glitch) and must be dropped.
    close = pd.Series([100.0, 200.0, 201.0, 202.0], index=idx)
    r = daily_returns(close)
    assert all(r.abs() <= MAX_ABS_DAILY_RET)
    # The glitch day return is removed; the others survive.
    assert len(r) == 2


# --------------------------------------------------------------------------- #
# weekday cohorts
# --------------------------------------------------------------------------- #
def test_weekday_cohorts_separate_monday():
    # 4 weeks of business days; inject -1% every Monday, +0.5% otherwise.
    idx = _bdays(date(2021, 1, 4), 20)  # 2021-01-04 is a Monday
    rets = pd.Series(
        [(-0.01 if d.weekday() == 0 else 0.005) for d in idx], index=idx
    )
    coh = weekday_cohorts(rets)
    assert coh[0].n == 4  # four Mondays
    assert coh[0].mean < 0
    for w in (1, 2, 3, 4):
        assert coh[w].mean > 0


def test_monday_abnormal_negative_when_injected():
    idx = _bdays(date(2021, 1, 4), 50)
    rets = pd.Series(
        [(-0.01 if d.weekday() == 0 else 0.002) for d in idx], index=idx
    )
    res = monday_abnormal(rets)
    assert isinstance(res, AbnormalResult)
    assert res.cohort_mean < 0
    assert res.baseline_mean > 0
    assert res.abnormal_mean < 0
    # after-cost shifts the mean down by exactly one round trip.
    assert abs(res.after_cost_mean - (res.cohort_mean - ROUND_TRIP_COST)) < 1e-12
    assert res.abnormal_t < 0  # cohort below baseline


# --------------------------------------------------------------------------- #
# pre-holiday mask (calendar-defined)
# --------------------------------------------------------------------------- #
def test_pre_holiday_mask_weekend_is_not_preholiday():
    # A clean run of business days with no missing weekday => no pre-holiday flags
    # (Fri->Mon weekend gaps must NOT count).
    idx = _bdays(date(2021, 3, 1), 15)
    mask = pre_holiday_mask(idx)
    # Last day cannot be labeled; every other day has only weekend gaps.
    assert not mask.iloc[:-1].any()


def test_pre_holiday_mask_flags_midweek_holiday_gap():
    # Build an index that skips Thursday 2021-07-01 (pretend holiday): the
    # Wednesday before it must be flagged pre-holiday.
    days = list(_bdays(date(2021, 6, 28), 10))
    holiday = pd.Timestamp(2021, 7, 1)  # a Thursday
    idx = pd.DatetimeIndex([d for d in days if d != holiday])
    mask = pre_holiday_mask(idx)
    wed = pd.Timestamp(2021, 6, 30)  # Wednesday before the skipped Thursday
    assert bool(mask.loc[wed]) is True
    # A normal Friday->Monday weekend in the same window stays False.
    fri = pd.Timestamp(2021, 7, 2)
    if fri in mask.index:
        assert bool(mask.loc[fri]) is False


def test_pre_holiday_abnormal_positive_when_injected():
    days = list(_bdays(date(2021, 1, 4), 120))
    # Drop a few mid-week days to create holiday gaps.
    holidays = {pd.Timestamp(2021, 1, 18), pd.Timestamp(2021, 2, 15), pd.Timestamp(2021, 4, 2)}
    idx = pd.DatetimeIndex([d for d in days if d not in holidays])
    mask = pre_holiday_mask(idx)
    base = np.full(len(idx), 0.001)
    base[mask.to_numpy()] = 0.02  # inject a fat positive pre-holiday drift
    rets = pd.Series(base, index=idx)
    res = pre_holiday_abnormal(rets)
    assert res.cohort_mean > res.baseline_mean
    assert res.abnormal_mean > 0
    assert res.abnormal_t > 0


# --------------------------------------------------------------------------- #
# IS / OOS split
# --------------------------------------------------------------------------- #
def test_split_is_oos_halves():
    idx = _bdays(date(2020, 1, 1), 10)
    r = pd.Series(np.arange(10, dtype=float), index=idx)
    is_r, oos_r = split_is_oos(r)
    assert len(is_r) == 5
    assert len(oos_r) == 5
    assert is_r.index.max() < oos_r.index.min()


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #
def _abn(**kw) -> AbnormalResult:
    base = dict(
        label="t", n=100, cohort_mean=-0.001, baseline_mean=0.0005,
        abnormal_mean=-0.0015, after_cost_mean=-0.0012, after_cost_abnormal=-0.0017,
        cohort_t=-3.0, abnormal_t=-3.0, pct_positive=0.45,
    )
    base.update(kw)
    return AbnormalResult(**base)


def _coh(mean: float, n: int = 50) -> CohortStats:
    return CohortStats("c", n, mean, mean, 0.01, 0.5, mean / 0.01)


def test_gate_passes_with_strong_negative_monday():
    full = _abn()  # after-cost mean negative, abnormal |t|=3
    g = evaluate_gate(
        full, _coh(-0.001), _coh(-0.0008),
        placebo_abnormal_t95=2.0, hypothesis_sign=-1,
    )
    assert g.passed
    assert all("PASS" in r for r in g.reasons)


def test_gate_fails_on_wrong_sign_after_cost():
    # Monday effect but after-cost mean is POSITIVE -> wrong direction -> fail.
    full = _abn(after_cost_mean=0.0003)
    g = evaluate_gate(
        full, _coh(-0.001), _coh(-0.0008),
        placebo_abnormal_t95=2.0, hypothesis_sign=-1,
    )
    assert not g.passed


def test_gate_fails_on_oos_sign_flip():
    full = _abn()
    g = evaluate_gate(
        full, _coh(-0.001), _coh(+0.0008),  # OOS flips positive
        placebo_abnormal_t95=2.0, hypothesis_sign=-1,
    )
    assert not g.passed


def test_gate_fails_when_placebo_absorbs():
    full = _abn(abnormal_t=-1.5)  # weak vs placebo band of 2.0
    g = evaluate_gate(
        full, _coh(-0.001), _coh(-0.0008),
        placebo_abnormal_t95=2.0, hypothesis_sign=-1,
    )
    assert not g.passed


def test_gate_fails_on_low_n():
    full = _abn(n=20)
    g = evaluate_gate(
        full, _coh(-0.001, n=10), _coh(-0.0008, n=10),
        placebo_abnormal_t95=2.0, hypothesis_sign=-1,
    )
    assert not g.passed
