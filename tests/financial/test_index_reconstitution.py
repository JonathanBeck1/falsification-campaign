"""Network-free tests for the T39 index-reconstitution (announce->effective) study.

Covers: the announce->effective CAR math on synthetic series with a known
injected jump inside the forced-flow window, the glitch guard, the placebo
draws, aggregation/t-stats, after-cost subtraction, the IS/OOS split, and the
full gate (including the placebo condition). No I/O — pure functions only.
"""

from __future__ import annotations

import random
from datetime import date

import numpy as np
import pandas as pd

from trader.catalysts.index_reconstitution import (
    ANNOUNCE_LEAD_TD,
    PRIMARY_WINDOW,
    ROUND_TRIP_COST,
    EventMetrics,
    after_cost_mean,
    aggregate,
    compute_event_metrics,
    evaluate_gate,
    placebo_cars,
    split_is_oos,
)


# --------------------------------------------------------------------------- #
# helpers: build synthetic flat price series with an injected event jump
# --------------------------------------------------------------------------- #
def _flat_prices(start: str, n: int, base: float = 100.0) -> pd.Series:
    idx = pd.bdate_range(start=start, periods=n)
    return pd.Series([base] * n, index=idx, dtype=float)


def _spy_flat(start: str, n: int) -> pd.Series:
    idx = pd.bdate_range(start=start, periods=n)
    return pd.Series([400.0] * n, index=idx, dtype=float)


# --------------------------------------------------------------------------- #
# CAR math: injected jump inside the announce->effective window
# --------------------------------------------------------------------------- #
def test_announce_eff_car_captures_injected_jump():
    n = 60
    close = _flat_prices("2015-01-01", n)
    spy = _spy_flat("2015-01-01", n)
    # effective day at index 30; announcement proxy at 30 - 5 = 25.
    eff_idx = 30
    eff_date = close.index[eff_idx].date()
    # inject a single +2% step on the announcement day (index 25) -> shows up in
    # the [-5,0] window but NOT in [0,+5].
    close.iloc[25:] *= 1.02
    m = compute_event_metrics(close, spy, eff_date, kind="add")
    assert m is not None
    # the +2% return lands exactly inside the announce->effective window.
    assert abs(m.car_announce_eff - 0.02) < 1e-6
    # and inside the pure run-up window [-5,-1] (announcement day is at -5).
    assert abs(m.car_announce_m1 - 0.02) < 1e-6
    # nothing happens after the effective day.
    assert abs(m.car_eff_p5) < 1e-9


def test_post_effective_jump_excluded_from_primary():
    n = 60
    close = _flat_prices("2015-01-01", n)
    spy = _spy_flat("2015-01-01", n)
    eff_idx = 30
    eff_date = close.index[eff_idx].date()
    # jump AFTER the effective day -> must NOT enter the announce->effective CAR.
    close.iloc[eff_idx + 1 :] *= 1.05
    m = compute_event_metrics(close, spy, eff_date, kind="add")
    assert m is not None
    assert abs(m.car_announce_eff) < 1e-9
    assert m.car_eff_p5 > 0.04  # the +5% shows up here instead


def test_market_adjustment_removes_common_move():
    n = 60
    idx = pd.bdate_range("2015-01-01", periods=n)
    # stock and SPY both rise 1%/day in the window -> abnormal return ~0.
    close = pd.Series(100.0 * (1.01 ** np.arange(n)), index=idx)
    spy = pd.Series(400.0 * (1.01 ** np.arange(n)), index=idx)
    eff_date = idx[30].date()
    m = compute_event_metrics(close, spy, eff_date, kind="add")
    assert m is not None
    assert abs(m.car_announce_eff) < 1e-6


def test_glitch_day_drops_event():
    n = 60
    close = _flat_prices("2015-01-01", n)
    spy = _spy_flat("2015-01-01", n)
    eff_date = close.index[30].date()
    # absurd >75% one-day move inside the window -> event dropped (returns None).
    close.iloc[27] *= 3.0
    assert compute_event_metrics(close, spy, eff_date, kind="add") is None


def test_thin_data_returns_none():
    close = _flat_prices("2015-01-01", 4)
    spy = _spy_flat("2015-01-01", 4)
    eff_date = close.index[-1].date()
    assert compute_event_metrics(close, spy, eff_date, kind="add") is None


def test_window_at_series_edge_returns_none():
    n = 60
    close = _flat_prices("2015-01-01", n)
    spy = _spy_flat("2015-01-01", n)
    # effective day too close to the start: t0 - lead would go negative.
    eff_date = close.index[2].date()
    assert compute_event_metrics(close, spy, eff_date, kind="add") is None


def test_announce_lead_constant_matches_window():
    assert PRIMARY_WINDOW == "car_announce_eff"
    assert ANNOUNCE_LEAD_TD == 5


# --------------------------------------------------------------------------- #
# placebo
# --------------------------------------------------------------------------- #
def test_placebo_on_flat_series_is_zero():
    n = 200
    close = _flat_prices("2015-01-01", n)
    spy = _spy_flat("2015-01-01", n)
    rng = random.Random(0)
    cars = placebo_cars(close, spy, n_draws=50, rng=rng)
    assert len(cars) == 50
    assert all(abs(c) < 1e-9 for c in cars)


