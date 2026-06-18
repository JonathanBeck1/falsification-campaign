"""Tests for the T22 index-dispersion pure core (catalysts/index_dispersion.py).

These pin the mechanism math (implied/realized average correlation), the
vega-neutral book construction and its friction, and the gate statistics. They
are network-free and disk-free — every function under test is pure.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trader.catalysts import index_dispersion as idp


# --------------------------------------------------------------------------- #
# implied_correlation — the decomposition identity
# --------------------------------------------------------------------------- #
def test_implied_correlation_perfectly_correlated_basket_is_one():
    # If the index vol EQUALS the weighted-average constituent vol, every name
    # moves together: implied correlation must be exactly 1.
    sig = np.array([0.30, 0.40, 0.50])
    w = np.array([1.0, 1.0, 1.0])
    index_iv = float(np.mean(sig))  # equal weights -> sum w_i sig_i (normalized)
    rho = idp.implied_correlation(index_iv, sig, w)
    assert abs(rho - 1.0) < 1e-9


def test_implied_correlation_diversified_index_is_below_one():
    # A lower index vol than the average constituent vol => rho < 1 (diversified).
    sig = np.array([0.40, 0.40, 0.40, 0.40])
    w = np.ones(4)
    # Independent names: index var = (1/N) * sigma^2 -> index_iv = sigma/sqrt(N).
    index_iv = 0.40 / np.sqrt(4)
    rho = idp.implied_correlation(index_iv, sig, w)
    assert abs(rho - 0.0) < 1e-9  # zero average correlation


def test_implied_correlation_weights_normalized():
    sig = np.array([0.3, 0.5])
    rho_a = idp.implied_correlation(0.4, sig, np.array([1.0, 1.0]))
    rho_b = idp.implied_correlation(0.4, sig, np.array([5.0, 5.0]))  # same after norm
    assert abs(rho_a - rho_b) < 1e-12


def test_implied_correlation_nan_guards():
    assert np.isnan(idp.implied_correlation(0.3, np.array([0.3]), np.array([1.0])))  # < 2 names
    assert np.isnan(idp.implied_correlation(-0.3, np.array([0.3, 0.4]), np.array([1.0, 1.0])))
    # A non-positive constituent vol is filtered; one survivor -> < 2 names -> NaN.
    assert np.isnan(idp.implied_correlation(0.3, np.array([0.3, -1.0]), np.array([1.0, 1.0])))


# --------------------------------------------------------------------------- #
# realized_correlation — diagnostic counterpart
# --------------------------------------------------------------------------- #
def test_realized_correlation_identical_paths_is_one():
    base = np.array([0.01, -0.02, 0.015, -0.005, 0.02, -0.01])
    rets = pd.DataFrame({"A": base, "B": base, "C": base})
    index_ret = base  # an equal basket of identical names == the index
    rho = idp.realized_correlation(index_ret, rets, np.ones(3))
    assert abs(rho - 1.0) < 1e-6


def test_realized_correlation_independent_paths_near_zero():
    rng = np.random.default_rng(0)
    n = 400
    a = rng.normal(0, 0.02, n)
    b = rng.normal(0, 0.02, n)
    c = rng.normal(0, 0.02, n)
    rets = pd.DataFrame({"A": a, "B": b, "C": c})
    w = np.ones(3) / 3
    index_ret = w[0] * a + w[1] * b + w[2] * c
    rho = idp.realized_correlation(index_ret, rets, np.ones(3))
    assert abs(rho) < 0.15  # independent -> small average correlation


# --------------------------------------------------------------------------- #
# straddle value / vega
# --------------------------------------------------------------------------- #
def test_straddle_value_and_vega_positive_atm():
    val = idp.straddle_value(100.0, 30.0, 0.30)
    vega = idp.straddle_vega(100.0, 30.0, 0.30)
    assert val > 0 and vega > 0


def test_straddle_nan_on_bad_inputs():
    assert np.isnan(idp.straddle_value(100.0, 30.0, 0.0))
    assert np.isnan(idp.straddle_value(-1.0, 30.0, 0.3))
    assert np.isnan(idp.straddle_vega(100.0, -5.0, 0.3))


def test_straddle_value_increases_with_iv():
    lo = idp.straddle_value(100.0, 30.0, 0.20)
    hi = idp.straddle_value(100.0, 30.0, 0.40)
    assert hi > lo


# --------------------------------------------------------------------------- #
# dispersion_period_pnl — vega-neutral construction + friction
# --------------------------------------------------------------------------- #
def _mark(value, vega, hs, spot=100.0, strike=100.0, iv=0.3):
    return idp.StraddleMark(
        value=value, vega=vega, half_spread=hs, spot=spot, strike=strike,
        tenor_days=30.0, iv=iv, expiration=pd.Timestamp("2023-02-01"),
    )


def test_dispersion_pnl_zero_when_nothing_moves():
    # Entry==exit values, no friction -> zero P&L.
    idx = _mark(5.0, 10.0, 0.0)
    legs = [
        idp.DispersionLeg(name=f"N{i}", entry=_mark(4.0, 8.0, 0.0), exit_value=4.0, exit_half_spread=0.0, weight=1.0)
        for i in range(6)
    ]
    out = idp.dispersion_period_pnl(idx, 5.0, 0.0, legs, charge_friction=False)
    assert abs(out["ret"]) < 1e-12


def test_dispersion_pnl_profits_when_names_disperse_more_than_index():
    # Names' straddles gain (they moved) while the index straddle is ~flat
    # (constituents moved apart, index didn't) -> dispersion (long basket) profits.
    idx = _mark(5.0, 10.0, 0.0)
    legs = [
        idp.DispersionLeg(name=f"N{i}", entry=_mark(4.0, 8.0, 0.0), exit_value=5.0, exit_half_spread=0.0, weight=1.0)
        for i in range(6)
    ]
    out = idp.dispersion_period_pnl(idx, 5.0, 0.0, legs, charge_friction=False)
    assert out["ret"] > 0
    assert out["long_only"] > 0
    assert abs(out["short_index_only"]) < 1e-12  # index flat


def test_dispersion_pnl_friction_reduces_return():
    idx = _mark(5.0, 10.0, 0.20)
    legs = [
        idp.DispersionLeg(name=f"N{i}", entry=_mark(4.0, 8.0, 0.15), exit_value=4.2, exit_half_spread=0.15, weight=1.0)
        for i in range(6)
    ]
    gross = idp.dispersion_period_pnl(idx, 5.1, 0.20, legs, charge_friction=False)["ret"]
    net = idp.dispersion_period_pnl(idx, 5.1, 0.20, legs, charge_friction=True)["ret"]
    assert net < gross


def test_dispersion_pnl_nan_when_too_few_names():
    idx = _mark(5.0, 10.0, 0.0)
    legs = [
        idp.DispersionLeg(name="N0", entry=_mark(4.0, 8.0, 0.0), exit_value=4.0, exit_half_spread=0.0, weight=1.0)
    ]
    out = idp.dispersion_period_pnl(idx, 5.0, 0.0, legs, charge_friction=False)
    assert np.isnan(out["ret"])


def test_dispersion_pnl_vega_neutral_sizing():
    # With the index flat and the basket flat, the net is zero regardless of how
    # the per-name vega differs from the index vega (sizing absorbs the mismatch).
    idx = _mark(5.0, 12.0, 0.0)
    legs = [
        idp.DispersionLeg(name=f"N{i}", entry=_mark(3.0, 5.0 + i, 0.0), exit_value=3.0, exit_half_spread=0.0, weight=1.0)
        for i in range(6)
    ]
    out = idp.dispersion_period_pnl(idx, 5.0, 0.0, legs, charge_friction=False)
    assert abs(out["ret"]) < 1e-12


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def test_tstat_and_summarize():
    s = pd.Series([0.01, 0.02, -0.005, 0.015, 0.0, 0.03])
    t = idp.tstat(s)
    summ = idp.summarize(s)
    assert summ["n"] == 6
    assert np.isfinite(t)
    assert "max_drawdown" in summ and summ["max_drawdown"] <= 0


def test_incremental_alpha_collapses_when_book_is_just_control():
    # book == 2 * control exactly -> alpha 0, beta 2.
    rng = np.random.default_rng(3)
    control = pd.Series(rng.normal(0, 1, 50))
    book = 2.0 * control
    inc = idp.incremental_alpha(book, control)
    assert abs(inc["alpha"]) < 1e-9
    assert abs(inc["beta"] - 2.0) < 1e-9


def test_incremental_alpha_detects_real_alpha():
    rng = np.random.default_rng(4)
    control = pd.Series(rng.normal(0, 1, 200))
    book = 0.5 + 0.3 * control + rng.normal(0, 0.05, 200)  # constant alpha 0.5
    inc = idp.incremental_alpha(book, control)
    assert inc["alpha"] > 0.3
    assert inc["alpha_t"] > 2.0


def test_sign_flip_placebo_small_for_strong_positive():
    s = pd.Series([0.02] * 40)  # all positive, constant -> extreme right tail
    p = idp.sign_flip_placebo(s, k=2000)
    assert p < 0.01


def test_sign_flip_placebo_mid_for_noise():
    rng = np.random.default_rng(5)
    s = pd.Series(rng.normal(0, 1, 60))
    s = s - s.mean()  # exactly zero-mean -> sign-flip null is symmetric about it
    p = idp.sign_flip_placebo(s, k=4000)
    assert 0.35 < p < 0.65
