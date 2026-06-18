"""Network-free unit tests for the T43 earnings-announcement premium core.

Every test runs on synthetic in-memory series; no yfinance, no I/O. We inject a
known announcement effect and confirm the core recovers it, that the BMO/AMC t0
convention is correct, that the placebo machinery excludes earnings windows, and
that the pre-registered gate fires on each kill criterion.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd
import pytest

from trader.catalysts.earnings_premium import (
    EVENT_WINDOWS,
    PRIMARY_WINDOW,
    ROUND_TRIP_COST,
    abnormal_returns,
    aggregate,
    compute_event,
    evaluate_gate,
    is_amc,
    jump_risk_correlation,
    non_earnings_car,
    premium_vs_baseline,
    resolve_t0_index,
    sample_non_earnings_cars,
    t_stat_one_sample,
    welch_t,
)


# --------------------------------------------------------------------------- #
# fixtures / builders
# --------------------------------------------------------------------------- #
def _trading_index(start: date, n: int) -> pd.DatetimeIndex:
    """A weekday-only trading-day index of length ``n``."""

    days: list[pd.Timestamp] = []
    cur = pd.Timestamp(start)
    while len(days) < n:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return pd.DatetimeIndex(days)


def _flat_prices(index: pd.DatetimeIndex, level: float = 100.0) -> pd.Series:
    return pd.Series([level] * len(index), index=index)


# --------------------------------------------------------------------------- #
# stats primitives
# --------------------------------------------------------------------------- #
def test_t_stat_zero_mean_series_is_near_zero():
    vals = [0.01, -0.01, 0.02, -0.02, 0.005, -0.005]
    assert abs(t_stat_one_sample(vals)) < 0.5


def test_t_stat_positive_series_is_large():
    vals = [0.02] * 10 + [0.018, 0.022]  # tightly positive
    assert t_stat_one_sample(vals) > 5.0


def test_welch_t_directional():
    a = [0.03, 0.031, 0.029, 0.030]
    b = [0.001, 0.0, -0.001, 0.0005]
    assert welch_t(a, b) > 2.0
    assert welch_t(b, a) < -2.0


# --------------------------------------------------------------------------- #
# BMO / AMC convention
# --------------------------------------------------------------------------- #
def test_is_amc_classification():
    assert is_amc(16) is True  # 4pm ET -> AMC
    assert is_amc(8) is False  # 8am ET -> BMO
    assert is_amc(None) is True  # missing -> conservative AMC


def test_resolve_t0_bmo_vs_amc_differ_by_one_session():
    idx = _trading_index(date(2020, 1, 6), 10)  # Mon Jan 6 ...
    ann = idx[3].date()  # an announcement ON a trading day
    bmo = resolve_t0_index(idx, ann, amc=False)
    amc = resolve_t0_index(idx, ann, amc=True)
    assert bmo == 3  # BMO prices same session
    assert amc == 4  # AMC prices next session


def test_resolve_t0_off_calendar_announcement():
    idx = _trading_index(date(2020, 1, 6), 10)
    # Saturday between idx[4] (Fri) and idx[5] (Mon)
    sat = idx[4].date() + timedelta(days=1)
    assert idx[4].weekday() == 4
    # Both BMO and AMC for a weekend announcement resolve to the next session.
    assert resolve_t0_index(idx, sat, amc=False) == 5
    assert resolve_t0_index(idx, sat, amc=True) == 5


def test_resolve_t0_out_of_range_returns_none():
    idx = _trading_index(date(2020, 1, 6), 5)
    assert resolve_t0_index(idx, date(2025, 1, 1), amc=True) is None


# --------------------------------------------------------------------------- #
# abnormal returns + event CAR recovery
# --------------------------------------------------------------------------- #
def test_abnormal_returns_remove_market():
    idx = _trading_index(date(2020, 1, 6), 30)
    # Stock and bench both rise 1%/day -> abnormal return ~ 0.
    growth = pd.Series([100.0 * (1.01**i) for i in range(len(idx))], index=idx)
    abn = abnormal_returns(growth, growth)
    assert abn.dropna().abs().max() < 1e-9


def test_compute_event_recovers_injected_premium():
    idx = _trading_index(date(2020, 1, 6), 60)
    bench = _flat_prices(idx)  # market does nothing
    close = _flat_prices(idx).copy()
    # Inject a +2% jump on the announcement day (BMO -> same session t0).
    ann_pos = 30
    # Build close path: flat, then +2% on ann day, flat after.
    levels = [100.0] * len(idx)
    for i in range(ann_pos, len(idx)):
        levels[i] = 102.0
    close = pd.Series(levels, index=idx)
    abn = abnormal_returns(close, bench)
    ev = compute_event(abn, idx[ann_pos].date(), "TST", amc=False)
    assert ev is not None
    # CAR over [-1,+1] should capture the +2% day-0 jump.
    assert ev.cars[PRIMARY_WINDOW] == pytest.approx(0.02, abs=1e-6)
    assert ev.cars["car_0_p0"] == pytest.approx(0.02, abs=1e-6)
    assert ev.t0_date == idx[ann_pos].date()


def test_compute_event_amc_shifts_window():
    idx = _trading_index(date(2020, 1, 6), 60)
    bench = _flat_prices(idx)
    ann_pos = 30  # announcement date sits on session 30 (AMC -> t0 = 31)
    # +2% reaction lands on session 31 (the next session).
    levels = [100.0] * len(idx)
    for i in range(ann_pos + 1, len(idx)):
        levels[i] = 102.0
    close = pd.Series(levels, index=idx)
    abn = abnormal_returns(close, bench)
    ev = compute_event(abn, idx[ann_pos].date(), "TST", amc=True)
    assert ev is not None
    assert ev.t0_date == idx[ann_pos + 1].date()
    assert ev.cars[PRIMARY_WINDOW] == pytest.approx(0.02, abs=1e-6)


def test_compute_event_drops_glitch():
    idx = _trading_index(date(2020, 1, 6), 60)
    bench = _flat_prices(idx)
    levels = [100.0] * len(idx)
    levels[31] = 1000.0  # +900% glitch inside the window
    close = pd.Series(levels, index=idx)
    abn = abnormal_returns(close, bench)
    assert compute_event(abn, idx[30].date(), "TST", amc=False) is None


def test_compute_event_incomplete_window_returns_none():
    idx = _trading_index(date(2020, 1, 6), 10)
    bench = _flat_prices(idx)
    close = _flat_prices(idx)
    abn = abnormal_returns(close, bench)
    # Announcement on the very last session -> +1 leg missing.
    assert compute_event(abn, idx[-1].date(), "TST", amc=False) is None


# --------------------------------------------------------------------------- #
# placebo / non-earnings sampling
# --------------------------------------------------------------------------- #
def test_non_earnings_car_sums_window():
    idx = _trading_index(date(2020, 1, 6), 20)
    # abn series with known values: 0.01 everywhere.
    abn = pd.Series([0.01] * len(idx), index=idx)
    car = non_earnings_car(abn, 10, EVENT_WINDOWS[PRIMARY_WINDOW])
    assert car == pytest.approx(0.03)  # 3 days * 0.01


def test_sample_non_earnings_excludes_earnings_windows():
    idx = _trading_index(date(2020, 1, 6), 80)
    abn = pd.Series([0.0] * len(idx), index=idx)
    earnings_positions = [20, 50]
    rng = random.Random(7)
    # Tag earnings-zone abn with a sentinel so we can detect leakage.
    for pos in earnings_positions:
        for d in range(pos - 5, pos + 6):
            abn.iloc[d] = 99.0  # huge -> would be a glitch / detectable
    samples = sample_non_earnings_cars(
        abn, earnings_positions, n_samples=20, rng=rng
    )
    # None of the sampled placebo CARs should touch the sentinel zone, so all ~0.
    assert len(samples) >= 10
    assert all(abs(s) < 1e-9 for s in samples)


def test_placebo_mean_is_near_zero_on_noise():
    idx = _trading_index(date(2018, 1, 1), 400)
    rng = random.Random(11)
    # Pure mean-zero noise abnormal returns.
    noise = [rng.gauss(0.0, 0.01) for _ in range(len(idx))]
    abn = pd.Series(noise, index=idx)
    samples = sample_non_earnings_cars(abn, [100, 200, 300], n_samples=100, rng=rng)
    stats = aggregate(samples, label="placebo")
    assert abs(stats.gross_mean) < 0.005
    assert abs(stats.t_stat) < 2.5  # in-noise


# --------------------------------------------------------------------------- #
# aggregation + cost + premium-vs-baseline
# --------------------------------------------------------------------------- #
def test_aggregate_after_cost_subtracts_round_trip():
    cars = [0.02, 0.02, 0.02, 0.02]
    stats = aggregate(cars, label="evt")
    assert stats.gross_mean == pytest.approx(0.02)
    assert stats.after_cost_mean == pytest.approx(0.02 - ROUND_TRIP_COST)
    assert stats.win_rate == pytest.approx(1.0)


def test_premium_vs_baseline_nets_out_drift():
    # Events average ~+1.5%, baseline (same-stock drift) averages ~+0.5% ->
    # the true premium is ~+1.0%. Use realistic dispersion so Welch t is defined.
    rng = random.Random(5)
    events = [0.015 + rng.gauss(0.0, 0.002) for _ in range(50)]
    baseline = [0.005 + rng.gauss(0.0, 0.002) for _ in range(200)]
    premium, t = premium_vs_baseline(events, baseline)
    assert premium == pytest.approx(0.01, abs=2e-3)
    assert t > 2.0


# --------------------------------------------------------------------------- #
# jump-risk vs alpha interpretation
# --------------------------------------------------------------------------- #
def test_jump_risk_correlation_high_when_premium_tracks_vol():
    idx = _trading_index(date(2020, 1, 6), 60)
    bench = _flat_prices(idx)
    rng = random.Random(3)
    events = []
    for k in range(40):
        # Each event: a single day-0 jump of size j; window_vol scales with |j|.
        j = rng.uniform(-0.05, 0.05)
        ann_pos = 30
        levels = [100.0] * len(idx)
        for i in range(ann_pos, len(idx)):
            levels[i] = 100.0 * (1.0 + j)
        close = pd.Series(levels, index=idx)
        abn = abnormal_returns(close, bench)
        ev = compute_event(abn, idx[ann_pos].date(), f"T{k}", amc=False)
        assert ev is not None
        events.append(ev)
    corr = jump_risk_correlation(events)
    # |CAR| and window vol are mechanically linked here -> strong positive corr.
    assert corr > 0.8


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #
def _gate(**overrides):
    base = dict(
        n_events=500,
        after_cost_mean=0.004,
        after_cost_t=3.0,
        is_mean=0.004,
        is_n=200,
        oos_mean=0.004,
        oos_n=300,
        placebo_mean=0.0001,
        placebo_t=0.3,
        premium_vs_base=0.003,
    )
    base.update(overrides)
    return evaluate_gate(**base)


def test_gate_passes_on_clean_positive_case():
    assert _gate().passed is True


def test_gate_fails_small_n():
    v = _gate(n_events=12)
    assert v.passed is False
    assert any("N=12" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_weak_t():
    assert _gate(after_cost_t=1.1).passed is False


def test_gate_fails_negative_after_cost():
    assert _gate(after_cost_mean=-0.001, after_cost_t=-3.0).passed is False


def test_gate_fails_oos_sign_flip():
    v = _gate(is_mean=0.005, oos_mean=-0.003)
    assert v.passed is False
    assert any("OOS sign stability" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_when_placebo_not_null():
    v = _gate(placebo_mean=0.004, placebo_t=3.5)
    assert v.passed is False
    assert any("placebo" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_when_premium_does_not_survive_baseline():
    v = _gate(premium_vs_base=-0.001)
    assert v.passed is False
    assert any("baseline" in r and "FAIL" in r for r in v.reasons)