def test_placebo_skips_glitch_windows():
    n = 200
    close = _flat_prices("2015-01-01", n)
    spy = _spy_flat("2015-01-01", n)
    close.iloc[100] *= 5.0  # one absurd day -> windows touching it are skipped
    rng = random.Random(1)
    cars = placebo_cars(close, spy, n_draws=80, rng=rng)
    # some draws skipped; the rest are clean zeros.
    assert len(cars) <= 80
    assert all(abs(c) < 1e-9 for c in cars)


def test_placebo_reproducible_with_seed():
    n = 150
    idx = pd.bdate_range("2015-01-01", periods=n)
    rs = np.random.RandomState(7)
    close = pd.Series(100.0 * np.cumprod(1 + rs.normal(0, 0.01, n)), index=idx)
    spy = pd.Series(400.0 * np.cumprod(1 + rs.normal(0, 0.005, n)), index=idx)
    a = placebo_cars(close, spy, n_draws=30, rng=random.Random(42))
    b = placebo_cars(close, spy, n_draws=30, rng=random.Random(42))
    assert a == b


# --------------------------------------------------------------------------- #
# aggregation, after-cost, IS/OOS split
# --------------------------------------------------------------------------- #
def _mk(eff: date, primary: float, kind: str = "add") -> EventMetrics:
    return EventMetrics(
        ticker="X",
        effective_date=eff,
        t0_date=eff,
        kind=kind,
        car_announce_eff=primary,
        car_announce_m1=primary,
        car_eff_p5=0.0,
    )


def test_aggregate_mean_and_t_stat():
    metrics = [_mk(date(2015, 1, 1), v) for v in (0.01, 0.02, 0.03, 0.04)]
    res = aggregate(metrics, label="adds")
    w = res.windows[PRIMARY_WINDOW]
    assert w.n == 4
    assert abs(w.mean - 0.025) < 1e-9
    assert w.pct_positive == 1.0
    assert w.t_stat > 0


def test_after_cost_subtracts_one_round_trip():
    metrics = [_mk(date(2015, 1, 1), 0.015) for _ in range(10)]
    w = aggregate(metrics, label="adds").windows[PRIMARY_WINDOW]
    assert abs(after_cost_mean(w) - (0.015 - ROUND_TRIP_COST)) < 1e-12


def test_split_is_oos_by_year():
    metrics = [
        _mk(date(2012, 6, 1), 0.01),
        _mk(date(2017, 6, 1), 0.01),
        _mk(date(2018, 6, 1), 0.01),
        _mk(date(2023, 6, 1), 0.01),
    ]
    is_, oos = split_is_oos(metrics)
    assert {m.effective_date.year for m in is_} == {2012, 2017}
    assert {m.effective_date.year for m in oos} == {2018, 2023}


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #
def _study(mean: float, n: int):
    # build a StudyResult whose primary window has a given mean & strong t-stat.
    metrics = [_mk(date(2015, 1, 1), mean) for _ in range(n)]
    # add tiny dispersion so the t-stat is finite and large for a real signal.
    metrics[0] = _mk(date(2015, 1, 1), mean + 1e-4)
    return aggregate(metrics, label="x")


def test_gate_fails_on_null_signal():
    # flat-ish ~0 adds, null placebo -> the predicted KILL.
    adds = _study(0.0001, 50)
    is_, oos = _study(0.0001, 25), _study(0.0001, 25)
    placebo = aggregate(
        [_mk(date(2015, 1, 1), 0.0) for _ in range(100)], label="pl"
    ).windows[PRIMARY_WINDOW]
    v = evaluate_gate(adds, is_, oos, placebo)
    assert v.passed is False
    assert any("after-cost signal" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_when_below_min_events():
    adds = _study(0.05, 10)  # big mean but N<30
    is_, oos = _study(0.05, 5), _study(0.05, 5)
    placebo = aggregate(
        [_mk(date(2015, 1, 1), 0.0) for _ in range(50)], label="pl"
    ).windows[PRIMARY_WINDOW]
    v = evaluate_gate(adds, is_, oos, placebo)
    assert v.passed is False
    assert any("N=10" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_when_placebo_not_null():
    # strong cohort AND strong placebo -> the edge is just name drift; KILL.
    adds = _study(0.05, 50)
    is_, oos = _study(0.05, 25), _study(0.05, 25)
    placebo = _study(0.05, 100).windows[PRIMARY_WINDOW]  # placebo also strong
    v = evaluate_gate(adds, is_, oos, placebo)
    assert v.passed is False
    assert any("placebo null" in r and "FAIL" in r for r in v.reasons)


def test_gate_passes_only_when_everything_holds():
    # a synthetic SURVIVOR: strong after-cost mean, both halves positive, null
    # placebo. Confirms the gate can pass (so a real null is a real FAIL).
    adds = _study(0.05, 60)
    is_, oos = _study(0.05, 30), _study(0.05, 30)
    placebo = aggregate(
        [_mk(date(2015, 1, 1), 0.0) for _ in range(200)], label="pl"
    ).windows[PRIMARY_WINDOW]
    v = evaluate_gate(adds, is_, oos, placebo)
    assert v.passed is True
    assert all("FAIL" not in r for r in v.reasons)
