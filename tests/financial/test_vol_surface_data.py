"""Network-free tests for the shared vol-surface foundation (T22-T26 infra).

Every test injects synthetic option frames and a stub underlying fetcher, so no
socket is opened and no parquet file is read. The synthetic options are priced
with the module's own Black-Scholes so we know the exact IV the solver must
recover, and surfaces are built on hand-constructed skewed/term-structured
frames so the sign and selection logic is checked against a known answer.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from trader.catalysts import vol_surface_data as v


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _bs_quote_frame(
    *,
    trade_date: str,
    expiration: str,
    spot: float,
    rows: list[tuple[float, str, float]],  # (strike, right, true_iv)
    tau_years: float,
    spread: float = 0.02,
    open_interest: int = 1000,
    underlying_close=None,
) -> pd.DataFrame:
    """Build a lake-shaped frame whose mids are exact BS prices at the true IVs.

    bid/ask straddle the BS price by ``spread/2`` so mid == the BS price and the
    solver must recover ``true_iv`` exactly.
    """

    recs = []
    for strike, right, true_iv in rows:
        is_call = right.upper().startswith("C")
        price = float(v.bs_price(spot, strike, tau_years, true_iv, is_call))
        recs.append(
            {
                "trade_date": trade_date,
                "root": "TEST",
                "expiration": expiration,
                "strike": float(strike),
                "right": right,
                "bid": price - spread / 2,
                "ask": price + spread / 2,
                "close": price,
                "volume": 10,
                "open_interest": open_interest,
                "underlying_close": underlying_close,
                "source": "synthetic",
            }
        )
    return pd.DataFrame(recs)


def _stub_underlying(value: float):
    def _fetch(ticker, start, end):
        days = pd.date_range(start, end, freq="D")
        return {d.date(): value for d in days}

    return _fetch


def _boom_underlying(*a, **k):
    """A fetcher that fails loudly — asserts parity covered every date."""

    raise AssertionError("underlying_fetcher (yfinance last-resort) must not be called")


def _parity_chain_frame(
    *,
    trade_date: str,
    expiration: str,
    spot: float,
    tau_years: float,
    strikes: list[float],
    iv: float = 0.30,
    r: float = v.DEFAULT_RISK_FREE_RATE,
    spread: float = 0.02,
    underlying_close=None,
) -> pd.DataFrame:
    """A two-sided call+put chain at every strike, priced by BS so put-call parity
    recovers ``spot`` exactly (C - P = S - K·e^{-rT}). ``underlying_close`` is
    None by default to force the parity path.
    """

    rows: list[tuple[float, str, float]] = []
    for k in strikes:
        rows.append((k, "C", iv))
        rows.append((k, "P", iv))
    frame = _bs_quote_frame(
        trade_date=trade_date,
        expiration=expiration,
        spot=spot,
        rows=rows,
        tau_years=tau_years,
        spread=spread,
        underlying_close=underlying_close,
    )
    return frame


# --------------------------------------------------------------------------- #
# 1. BS IV solver recovers a known IV
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("is_call", [True, False])
@pytest.mark.parametrize("true_iv", [0.12, 0.30, 0.85, 1.40])
def test_iv_solver_recovers_known_iv(is_call: bool, true_iv: float):
    S, K, T = 100.0, 105.0, 0.5
    price = v.bs_price(S, K, T, true_iv, is_call)
    iv = float(v.implied_vol(price, S, K, T, is_call))
    assert iv == pytest.approx(true_iv, abs=1e-5)


def test_iv_solver_vectorized_smile_recovery():
    spot = 100.0
    strikes = np.array([80, 90, 100, 110, 120.0])
    true = np.array([0.45, 0.38, 0.30, 0.34, 0.41])
    is_call = np.array([False, False, True, True, True])
    prices = v.bs_price(spot, strikes, 0.25, true, is_call)
    ivs = v.implied_vol(prices, spot, strikes, 0.25, is_call)
    assert np.allclose(ivs, true, atol=1e-4)


def test_iv_solver_returns_nan_on_unusable_quotes():
    # price<=0, T<=0, below intrinsic -> all NaN.
    prices = np.array([0.0, -1.0, 0.10])  # last: way below intrinsic for ITM call
    S = np.array([100.0, 100.0, 100.0])
    K = np.array([100.0, 100.0, 50.0])
    T = np.array([0.25, 0.0, 0.25])
    is_call = np.array([True, True, True])
    ivs = v.implied_vol(prices, S, K, T, is_call)
    assert np.all(np.isnan(ivs))


def test_iv_solver_handles_nonfinite_inputs():
    ivs = v.implied_vol(
        np.array([np.nan, 5.0]),
        np.array([100.0, np.inf]),
        np.array([100.0, 100.0]),
        np.array([0.25, 0.25]),
        np.array([True, True]),
    )
    assert np.all(np.isnan(ivs))


# --------------------------------------------------------------------------- #
# 2. Loader: mid, two-sided filter, underlying-null -> fallback
# --------------------------------------------------------------------------- #
def test_loader_uses_lake_underlying_when_present():
    frame = _bs_quote_frame(
        trade_date="2024-03-01",
        expiration="2024-03-29",
        spot=100.0,
        rows=[(100.0, "C", 0.30)],
        tau_years=28 / 365,
        underlying_close=123.45,  # lake provides it
    )

    def _boom(*a, **k):  # fetcher must NOT be called when lake has the value
        raise AssertionError("underlying_fetcher should not be called")

    out = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        underlying_fetcher=_boom, frames=[frame],
    )
    assert len(out) == 1
    assert out["underlying"].iloc[0] == pytest.approx(123.45)


def test_loader_uses_parity_spot_when_underlying_null():
    # Null lake underlying -> the parity-derived spot (NOT yfinance) is used. The
    # matched call/put chain is priced so parity recovers spot=100 exactly; the
    # yfinance fetcher must therefore never be reached.
    frame = _parity_chain_frame(
        trade_date="2024-03-01", expiration="2024-03-29", spot=100.0,
        tau_years=28 / 365, strikes=[95.0, 100.0, 105.0], underlying_close=None,
    )
    out = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        underlying_fetcher=_boom_underlying, frames=[frame],
    )
    assert not out.empty
    assert out["underlying"].iloc[0] == pytest.approx(100.0, abs=0.05)
    # mid is the midpoint of bid/ask
    assert out["mid"].iloc[0] == pytest.approx((out["bid"].iloc[0] + out["ask"].iloc[0]) / 2)


def test_parity_spot_recovers_unadjusted_scale_for_post_split_name():
    # The bug this fix exists for: lake strikes are UNADJUSTED (~$790 scale, e.g.
    # AVGO pre its 2024 split) while yfinance returns a SPLIT-ADJUSTED close (~$79,
    # ~10x off). Parity must recover the ~$790 scale that matches the strikes, and
    # must NOT use the wrong-scale yfinance value.
    true_spot = 790.0
    frame = _parity_chain_frame(
        trade_date="2023-06-01", expiration="2023-06-30", spot=true_spot,
        tau_years=29 / 365, strikes=[770.0, 780.0, 790.0, 800.0, 810.0],
        iv=0.32, underlying_close=None,
    )
    out = v.load_option_quotes(
        "TEST", date(2023, 6, 1), date(2023, 6, 1),
        # A split-adjusted (10x-too-small) yfinance value that, if used, would put
        # "ATM" on a deep-ITM strike and blow IV up. Parity must override it.
        underlying_fetcher=_stub_underlying(true_spot / 10.0), frames=[frame],
    )
    assert not out.empty
    spot = out["underlying"].iloc[0]
    assert spot == pytest.approx(true_spot, rel=0.01)  # ~790, not ~79
    # And the recovered ATM IV is sane (~32%), not the ~290% the split-adjusted
    # spot would have produced.
    enriched = v.compute_implied_vols(out)
    atm = v.atm_iv(enriched, date(2023, 6, 1), target_days=29)
    assert 0.10 < atm < 0.60


def test_parity_spot_with_discount_matches_closed_form():
    # parity_spot_from_expiry must invert S = K·e^{-rT} + (C - P) including the
    # discount, recovering the exact spot the chain was priced at.
    frame = _parity_chain_frame(
        trade_date="2024-03-01", expiration="2024-06-29", spot=250.0,
        tau_years=120 / 365, strikes=[240.0, 245.0, 250.0, 255.0, 260.0],
        iv=0.45, underlying_close=None,
    )
    quotes = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        underlying_fetcher=_boom_underlying, frames=[frame],
    )
    # parity helper on the single expiration directly
    spot = v.parity_spot_from_expiry(quotes)
    assert spot == pytest.approx(250.0, abs=0.05)


def test_parity_spot_picks_shortest_liquid_expiration():
    # Two expiries on the same date; the loader's per-date parity must use the
    # shortest tenor. Both recover the same spot here, so we just confirm a valid
    # spot is attached without touching yfinance.
    near = _parity_chain_frame(
        trade_date="2024-03-01", expiration="2024-03-15", spot=120.0,
        tau_years=14 / 365, strikes=[115.0, 120.0, 125.0], underlying_close=None,
    )
    far = _parity_chain_frame(
        trade_date="2024-03-01", expiration="2024-06-15", spot=120.0,
        tau_years=106 / 365, strikes=[110.0, 120.0, 130.0], underlying_close=None,
    )
    out = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        underlying_fetcher=_boom_underlying, frames=[near, far],
    )
    assert not out.empty
    assert out["underlying"].to_numpy() == pytest.approx(120.0, abs=0.05)


def test_parity_spot_returns_nan_without_matched_pair():
    # Only calls, no puts -> parity cannot invert -> NaN (loader then falls back).
    calls_only = _bs_quote_frame(
        trade_date="2024-03-01", expiration="2024-03-29", spot=100.0,
        rows=[(95.0, "C", 0.30), (100.0, "C", 0.30), (105.0, "C", 0.30)],
        tau_years=28 / 365, underlying_close=None,
    )
    quotes_like = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        # yfinance must rescue the date parity can't invert.
        underlying_fetcher=_stub_underlying(100.0), frames=[calls_only],
    )
    assert v.parity_spot_from_expiry(quotes_like) != v.parity_spot_from_expiry(quotes_like) \
        or quotes_like.empty  # NaN != NaN
    # End-to-end: loader still attaches an underlying via the yfinance last resort.
    assert not quotes_like.empty
    assert (quotes_like["underlying"] == 100.0).all()


def test_yfinance_is_last_resort_only_when_parity_fails():
    # A date with a parity-invertible chain AND a date with calls-only. The first
    # gets parity spot; only the second reaches yfinance.
    parity_ok = _parity_chain_frame(
        trade_date="2024-03-01", expiration="2024-03-29", spot=200.0,
        tau_years=28 / 365, strikes=[195.0, 200.0, 205.0], underlying_close=None,
    )
    calls_only = _bs_quote_frame(
        trade_date="2024-03-04", expiration="2024-04-01", spot=999.0,
        rows=[(990.0, "C", 0.30), (1000.0, "C", 0.30)],
        tau_years=28 / 365, underlying_close=None,
    )
    out = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 4),
        underlying_fetcher=_stub_underlying(999.0), frames=[parity_ok, calls_only],
    )
    by_date = out.groupby(out["trade_date"].dt.normalize())["underlying"].first()
    assert by_date[pd.Timestamp("2024-03-01")] == pytest.approx(200.0, abs=0.05)  # parity
    assert by_date[pd.Timestamp("2024-03-04")] == pytest.approx(999.0, abs=0.05)  # yfinance


def test_loader_drops_one_sided_and_nonpositive_mids():
    base = _bs_quote_frame(
        trade_date="2024-03-01", expiration="2024-03-29", spot=100.0,
        rows=[(100.0, "C", 0.30)], tau_years=28 / 365, underlying_close=100.0,
    )
    bad = base.copy()
    bad.loc[0, "strike"] = 110.0
    bad.loc[0, "bid"] = 0.0  # one-sided -> dropped
    bad.loc[0, "ask"] = 1.0
    out = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        underlying_fetcher=_stub_underlying(100.0),
        frames=[base, bad],
    )
    # only the good two-sided row survives
    assert len(out) == 1
    assert out["strike"].iloc[0] == 100.0


def test_loader_drops_rows_with_no_underlying_anywhere():
    frame = _bs_quote_frame(
        trade_date="2024-03-01", expiration="2024-03-29", spot=100.0,
        rows=[(100.0, "C", 0.30)], tau_years=28 / 365, underlying_close=None,
    )
    # fetcher returns nothing -> row cannot get an underlying -> dropped.
    out = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        underlying_fetcher=lambda *a, **k: {}, frames=[frame],
    )
    assert out.empty


def test_loader_drops_expired_rows():
    frame = _bs_quote_frame(
        trade_date="2024-03-29", expiration="2024-03-29", spot=100.0,
        rows=[(100.0, "C", 0.30)], tau_years=0.0, underlying_close=100.0,
    )
    out = v.load_option_quotes(
        "TEST", date(2024, 3, 29), date(2024, 3, 29),
        underlying_fetcher=_stub_underlying(100.0), frames=[frame],
    )
    assert out.empty  # tau == 0 dropped


# --------------------------------------------------------------------------- #
# 3. compute_implied_vols + quality guards
# --------------------------------------------------------------------------- #
def test_compute_implied_vols_recovers_and_adds_columns():
    frame = _bs_quote_frame(
        trade_date="2024-03-01", expiration="2024-03-29", spot=100.0,
        rows=[(95.0, "P", 0.33), (100.0, "C", 0.30), (105.0, "C", 0.31)],
        tau_years=28 / 365, underlying_close=100.0,
    )
    quotes = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        underlying_fetcher=_stub_underlying(100.0), frames=[frame],
    )
    enriched = v.compute_implied_vols(quotes)
    for col in ("iv", "delta", "moneyness", "log_moneyness"):
        assert col in enriched
    by_strike = dict(zip(enriched["strike"], enriched["iv"], strict=True))
    assert by_strike[100.0] == pytest.approx(0.30, abs=1e-4)
    assert by_strike[95.0] == pytest.approx(0.33, abs=1e-4)


def test_bad_iv_excluded_by_guards():
    # An option priced at a 500% vol (above MAX_VALID_IV=300%) must be set NaN.
    frame = _bs_quote_frame(
        trade_date="2024-03-01", expiration="2024-03-29", spot=100.0,
        rows=[(100.0, "C", 0.30), (130.0, "C", 5.00)],
        tau_years=28 / 365, underlying_close=100.0,
    )
    quotes = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        underlying_fetcher=_stub_underlying(100.0), frames=[frame],
    )
    enriched = v.compute_implied_vols(quotes)
    ivs = dict(zip(enriched["strike"], enriched["iv"], strict=True))
    assert ivs[100.0] == pytest.approx(0.30, abs=1e-4)
    assert np.isnan(ivs[130.0])  # 500% vol excluded


def test_min_open_interest_guard_excludes_low_oi():
    frame = _bs_quote_frame(
        trade_date="2024-03-01", expiration="2024-03-29", spot=100.0,
        rows=[(100.0, "C", 0.30)], tau_years=28 / 365,
        open_interest=5, underlying_close=100.0,
    )
    quotes = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        underlying_fetcher=_stub_underlying(100.0), frames=[frame],
    )
    cfg = v.SurfaceConfig(min_open_interest=100)
    enriched = v.compute_implied_vols(quotes, config=cfg)
    assert np.isnan(enriched["iv"].iloc[0])  # OI 5 < 100 -> excluded


# --------------------------------------------------------------------------- #
# 4. surfaces: ATM-tenor selection, skew sign, term structure
# --------------------------------------------------------------------------- #
def _two_expiry_surface(spot=100.0):
    """30d and 90d expiries; both with a downside skew (puts richer)."""
    near = _bs_quote_frame(
        trade_date="2024-03-01", expiration="2024-03-31", spot=spot,
        rows=[
            (85.0, "P", 0.40), (90.0, "P", 0.37), (95.0, "P", 0.34),
            (100.0, "C", 0.30), (100.0, "P", 0.30),
            (105.0, "C", 0.28), (110.0, "C", 0.27), (115.0, "C", 0.26),
        ],
        tau_years=30 / 365, underlying_close=spot,
    )
    far = _bs_quote_frame(
        trade_date="2024-03-01", expiration="2024-05-30", spot=spot,
        rows=[
            (85.0, "P", 0.36), (90.0, "P", 0.34), (95.0, "P", 0.32),
            (100.0, "C", 0.29), (100.0, "P", 0.29),
            (105.0, "C", 0.28), (110.0, "C", 0.27), (115.0, "C", 0.26),
        ],
        tau_years=90 / 365, underlying_close=spot,
    )
    quotes = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        underlying_fetcher=_stub_underlying(spot), frames=[near, far],
    )
    return v.compute_implied_vols(quotes)


def test_atm_iv_selects_nearest_tenor():
    enriched = _two_expiry_surface()
    # ATM at 30d should pick the 30d expiry (ATM IV ~0.30).
    near = v.atm_iv(enriched, date(2024, 3, 1), target_days=30)
    assert near == pytest.approx(0.30, abs=0.01)
    # ATM at 90d should pick the 90d expiry (ATM IV ~0.29).
    far = v.atm_iv(enriched, date(2024, 3, 1), target_days=90)
    assert far == pytest.approx(0.29, abs=0.01)
    assert near > far  # the synthetic near term is more expensive


def test_skew_sign_positive_for_put_rich_surface():
    enriched = _two_expiry_surface()
    skew = v.risk_reversal_25d(enriched, date(2024, 3, 1), target_days=30)
    # 25d put IV > 25d call IV by construction -> positive skew.
    assert skew > 0


def test_skew_sign_negative_for_call_rich_surface():
    # Invert the smile: calls richer than puts -> negative 25d skew.
    frame = _bs_quote_frame(
        trade_date="2024-03-01", expiration="2024-03-31", spot=100.0,
        rows=[
            (85.0, "P", 0.26), (90.0, "P", 0.27), (95.0, "P", 0.28),
            (100.0, "C", 0.30), (100.0, "P", 0.30),
            (105.0, "C", 0.34), (110.0, "C", 0.37), (115.0, "C", 0.40),
        ],
        tau_years=30 / 365, underlying_close=100.0,
    )
    quotes = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        underlying_fetcher=_stub_underlying(100.0), frames=[frame],
    )
    enriched = v.compute_implied_vols(quotes)
    skew = v.risk_reversal_25d(enriched, date(2024, 3, 1), target_days=30)
    assert skew < 0


def test_term_structure_slope():
    enriched = _two_expiry_surface()
    ts = v.term_structure(enriched, date(2024, 3, 1), near_days=30, far_days=90)
    assert ts["near_iv"] == pytest.approx(0.30, abs=0.01)
    assert ts["far_iv"] == pytest.approx(0.29, abs=0.01)
    # near richer than far -> downward (backwardated) slope.
    assert ts["slope"] == pytest.approx(ts["far_iv"] - ts["near_iv"], abs=1e-9)
    assert ts["slope"] < 0


def test_iv_grid_returns_valid_points_only():
    enriched = _two_expiry_surface()
    grid = v.iv_grid(enriched, date(2024, 3, 1))
    assert not grid.empty
    assert grid["iv"].notna().all()
    assert {"tenor_days", "moneyness", "delta", "iv"}.issubset(grid.columns)
    # two distinct expiries present
    assert grid["expiration"].nunique() == 2


def test_surface_summary_aggregates():
    enriched = _two_expiry_surface()
    summary = v.surface_summary(enriched, date(2024, 3, 1))
    assert summary["atm_iv_30d"] == pytest.approx(0.30, abs=0.01)
    assert summary["skew_25d"] > 0
    assert summary["ts_slope"] < 0
    assert summary["n_valid_points"] > 0


# --------------------------------------------------------------------------- #
# 5. empty-input robustness
# --------------------------------------------------------------------------- #
def test_empty_inputs_do_not_crash():
    empty = v.load_option_quotes(
        "TEST", date(2024, 3, 1), date(2024, 3, 1),
        underlying_fetcher=_stub_underlying(100.0), frames=[],
    )
    assert empty.empty
    enriched = v.compute_implied_vols(empty)
    assert enriched.empty
    assert np.isnan(v.atm_iv(enriched, date(2024, 3, 1)))
    assert np.isnan(v.risk_reversal_25d(enriched, date(2024, 3, 1)))
    assert v.iv_grid(enriched, date(2024, 3, 1)).empty
