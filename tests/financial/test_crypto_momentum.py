"""Network-free unit tests for the T33 time-series-momentum engine (pure core).

Cover the load-bearing invariants the pre-reg depends on: the trailing-return
signal is LAGGED (no same-day look-ahead), an uptrend produces a long position
that profits while a downtrend stays FLAT (long-flat semantics), turnover cost
only hits names that FLIP position, gross - cost = book, the placebo preserves
exposure but destroys timing, buy-and-hold benchmarks are correct, and the
stats/split helpers behave.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trader.catalysts.crypto_momentum import (
    buy_and_hold,
    daily_close_panel,
    daily_return_panel,
    daily_stats,
    momentum_positions,
    run_momentum,
    split_is_oos,
)


def _rising(start: str, n: int, step: float, sym: str) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
    close = 100.0 * (1.0 + step) ** np.arange(n)
    return pd.DataFrame({"close": close}, index=idx)


def test_close_and_return_panels():
    k = {"A": _rising("2021-01-01", 5, 0.01, "A")}
    close = daily_close_panel(k)
    assert list(close.columns) == ["A"]
    assert close.index.tz is None  # tz stripped for alignment
    ret = daily_return_panel(close)
    assert pd.isna(ret["A"].iloc[0])
    assert np.isclose(ret["A"].iloc[1], 0.01)


def test_signal_is_lagged_no_same_day_lookahead():
    # 10 rising days: trailing-3 return turns positive, but the position must use
    # only data through t-1 (one extra shift beyond the lookback window).
    close = daily_close_panel({"A": _rising("2021-01-01", 10, 0.05, "A")})["A"].to_frame()
    pos = momentum_positions(close, lookback=3)
    # r_trail uses close.shift(3); position uses an ADDITIONAL .shift(1). So the
    # first non-NaN position appears at index 4 (needs close[t-1] and close[t-1-3]).
    assert pos["A"].iloc[:4].isna().all()
    assert pos["A"].iloc[4] == 1.0  # rising → long once the lagged signal exists


def test_uptrend_goes_long_downtrend_stays_flat():
    up = daily_close_panel({"A": _rising("2021-01-01", 30, 0.02, "A")})
    down = daily_close_panel({"B": _rising("2021-01-01", 30, -0.02, "B")})
    ret_up = daily_return_panel(up)
    ret_down = daily_return_panel(down)
    res_up = run_momentum(up, ret_up, lookback=5, cost=0.0)
    res_down = run_momentum(down, ret_down, lookback=5, cost=0.0)
    # Uptrend: long position earns the +returns → book strictly positive.
    assert (res_up.book_ret.dropna() > 0).all()
    # Downtrend long-flat: trailing return < 0 → FLAT → no names held → all NaN.
    assert res_down.n_names.max() == 0


def test_long_short_shorts_the_downtrend():
    down = daily_close_panel({"B": _rising("2021-01-01", 30, -0.02, "B")})
    ret_down = daily_return_panel(down)
    res = run_momentum(down, ret_down, lookback=5, cost=0.0, long_short=True)
    # short a falling asset → positive book.
    assert (res.book_ret.dropna() > 0).all()


def test_turnover_cost_only_on_position_flips():
    # Steady uptrend → position is a stable long → turnover ~0 after entry.
    up = daily_close_panel({"A": _rising("2021-01-01", 30, 0.02, "A")})
    ret_up = daily_return_panel(up)
    res = run_momentum(up, ret_up, lookback=5, cost=0.0012)
    costs = res.cost_component.dropna()
    assert costs.iloc[0] > 0          # entry day pays cost
    assert np.isclose(costs.iloc[-1], 0.0)  # stable long → no later cost


def test_gross_minus_cost_equals_book():
    up = daily_close_panel({"A": _rising("2021-01-01", 30, 0.02, "A"),
                            "C": _rising("2021-01-01", 30, 0.01, "C")})
    ret_up = daily_return_panel(up)
    res = run_momentum(up, ret_up, lookback=5, cost=0.0012)
    recon = (res.gross_ret - res.cost_component).dropna()
    pd.testing.assert_series_equal(recon, res.book_ret.dropna(), check_names=False)


def test_placebo_preserves_exposure_but_is_deterministic():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2021-01-01", periods=120, freq="D")
    close = pd.DataFrame(
        100.0 * np.cumprod(1 + rng.normal(0, 0.03, size=(120, 6)), axis=0),
        columns=list("ABCDEF"), index=idx,
    )
    ret = daily_return_panel(close)
    a = run_momentum(close, ret, lookback=30, cost=0.0, placebo_seed=7)
    b = run_momentum(close, ret, lookback=30, cost=0.0, placebo_seed=7)
    pd.testing.assert_series_equal(a.book_ret, b.book_ret)  # deterministic
    # Placebo preserves AVERAGE exposure: same number of long-days as the real
    # signal across the panel (only the timing is permuted).
    real = run_momentum(close, ret, lookback=30, cost=0.0)
    assert int(real.n_names.sum()) == int(a.n_names.sum())


def test_buy_and_hold_series_and_universe():
    s = pd.Series([0.01, -0.02, 0.03], index=pd.date_range("2021-01-01", periods=3))
    assert buy_and_hold(s).equals(s.rename("bh"))
    df = pd.DataFrame({"A": [0.10, 0.0], "B": [0.0, 0.20]},
                      index=pd.date_range("2021-01-01", periods=2))
    bh = buy_and_hold(df)
    assert np.isclose(bh.iloc[0], 0.05) and np.isclose(bh.iloc[1], 0.10)


def test_daily_stats_and_split():
    s = pd.Series([0.001, -0.0005, 0.002, 0.0, 0.001],
                  index=pd.date_range("2022-12-29", periods=5))
    st = daily_stats(s)
    assert st["n"] == 5
    assert st["maxdd"] <= 0.0  # drawdown is non-positive
    is_, oos = split_is_oos(s, "2023-01-01")
    assert len(is_) == 3 and len(oos) == 2
