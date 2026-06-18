"""Unit tests for the CEF activist-follow event-study engine."""

from __future__ import annotations

import pandas as pd
import pytest

from trader.catalysts.cef_study import (
    CefStudyResult,
    WindowStat,
    aggregate,
    compute_cef_event,
    evaluate_gate,
)


def _bdays(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2021-01-04", periods=n)


def _series(idx: pd.DatetimeIndex, t0: int):
    """Benchmark flat at 100; target flat until entry (t0+1), then ramps +10%
    over the next 126 trading days and holds — a clean known post-entry excess."""
    bench = pd.Series([100.0] * len(idx), index=idx, name="PCEF")
    entry, end = t0 + 1, t0 + 1 + 126
    tgt = []
    for i in range(len(idx)):
        if i <= entry:
            tgt.append(100.0)
        elif i <= end:
            tgt.append(100.0 + 10.0 * (i - entry) / 126)
        else:
            tgt.append(110.0)
    return pd.Series(tgt, index=idx, name="TGT"), bench


def test_compute_recovers_known_forward_excess():
    idx = _bdays(460)
    t0 = 200
    tgt, bench = _series(idx, t0)
    event_date = idx[t0].date()
    m = compute_cef_event(tgt, bench, event_date)
    assert m is not None
    assert m.t0_date == event_date
    assert m.exc_6m == pytest.approx(0.10, rel=1e-3)    # +10% over 126d from entry
    assert m.exc_12m == pytest.approx(0.10, rel=1e-3)   # holds after the ramp
    assert m.exc_1m == pytest.approx(0.10 * 21 / 126, rel=1e-2)
    assert m.exc_pre == pytest.approx(0.0, abs=1e-9)     # flat pre-disclosure
    assert m.exc_ann == pytest.approx(0.0, abs=1e-9)


def test_compute_returns_none_when_window_incomplete():
    idx = _bdays(200)
    tgt, bench = _series(idx, 100)
    assert compute_cef_event(tgt, bench, idx[180].date()) is None


def test_aggregate_means_and_pct_positive():
    idx = _bdays(460)
    metrics = []
    for t0 in (190, 200, 210, 220):
        tgt, bench = _series(idx, t0)
        m = compute_cef_event(tgt, bench, idx[t0].date())
        assert m is not None
        metrics.append(m)
    res = aggregate(metrics, label="real")
    assert res.n_events == 4
    assert res.stats["exc_6m"].mean == pytest.approx(0.10, rel=1e-3)
    assert res.stats["exc_6m"].pct_positive == pytest.approx(1.0)


def _result(cap_mean, cap_t, pre_mean, n) -> CefStudyResult:
    stats = {
        "exc_6m": WindowStat("exc_6m", n, cap_mean, cap_mean, 1.0 if cap_mean > 0 else 0.0, cap_t),
        "exc_pre": WindowStat("exc_pre", n, pre_mean, pre_mean, 0.0, 0.0),
    }
    return CefStudyResult(label="x", n_events=n, stats=stats)


def test_gate_passes_when_capturable_drift_is_real():
    real = _result(0.04, 3.0, 0.01, 60)
    early = _result(0.03, 2.1, 0.01, 30)
    late = _result(0.05, 2.4, 0.01, 30)
    v = evaluate_gate(real, early, late)
    assert v.passed, v.reasons


def test_gate_fails_when_effect_is_in_pre_runup():
    # significant 6m drift, but the pre-disclosure run-up is even larger →
    # the edge was gone before a follower could act.
    real = _result(0.04, 3.0, 0.06, 60)
    early = _result(0.03, 2.1, 0.06, 30)
    late = _result(0.05, 2.4, 0.06, 30)
    v = evaluate_gate(real, early, late)
    assert not v.passed
    assert any("exceeds pre-run-up" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_on_weak_t_and_oos_flip():
    real = _result(0.01, 0.6, 0.0, 60)     # insignificant
    early = _result(0.03, 2.1, 0.0, 30)
    late = _result(-0.02, -1.5, 0.0, 30)    # flips sign OOS
    v = evaluate_gate(real, early, late)
    assert not v.passed
