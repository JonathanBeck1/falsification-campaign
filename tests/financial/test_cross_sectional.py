"""Network-free tests for cross-sectional strategy mining."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from trader.mining.cross_sectional import (
    SECTORS,
    _apply_position,
    generate_cross_sectional_variants,
)

INDEX = pd.bdate_range("2015-01-01", "2024-12-31")
ALL_TICKERS = {
    "SPY",
    "IVV",
    "QQQ",
    "XLK",
    "IWM",
    "IJR",
    "XLF",
    "KRE",
    "XLE",
    "XOP",
    "GLD",
    "SLV",
    "EFA",
    "VEA",
    "HYG",
    "JNK",
    "TLT",
    "IEF",
    "EWZ",
    "EEM",
    "IYT",
    *SECTORS,
}


def _synthetic_prices(tickers: set[str], seed: int = 42) -> dict[str, pd.Series]:
    rng = np.random.default_rng(seed)
    market = rng.normal(0.0002, 0.006, len(INDEX))
    prices: dict[str, pd.Series] = {}
    for ticker in sorted(tickers):
        returns = market + rng.normal(0.0, 0.004, len(INDEX))
        prices[ticker] = pd.Series(100.0 * np.exp(np.cumsum(returns)), index=INDEX, name=ticker)
    return prices


def test_generate_variants_runs() -> None:
    variants = list(generate_cross_sectional_variants(_synthetic_prices(ALL_TICKERS)))
    families = {variant.family for variant in variants}

    assert {
        "pair_zscore",
        "sector_rotation_ls",
        "sector_rotation_lo",
        "lead_lag",
        "dispersion_timing",
    } <= families
    assert all(
        isinstance(variant.daily_returns, pd.Series) and not variant.daily_returns.empty
        for variant in variants
    )


def test_pair_zscore_no_lookahead() -> None:
    rng = np.random.default_rng(7)
    common_walk = np.cumsum(rng.normal(0.0, 0.01, len(INDEX)))
    spread = np.zeros(len(INDEX))
    for index in range(1, len(spread)):
        spread[index] = 0.85 * spread[index - 1] + rng.normal(0.0, 0.01)
    prices = {
        "SPY": pd.Series(100.0 * np.exp(common_walk + spread), index=INDEX),
        "IVV": pd.Series(100.0 * np.exp(common_walk), index=INDEX),
    }
    variant = next(
        candidate
        for candidate in generate_cross_sectional_variants(prices)
        if candidate.name == "pair_SPY_IVV_W20_z1.0_h5"
    )

    assert not variant.daily_returns.empty
    assert np.isfinite(variant.daily_returns.to_numpy()).all()

    idx = pd.bdate_range("2024-01-01", periods=5)
    position = pd.Series([0.0, 0.0, 1.0, 1.0, 1.0], index=idx)
    returns = pd.Series([0.0, 0.0, 0.25, 0.10, 0.0], index=idx)
    pnl = _apply_position(position, returns)
    assert pnl.loc[idx[2]] == 0.0
    assert pnl.loc[idx[3]] == 0.10


def test_sector_rotation_shapes() -> None:
    variants = [
        variant
        for variant in generate_cross_sectional_variants(_synthetic_prices(set(SECTORS)))
        if variant.family.startswith("sector_rotation")
    ]

    assert len(variants) == 6
    assert all(not variant.daily_returns.empty for variant in variants)
    assert all((variant.daily_returns.abs() < 0.5).all() for variant in variants)


def test_lead_lag_signal() -> None:
    rng = np.random.default_rng(123)
    leader_returns = rng.choice(np.array([-0.01, 0.01]), size=len(INDEX))
    follower_returns = np.zeros(len(INDEX))
    follower_returns[1:] = np.where(leader_returns[:-1] > 0.0, 0.01, -0.01)
    prices = {
        "XLK": pd.Series(100.0 * np.cumprod(1.0 + leader_returns), index=INDEX),
        "QQQ": pd.Series(100.0 * np.cumprod(1.0 + follower_returns), index=INDEX),
    }
    variant = next(
        candidate
        for candidate in generate_cross_sectional_variants(prices)
        if candidate.name == "leadlag_XLK_to_QQQ_L1"
    )
    daily = variant.daily_returns
    sharpe = float(daily.mean() / daily.std(ddof=1) * math.sqrt(252))

    assert sharpe > 0.0


def test_dispersion_timing_variants_exist() -> None:
    prices = _synthetic_prices({*SECTORS, "QQQ"})
    variants = [
        variant
        for variant in generate_cross_sectional_variants(prices)
        if variant.family == "dispersion_timing"
    ]

    assert len(variants) == 2
    assert {variant.name for variant in variants} == {"disp_low_QQQ", "disp_high_QQQ"}
