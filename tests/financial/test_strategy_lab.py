"""Tests for the strategy-mining lab — the key property: noise is rejected."""

from __future__ import annotations

import numpy as np
import pandas as pd

from trader.mining.lab import annualized_sharpe, run_lab
from trader.mining.strategies import Variant, _strategy_returns


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2017-01-02", periods=n)


def test_strategy_returns_have_no_lookahead():
    idx = _idx(5)
    close = pd.Series([100, 101, 102, 101, 103], index=idx, dtype=float)
    pos = pd.Series([1, 1, 0, 0, 1], index=idx, dtype=float)
    r = _strategy_returns(close, pos)
    # day 1->2 used position from day0 (1) * return(101/100-1)=+0.01
    assert r.iloc[0] == pytest_approx(0.01)
    # day 2->3 used position from day1 (1) * return(102/101-1)
    assert r.iloc[1] == pytest_approx(102 / 101 - 1)


def test_annualized_sharpe_basic():
    r = pd.Series([0.001] * 252)  # constant positive, zero vol -> guarded to 0
    assert annualized_sharpe(r) == 0.0
    rng = np.random.default_rng(0)
    noisy = pd.Series(rng.normal(0.0005, 0.01, 1000))
    s = annualized_sharpe(noisy)
    assert isinstance(s, float)


def _noise_variant(name: str, idx: pd.DatetimeIndex, rng) -> Variant:
    return Variant(name, "X", "noise",
                   pd.Series(rng.normal(0.0, 0.01, len(idx)), index=idx))


def test_lab_rejects_pure_noise():
    idx = _idx(1000)
    rng = np.random.default_rng(42)
    variants = [_noise_variant(f"noise_{i}", idx, rng) for i in range(60)]
    rep = run_lab(variants, split="2020-01-01")
    assert rep.n_trials == 60
    # The best-of-60 noise variant must NOT clear the deflation + OOS gate.
    assert len(rep.oos_confirmed) == 0
    assert rep.best_dsr < 0.95  # selection-corrected: best noise is not "real"


def test_lab_finds_a_planted_real_signal():
    idx = _idx(1000)
    rng = np.random.default_rng(7)
    variants = [_noise_variant(f"noise_{i}", idx, rng) for i in range(40)]
    # plant one genuinely strong, persistent signal (high Sharpe in BOTH halves)
    real = pd.Series(rng.normal(0.0010, 0.004, len(idx)), index=idx)  # SR ~ 4
    variants.append(Variant("planted_real", "X", "planted", real))
    rep = run_lab(variants, split="2020-01-01")
    assert rep.best is not None and rep.best.name == "planted_real"
    assert rep.best_dsr >= 0.95
    assert any(s.name == "planted_real" for s in rep.oos_confirmed)


def pytest_approx(x):
    import pytest
    return pytest.approx(x)
