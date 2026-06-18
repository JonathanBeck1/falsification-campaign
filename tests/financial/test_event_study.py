"""Tests for the shared event-study primitives (trader.research.event_study).

These pin behavioral equivalence with the per-module implementations the shared
module replaces: dropna→sort→DatetimeIndex, beta-1 abnormal returns with a
forward-filled benchmark, and the (n, mean, median, pct_positive, t_stat) window
aggregation with the campaign's 0.0-on-degenerate t-stat convention.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trader.research import event_study as es
from trader.research import gate


def test_sorted_close_drops_nan_sorts_and_datetime_indexes():
    s = pd.Series(
        [3.0, np.nan, 1.0, 2.0],
        index=pd.to_datetime(["2024-01-03", "2024-01-02", "2024-01-01", "2024-01-04"]),
    )
    out = es.sorted_close(s)
    assert list(out.values) == [1.0, 3.0, 2.0]  # nan dropped, sorted by date
    assert isinstance(out.index, pd.DatetimeIndex)
    assert list(out.index) == list(pd.to_datetime(["2024-01-01", "2024-01-03", "2024-01-04"]))


def test_abnormal_returns_market_adjusted_beta_one():
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    close = pd.Series([100.0, 110.0, 121.0], index=idx)  # +10%, +10%
    bench = pd.Series([100.0, 104.0, 104.0], index=idx)  # +4%, 0%
    abn = es.abnormal_returns(close, bench)
    # day 0 NaN; day1 = 0.10 - 0.04 = 0.06; day2 = 0.10 - 0.0 = 0.10
    assert np.isnan(abn.iloc[0])
    assert abs(abn.iloc[1] - 0.06) < 1e-12
    assert abs(abn.iloc[2] - 0.10) < 1e-12


def test_abnormal_returns_beta_scales_benchmark():
    idx = pd.to_datetime(["2024-01-01", "2024-01-02"])
    close = pd.Series([100.0, 110.0], index=idx)  # +10%
    bench = pd.Series([100.0, 105.0], index=idx)  # +5%
    half = es.abnormal_returns(close, bench, beta=0.5)
    assert abs(half.iloc[1] - (0.10 - 0.5 * 0.05)) < 1e-12


def test_abnormal_returns_forward_fills_benchmark_gaps():
    cidx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    close = pd.Series([100.0, 101.0, 102.0], index=cidx)
    bench = pd.Series([100.0, 100.0], index=pd.to_datetime(["2024-01-01", "2024-01-03"]))
    abn = es.abnormal_returns(close, bench)
    # bench ffilled to day2 -> bench return 0 there; abnormal == stock return
    assert abs(abn.iloc[1] - (101.0 / 100.0 - 1.0)) < 1e-12


def test_cumulative_abnormal_return_window_inclusive():
    abn = pd.Series([np.nan, 0.01, 0.02, -0.005, 0.03])
    # t0 at pos 1, window [0,+2] -> abn[1]+abn[2]+abn[3]
    car = es.cumulative_abnormal_return(abn, t0_pos=1, start=0, end=2)
    assert abs(car - (0.01 + 0.02 - 0.005)) < 1e-12


def test_cumulative_abnormal_return_out_of_range_is_nan():
    abn = pd.Series([0.01, 0.02])
    assert np.isnan(es.cumulative_abnormal_return(abn, t0_pos=1, start=0, end=5))
    assert np.isnan(es.cumulative_abnormal_return(abn, t0_pos=0, start=-3, end=0))


def test_aggregate_window_matches_house_convention():
    vals = [0.01, -0.02, 0.03, np.nan, 0.0]
    ws = es.aggregate_window("CAR[+1,+21]", vals)
    clean = [0.01, -0.02, 0.03, 0.0]
    assert ws.n == 4
    assert abs(ws.mean - float(np.mean(clean))) < 1e-12
    assert abs(ws.median - float(np.median(clean))) < 1e-12
    assert abs(ws.pct_positive - 0.5) < 1e-12  # 2 of 4 strictly positive
    # t_stat is exactly gate.t_stat on the cleaned values
    assert abs(ws.t_stat - gate.t_stat(clean)) < 1e-12


def test_aggregate_window_empty_matches_canonical():
    # Canonical _stat convention for n==0: mean/median/pct_positive are NaN,
    # t_stat is 0.0 (the campaign's degenerate t convention).
    ws = es.aggregate_window("x", [np.nan, np.nan])
    assert ws.n == 0
    assert np.isnan(ws.mean) and np.isnan(ws.median) and np.isnan(ws.pct_positive)
    assert ws.t_stat == 0.0


def test_welch_t_matches_manual_and_degenerate():
    a = [0.05, 0.04, 0.06, 0.05]
    b = [0.00, 0.01, -0.01, 0.00]
    # a clearly > b -> positive
    assert gate.welch_t(a, b) > 2.0
    # degenerate: < 2 obs on a side -> 0.0
    assert gate.welch_t([0.1], b) == 0.0
    # zero pooled variance -> 0.0
    assert gate.welch_t([1.0, 1.0, 1.0], [1.0, 1.0, 1.0]) == 0.0


def test_welch_t_drops_non_finite():
    a = [0.05, float("inf"), 0.06, 0.05, 0.04]
    b = [0.0, 0.0, 0.01]
    # inf dropped, still computes finitely
    out = gate.welch_t(a, b)
    assert np.isfinite(out) and out > 0
