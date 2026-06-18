"""Parameterized strategy families for the mining lab.

Each family maps a price series -> a daily POSITION series (the position is
applied to the NEXT day's return, so there is no look-ahead). A generator
expands families x parameter grids x tickers into hundreds of candidate
variants. The whole point of the lab is that testing many variants inflates the
best in-sample Sharpe under the null — which the deflated Sharpe ratio then
corrects for.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Variant:
    name: str
    ticker: str
    family: str
    daily_returns: pd.Series  # strategy daily returns (position applied next day)


def _strategy_returns(close: pd.Series, position: pd.Series) -> pd.Series:
    """Daily strategy return = yesterday's position * today's asset return."""
    asset_ret = close.pct_change()
    return (position.shift(1) * asset_ret).dropna()


# --- families: close -> position (-1/0/1) -----------------------------------
def tsmom(close: pd.Series, lookback: int, *, long_short: bool) -> pd.Series:
    mom = close.pct_change(lookback)
    pos = (mom > 0).astype(float)
    if long_short:
        pos = pos * 2 - 1  # 1 / -1
    return pos


def ma_cross(close: pd.Series, fast: int, slow: int, *, long_short: bool) -> pd.Series:
    if fast >= slow:
        return pd.Series(0.0, index=close.index)
    pos = (close.rolling(fast).mean() > close.rolling(slow).mean()).astype(float)
    if long_short:
        pos = pos * 2 - 1
    return pos


def mean_reversion(close: pd.Series, window: int, z_thresh: float) -> pd.Series:
    ma = close.rolling(window).mean()
    sd = close.rolling(window).std(ddof=0)
    z = (close - ma) / sd.replace(0.0, float("nan"))
    pos = pd.Series(0.0, index=close.index)
    pos[z < -z_thresh] = 1.0   # buy dips
    pos[z > z_thresh] = -1.0   # fade spikes
    return pos


def vol_breakout(close: pd.Series, window: int) -> pd.Series:
    hi = close.rolling(window).max()
    return (close >= hi).astype(float)  # long-only breakout


def seasonal_dow(close: pd.Series, weekday: int) -> pd.Series:
    # long only on a given weekday (0=Mon .. 4=Fri); a classic noise-mine family
    return pd.Series((close.index.dayofweek == weekday).astype(float), index=close.index)


def generate_variants(prices: dict[str, pd.Series]) -> Iterator[Variant]:
    """Expand every family x grid x ticker into candidate variants."""
    for ticker, close in prices.items():
        if close is None or len(close) < 260:
            continue
        for lb in (5, 10, 20, 50, 100, 150, 200):
            for ls in (False, True):
                tag = "ls" if ls else "lo"
                yield Variant(f"tsmom_{lb}_{tag}_{ticker}", ticker, "tsmom",
                              _strategy_returns(close, tsmom(close, lb, long_short=ls)))
        for fast in (5, 10, 20, 50):
            for slow in (20, 50, 100, 200):
                if fast >= slow:
                    continue
                for ls in (False, True):
                    tag = "ls" if ls else "lo"
                    yield Variant(f"macross_{fast}_{slow}_{tag}_{ticker}", ticker, "ma_cross",
                                  _strategy_returns(close, ma_cross(close, fast, slow, long_short=ls)))
        for w in (10, 20, 50):
            for z in (1.0, 1.5, 2.0):
                yield Variant(f"meanrev_{w}_{z}_{ticker}", ticker, "mean_reversion",
                              _strategy_returns(close, mean_reversion(close, w, z)))
        for w in (20, 50, 100, 200):
            yield Variant(f"volbreak_{w}_{ticker}", ticker, "vol_breakout",
                          _strategy_returns(close, vol_breakout(close, w)))
        for d in range(5):
            yield Variant(f"dow_{d}_{ticker}", ticker, "seasonal_dow",
                          _strategy_returns(close, seasonal_dow(close, d)))
