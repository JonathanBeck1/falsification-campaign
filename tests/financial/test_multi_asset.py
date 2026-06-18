from __future__ import annotations

import numpy as np
import pandas as pd

from trader.mining.multi_asset import generate_multi_asset_variants
from trader.mining.strategies import Variant


def _prices() -> dict[str, pd.Series]:
    index = pd.date_range("2018-01-01", periods=800, freq="B")
    prices: dict[str, pd.Series] = {}
    for seed, ticker in enumerate(
        ("SPY", "QQQ", "TLT", "IEF", "GLD", "HYG", "LQD", "UUP", "VIXY", "VIX"),
        start=1,
    ):
        rng = np.random.default_rng(seed)
        daily = rng.normal(0.0002, 0.01, len(index))
        values = 100.0 * np.exp(np.cumsum(daily))
        prices[ticker] = pd.Series(values, index=index, name=ticker)
    return prices


def test_generate_variants_produces_variants() -> None:
    variants = list(generate_multi_asset_variants(_prices()))

    assert len(variants) >= 40
    assert all(isinstance(variant, Variant) for variant in variants)
    assert all(
        isinstance(variant.daily_returns, pd.Series)
        and not variant.daily_returns.empty
        for variant in variants
    )


def test_no_lookahead_in_a_known_family() -> None:
    prices = _prices()
    variants = list(generate_multi_asset_variants(prices))
    variant = next(v for v in variants if v.name == "bonds_eq_z60_trend_SPY")

    assert variant.daily_returns.index[0] >= prices["SPY"].index[60]


def test_missing_required_ticker_skips_family() -> None:
    prices = _prices()
    del prices["TLT"]
    variants = list(generate_multi_asset_variants(prices))
    families = {variant.family for variant in variants}

    assert "bonds_equity_ratio" not in families
    assert "yield_curve_proxy" not in families
    assert "vix_regime" in families


def test_target_tickers_are_only_spy_or_qqq() -> None:
    variants = list(generate_multi_asset_variants(_prices()))

    assert all(variant.ticker in {"SPY", "QQQ"} for variant in variants)


def test_variant_names_unique() -> None:
    variants = list(generate_multi_asset_variants(_prices()))

    assert len({variant.name for variant in variants}) == len(variants)
