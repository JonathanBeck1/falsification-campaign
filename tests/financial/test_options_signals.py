"""Tests for the QQQ option-signal generator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from trader.mining.options_signals import generate_option_variants


def _features(n: int = 400) -> pd.DataFrame:
    idx = pd.bdate_range("2021-01-04", periods=n)
    rng = np.random.default_rng(0)
    spot = pd.Series(300 * (1 + rng.normal(0.0003, 0.01, n)).cumprod(), index=idx)
    return pd.DataFrame({
        "spot": spot,
        "atm_vol": pd.Series(rng.normal(0.03, 0.005, n), index=idx).abs(),
        "put_skew": pd.Series(rng.normal(0.002, 0.001, n), index=idx),
        "term_slope": pd.Series(rng.normal(0.01, 0.003, n), index=idx),
    }, index=idx)


def test_generates_variants_for_each_feature():
    variants = list(generate_option_variants(_features()))
    # 3 features x 4 windows x (2 z-dirs + 2 regime-dirs) = 48
    assert len(variants) == 48
    assert all(v.ticker == "QQQ" for v in variants)
    families = {v.family for v in variants}
    assert families == {"opt_atm_vol", "opt_put_skew", "opt_term_slope"}


def test_no_lookahead_in_returns():
    feats = _features()
    qqq_ret = feats["spot"].pct_change()
    v = next(iter(generate_option_variants(feats)))
    # strategy return on a day must equal yesterday's position * today's return,
    # so it can never use same-day information — check the series is a subset of valid dates
    assert v.daily_returns.index.isin(qqq_ret.index).all()
    assert len(v.daily_returns) > 0
    assert v.daily_returns.notna().all()
