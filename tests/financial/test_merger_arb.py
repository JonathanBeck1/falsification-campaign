"""Network-free unit tests for the T40 cash-merger-arbitrage core.

Every test runs on the hardcoded event list and synthetic in-memory price series;
no yfinance, no EDGAR, no I/O. We confirm the per-deal return math, the
outcome-stratified census, and — decisively — that the pre-registered gate fires
DATA_WALL when the completed-deal arm is unpriceable (the inverse-survivorship
trap that the live study actually hits), and KILL/SURVIVES otherwise.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from trader.catalysts.merger_arb import (
    MIN_COMPLETED_PRICEABLE,
    Census,
    CohortStats,
    MergerEvent,
    aggregate,
    annualize,
    build_census,
    compute_deal_return,
    curated_events,
    entry_close,
    evaluate,
    mean,
    median,
    std,
    t_stat_one_sample,
)


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #
def _trading_index(start: date, n: int) -> pd.DatetimeIndex:
    days: list[pd.Timestamp] = []
    cur = pd.Timestamp(start)
    while len(days) < n:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return pd.DatetimeIndex(days)


def _series(start: date, prices: list[float]) -> pd.Series:
    idx = _trading_index(start, len(prices))
    return pd.Series(prices, index=idx)


# --------------------------------------------------------------------------- #
# stats primitives
# --------------------------------------------------------------------------- #
def test_mean_median_std_basic():
    assert mean([1.0, 2.0, 3.0]) == 2.0
    assert median([1.0, 2.0, 3.0]) == 2.0
    assert median([1.0, 2.0, 3.0, 4.0]) == 2.5
    assert abs(std([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]) - 2.138) < 0.01


def test_mean_skips_nan():
    assert mean([1.0, float("nan"), 3.0]) == 2.0


def test_t_stat_against_mu():
    # A spread of values around 0.10: tested against mu=0.04 -> clearly positive
    # t; tested against their own mean -> ~0.
    vals = [0.09, 0.10, 0.11, 0.10, 0.10, 0.095, 0.105, 0.10, 0.10, 0.102]
    assert t_stat_one_sample(vals, mu=0.04) > 5.0
    assert abs(t_stat_one_sample(vals, mu=mean(vals))) < 1e-6


def test_t_stat_too_few_obs_is_zero():
    assert t_stat_one_sample([0.1], mu=0.0) == 0.0
    assert t_stat_one_sample([], mu=0.0) == 0.0


# --------------------------------------------------------------------------- #
# annualize
# --------------------------------------------------------------------------- #
def test_annualize_one_year_is_identity():
    assert abs(annualize(0.10, 365) - 0.10) < 1e-9


def test_annualize_half_year_compounds_up():
    # +5% in 182.5 days annualizes to ~ (1.05)^2 - 1 = 10.25%
    assert abs(annualize(0.05, 182) - ((1.05) ** (365 / 182) - 1)) < 1e-9
    assert annualize(0.05, 182) > 0.10


def test_annualize_total_wipeout_is_minus_one():
    assert annualize(-1.0, 100) == -1.0
    assert annualize(-1.5, 100) == -1.0


# --------------------------------------------------------------------------- #
# entry / per-deal return
# --------------------------------------------------------------------------- #
def test_entry_close_first_session_on_or_after_announce():
    # 7 weekdays from Mon 2022-01-03: 01-03,04,05,06,07,10,11.
    s = _series(date(2022, 1, 3), [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0])
    # announce on Sat 01-08 -> first session on/after is Mon 01-10 (price 15.0).
    res = entry_close(s, date(2022, 1, 8))
    assert res is not None
    price, d = res
    assert d == date(2022, 1, 10)
    assert price == 15.0
    # announce exactly on a trading day -> that day is the entry.
    res2 = entry_close(s, date(2022, 1, 5))
    assert res2 is not None and res2[1] == date(2022, 1, 5) and res2[0] == 12.0


def test_entry_close_none_when_announce_after_series():
    s = _series(date(2022, 1, 3), [10.0, 11.0])
    assert entry_close(s, date(2030, 1, 1)) is None


def test_completed_deal_pays_deal_price_positive_return():
    # entry at 90 on announce, deal price 100 -> ~+11% gross to the cash payout.
    ev = MergerEvent("X", date(2022, 1, 3), 100.0, "completed", "Acq")
    prices = [90.0] * 60  # flat at the spread until close
    s = _series(date(2022, 1, 3), prices)
    r = compute_deal_return(ev, s)
    assert r is not None
    assert r.outcome == "completed"
    assert r.terminal_value == 100.0
    assert r.gross_total > 0.10  # (100/90 - 1) ~ 0.111
    assert r.after_cost_annual > 0  # positive annualized


def test_broken_deal_marks_the_crater_negative_return():
    # entry at 95 (priced near a 100 deal), then deal breaks and stock craters to 60.
    ev = MergerEvent("Y", date(2022, 1, 3), 100.0, "broken", "Acq")
    prices = [95.0] * 5 + [60.0] * 60  # crater after a few days
    s = _series(date(2022, 1, 3), prices)
    r = compute_deal_return(ev, s, broken_mark_lag_td=30)
    assert r is not None
    assert r.outcome == "broken"
    assert r.terminal_value == 60.0  # marked at the realized crater, NOT 100
    assert r.gross_total < -0.30
    assert r.excess_annual < 0


def test_broken_deal_does_not_assume_deal_price():
    # The whole survivorship point: a broken deal must NOT be credited the deal
    # price. terminal_value comes from the realized path, never event.deal_price.
    ev = MergerEvent("Z", date(2022, 1, 3), 200.0, "broken", "Acq")
    prices = [150.0] * 40
    s = _series(date(2022, 1, 3), prices)
    r = compute_deal_return(ev, s, broken_mark_lag_td=30)
    assert r is not None
    assert r.terminal_value == 150.0
    assert r.terminal_value != ev.deal_price


# --------------------------------------------------------------------------- #
# curated list integrity
# --------------------------------------------------------------------------- #
def test_curated_events_strip_sentinels_and_dupes():
    evs = curated_events()
    tickers = [e.ticker for e in evs]
    assert len(tickers) == len(set(tickers))  # no dupes
    assert all(e.deal_price > 0 for e in evs)
    assert all(e.acquirer != "sentinel" for e in evs)
    # outcome-balanced: both arms present, broken arm non-trivial.
    comp = [e for e in evs if e.outcome == "completed"]
    brk = [e for e in evs if e.outcome == "broken"]
    assert len(comp) >= 20
    assert len(brk) >= 5  # broken deals INCLUDED by construction


def test_curated_events_span_2015_to_2025():
    years = [e.announce_date.year for e in curated_events()]
    assert min(years) <= 2016
    assert max(years) >= 2023


# --------------------------------------------------------------------------- #
# census + outcome stratification
# --------------------------------------------------------------------------- #
def test_census_counts_by_outcome():
    evs = [
        MergerEvent("A", date(2020, 1, 1), 10.0, "completed"),
        MergerEvent("B", date(2020, 1, 1), 10.0, "completed"),
        MergerEvent("C", date(2020, 1, 1), 10.0, "broken"),
    ]
    # Only B (completed) and C (broken) priceable.
    c = build_census(evs, priceable_tickers={"B", "C"})
    assert c.n_total == 3
    assert c.n_completed == 2
    assert c.n_broken == 1
    assert c.n_completed_priceable == 1
    assert c.n_broken_priceable == 1
    assert abs(c.completed_purge_rate - 0.5) < 1e-9
    assert c.broken_purge_rate == 0.0


def test_census_full_completed_purge():
    evs = [
        MergerEvent("A", date(2020, 1, 1), 10.0, "completed"),
        MergerEvent("B", date(2020, 1, 1), 10.0, "completed"),
        MergerEvent("C", date(2020, 1, 1), 10.0, "broken"),
    ]
    c = build_census(evs, priceable_tickers={"C"})  # only the broken one survives
    assert c.n_completed_priceable == 0
    assert c.completed_purge_rate == 1.0
    assert c.n_broken_priceable == 1


# --------------------------------------------------------------------------- #
# gate: DATA_WALL precedence (the live outcome)
# --------------------------------------------------------------------------- #
def _stats(n: int, excess_mean: float, t: float) -> CohortStats:
    return CohortStats(
        label="pooled",
        n=n,
        excess_mean=excess_mean,
        excess_median=excess_mean,
        excess_t=t,
        win_rate=0.5,
        after_cost_annual_mean=excess_mean + 0.04,
    )


def test_gate_data_wall_when_completed_arm_unpriceable():
    # completed arm purged below threshold -> DATA_WALL regardless of any returns.
    census = Census(
        n_total=33,
        n_completed=24,
        n_broken=9,
        n_completed_priceable=1,  # < MIN_COMPLETED_PRICEABLE
        n_broken_priceable=4,
        n_priceable=5,
    )
    v = evaluate(
        census,
        _stats(5, 0.50, 4.0),  # even a (fake) huge edge cannot rescue it
        is_mean=0.5,
        is_n=2,
        oos_mean=0.5,
        oos_n=3,
        placebo_t=0.0,
    )
    assert v.status == "DATA_WALL"
    assert any("DATA_WALL" in r for r in v.reasons)
    assert MIN_COMPLETED_PRICEABLE >= 15


def test_gate_kill_when_priceable_but_no_edge():
    census = Census(
        n_total=40,
        n_completed=30,
        n_broken=10,
        n_completed_priceable=20,  # >= threshold: completed arm priceable
        n_broken_priceable=8,
        n_priceable=35,
    )
    v = evaluate(
        census,
        _stats(35, -0.01, -0.4),  # below T-bill, t small
        is_mean=-0.01,
        is_n=18,
        oos_mean=0.005,
        oos_n=17,
        placebo_t=0.1,
    )
    assert v.status == "KILL"


def test_gate_survives_only_when_everything_passes():
    census = Census(
        n_total=40,
        n_completed=30,
        n_broken=10,
        n_completed_priceable=20,
        n_broken_priceable=8,
        n_priceable=35,
    )
    v = evaluate(
        census,
        _stats(35, 0.06, 3.5),  # +6% excess, strong t
        is_mean=0.05,
        is_n=18,
        oos_mean=0.07,
        oos_n=17,
        placebo_t=0.3,
    )
    assert v.status == "SURVIVES"


def test_gate_kill_on_oos_sign_flip_even_if_primary_strong():
    census = Census(
        n_total=40,
        n_completed=30,
        n_broken=10,
        n_completed_priceable=20,
        n_broken_priceable=8,
        n_priceable=35,
    )
    v = evaluate(
        census,
        _stats(35, 0.06, 3.5),
        is_mean=0.12,  # IS positive
        is_n=18,
        oos_mean=-0.03,  # OOS negative -> sign flip
        oos_n=17,
        placebo_t=0.3,
    )
    assert v.status == "KILL"


def test_gate_kill_when_placebo_not_null():
    census = Census(
        n_total=40,
        n_completed=30,
        n_broken=10,
        n_completed_priceable=20,
        n_broken_priceable=8,
        n_priceable=35,
    )
    v = evaluate(
        census,
        _stats(35, 0.06, 3.5),
        is_mean=0.05,
        is_n=18,
        oos_mean=0.07,
        oos_n=17,
        placebo_t=2.8,  # placebo "works" -> spurious
    )
    assert v.status == "KILL"


# --------------------------------------------------------------------------- #
# aggregate
# --------------------------------------------------------------------------- #
def test_aggregate_excess_and_winrate():
    from trader.catalysts.merger_arb import DealReturn

    def dr(excess: float) -> DealReturn:
        return DealReturn(
            ticker="T",
            announce_date=date(2020, 1, 1),
            outcome="completed",
            entry_price=10.0,
            entry_date=date(2020, 1, 1),
            terminal_value=11.0,
            terminal_date=date(2020, 6, 1),
            holding_days=150,
            gross_total=0.1,
            after_cost_annual=excess + 0.04,
            excess_annual=excess,
        )

    rs = [dr(0.05), dr(-0.02), dr(0.03), dr(-0.10)]
    st = aggregate(rs, label="pooled")
    assert st.n == 4
    assert abs(st.excess_mean - mean([0.05, -0.02, 0.03, -0.10])) < 1e-12
    assert abs(st.win_rate - 0.5) < 1e-12
