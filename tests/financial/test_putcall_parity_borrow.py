"""Network-free tests for T26 (put-call parity / implied borrow).

The decisive tests inject a synthetic option chain whose call/put mids are built
to satisfy put-call parity at a *known* carry ``q``, then check the pure solver
recovers exactly that ``q`` — so a wrong sign or a units bug cannot hide. The
cross-sectional sort, the dispersion precondition, and the gate are each pinned
on hand-built inputs with a known answer. No socket, no parquet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trader.catalysts import putcall_parity_borrow as pb
from trader.catalysts.vol_surface_data import DEFAULT_RISK_FREE_RATE, bs_price


# --------------------------------------------------------------------------- #
# helpers: build a parity-consistent chain at a KNOWN carry q
# --------------------------------------------------------------------------- #
def _parity_chain(
    *,
    spot: float,
    strikes: list[float],
    tau: float,
    iv: float,
    q: float,
    r: float = DEFAULT_RISK_FREE_RATE,
    expiration: str = "2023-02-15",
    trade_date: str = "2023-01-16",
) -> pd.DataFrame:
    """A loader-shaped enriched frame whose C/P mids imply exactly carry ``q``.

    The call is priced by Black-Scholes with carry ``q`` (so ``S*e^{-q tau}`` is
    the discounted forward). The PUT mid is then *defined* by put-call parity:
    ``P = C - S*e^{-q tau} + K*e^{-r tau}``. This guarantees the recovered
    implied carry equals ``q`` to solver precision, independent of the call's IV.
    """

    rows = []
    for k in strikes:
        # Carry-aware BS call: pass q as the dividend/carry yield.
        call = float(bs_price(spot, k, tau, iv, True, r=r, q=q))
        put = call - spot * np.exp(-q * tau) + k * np.exp(-r * tau)
        for right, mid in (("C", call), ("P", put)):
            rows.append(
                {
                    "trade_date": pd.Timestamp(trade_date),
                    "expiration": pd.Timestamp(expiration),
                    "tau": tau,
                    "root": "TEST",
                    "strike": float(k),
                    "right": right,
                    "mid": float(mid),
                    "underlying": float(spot),
                }
            )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# implied_carry: exact recovery
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("q_true", [0.0, 0.01, 0.05, 0.20, -0.02])
def test_implied_carry_recovers_known_borrow(q_true: float):
    spot, strike, tau, iv = 100.0, 100.0, 0.25, 0.30
    r = DEFAULT_RISK_FREE_RATE
    call = float(bs_price(spot, strike, tau, iv, True, r=r, q=q_true))
    put = call - spot * np.exp(-q_true * tau) + strike * np.exp(-r * tau)
    got = float(pb.implied_carry(call, put, spot, strike, tau, r=r))
    assert got == pytest.approx(q_true, abs=1e-9)


def test_implied_carry_is_vectorized():
    spot, tau, iv = 100.0, 0.25, 0.30
    r = DEFAULT_RISK_FREE_RATE
    strikes = np.array([90.0, 100.0, 110.0])
    q_true = 0.08
    calls = bs_price(spot, strikes, tau, iv, True, r=r, q=q_true)
    puts = calls - spot * np.exp(-q_true * tau) + strikes * np.exp(-r * tau)
    got = pb.implied_carry(calls, puts, spot, strikes, tau, r=r)
    assert np.allclose(got, q_true, atol=1e-9)


def test_implied_carry_nan_on_bad_inputs():
    # Non-positive parity argument (C - P + K e^{-rT} <= 0) -> NaN, not a crash.
    got = pb.implied_carry(0.0, 1e9, 100.0, 100.0, 0.25)
    assert np.isnan(got)
    # Non-finite / non-positive spot, strike, tau all -> NaN.
    assert np.isnan(pb.implied_carry(5.0, 4.0, -1.0, 100.0, 0.25))
    assert np.isnan(pb.implied_carry(5.0, 4.0, 100.0, 100.0, 0.0))
    assert np.isnan(pb.implied_carry(np.nan, 4.0, 100.0, 100.0, 0.25))


# --------------------------------------------------------------------------- #
# parity_pairs: filtering + carry column
# --------------------------------------------------------------------------- #
def test_parity_pairs_filters_and_solves():
    chain = _parity_chain(spot=100.0, strikes=[98.0, 100.0, 102.0], tau=0.25, iv=0.3, q=0.05)
    pairs = pb.parity_pairs(chain)
    assert len(pairs) == 3
    assert np.allclose(pairs["q_star"], 0.05, atol=1e-9)
    assert list(pairs.columns) == [
        "expiration", "strike", "tau", "moneyness", "call_mid", "put_mid", "q_star",
    ]


def test_parity_pairs_drops_off_money_and_off_tenor():
    # One in-band strike, one far-OTM strike (|K/S-1| > window), one too-short tenor.
    near = _parity_chain(spot=100.0, strikes=[100.0], tau=0.25, iv=0.3, q=0.05)
    far = _parity_chain(spot=100.0, strikes=[140.0], tau=0.25, iv=0.3, q=0.05)
    short = _parity_chain(
        spot=100.0, strikes=[100.0], tau=2.0 / 365.0, iv=0.3, q=0.05,
        expiration="2023-01-18",
    )
    pairs = pb.parity_pairs(pd.concat([near, far, short], ignore_index=True))
    # Only the near, in-tenor strike survives.
    assert len(pairs) == 1
    assert pairs["strike"].iloc[0] == 100.0


def test_parity_pairs_empty_input():
    out = pb.parity_pairs(pd.DataFrame())
    assert out.empty
    assert "q_star" in out.columns


# --------------------------------------------------------------------------- #
# name_date_borrow: robust median, min-pairs floor
# --------------------------------------------------------------------------- #
def test_name_date_borrow_is_median_and_robust():
    chain = _parity_chain(spot=100.0, strikes=[97.0, 100.0, 103.0], tau=0.25, iv=0.3, q=0.06)
    nb = pb.name_date_borrow(chain, "TEST", "2023-01-16")
    assert nb is not None
    assert nb.n_pairs == 3
    assert nb.implied_borrow == pytest.approx(0.06, abs=1e-9)
    assert nb.ticker == "TEST"


def test_name_date_borrow_median_ignores_one_bad_pair():
    good = _parity_chain(spot=100.0, strikes=[98.0, 100.0, 102.0], tau=0.25, iv=0.3, q=0.04)
    # Corrupt one put mid hugely -> its q_star is an outlier; median must hold.
    good.loc[(good["strike"] == 102.0) & (good["right"] == "P"), "mid"] *= 3.0
    nb = pb.name_date_borrow(good, "TEST", "2023-01-16")
    assert nb is not None
    # Median over {q(98), q(100), q(102_corrupt)} still ~0.04 (the corrupt one is
    # the high/low extreme, not the middle).
    assert nb.implied_borrow == pytest.approx(0.04, abs=1e-3)


def test_name_date_borrow_returns_none_below_min_pairs():
    chain = _parity_chain(spot=100.0, strikes=[100.0], tau=0.25, iv=0.3, q=0.05)
    assert pb.name_date_borrow(chain, "TEST", "2023-01-16", min_pairs=2) is None


# --------------------------------------------------------------------------- #
# forward_return
# --------------------------------------------------------------------------- #
def test_forward_return_basic():
    idx = pd.bdate_range("2023-01-02", periods=30)
    close = pd.Series(np.linspace(100.0, 129.0, 30), index=idx)
    # 21-day forward from the first date.
    r = pb.forward_return(close, idx[0], 21)
    assert r == pytest.approx(close.iloc[21] / close.iloc[0] - 1.0, rel=1e-12)


def test_forward_return_nan_when_window_runs_off_end():
    idx = pd.bdate_range("2023-01-02", periods=10)
    close = pd.Series(np.arange(100.0, 110.0), index=idx)
    assert np.isnan(pb.forward_return(close, idx[0], 21))


# --------------------------------------------------------------------------- #
# cross_section_spread: low-minus-high sort
# --------------------------------------------------------------------------- #
def test_cross_section_spread_sign_when_high_borrow_underperforms():
    # 6 names; borrow ascending A..F. Make high-borrow names have LOW returns
    # (the hypothesis). Terciles of 6 -> 2 per leg.
    borrows = [("A", 0.0), ("B", 0.01), ("C", 0.02), ("D", 0.03), ("E", 0.04), ("F", 0.05)]
    # low-borrow (A,B) +2%, high-borrow (E,F) -2%.
    abn = {"A": 0.02, "B": 0.02, "C": 0.0, "D": 0.0, "E": -0.02, "F": -0.02}
    rs = pb.cross_section_spread(borrows, abn, pd.Timestamp("2023-01-16"))
    assert rs is not None
    assert rs.spread == pytest.approx(0.04, abs=1e-12)  # low(+0.02) - high(-0.02)
    assert rs.borrow_dispersion == pytest.approx(0.045 - 0.005, abs=1e-12)
    assert rs.low_borrow_ret == pytest.approx(0.02)
    assert rs.high_borrow_ret == pytest.approx(-0.02)


def test_cross_section_spread_none_when_too_few_names():
    assert pb.cross_section_spread([("A", 0.0), ("B", 0.01)], {"A": 0.1, "B": 0.2}, pd.Timestamp("2023-01-16")) is None


def test_cross_section_spread_skips_names_without_return():
    borrows = [("A", 0.0), ("B", 0.01), ("C", 0.02), ("D", 0.03)]
    abn = {"A": 0.01, "C": -0.01, "D": -0.02}  # B has no return -> dropped
    rs = pb.cross_section_spread(borrows, abn, pd.Timestamp("2023-01-16"))
    assert rs is not None
    assert rs.n_names == 3  # B dropped, 3 usable names remain


# --------------------------------------------------------------------------- #
# aggregate + gate
# --------------------------------------------------------------------------- #
def test_aggregate_spreads_after_cost():
    spreads = [0.01, 0.02, 0.03]
    st = pb.aggregate_spreads(spreads, label="primary", spread_cost=0.002)
    assert st.n == 3
    assert st.gross_mean == pytest.approx(0.02)
    assert st.after_cost_mean == pytest.approx(0.018)
    assert st.win_rate == pytest.approx(1.0)


def test_gate_data_wall_when_borrow_does_not_disperse():
    # Dispersion below the floor -> DATA_WALL regardless of everything else.
    v = pb.evaluate_gate(
        n_spreads=50,
        after_cost_mean=0.05,
        after_cost_t=5.0,
        is_mean=0.05, is_n=25, oos_mean=0.05, oos_n=25,
        median_borrow_dispersion=0.0005,  # 5 bps, below 100 bps floor
        placebo_t=0.1,
    )
    assert v.data_wall is True
    assert v.passed is False
    assert v.reasons[0].startswith("DATA_WALL")


def test_gate_passes_when_everything_holds():
    v = pb.evaluate_gate(
        n_spreads=40,
        after_cost_mean=0.01,
        after_cost_t=3.0,
        is_mean=0.01, is_n=20, oos_mean=0.008, oos_n=20,
        median_borrow_dispersion=0.05,  # 500 bps, disperses
        placebo_t=0.3,
    )
    assert v.data_wall is False
    assert v.passed is True


def test_gate_fails_on_oos_sign_flip():
    v = pb.evaluate_gate(
        n_spreads=40,
        after_cost_mean=0.01,
        after_cost_t=3.0,
        is_mean=0.02, is_n=20, oos_mean=-0.01, oos_n=20,  # sign flip
        median_borrow_dispersion=0.05,
        placebo_t=0.3,
    )
    assert v.passed is False


def test_iqr_noise_floor():
    assert pb.iqr([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx(2.0)
    assert np.isnan(pb.iqr([1.0, 2.0]))
