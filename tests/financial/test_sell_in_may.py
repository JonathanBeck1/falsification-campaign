"""Network-free tests for the Sell-in-May / Halloween study (T49).

Covers: the small pure stats (mean/std/Sharpe/annualized return/Welch t), the
daily->monthly resample, the calendar season split, the seasonal-strategy and
buy-and-hold return streams (incl. the once-a-year round-trip cost), and the
gate logic (decisive Sharpe-vs-B&H check + OOS stability). No I/O — synthetic
in-memory series only, several with an injected seasonal effect.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from trader.catalysts.sell_in_may import (
    ROUND_TRIP_COST,
    SeasonSplit,
    StrategyStats,
    annualized_return,
    annualized_sharpe,
    buy_and_hold_returns,
    evaluate_gate,
    is_winter,
    mean,
    seasonal_strategy_returns,
    split_by_season,
    std,
    summarize_strategy,
    to_monthly_returns,
    welch_t,
)


# --------------------------------------------------------------------------- #
# season membership
# --------------------------------------------------------------------------- #
def test_is_winter_covers_nov_through_apr():
    assert all(is_winter(m) for m in (11, 12, 1, 2, 3, 4))
    assert not any(is_winter(m) for m in (5, 6, 7, 8, 9, 10))


# --------------------------------------------------------------------------- #
# small pure stats
# --------------------------------------------------------------------------- #
def test_mean_std_basic():
    assert abs(mean([0.01, 0.02, 0.03]) - 0.02) < 1e-12
    assert abs(std([0.0, 0.2]) - 0.2 / math.sqrt(2.0)) < 1e-12  # ddof=1


def test_stats_drop_glitch_values():
    # a +200% month is beyond MAX_ABS_MONTHLY_RET and is dropped
    assert abs(mean([0.01, 2.0, 0.03]) - 0.02) < 1e-12


def test_annualized_sharpe_sign_and_zero_var():
    pos = annualized_sharpe([0.01] * 12)  # zero variance -> NaN, not inf
    assert pos != pos
    s = annualized_sharpe([0.02, -0.01, 0.03, 0.00])
    assert s > 0
    assert annualized_sharpe([0.01]) != annualized_sharpe([0.01])  # <2 obs -> NaN


def test_annualized_sharpe_rf_lowers_it():
    r = [0.02, 0.01, 0.03, 0.00, 0.02, -0.01]
    assert annualized_sharpe(r, rf_monthly=0.0) > annualized_sharpe(r, rf_monthly=0.01)


def test_annualized_return_geometric():
    # +1% every month for 12 months -> 1.01**12 - 1
    assert abs(annualized_return([0.01] * 12) - (1.01**12 - 1.0)) < 1e-12


def test_welch_t_positive_when_a_exceeds_b():
    a = [0.03, 0.04, 0.02, 0.05]
    b = [-0.01, 0.00, -0.02, 0.01]
    assert welch_t(a, b) > 0
    assert welch_t(b, a) < 0


def test_welch_t_zero_on_too_few_obs():
    assert welch_t([0.01], [0.02, 0.03]) == 0.0


# --------------------------------------------------------------------------- #
# daily -> monthly resample
# --------------------------------------------------------------------------- #
def test_to_monthly_returns_counts_and_values():
    # 6 months of daily data, each month a flat level stepping +1% month to month
    idx = pd.bdate_range(date(2020, 1, 1), date(2020, 6, 30))
    level = pd.Series(100.0, index=idx, name="SPY")
    # bump each calendar month's level so month-end ratios are known
    for i, m in enumerate(range(1, 7)):
        level[level.index.month == m] = 100.0 * (1.01**i)
    rets = to_monthly_returns(level)
    # months 2..6 each ~ +1% vs prior month-end
    assert len(rets) == 5
    assert all(abs(r - 0.01) < 1e-6 for r in rets)


# --------------------------------------------------------------------------- #
# season split
# --------------------------------------------------------------------------- #
def _monthly_series(start_year: int, n_months: int, *, winter_r: float, summer_r: float) -> pd.Series:
    idx = pd.date_range(date(start_year, 1, 31), periods=n_months, freq="ME")
    vals = [winter_r if is_winter(ts.month) else summer_r for ts in idx]
    return pd.Series(vals, index=idx, name="monthly_return")


def test_split_routes_months_correctly():
    s = _monthly_series(2000, 24, winter_r=0.02, summer_r=-0.01)
    sp = split_by_season(s)
    assert sp.n_winter == 12 and sp.n_summer == 12
    assert all(abs(w - 0.02) < 1e-12 for w in sp.winter)
    assert all(abs(x + 0.01) < 1e-12 for x in sp.summer)


def test_split_drops_glitch_month():
    s = _monthly_series(2000, 12, winter_r=0.02, summer_r=-0.01)
    s.iloc[0] = 5.0  # January (winter) glitch
    sp = split_by_season(s)
    assert sp.n_winter == 5  # one winter month dropped


# --------------------------------------------------------------------------- #
# strategy vs buy-and-hold return streams
# --------------------------------------------------------------------------- #
def test_seasonal_holds_equity_in_winter_cash_in_summer():
    s = _monthly_series(2000, 12, winter_r=0.02, summer_r=0.03)
    strat = seasonal_strategy_returns(s, rf_monthly=0.0, round_trip_cost=0.0)
    bh = buy_and_hold_returns(s)
    assert len(strat) == 12 and len(bh) == 12
    for ts, sr in zip(s.index, strat, strict=True):
        if is_winter(ts.month):
            assert abs(sr - 0.02) < 1e-12  # equity return in winter
        else:
            assert abs(sr - 0.0) < 1e-12  # cash (0%) in summer


def test_round_trip_cost_charged_once_in_november():
    s = _monthly_series(2000, 12, winter_r=0.02, summer_r=0.03)
    strat = seasonal_strategy_returns(s, rf_monthly=0.0, round_trip_cost=ROUND_TRIP_COST)
    nov = [sr for ts, sr in zip(s.index, strat, strict=True) if ts.month == 11]
    other_winter = [
        sr for ts, sr in zip(s.index, strat, strict=True)
        if is_winter(ts.month) and ts.month != 11
    ]
    assert all(abs(sr - (0.02 - ROUND_TRIP_COST)) < 1e-12 for sr in nov)
    assert all(abs(sr - 0.02) < 1e-12 for sr in other_winter)


def test_cash_uses_rf_rate_in_summer():
    s = _monthly_series(2000, 12, winter_r=0.02, summer_r=0.03)
    strat = seasonal_strategy_returns(s, rf_monthly=0.001, round_trip_cost=0.0)
    summer = [sr for ts, sr in zip(s.index, strat, strict=True) if not is_winter(ts.month)]
    assert all(abs(sr - 0.001) < 1e-12 for sr in summer)


def test_summarize_strategy_fields():
    st = summarize_strategy([0.01, -0.005, 0.02, 0.0], label="x", time_in_market=0.5)
    assert st.label == "x"
    assert st.n == 4
    assert st.time_in_market == 0.5
    assert st.ann_return == st.ann_return  # not NaN
    assert st.sharpe == st.sharpe


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #
def _split(nw: int, ns: int, *, wr: float, sr: float) -> SeasonSplit:
    return SeasonSplit(winter=[wr] * nw, summer=[sr] * ns)


def _stats(label: str, sharpe: float) -> StrategyStats:
    return StrategyStats(label=label, n=100, ann_return=0.1, ann_vol=0.1, sharpe=sharpe, time_in_market=0.5)


def test_gate_passes_when_seasonal_beats_bh_sharpe_and_oos_stable():
    full = _split(120, 120, wr=0.015, sr=0.002)
    is_sp = _split(60, 60, wr=0.015, sr=0.002)
    oos_sp = _split(60, 60, wr=0.014, sr=0.003)
    v = evaluate_gate(
        full,
        _stats("seasonal", 0.9),
        _stats("bh", 0.6),
        diff_t_full=3.0,
        split_is=is_sp,
        split_oos=oos_sp,
        seasonal_sharpe_is=0.9,
        bh_sharpe_is=0.6,
        seasonal_sharpe_oos=0.8,
        bh_sharpe_oos=0.5,
    )
    assert v.passed is True


def test_gate_kills_when_seasonal_sharpe_not_above_bh():
    # the decisive failure mode: seasonal merely matches/trails B&H Sharpe
    full = _split(120, 120, wr=0.015, sr=0.002)
    sp = _split(60, 60, wr=0.015, sr=0.002)
    v = evaluate_gate(
        full,
        _stats("seasonal", 0.55),
        _stats("bh", 0.60),  # B&H higher -> exposure, not alpha
        diff_t_full=3.0,
        split_is=sp,
        split_oos=sp,
        seasonal_sharpe_is=0.55,
        bh_sharpe_is=0.60,
        seasonal_sharpe_oos=0.55,
        bh_sharpe_oos=0.60,
    )
    assert v.passed is False
    assert any("risk-adjusted" in r and "FAIL" in r for r in v.reasons)


def test_gate_kills_on_weak_seasonal_tstat():
    full = _split(120, 120, wr=0.006, sr=0.005)
    sp = _split(60, 60, wr=0.006, sr=0.005)
    v = evaluate_gate(
        full,
        _stats("seasonal", 0.9),
        _stats("bh", 0.6),
        diff_t_full=0.7,  # in-noise seasonal split
        split_is=sp,
        split_oos=sp,
        seasonal_sharpe_is=0.9,
        bh_sharpe_is=0.6,
        seasonal_sharpe_oos=0.9,
        bh_sharpe_oos=0.6,
    )
    assert v.passed is False
    assert any("seasonal split" in r and "FAIL" in r for r in v.reasons)


def test_gate_kills_on_oos_sign_flip():
    full = _split(120, 120, wr=0.015, sr=0.002)
    is_sp = _split(60, 60, wr=0.015, sr=0.002)  # winter > summer
    oos_sp = _split(60, 60, wr=0.001, sr=0.004)  # winter < summer -> flip
    v = evaluate_gate(
        full,
        _stats("seasonal", 0.9),
        _stats("bh", 0.6),
        diff_t_full=3.0,
        split_is=is_sp,
        split_oos=oos_sp,
        seasonal_sharpe_is=0.9,
        bh_sharpe_is=0.6,
        seasonal_sharpe_oos=0.9,
        bh_sharpe_oos=0.6,
    )
    assert v.passed is False
    assert any("OOS stability" in r and "FAIL" in r for r in v.reasons)


def test_gate_kills_when_sharpe_verdict_flips_across_halves():
    full = _split(120, 120, wr=0.015, sr=0.002)
    sp = _split(60, 60, wr=0.015, sr=0.002)
    v = evaluate_gate(
        full,
        _stats("seasonal", 0.9),
        _stats("bh", 0.6),
        diff_t_full=3.0,
        split_is=sp,
        split_oos=sp,
        seasonal_sharpe_is=0.9,
        bh_sharpe_is=0.6,  # IS: seasonal wins
        seasonal_sharpe_oos=0.4,
        bh_sharpe_oos=0.6,  # OOS: B&H wins -> verdict flips
    )
    assert v.passed is False
    assert any("OOS stability" in r and "FAIL" in r for r in v.reasons)


def test_seasonal_effect_recovered_from_synthetic_series():
    # inject winter > summer; confirm split means and Welch t recover it
    rng = np.random.default_rng(7)
    idx = pd.date_range(date(1990, 1, 31), periods=360, freq="ME")
    vals = [
        (0.015 if is_winter(ts.month) else 0.000) + float(rng.normal(0, 0.01))
        for ts in idx
    ]
    s = pd.Series(vals, index=idx, name="monthly_return")
    sp = split_by_season(s)
    assert mean(sp.winter) > mean(sp.summer)
    assert welch_t(sp.winter, sp.summer) > 5  # strong injected effect
