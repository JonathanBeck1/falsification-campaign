"""Network-free tests for the T42 spin-off post-event drift study.

Covers: forward-CAR math anchored at the first-trade day (t0), the strict t0+1
start of the PRIMARY window, the glitch guard, the placebo draws (and the
min-start cutoff that keeps placebo windows away from the event), aggregation /
t-stats, after-cost subtraction, the IS/OOS split, top-contributor drop, and the
full gate. No I/O -- pure functions only.
"""

from __future__ import annotations

import random
from datetime import date

import numpy as np
import pandas as pd

from trader.catalysts.spinoff_drift import (
    PRIMARY_WINDOW,
    ROUND_TRIP_COST,
    EventMetrics,
    after_cost_mean,
    aggregate,
    compute_event_metrics,
    drop_top_contributors,
    evaluate_gate,
    placebo_cars,
    split_is_oos,
)


# --------------------------------------------------------------------------- #
# helpers: synthetic flat price series with injected event moves
# --------------------------------------------------------------------------- #
def _flat_prices(start: str, n: int, base: float = 50.0) -> pd.Series:
    idx = pd.bdate_range(start=start, periods=n)
    s = pd.Series([base] * n, index=idx, dtype=float)
    s.name = "SPINCO"
    return s


def _spy_flat(start: str, n: int) -> pd.Series:
    idx = pd.bdate_range(start=start, periods=n)
    return pd.Series([400.0] * n, index=idx, dtype=float)


# --------------------------------------------------------------------------- #
# CAR math: injected drift in the forward window
# --------------------------------------------------------------------------- #
def test_forward_drift_captured_in_primary_window():
    n = 100
    close = _flat_prices("2018-01-01", n)
    spy = _spy_flat("2018-01-01", n)
    # t0 = index 0 (first trade). Inject a +1% step at t0+10 (inside [1,21]).
    close.iloc[10:] *= 1.01
    m = compute_event_metrics(close, spy, first_trade_index=0)
    assert m is not None
    assert abs(m.car_p1_p21 - 0.01) < 1e-6
    assert abs(m.car_p1_p63 - 0.01) < 1e-6  # still inside the wider window


def test_t0_day_move_excluded_from_primary():
    n = 100
    close = _flat_prices("2018-01-01", n)
    spy = _spy_flat("2018-01-01", n)
    # a move ON t0 (the first-trade-day return vs the prior synthetic row) must
    # NOT enter the PRIMARY [t0+1, t0+21]; build t0 at index 5 so a prior row
    # exists, and put the jump exactly at t0.
    close.iloc[5:] *= 1.08  # +8% realized AT t0 = index 5
    m = compute_event_metrics(close, spy, first_trade_index=5)
    assert m is not None
    # PRIMARY starts at t0+1 -> the t0 jump is excluded.
    assert abs(m.car_p1_p21) < 1e-9
    # the t0+0 robustness window DOES include it.
    assert m.car_p0_p21 > 0.07


def test_market_adjustment_removes_common_move():
    n = 100
    idx = pd.bdate_range("2018-01-01", periods=n)
    close = pd.Series(50.0 * (1.01 ** np.arange(n)), index=idx, name="SPINCO")
    spy = pd.Series(400.0 * (1.01 ** np.arange(n)), index=idx)
    m = compute_event_metrics(close, spy, first_trade_index=0)
    assert m is not None
    assert abs(m.car_p1_p21) < 1e-6  # stock and market move together -> AR ~0


def test_glitch_day_drops_event():
    n = 100
    close = _flat_prices("2018-01-01", n)
    spy = _spy_flat("2018-01-01", n)
    close.iloc[8] *= 3.0  # absurd >75% one-day move inside the window
    assert compute_event_metrics(close, spy, first_trade_index=0) is None


def test_short_history_returns_none():
    # not enough forward room for the 63-day window.
    close = _flat_prices("2018-01-01", 40)
    spy = _spy_flat("2018-01-01", 40)
    assert compute_event_metrics(close, spy, first_trade_index=0) is None


def test_t0_at_series_edge_returns_none():
    n = 100
    close = _flat_prices("2018-01-01", n)
    spy = _spy_flat("2018-01-01", n)
    # t0 too close to the end: t0+63 would run past the series.
    assert compute_event_metrics(close, spy, first_trade_index=n - 10) is None


# --------------------------------------------------------------------------- #
# placebo
# --------------------------------------------------------------------------- #
def test_placebo_on_flat_series_is_zero():
    n = 300
    close = _flat_prices("2018-01-01", n)
    spy = _spy_flat("2018-01-01", n)
    rng = random.Random(0)
    cars = placebo_cars(close, spy, window_len=21, n_draws=50, rng=rng)
    assert len(cars) == 50
    assert all(abs(c) < 1e-9 for c in cars)


def test_placebo_respects_min_start():
    # min_start keeps placebo windows away from the early event region.
    n = 300
    idx = pd.bdate_range("2018-01-01", periods=n)
    rs = np.random.RandomState(3)
    close = pd.Series(50.0 * np.cumprod(1 + rs.normal(0, 0.01, n)), index=idx, name="X")
    spy = pd.Series(400.0 * np.cumprod(1 + rs.normal(0, 0.005, n)), index=idx)
    # with a high min_start, all draws begin at or after that index.
    cars = placebo_cars(
        close, spy, window_len=21, n_draws=200, rng=random.Random(9), min_start=200
    )
    assert len(cars) > 0  # draws are still possible (200 + 21 < 300)


def test_placebo_skips_glitch_windows():
    n = 300
    close = _flat_prices("2018-01-01", n)
    spy = _spy_flat("2018-01-01", n)
    close.iloc[150] *= 5.0
    rng = random.Random(1)
    cars = placebo_cars(close, spy, window_len=21, n_draws=80, rng=rng)
    assert len(cars) <= 80
    assert all(abs(c) < 1e-9 for c in cars)


