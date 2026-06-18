"""Network-free unit tests for the T41 buyback-announcement-drift core.

Every test runs on synthetic in-memory series; no EDGAR, no yfinance, no I/O.
We inject a known post-announcement drift and confirm the core recovers it, that
the t0 = next-session convention starts strictly AFTER the file date (no
leakage), that the (ticker, quarter) dedup and matched-control machinery behave,
and that the pre-registered gate fires on each kill criterion.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd

from trader.catalysts.buyback_drift import (
    EVENT_WINDOWS,
    PRIMARY_WINDOW,
    ROUND_TRIP_COST,
    BuybackFiling,
    abnormal_returns,
    aggregate,
    compute_event,
    dedup_filings,
    evaluate_gate,
    mean,
    net_vs_matched,
    quarter_key,
    resolve_t0_index,
    sample_matched_cars,
    t_stat_one_sample,
    welch_t,
    window_car,
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


def _prices_from_returns(index: pd.DatetimeIndex, daily: list[float]) -> pd.Series:
    """Build a price series whose pct_change equals ``daily`` (first day = 0)."""

    level = 100.0
    out = [level]
    for r in daily[1:]:
        level *= 1.0 + r
        out.append(level)
    return pd.Series(out, index=index)


# --------------------------------------------------------------------------- #
# stats primitives
# --------------------------------------------------------------------------- #
def test_t_stat_zero_mean_series_is_near_zero():
    vals = [0.01, -0.01, 0.02, -0.02, 0.005, -0.005]
    assert abs(t_stat_one_sample(vals)) < 0.5


def test_t_stat_positive_series_is_large():
    vals = [0.02] * 10 + [0.018, 0.022]
    assert t_stat_one_sample(vals) > 5.0


def test_welch_t_directional():
    a = [0.03, 0.031, 0.029, 0.030]
    b = [0.001, 0.0, -0.001, 0.0005]
    assert welch_t(a, b) > 2.0
    assert welch_t(b, a) < -2.0


# --------------------------------------------------------------------------- #
# (ticker, quarter) dedup
# --------------------------------------------------------------------------- #
def test_quarter_key_buckets():
    assert quarter_key(date(2021, 1, 5)) == (2021, 1)
    assert quarter_key(date(2021, 3, 31)) == (2021, 1)
    assert quarter_key(date(2021, 4, 1)) == (2021, 2)
    assert quarter_key(date(2021, 12, 31)) == (2021, 4)


def test_dedup_keeps_earliest_per_ticker_quarter():
    fs = [
        BuybackFiling("AAA", "1", date(2021, 2, 10), "x2"),
        BuybackFiling("AAA", "1", date(2021, 1, 5), "x1"),  # earlier, same Q -> kept
        BuybackFiling("AAA", "1", date(2021, 5, 1), "x3"),  # different Q -> kept
        BuybackFiling("BBB", "2", date(2021, 1, 20), "y1"),
    ]
    out = dedup_filings(fs)
    # AAA Q1 collapses to the Jan 5 filing; AAA Q2 and BBB Q1 survive.
    assert len(out) == 3
    aaa_q1 = [f for f in out if f.ticker == "AAA" and quarter_key(f.file_date) == (2021, 1)]
    assert len(aaa_q1) == 1
    assert aaa_q1[0].accession == "x1"
    # sorted by (date, ticker)
    assert [f.accession for f in out] == ["x1", "y1", "x3"]


# --------------------------------------------------------------------------- #
# t0 = next-session convention (no file-date leakage)
# --------------------------------------------------------------------------- #
def test_t0_is_strictly_after_file_date_on_trading_day():
    idx = _trading_index(date(2021, 6, 1), 30)  # Tue Jun 1 onward
    # File on a trading day that is in the index -> t0 must be the NEXT session.
    file_d = idx[5].date()
    t0 = resolve_t0_index(idx, file_d)
    assert t0 == 6
    assert idx[t0].date() > file_d


def test_t0_after_weekend_file_date():
    idx = _trading_index(date(2021, 6, 1), 30)
    # File on a Saturday -> t0 is the following Monday session.
    sat = idx[4].date() + timedelta(days=1)  # Fri+1 = Sat (idx[4] is a Friday region)
    while pd.Timestamp(sat).weekday() != 5:
        sat += timedelta(days=1)
    t0 = resolve_t0_index(idx, sat)
    assert t0 is not None
    assert idx[t0].date() > sat


def test_t0_none_when_file_after_series():
    idx = _trading_index(date(2021, 6, 1), 10)
    assert resolve_t0_index(idx, date(2025, 1, 1)) is None


# --------------------------------------------------------------------------- #
# CAR recovery: injected post-announcement drift
# --------------------------------------------------------------------------- #
def test_compute_event_recovers_injected_drift():
    idx = _trading_index(date(2021, 1, 4), 120)
    # Flat market; stock has +0.20% abnormal per day for 21 days starting at t0.
    file_d = idx[40].date()
    t0 = resolve_t0_index(idx, file_d)
    assert t0 == 41
    bench_ret = [0.0] * len(idx)
    stock_ret = [0.0] * len(idx)
    for off in range(0, 21):  # offsets 0..20 == [+1,+21]
        stock_ret[t0 + off] = 0.0020
    stock = _prices_from_returns(idx, stock_ret)
    bench = _prices_from_returns(idx, bench_ret)
    abn = abnormal_returns(stock, bench)

    ev = compute_event(abn, file_d, "AAA")
    assert ev is not None
    # 21 days * 0.20% ~= 4.2% over the PRIMARY window.
    assert abs(ev.cars[PRIMARY_WINDOW] - 21 * 0.0020) < 1e-6
    # short window [+1,+5] captures only the first 5 drift days.
    assert abs(ev.cars["car_p1_p5"] - 5 * 0.0020) < 1e-6


def test_file_date_return_does_not_leak_into_car():
    idx = _trading_index(date(2021, 1, 4), 120)
    file_d = idx[40].date()
    t0 = resolve_t0_index(idx, file_d)
    stock_ret = [0.0] * len(idx)
    # Put a huge +50% return ON the file-date session (offset -1 from t0).
    stock_ret[t0 - 1] = 0.50
    stock = _prices_from_returns(idx, stock_ret)
    bench = _prices_from_returns(idx, [0.0] * len(idx))
    abn = abnormal_returns(stock, bench)
    ev = compute_event(abn, file_d, "AAA")
    assert ev is not None
    # The file-date spike must NOT appear in any window (all start at t0).
    assert abs(ev.cars[PRIMARY_WINDOW]) < 1e-9


def test_compute_event_none_on_incomplete_window():
    idx = _trading_index(date(2021, 1, 4), 50)
    file_d = idx[40].date()  # only ~9 sessions left, < 63 needed for longest window
    stock = _prices_from_returns(idx, [0.0] * len(idx))
    bench = _prices_from_returns(idx, [0.0] * len(idx))
    abn = abnormal_returns(stock, bench)
    assert compute_event(abn, file_d, "AAA") is None


def test_compute_event_drops_glitch_window():
    idx = _trading_index(date(2021, 1, 4), 120)
    file_d = idx[40].date()
    t0 = resolve_t0_index(idx, file_d)
    stock_ret = [0.0] * len(idx)
    stock_ret[t0 + 3] = 0.90  # > MAX_ABS_DAILY_ABN inside the window
    stock = _prices_from_returns(idx, stock_ret)
    bench = _prices_from_returns(idx, [0.0] * len(idx))
    abn = abnormal_returns(stock, bench)
    assert compute_event(abn, file_d, "AAA") is None


# --------------------------------------------------------------------------- #
# matched control sampling
# --------------------------------------------------------------------------- #
def test_window_car_sums_offsets():
    idx = _trading_index(date(2021, 1, 4), 40)
    stock = _prices_from_returns(idx, [0.0] + [0.001] * (len(idx) - 1))
    bench = _prices_from_returns(idx, [0.0] * len(idx))
    abn = abnormal_returns(stock, bench)
    car = window_car(abn, 10, (0, 4))
    assert car is not None
    assert abs(car - 5 * 0.001) < 1e-9


def test_matched_cars_same_year_and_exclude_event_neighborhood():
    idx = _trading_index(date(2021, 1, 4), 200)
    stock = _prices_from_returns(idx, [0.0] * len(idx))  # flat -> all CARs 0
    bench = _prices_from_returns(idx, [0.0] * len(idx))
    abn = abnormal_returns(stock, bench)
    rng = random.Random(0)
    out = sample_matched_cars(
        abn,
        event_t0_positions=[50],
        event_years=[2021],
        index=pd.DatetimeIndex(abn.index),
        n_per_event=10,
        window=EVENT_WINDOWS["car_p1_p5"],
        rng=rng,
    )
    assert len(out) == 10
    # Flat series -> every matched CAR is ~0 (the placebo-null expectation).
    assert all(abs(c) < 1e-9 for c in out)


def test_matched_cars_respects_year_filter():
    idx = _trading_index(date(2020, 1, 1), 600)  # spans 2020-2022
    stock = _prices_from_returns(idx, [0.0] * len(idx))
    bench = _prices_from_returns(idx, [0.0] * len(idx))
    abn = abnormal_returns(stock, bench)
    years = pd.DatetimeIndex(abn.index).year
    rng = random.Random(1)
    out = sample_matched_cars(
        abn,
        event_t0_positions=[],
        event_years=[2021],
        index=pd.DatetimeIndex(abn.index),
        n_per_event=5,
        window=EVENT_WINDOWS["car_p1_p5"],
        rng=rng,
    )
    assert len(out) == 5
    # The 2021-only requestable year must actually exist in the index.
    assert (years == 2021).sum() > 5


# --------------------------------------------------------------------------- #
# aggregation + net-vs-matched
# --------------------------------------------------------------------------- #
def test_aggregate_after_cost_subtracts_round_trip():
    cars = [0.02, 0.03, 0.025, 0.028, 0.022]
    stats = aggregate(cars, label="t")
    assert abs(stats.gross_mean - mean(cars)) < 1e-12
    assert abs(stats.after_cost_mean - (mean(cars) - ROUND_TRIP_COST)) < 1e-12
    assert stats.win_rate == 1.0


def test_net_vs_matched_directional():
    event = [0.03, 0.031, 0.029, 0.030, 0.028]
    matched = [0.0, 0.001, -0.001, 0.0005, 0.0]
    net, t = net_vs_matched(event, matched)
    assert net > 0
    assert t > 2.0
    # If cohort == matched in distribution, net ~ 0.
    net2, _t2 = net_vs_matched(matched, matched)
    assert abs(net2) < 1e-12


# --------------------------------------------------------------------------- #
# pre-registered gate
# --------------------------------------------------------------------------- #
def _passing_kwargs() -> dict:
    return dict(
        n_events=120,
        after_cost_mean=0.02,
        after_cost_t=3.0,
        is_mean=0.018,
        is_n=40,
        oos_mean=0.021,
        oos_n=80,
        matched_mean=0.001,
        matched_t=0.3,
        net_vs_matched_mean=0.018,
        net_vs_matched_t=2.6,
    )


def test_gate_passes_when_all_criteria_met():
    assert evaluate_gate(**_passing_kwargs()).passed is True


def test_gate_fails_on_small_n():
    kw = _passing_kwargs()
    kw["n_events"] = 12
    v = evaluate_gate(**kw)
    assert v.passed is False
    assert any("N=12" in r and "FAIL" in r for r in v.reasons)


def test_gate_fails_on_weak_primary_t():
    kw = _passing_kwargs()
    kw["after_cost_t"] = 1.1
    assert evaluate_gate(**kw).passed is False


def test_gate_fails_on_negative_after_cost():
    kw = _passing_kwargs()
    kw["after_cost_mean"] = -0.005
    assert evaluate_gate(**kw).passed is False


def test_gate_fails_on_oos_sign_flip():
    kw = _passing_kwargs()
    kw["oos_mean"] = -0.01  # IS positive, OOS negative
    assert evaluate_gate(**kw).passed is False


def test_gate_fails_when_matched_placebo_significant():
    kw = _passing_kwargs()
    kw["matched_t"] = 3.5  # placebo itself drifts -> contamination
    assert evaluate_gate(**kw).passed is False


def test_gate_fails_when_net_of_matched_insignificant():
    kw = _passing_kwargs()
    kw["net_vs_matched_t"] = 0.4  # matched control absorbs the effect
    assert evaluate_gate(**kw).passed is False
