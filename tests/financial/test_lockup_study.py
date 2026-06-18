"""Unit tests for the lock-up event-study engine on synthetic series."""

from __future__ import annotations

import pandas as pd
import pytest

from trader.catalysts.lockup_study import (
    StudyResult,
    WindowAgg,
    aggregate,
    compute_event_metrics,
    evaluate_gate,
)


def _bdays(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2022-01-03", periods=n)


def _make_stock(idx: pd.DatetimeIndex, t0: int) -> tuple[pd.Series, pd.Series]:
    """Stock flat except a clean -2%/day drop on event days t0+1..t0+5, with tiny
    deterministic baseline noise in [-40,-20] so the pre-window std is non-zero."""
    rets = [0.0] * len(idx)
    for i in range(t0 - 40, t0 - 19):       # baseline window: alternating +/-0.1%
        rets[i] = 0.001 if i % 2 == 0 else -0.001
    for i in range(t0 + 1, t0 + 6):         # post drop
        rets[i] = -0.02
    close = [100.0]
    for r in rets[1:]:
        close.append(close[-1] * (1 + r))
    close_s = pd.Series(close, index=idx, name="TEST")
    vol_s = pd.Series([1_000_000] * len(idx), index=idx, name="TEST")
    return close_s, vol_s


def test_compute_event_metrics_recovers_known_car_and_vol():
    idx = _bdays(120)
    t0 = 60
    close, volume = _make_stock(idx, t0)
    spy = pd.Series([100.0] * len(idx), index=idx, name="SPY")  # flat → AR == stock ret
    event_date = idx[t0].date()

    m = compute_event_metrics(close, volume, spy, event_date)
    assert m is not None
    assert m.t0_date == event_date
    assert m.car_0_p5 == pytest.approx(-0.10)     # 0 + 5*(-0.02)
    assert m.car_0_p21 == pytest.approx(-0.10)    # no other moves after
    assert m.car_m5_m1 == pytest.approx(0.0)      # quiet pre-window
    assert m.car_m1_p1 == pytest.approx(-0.02)    # only t0+1 moves
    assert m.vol_ratio > 1.25                     # post far noisier than baseline
    assert m.median_dollar_volume == pytest.approx(100.0 * 1_000_000, rel=0.05)


def test_offset_shifts_event_window_for_placebo():
    idx = _bdays(220)
    t0 = 140  # large enough that the placebo window (t0-90) still has 40 days before it
    close, volume = _make_stock(idx, t0)
    spy = pd.Series([100.0] * len(idx), index=idx, name="SPY")
    event_date = idx[t0].date()

    real = compute_event_metrics(close, volume, spy, event_date)
    placebo = compute_event_metrics(close, volume, spy, event_date, offset_trading_days=-90)
    assert real is not None and placebo is not None
    assert real.car_0_p5 == pytest.approx(-0.10)
    assert placebo.car_0_p5 == pytest.approx(0.0)   # placebo window is quiet
    assert placebo.t0_date == idx[t0 - 90].date()


def test_compute_event_metrics_returns_none_when_window_incomplete():
    idx = _bdays(50)
    close, volume = _make_stock(idx, 30)
    spy = pd.Series([100.0] * len(idx), index=idx, name="SPY")
    assert compute_event_metrics(close, volume, spy, idx[45].date()) is None


def test_aggregate_computes_mean_and_pct_negative():
    idx = _bdays(120)
    spy = pd.Series([100.0] * len(idx), index=idx, name="SPY")
    metrics = []
    for t0 in (55, 60, 65, 70):
        close, volume = _make_stock(idx, t0)
        m = compute_event_metrics(close, volume, spy, idx[t0].date())
        assert m is not None
        metrics.append(m)

    res = aggregate(metrics, label="real")
    car = res.windows["car_0_p21"]
    assert res.n_events == 4
    assert car.mean == pytest.approx(-0.10)
    assert car.pct_negative == pytest.approx(1.0)
    assert car.t_stat < 0   # all events strongly negative → significantly negative t


def _study(primary_mean: float, primary_t: float, vol_mean: float, vol_t: float, n: int) -> StudyResult:
    car = WindowAgg("car_0_p21", n, primary_mean, primary_mean, 1.0 if primary_mean < 0 else 0.0, primary_t)
    vol = WindowAgg("vol_ratio", n, vol_mean, vol_mean, 0.0, vol_t)
    return StudyResult(label="x", n_events=n, windows={"car_0_p21": car}, vol_ratio=vol)


def test_gate_passes_when_all_criteria_met():
    real = _study(-0.03, -3.0, 1.1, 1.0, 50)
    placebo = _study(-0.004, -0.4, 1.0, 0.0, 50)
    oos_early = _study(-0.02, -2.1, 1.1, 1.0, 25)
    oos_late = _study(-0.035, -2.5, 1.1, 1.0, 25)
    verdict = evaluate_gate(real, placebo, oos_early, oos_late)
    assert verdict.passed, verdict.reasons


def test_gate_fails_on_placebo_and_oos():
    real = _study(-0.03, -3.0, 1.0, 0.0, 50)
    placebo = _study(-0.05, -4.0, 1.0, 0.0, 50)       # placebo MORE negative
    oos_early = _study(-0.02, -2.1, 1.0, 0.0, 25)
    oos_late = _study(+0.01, +1.0, 1.0, 0.0, 25)       # sign flips OOS
    verdict = evaluate_gate(real, placebo, oos_early, oos_late)
    assert not verdict.passed
    assert any("beats placebo" in r and "FAIL" in r for r in verdict.reasons)
    assert any("OOS sign stable" in r and "FAIL" in r for r in verdict.reasons)


def test_gate_fails_on_insufficient_n():
    real = _study(-0.03, -3.0, 1.0, 0.0, 12)
    placebo = _study(-0.004, -0.4, 1.0, 0.0, 12)
    oos_early = _study(-0.02, -2.1, 1.0, 0.0, 6)
    oos_late = _study(-0.03, -2.5, 1.0, 0.0, 6)
    verdict = evaluate_gate(real, placebo, oos_early, oos_late)
    assert not verdict.passed
    assert any("N=12" in r and "FAIL" in r for r in verdict.reasons)