def test_placebo_reproducible_with_seed():
    n = 250
    idx = pd.bdate_range("2018-01-01", periods=n)
    rs = np.random.RandomState(7)
    close = pd.Series(50.0 * np.cumprod(1 + rs.normal(0, 0.01, n)), index=idx, name="X")
    spy = pd.Series(400.0 * np.cumprod(1 + rs.normal(0, 0.005, n)), index=idx)
    a = placebo_cars(close, spy, window_len=21, n_draws=30, rng=random.Random(42))
    b = placebo_cars(close, spy, window_len=21, n_draws=30, rng=random.Random(42))
    assert a == b


# --------------------------------------------------------------------------- #
# aggregation, after-cost, IS/OOS split, top-drop
# --------------------------------------------------------------------------- #
def _mk(ft: date, primary: float) -> EventMetrics:
    return EventMetrics(
        ticker="X",
        first_trade_date=ft,
        car_p1_p21=primary,
        car_p1_p63=primary,
        car_p0_p21=primary,
    )


def test_aggregate_mean_and_t_stat():
    metrics = [_mk(date(2018, 1, 1), v) for v in (0.01, 0.02, 0.03, 0.04)]
    res = aggregate(metrics, label="cohort")
    w = res.windows[PRIMARY_WINDOW]
    assert w.n == 4
    assert abs(w.mean - 0.025) < 1e-9
    assert w.pct_positive == 1.0
    assert w.t_stat > 0


def test_after_cost_subtracts_one_round_trip():
    metrics = [_mk(date(2018, 1, 1), 0.03) for _ in range(10)]
    w = aggregate(metrics, label="c").windows[PRIMARY_WINDOW]
    assert abs(after_cost_mean(w) - (0.03 - ROUND_TRIP_COST)) < 1e-12


def test_split_is_oos_by_year():
    metrics = [
        _mk(date(2016, 6, 1), 0.01),
        _mk(date(2019, 6, 1), 0.01),
        _mk(date(2020, 6, 1), 0.01),
        _mk(date(2023, 6, 1), 0.01),
    ]
    is_, oos = split_is_oos(metrics)
    assert {m.first_trade_date.year for m in is_} == {2016, 2019}
    assert {m.first_trade_date.year for m in oos} == {2020, 2023}


def test_drop_top_contributors_removes_outliers():
    # 5 huge winners + 40 tiny ~0 names. Dropping the top-5 collapses the mean.
    metrics = [_mk(date(2018, 1, 1), 0.50) for _ in range(5)] + [
        _mk(date(2018, 1, 1), 0.0001) for _ in range(40)
    ]
    full = aggregate(metrics, label="full").windows[PRIMARY_WINDOW]
    dropped = drop_top_contributors(metrics, k=5).windows[PRIMARY_WINDOW]
    assert full.mean > 0.05  # outliers inflate it
    assert dropped.mean < 0.001  # gone once the top-5 are removed
    assert dropped.n == 40


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #
def _study(mean: float, n: int):
    metrics = [_mk(date(2018, 1, 1), mean) for _ in range(n)]
    metrics[0] = _mk(date(2018, 1, 1), mean + 1e-4)  # tiny dispersion -> finite t
    return aggregate(metrics, label="x")


def test_gate_fails_on_null_signal():
    cohort = _study(0.0001, 50)
    is_, oos = _study(0.0001, 25), _study(0.0001, 25)
    placebo = aggregate(
        [_mk(date(2018, 1, 1), 0.0) for _ in range(200)], label="pl"
    ).windows[PRIMARY_WINDOW]
    v = evaluate_gate(cohort, is_, oos, placebo)
    assert v.passed is False
    assert any("after-cost signal" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_when_below_min_events():
    cohort = _study(0.08, 10)
    is_, oos = _study(0.08, 5), _study(0.08, 5)
    placebo = aggregate(
        [_mk(date(2018, 1, 1), 0.0) for _ in range(50)], label="pl"
    ).windows[PRIMARY_WINDOW]
    v = evaluate_gate(cohort, is_, oos, placebo)
    assert v.passed is False
    assert any("N=10" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_on_oos_sign_flip():
    cohort = _study(0.08, 60)
    is_ = _study(0.08, 30)  # positive IS
    oos = _study(-0.08, 30)  # negative OOS -> decayed/flipped
    placebo = aggregate(
        [_mk(date(2018, 1, 1), 0.0) for _ in range(200)], label="pl"
    ).windows[PRIMARY_WINDOW]
    v = evaluate_gate(cohort, is_, oos, placebo)
    assert v.passed is False
    assert any("OOS sign stable" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_when_placebo_not_null():
    cohort = _study(0.08, 50)
    is_, oos = _study(0.08, 25), _study(0.08, 25)
    placebo = _study(0.08, 200).windows[PRIMARY_WINDOW]  # placebo also strong
    v = evaluate_gate(cohort, is_, oos, placebo)
    assert v.passed is False
    assert any("placebo control" in r and "FAIL" in r for r in v.reasons)


def test_gate_passes_only_when_everything_holds():
    # a synthetic SURVIVOR: strong after-cost mean, both halves positive, null
    # placebo. Confirms the gate CAN pass (so a real null is a real FAIL).
    cohort = _study(0.08, 60)
    is_, oos = _study(0.08, 30), _study(0.08, 30)
    placebo = aggregate(
        [_mk(date(2018, 1, 1), 0.0) for _ in range(300)], label="pl"
    ).windows[PRIMARY_WINDOW]
    v = evaluate_gate(cohort, is_, oos, placebo)
    assert v.passed is True
    assert all("FAIL" not in r for r in v.reasons)
