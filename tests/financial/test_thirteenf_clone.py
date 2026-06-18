"""Unit tests for the 13F clone event-study engine. Network-free."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from trader.catalysts.thirteenf_clone import (
    ROUND_TRIP_COST,
    CloneEvent,
    EventMetrics,
    Filing,
    Holding,
    StudyResult,
    WindowStat,
    aggregate,
    build_clone_events,
    compute_event_metrics,
    dedupe_events,
    evaluate_gate,
    new_positions,
    normalize_cusip,
)


def _h(cusip, ticker="AAA", value=1_000_000.0, issuer=None):
    return Holding(cusip=cusip, ticker=ticker, issuer=issuer or ticker, value=value)


def _filing(cik, fdate, rperiod, holdings, manager="MGR"):
    return Filing(
        cik=cik,
        manager=manager,
        filing_date=fdate,
        report_period=rperiod,
        holdings=tuple(holdings),
    )


# --------------------------------------------------------------------------- #
# normalize / new_positions
# --------------------------------------------------------------------------- #
def test_normalize_cusip_uppercases_and_strips():
    assert normalize_cusip("  02005n100 ") == "02005N100"


def test_new_positions_are_cusips_absent_from_prior():
    prior = [_h("AAA111", "AAA"), _h("BBB222", "BBB")]
    current = [_h("BBB222", "BBB"), _h("CCC333", "CCC"), _h("DDD444", "DDD")]
    new = new_positions(current, prior)
    assert {h.cusip for h in new} == {"CCC333", "DDD444"}


def test_new_positions_uses_cusip_not_ticker():
    # same ticker label but the CUSIP already existed -> NOT new
    prior = [_h("AAA111", "AAA")]
    current = [_h("AAA111", "AAA-relabeled")]
    assert new_positions(current, prior) == []


def test_new_positions_empty_when_nothing_added():
    prior = [_h("AAA111"), _h("BBB222")]
    assert new_positions(prior, prior) == []


# --------------------------------------------------------------------------- #
# build_clone_events
# --------------------------------------------------------------------------- #
def test_first_filing_yields_no_events():
    f0 = _filing("1", date(2020, 5, 15), date(2020, 3, 31), [_h("AAA111", "AAA")])
    assert build_clone_events([f0]) == []


def test_event_anchored_on_filing_date_not_report_period():
    f0 = _filing("1", date(2020, 2, 14), date(2019, 12, 31), [_h("AAA111", "AAA")])
    f1 = _filing(
        "1", date(2020, 5, 15), date(2020, 3, 31),
        [_h("AAA111", "AAA"), _h("BBB222", "BBB")],
    )
    events = build_clone_events([f0, f1])
    assert len(events) == 1
    ev = events[0]
    assert ev.ticker == "BBB"
    # the structural point: t0 anchor is the FILING date (ex-ante), not Q-end
    assert ev.filing_date == date(2020, 5, 15)
    assert ev.report_period == date(2020, 3, 31)


def test_build_events_orders_filings_by_filing_date():
    # pass out of order; the "new" diff must still be vs the chronological prior
    f_late = _filing(
        "1", date(2020, 5, 15), date(2020, 3, 31),
        [_h("AAA111", "AAA"), _h("BBB222", "BBB")],
    )
    f_early = _filing("1", date(2020, 2, 14), date(2019, 12, 31), [_h("AAA111", "AAA")])
    events = build_clone_events([f_late, f_early])
    assert [e.ticker for e in events] == ["BBB"]


def test_min_value_filter_drops_de_minimis():
    f0 = _filing("1", date(2020, 2, 14), date(2019, 12, 31), [_h("AAA111", "AAA")])
    f1 = _filing(
        "1", date(2020, 5, 15), date(2020, 3, 31),
        [_h("AAA111", "AAA"), _h("BBB222", "BBB", value=10.0)],
    )
    assert build_clone_events([f0, f1], min_value=1_000.0) == []


def test_events_without_ticker_are_skipped():
    f0 = _filing("1", date(2020, 2, 14), date(2019, 12, 31), [_h("AAA111", "AAA")])
    f1 = _filing(
        "1", date(2020, 5, 15), date(2020, 3, 31),
        [_h("AAA111", "AAA"), _h("BBB222", "")],
    )
    assert build_clone_events([f0, f1]) == []


# --------------------------------------------------------------------------- #
# dedupe_events
# --------------------------------------------------------------------------- #
def test_dedupe_collapses_same_ticker_same_filing_date_keeping_highest_value():
    e_lo = CloneEvent("1", "A", "XYZ", "X1", "XYZ", date(2020, 5, 15), date(2020, 3, 31), 5.0)
    e_hi = CloneEvent("2", "B", "XYZ", "X1", "XYZ", date(2020, 5, 15), date(2020, 3, 31), 9.0)
    out = dedupe_events([e_lo, e_hi])
    assert len(out) == 1
    assert out[0].value == 9.0 and out[0].cik == "2"


def test_dedupe_keeps_distinct_filing_dates():
    e1 = CloneEvent("1", "A", "XYZ", "X1", "XYZ", date(2020, 5, 15), date(2020, 3, 31), 5.0)
    e2 = CloneEvent("1", "A", "XYZ", "X1", "XYZ", date(2020, 8, 14), date(2020, 6, 30), 5.0)
    assert len(dedupe_events([e1, e2])) == 2


# --------------------------------------------------------------------------- #
# compute_event_metrics (CAR semantics)
# --------------------------------------------------------------------------- #
def _series(start, n, daily_ret, name="X"):
    idx = pd.bdate_range(start=start, periods=n)
    prices = 100.0 * np.cumprod(np.r_[1.0, np.full(n - 1, 1.0 + daily_ret)])
    s = pd.Series(prices, index=idx, name=name)
    return s


def _event(fdate):
    return CloneEvent(
        cik="1", manager="M", ticker="X", cusip="X1", issuer="X",
        filing_date=fdate, report_period=date(2020, 3, 31), value=1.0,
    )


def test_returns_none_when_window_insufficient():
    close = _series("2020-01-02", 50, 0.001)  # far fewer than 252+2 bars
    spy = _series("2020-01-02", 50, 0.0, name="SPY")
    assert compute_event_metrics(close, spy, _event(date(2020, 1, 2))) is None


def test_market_adjustment_zeroes_out_when_stock_tracks_spy():
    # stock and SPY identical -> abnormal return is ~0 every day
    close = _series("2020-01-02", 300, 0.001)
    spy = _series("2020-01-02", 300, 0.001, name="SPY")
    m = compute_event_metrics(close, spy, _event(date(2020, 1, 2)))
    assert m is not None
    assert abs(m.car_0_p63) < 1e-9
    assert abs(m.car_0_p252) < 1e-9


def test_positive_abnormal_return_accumulates_with_horizon():
    # stock outperforms SPY by ~10 bps/day -> CAR grows with the window
    close = _series("2020-01-02", 300, 0.0015)
    spy = _series("2020-01-02", 300, 0.0005, name="SPY")
    m = compute_event_metrics(close, spy, _event(date(2020, 1, 2)))
    assert m is not None
    assert m.car_0_p21 > 0
    assert m.car_0_p63 > m.car_0_p21
    assert m.car_0_p252 > m.car_0_p126


def test_t0_is_first_trading_day_on_or_after_event():
    close = _series("2020-01-02", 300, 0.001)
    spy = _series("2020-01-02", 300, 0.0, name="SPY")
    # event on a weekend -> t0 should snap to the next business day
    m = compute_event_metrics(close, spy, _event(date(2020, 1, 4)))  # Sat
    assert m is not None
    assert m.t0_date == date(2020, 1, 6)  # Monday


# --------------------------------------------------------------------------- #
# aggregate + cost
# --------------------------------------------------------------------------- #
def _metrics(values):
    return [
        EventMetrics("1", "M", "X", date(2020, 5, 15), date(2020, 5, 15),
                     v, v, v, v)
        for v in values
    ]


def test_aggregate_basic_stats():
    res = aggregate(_metrics([0.01, 0.03, -0.01, 0.05]), label="real")
    s = res.stats["car_0_p63"]
    assert s.n == 4
    assert s.mean == pytest.approx(0.02)
    assert s.pct_positive == pytest.approx(0.75)


def test_cost_subtracts_from_every_event():
    gross = aggregate(_metrics([0.02, 0.02, 0.02]), label="g")
    net = aggregate(_metrics([0.02, 0.02, 0.02]), label="n", cost=ROUND_TRIP_COST)
    assert net.stats["car_0_p63"].mean == pytest.approx(
        gross.stats["car_0_p63"].mean - ROUND_TRIP_COST
    )


# --------------------------------------------------------------------------- #
# evaluate_gate
# --------------------------------------------------------------------------- #
def _result(mean, t, n=40, primary_only=True):
    base = WindowStat("car_0_p63", n, mean, mean, 0.6, t)
    stats = {
        k: (base if k == "car_0_p63" else WindowStat(k, n, mean, mean, 0.6, t))
        for k in ("car_0_p21", "car_0_p63", "car_0_p126", "car_0_p252")
    }
    return StudyResult(label="x", n_events=n, stats=stats)


def test_gate_passes_when_all_hold():
    real = _result(0.02, 3.0)
    placebo = _result(0.0, 0.1)
    early = _result(0.02, 2.5)
    late = _result(0.015, 2.2)
    v = evaluate_gate(real, placebo, early, late)
    assert v.passed is True


def test_gate_fails_on_low_t():
    real = _result(0.02, 1.0)
    placebo = _result(0.0, 0.1)
    v = evaluate_gate(real, placebo, _result(0.02, 1.0), _result(0.02, 1.0))
    assert v.passed is False
    assert any("FAIL" in r and "primary" in r for r in v.reasons)


def test_gate_fails_on_small_n():
    real = _result(0.02, 3.0, n=10)
    v = evaluate_gate(real, _result(0.0, 0.1), _result(0.02, 3.0, n=10),
                      _result(0.02, 3.0, n=10))
    assert v.passed is False
    assert any("FAIL" in r and "N=" in r for r in v.reasons)


def test_gate_fails_on_oos_sign_flip():
    real = _result(0.02, 3.0)
    placebo = _result(0.0, 0.1)
    early = _result(0.03, 2.5)   # positive IS
    late = _result(-0.02, -2.2)  # negative OOS -> flip
    v = evaluate_gate(real, placebo, early, late)
    assert v.passed is False
    assert any("FAIL" in r and "OOS" in r for r in v.reasons)


def test_gate_fails_when_placebo_not_beaten():
    real = _result(0.01, 3.0)
    placebo = _result(0.015, 3.0)  # placebo higher than real
    v = evaluate_gate(real, placebo, _result(0.01, 2.5), _result(0.01, 2.5))
    assert v.passed is False
    assert any("FAIL" in r and "placebo" in r for r in v.reasons)
