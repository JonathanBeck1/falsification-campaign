"""Unit tests for the insider-buy-cluster event-study engine. Network-free."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from trader.catalysts.insider_clusters import (
    Cluster,
    EventMetrics,
    InsiderBuy,
    StudyResult,
    WindowStat,
    after_cost_metrics,
    aggregate,
    build_clusters,
    compute_event_metrics,
    drop_top_contributors,
    evaluate_gate,
    normalize_insider,
)


def _buy(cik, insider, d, ticker="ABC", shares=100.0, price=10.0):
    return InsiderBuy(
        cik=cik, ticker=ticker, issuer=ticker, insider=insider,
        trade_date=d, shares=shares, price=price,
    )


# --------------------------------------------------------------------------- #
# Cluster detection
# --------------------------------------------------------------------------- #
def test_normalize_insider_collapses_case_and_space():
    assert normalize_insider("  John   Q  Smith ") == "JOHN Q SMITH"


def test_two_distinct_insiders_within_window_form_a_cluster():
    buys = [
        _buy("1", "Alice", date(2021, 3, 1)),
        _buy("1", "Bob", date(2021, 3, 10)),
    ]
    clusters = build_clusters(buys, k_distinct=2, window_days=30)
    assert len(clusters) == 1
    c = clusters[0]
    assert c.n_distinct_insiders == 2
    assert c.event_date == date(2021, 3, 10)   # anchored on the LAST buy
    assert c.first_date == date(2021, 3, 1)
    assert c.n_buys == 2


def test_single_insider_many_tickets_is_not_a_cluster():
    # one insider buying repeatedly is NOT a cluster, no matter how many tickets
    buys = [
        _buy("1", "Alice", date(2021, 3, 1)),
        _buy("1", "alice", date(2021, 3, 2)),   # same name, different case
        _buy("1", "ALICE", date(2021, 3, 3)),
    ]
    assert build_clusters(buys, k_distinct=2, window_days=30) == []


def test_distinct_insiders_too_far_apart_do_not_cluster():
    buys = [
        _buy("1", "Alice", date(2021, 3, 1)),
        _buy("1", "Bob", date(2021, 5, 1)),   # 61 days later
    ]
    assert build_clusters(buys, k_distinct=2, window_days=30) == []


def test_different_issuers_do_not_cross_cluster():
    # Aberdeen-style: same insider buying 1 each across many DIFFERENT issuers.
    buys = [
        _buy("A", "Stephen Bird", date(2021, 3, 1), ticker="FAX"),
        _buy("B", "Stephen Bird", date(2021, 3, 1), ticker="IAF"),
        _buy("C", "Stephen Bird", date(2021, 3, 1), ticker="AGD"),
    ]
    assert build_clusters(buys, k_distinct=2, window_days=30) == []


def test_k3_is_stricter_than_k2():
    buys = [
        _buy("1", "Alice", date(2021, 3, 1)),
        _buy("1", "Bob", date(2021, 3, 5)),
    ]
    assert len(build_clusters(buys, k_distinct=2)) == 1
    assert build_clusters(buys, k_distinct=3) == []
    buys.append(_buy("1", "Carol", date(2021, 3, 8)))
    assert len(build_clusters(buys, k_distinct=3)) == 1


def test_absorb_prevents_double_counting_same_wave():
    # a continuous 5-week buying wave should be ONE cluster, not two.
    buys = [
        _buy("1", "Alice", date(2021, 3, 1)),
        _buy("1", "Bob", date(2021, 3, 5)),
        _buy("1", "Carol", date(2021, 3, 28)),
        _buy("1", "Dave", date(2021, 4, 2)),
    ]
    clusters = build_clusters(buys, k_distinct=2, window_days=30, merge_days=30)
    assert len(clusters) == 1
    assert clusters[0].n_buys == 4


def test_two_separate_waves_make_two_clusters():
    buys = [
        _buy("1", "Alice", date(2021, 3, 1)),
        _buy("1", "Bob", date(2021, 3, 5)),
        # gap well beyond window + merge
        _buy("1", "Carol", date(2021, 9, 1)),
        _buy("1", "Dave", date(2021, 9, 5)),
    ]
    clusters = build_clusters(buys, k_distinct=2, window_days=30, merge_days=30)
    assert len(clusters) == 2


def test_total_value_sums_shares_times_price():
    buys = [
        _buy("1", "Alice", date(2021, 3, 1), shares=100, price=10),
        _buy("1", "Bob", date(2021, 3, 2), shares=50, price=20),
    ]
    c = build_clusters(buys, k_distinct=2)[0]
    assert c.total_value == pytest.approx(100 * 10 + 50 * 20)
    assert c.total_shares == pytest.approx(150)


# --------------------------------------------------------------------------- #
# CAR computation
# --------------------------------------------------------------------------- #
def _bdays(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2021-01-04", periods=n)


def test_car_recovers_known_market_adjusted_drift():
    """SPY flat; stock rises a constant 0.1%/day from t0 onward. CAR over
    [0,+63] should be ~ 63 * 0.001 of abnormal return."""
    idx = _bdays(400)
    t0 = 100
    spy = pd.Series([100.0] * len(idx), index=idx, name="SPY")
    px = []
    val = 100.0
    for i in range(len(idx)):
        if i <= t0:
            px.append(100.0)
        else:
            val *= 1.001  # +0.1% per trading day after t0
            px.append(val)
    stock = pd.Series(px, index=idx, name="ABC")
    cl = Cluster(
        cik="1", ticker="ABC", issuer="ABC", event_date=idx[t0].date(),
        first_date=idx[t0].date(), n_distinct_insiders=2, n_buys=2,
        total_shares=0.0, total_value=0.0, insiders=("ALICE", "BOB"),
    )
    m = compute_event_metrics(stock, spy, cl)
    assert m is not None
    assert m.t0_date == idx[t0].date()
    # 63 daily abnormal returns of ~0.001 each (t0+1..t0+63; AR at t0 itself ~0)
    assert m.car_0_p63 == pytest.approx(63 * 0.001, rel=2e-2)
    assert m.car_0_p21 == pytest.approx(21 * 0.001, rel=2e-2)
    assert m.car_0_p63 > m.car_0_p21 > 0


def test_car_market_adjustment_nets_out_common_move():
    """Stock and SPY move identically -> abnormal return ~ 0 at every horizon."""
    idx = _bdays(400)
    t0 = 100
    base = pd.Series(
        [100.0 * (1.0005 ** i) for i in range(len(idx))], index=idx
    )
    spy = base.copy()
    spy.name = "SPY"
    stock = base.copy()
    stock.name = "ABC"
    cl = Cluster(
        cik="1", ticker="ABC", issuer="ABC", event_date=idx[t0].date(),
        first_date=idx[t0].date(), n_distinct_insiders=2, n_buys=2,
        total_shares=0.0, total_value=0.0, insiders=("ALICE", "BOB"),
    )
    m = compute_event_metrics(stock, spy, cl)
    assert m is not None
    assert m.car_0_p252 == pytest.approx(0.0, abs=1e-9)


def test_compute_returns_none_when_window_incomplete():
    idx = _bdays(200)
    spy = pd.Series([100.0] * len(idx), index=idx, name="SPY")
    stock = pd.Series([100.0] * len(idx), index=idx, name="ABC")
    cl = Cluster(
        cik="1", ticker="ABC", issuer="ABC", event_date=idx[180].date(),
        first_date=idx[180].date(), n_distinct_insiders=2, n_buys=2,
        total_shares=0.0, total_value=0.0, insiders=("A", "B"),
    )
    assert compute_event_metrics(stock, spy, cl) is None


def test_placebo_event_date_override():
    idx = _bdays(400)
    spy = pd.Series([100.0] * len(idx), index=idx, name="SPY")
    stock = pd.Series([100.0] * len(idx), index=idx, name="ABC")
    cl = Cluster(
        cik="1", ticker="ABC", issuer="ABC", event_date=idx[350].date(),
        first_date=idx[350].date(), n_distinct_insiders=2, n_buys=2,
        total_shares=0.0, total_value=0.0, insiders=("A", "B"),
    )
    # real event date has no forward window; an earlier placebo date does
    assert compute_event_metrics(stock, spy, cl) is None
    m = compute_event_metrics(stock, spy, cl, event_date=idx[100].date())
    assert m is not None
    assert m.t0_date == idx[100].date()


# --------------------------------------------------------------------------- #
# Aggregation + gate
# --------------------------------------------------------------------------- #
def _metrics_with(values):
    return [
        EventMetrics(
            cik=str(i), ticker="X", event_date=date(2021, 1, 1),
            t0_date=date(2021, 1, 1), n_distinct_insiders=2,
            car_0_p21=v, car_0_p63=v, car_0_p126=v, car_0_p252=v,
        )
        for i, v in enumerate(values)
    ]


def test_aggregate_mean_pct_positive_and_tstat():
    res = aggregate(_metrics_with([0.05, 0.05, 0.05, 0.05]), label="real")
    assert res.n_events == 4
    s = res.stats["car_0_p63"]
    assert s.mean == pytest.approx(0.05)
    assert s.pct_positive == pytest.approx(1.0)


def _result(mean, t, n) -> StudyResult:
    stats = {
        k: WindowStat(k, n, mean, mean, 1.0 if mean > 0 else 0.0, t)
        for k in ("car_0_p21", "car_0_p63", "car_0_p126", "car_0_p252")
    }
    return StudyResult(label="x", n_events=n, stats=stats)


def test_gate_passes_when_signal_is_real():
    real = _result(0.04, 3.0, 60)
    placebo = _result(0.0, 0.0, 60)
    early = _result(0.03, 2.2, 30)
    late = _result(0.05, 2.4, 30)
    v = evaluate_gate(real, placebo, early, late)
    assert v.passed, v.reasons


def test_gate_fails_on_low_n():
    real = _result(0.04, 3.0, 12)
    placebo = _result(0.0, 0.0, 12)
    v = evaluate_gate(real, placebo, _result(0.03, 2.2, 6), _result(0.05, 2.4, 6))
    assert not v.passed
    assert any("N=12" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_when_placebo_matches():
    real = _result(0.04, 3.0, 60)
    placebo = _result(0.05, 3.0, 60)   # placebo just as good -> no edge
    v = evaluate_gate(real, placebo, _result(0.04, 2.2, 30), _result(0.04, 2.4, 30))
    assert not v.passed
    assert any("beats placebo" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_on_oos_sign_flip():
    real = _result(0.04, 3.0, 60)
    placebo = _result(0.0, 0.0, 60)
    early = _result(0.06, 2.2, 30)
    late = _result(-0.02, -1.5, 30)    # flips sign in the late half
    v = evaluate_gate(real, placebo, early, late)
    assert not v.passed
    assert any("OOS sign stable" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_on_weak_tstat():
    real = _result(0.04, 1.1, 60)      # right sign, too weak
    placebo = _result(0.0, 0.0, 60)
    v = evaluate_gate(real, placebo, _result(0.04, 1.0, 30), _result(0.04, 1.0, 30))
    assert not v.passed


def test_gate_fails_when_oos_half_too_thin():
    # right sign both halves, but the late half has < 10 events -> OOS untestable
    real = _result(0.04, 3.0, 60)
    placebo = _result(0.0, 0.0, 60)
    early = _result(0.03, 2.2, 55)
    late = _result(0.05, 2.4, 5)       # only 5 events in the OOS half
    v = evaluate_gate(real, placebo, early, late)
    assert not v.passed
    assert any("OOS sign stable" in r and "FAIL" in r for r in v.reasons)


# --------------------------------------------------------------------------- #
# After-cost adjustment + concentration robustness
# --------------------------------------------------------------------------- #
def test_after_cost_subtracts_one_round_trip_from_every_window():
    m = _metrics_with([0.05])[0]
    (ac,) = after_cost_metrics([m], round_trip=0.004)
    assert ac.car_0_p21 == pytest.approx(0.05 - 0.004)
    assert ac.car_0_p63 == pytest.approx(0.05 - 0.004)
    assert ac.car_0_p126 == pytest.approx(0.05 - 0.004)
    assert ac.car_0_p252 == pytest.approx(0.05 - 0.004)


def test_after_cost_can_flip_a_thin_gross_edge_negative():
    res = aggregate(after_cost_metrics(_metrics_with([0.002, 0.003, 0.001]),
                                       round_trip=0.004), label="ac")
    assert res.stats["car_0_p63"].mean < 0


def test_drop_top_contributors_removes_largest_primary_events():
    metrics = _metrics_with([0.01, 0.02, 0.50, 0.03])  # 0.50 is the multibagger
    kept = drop_top_contributors(metrics, k=1)
    assert len(kept) == 3
    assert all(m.car_0_p63 < 0.50 for m in kept)


def test_drop_top_contributors_reveals_outlier_driven_mean():
    # mean is positive only because of one huge survivor; drop it -> mean flips
    metrics = _metrics_with([-0.05, -0.04, -0.03, 1.0])
    assert aggregate(metrics, label="raw").stats["car_0_p63"].mean > 0
    kept = drop_top_contributors(metrics, k=1)
    assert aggregate(kept, label="trimmed").stats["car_0_p63"].mean < 0
