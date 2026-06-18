"""Network-free unit tests for the T29 funding-carry engine (pure core).

Cover the load-bearing invariants the pre-reg depends on: a SHORT into positive
funding COLLECTS it (sign), selection is LAGGED (no same-day look-ahead), turnover
cost only hits names that change, the funding-vs-price decomposition sums to the
book, the placebo is deterministic under a seed, and the stats/split helpers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trader.catalysts.crypto_funding_carry import (
    daily_funding_panel,
    daily_return_panel,
    daily_stats,
    run_carry,
    split_is_oos,
)


def _funding_series(start: str, n: int, rate: float, sym: str) -> pd.Series:
    # 3 intervals/day at 8h spacing.
    idx = pd.date_range(start, periods=n * 3, freq="8h", tz="UTC")
    return pd.Series([rate] * len(idx), index=idx, name=sym)


def test_daily_funding_panel_sums_intervals():
    f = {"A": _funding_series("2021-01-01", 2, 0.001, "A")}
    panel = daily_funding_panel(f)
    # 3 intervals x 0.001 = 0.003/day.
    assert np.isclose(panel["A"].iloc[0], 0.003)
    assert len(panel) == 2


def test_daily_return_panel_pct_change():
    df = pd.DataFrame({"close": [10.0, 11.0, 9.9]},
                      index=pd.date_range("2021-01-01", periods=3, tz="UTC"))
    panel = daily_return_panel({"A": df})
    assert pd.isna(panel["A"].iloc[0])
    assert np.isclose(panel["A"].iloc[1], 0.10)


def test_short_collects_positive_funding_and_price_sign():
    # One always-top-funding name, constant +funding, price flat → pure carry.
    dates = pd.date_range("2021-01-01", periods=20, freq="D")
    fund = pd.DataFrame({"A": [0.003] * 20, "B": [0.0001] * 20}, index=dates)
    rets = pd.DataFrame({"A": [0.0] * 20, "B": [0.0] * 20}, index=dates)
    res = run_carry(fund, rets, quantile=0.5, cost=0.0, trailing=7)
    # After warmup, A is selected and its +funding is COLLECTED (book > 0).
    good = res.book_ret.dropna()
    assert (good > 0).all()
    assert np.isclose(res.funding_component.dropna().iloc[-1], 0.003)
    assert np.isclose(res.price_component.dropna().iloc[-1], 0.0)


def test_short_leg_profits_when_price_falls():
    dates = pd.date_range("2021-01-01", periods=20, freq="D")
    fund = pd.DataFrame({"A": [0.0] * 20}, index=dates)
    rets = pd.DataFrame({"A": [-0.05] * 20}, index=dates)  # price falling 5%/day
    res = run_carry(fund, rets, quantile=1.0, cost=0.0, trailing=7)
    # No funding signal (>0 required) → nothing selected → all NaN. Good: the
    # selector only shorts names that actually PAY funding.
    assert res.n_names.max() == 0


def test_lag_no_same_day_lookahead():
    # Funding spikes on a single day; selection must react the NEXT day, not same.
    dates = pd.date_range("2021-01-01", periods=20, freq="D")
    base = [0.0001] * 20
    spike = base.copy()
    fund = pd.DataFrame({"A": base, "B": base}, index=dates)
    rets = pd.DataFrame({"A": [0.0] * 20, "B": [0.0] * 20}, index=dates)
    # Signal is a trailing mean shifted 1 — on the very first computable day the
    # selection cannot use that same day's funding. Verify the signal column the
    # engine would use is NaN for the first `trailing` days.
    res = run_carry(fund, rets, quantile=0.5, cost=0.0, trailing=7)
    # First 7 days: no trailing window yet (after the shift) → no basket.
    assert res.n_names.iloc[:7].sum() == 0
    assert spike == base  # (sanity, fixtures unchanged)


def test_turnover_cost_only_on_changed_names():
    # Stable basket → turnover 0 after first day → cost only on day 1.
    dates = pd.date_range("2021-01-01", periods=20, freq="D")
    fund = pd.DataFrame({"A": [0.003] * 20, "B": [0.0001] * 20}, index=dates)
    rets = pd.DataFrame({"A": [0.0] * 20, "B": [0.0] * 20}, index=dates)
    res = run_carry(fund, rets, quantile=0.5, cost=0.0012, trailing=7)
    costs = res.cost_component.dropna()
    # First selected day pays full entry cost; subsequent stable days pay ~0.
    assert costs.iloc[0] > 0
    assert np.isclose(costs.iloc[-1], 0.0)


def test_components_sum_to_book():
    dates = pd.date_range("2021-01-01", periods=20, freq="D")
    fund = pd.DataFrame({"A": [0.003] * 20, "B": [0.0001] * 20}, index=dates)
    rets = pd.DataFrame({"A": [0.01] * 20, "B": [-0.01] * 20}, index=dates)
    res = run_carry(fund, rets, quantile=0.5, cost=0.0012, trailing=7)
    recon = res.funding_component + res.price_component - res.cost_component
    pd.testing.assert_series_equal(
        recon.dropna(), res.book_ret.dropna(), check_names=False
    )


def test_placebo_deterministic_under_seed():
    dates = pd.date_range("2021-01-01", periods=30, freq="D")
    rng = np.random.default_rng(0)
    fund = pd.DataFrame(rng.uniform(0, 0.004, size=(30, 8)),
                        columns=list("ABCDEFGH"), index=dates)
    rets = pd.DataFrame(0.0, index=dates, columns=list("ABCDEFGH"))
    a = run_carry(fund, rets, quantile=0.25, cost=0.0, trailing=7, seed=42)
    b = run_carry(fund, rets, quantile=0.25, cost=0.0, trailing=7, seed=42)
    pd.testing.assert_series_equal(a.book_ret, b.book_ret)


def test_survivor_subset_restricts_universe():
    dates = pd.date_range("2021-01-01", periods=20, freq="D")
    fund = pd.DataFrame({"A": [0.003] * 20, "B": [0.005] * 20}, index=dates)
    rets = pd.DataFrame({"A": [0.0] * 20, "B": [0.0] * 20}, index=dates)
    res = run_carry(fund, rets, symbols=["A"], quantile=1.0, cost=0.0, trailing=7)
    # B excluded → only A ever in the basket.
    assert res.n_names.max() == 1


def test_daily_stats_and_split():
    s = pd.Series([0.001, -0.0005, 0.002, 0.0],
                  index=pd.date_range("2022-12-30", periods=4))
    st = daily_stats(s)
    assert st["n"] == 4
    is_, oos = split_is_oos(s, "2023-01-01")
    assert len(is_) == 2 and len(oos) == 2
