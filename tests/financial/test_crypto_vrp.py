"""Network-free unit tests for the T32 crypto-VRP engine (pure core + gate).

Cover the invariants the pre-registration (research/crypto_vrp_preregistration.md)
depends on:
  * forward RV uses returns strictly AFTER the observation day (no look-ahead),
  * the short-vol accrual collects entry implied variance and pays realized
    daily variance, so a single huge daily move produces a large LOSS (the tail),
  * entry IV is LAGGED (iv(t-1)), never same-day,
  * the long-vol placebo mirrors the short book up to cost,
  * the mechanism correlation is +1 when P&L is a clean function of the spread
    and ~0 when it is not (the equity-kill failure mode),
  * the quartile gradient + monotonicity helper,
  * drop-worst-month removes the right month,
  * the gate KILLS on mechanism-null / tail-hinge / OOS-flip,
  * the DVOL JSON parser keeps closes, normalizes to UTC days, drops junk.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trader.catalysts.crypto_vrp import (
    VrpResult,
    book_stats,
    daily_log_returns,
    drop_worst_month,
    dvol_to_fraction,
    evaluate_gate,
    is_monotone_increasing,
    iv_rv_spread,
    mechanism_corr,
    realized_vol_1d,
    realized_vol_forward,
    short_vol_book,
    split_is_oos,
    spread_quartile_gradient,
)
from trader.catalysts.crypto_vrp_data import (
    DVOL_INCEPTION,
    parse_dvol_payload,
)


def _const_iv(start: str, n: int, level: float) -> pd.Series:
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
    return pd.Series(level, index=idx, name="iv")


def _flat_close(start: str, n: int, price: float = 100.0) -> pd.Series:
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
    return pd.Series(price, index=idx, name="close")


# --------------------------------------------------------------------------- #
# Vol construction
# --------------------------------------------------------------------------- #
def test_log_returns_and_1d_vol():
    c = pd.Series([100.0, 110.0], index=pd.date_range("2021-04-01", periods=2, tz="UTC"))
    r = daily_log_returns(c)
    assert np.isclose(r.iloc[0], np.log(1.1))
    rv1 = realized_vol_1d(c)
    assert np.isclose(rv1.iloc[0], abs(np.log(1.1)) * np.sqrt(365))


def test_forward_rv_is_strictly_forward():
    # A price series flat then volatile: rv_fwd at the boundary must see the
    # FUTURE volatility, not the past (look-ahead audit).
    idx = pd.date_range("2021-04-01", periods=40, tz="UTC")
    prices = [100.0] * 20 + list(100.0 * np.cumprod(1 + 0.05 * (-1) ** np.arange(20)))
    c = pd.Series(prices, index=idx)
    rv = realized_vol_forward(c, window=5)
    # Early (flat-future) days have ~0 forward vol; later days see the choppy run.
    assert rv.iloc[0] < rv.iloc[-1]
    # The flat region (day 0) looks forward into days 1..5 which are still flat.
    assert rv.iloc[0] < 1e-9


def test_iv_rv_spread_and_dvol_fraction():
    dvol = pd.Series([75.0, 80.0], index=pd.date_range("2021-04-01", periods=2, tz="UTC"))
    iv = dvol_to_fraction(dvol)
    assert np.isclose(iv.iloc[0], 0.75)
    c = _flat_close("2021-04-01", 40)
    df = iv_rv_spread(iv.reindex(c.index).ffill(), c, window=5)
    # Flat spot ⇒ RV≈0 ⇒ vrp ≈ iv (premium is the whole IV).
    assert (df["vrp"] > 0).all()
    assert np.allclose(df["vrp"], df["iv"], atol=1e-6)


# --------------------------------------------------------------------------- #
# Short-vol book — the tail and the lag
# --------------------------------------------------------------------------- #
def test_short_vol_profits_when_realized_is_zero():
    # Flat spot (RV=0), positive IV ⇒ short vol collects pure premium each day.
    iv = _const_iv("2021-04-01", 30, 0.75)
    c = _flat_close("2021-04-01", 30)
    res = short_vol_book(iv, c, friction_vol_pts=0.0)
    assert (res.gross_ret > 0).all()
    # gross(t) = iv^2/(2 iv) = iv/2 when rv=0.
    assert np.allclose(res.gross_ret, 0.75 / 2.0)


def test_short_vol_takes_a_large_loss_on_a_vol_spike():
    # One catastrophic day: short vol must LOSE big (the crypto tail).
    idx = pd.date_range("2021-04-01", periods=10, tz="UTC")
    prices = [100.0] * 5 + [50.0] + [50.0] * 4  # a -50% day
    c = pd.Series(prices, index=idx)
    iv = _const_iv("2021-04-01", 10, 0.75)
    res = short_vol_book(iv, c, friction_vol_pts=0.0)
    # The spike day's P&L is the worst by a wide margin and is negative.
    assert res.book_ret.min() < 0
    spike_day = idx[5].tz_localize(None)  # engine strips tz
    assert res.book_ret.loc[spike_day] == res.book_ret.min()


def test_entry_iv_is_lagged():
    # If entry IV were same-day, a day-t IV jump would change day-t P&L; it must
    # only affect day t+1. Build IV that is 0 until a jump, flat spot.
    idx = pd.date_range("2021-04-01", periods=6, tz="UTC")
    iv = pd.Series([0.0, 0.0, 0.0, 0.80, 0.80, 0.80], index=idx, name="iv")
    c = _flat_close("2021-04-01", 6)
    res = short_vol_book(iv, c, friction_vol_pts=0.0)
    # iv>0 entries start the day AFTER iv jumps (lagged): first nonzero P&L day
    # is the one following the first iv>0 day.
    nonzero = res.gross_ret[res.gross_ret != 0]
    assert nonzero.index[0] == idx[4].tz_localize(None)  # iv[3] jumped ⇒ P&L on day 4


def test_long_vol_placebo_mirrors_short():
    iv = _const_iv("2021-04-01", 20, 0.6)
    rng = np.random.default_rng(0)
    c = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.02, 20)),
                  index=pd.date_range("2021-04-01", periods=20, tz="UTC"))
    short = short_vol_book(iv, c, friction_vol_pts=0.0, sign=+1)
    long_ = short_vol_book(iv, c, friction_vol_pts=0.0, sign=-1)
    assert np.allclose(short.gross_ret, -long_.gross_ret)


def test_cost_reduces_net_below_gross():
    iv = _const_iv("2021-04-01", 10, 0.5)
    c = _flat_close("2021-04-01", 10)
    res = short_vol_book(iv, c, friction_vol_pts=2.0)
    assert (res.book_ret < res.gross_ret).all()
    assert np.allclose(res.gross_ret - res.book_ret, (2.0 / 100.0) / 2.0)


# --------------------------------------------------------------------------- #
# Mechanism + quartiles + tail
# --------------------------------------------------------------------------- #
def test_mechanism_corr_high_when_pnl_tracks_spread():
    idx = pd.date_range("2021-04-01", periods=50, tz="UTC")
    spread = pd.Series(np.linspace(-0.2, 0.2, 50), index=idx)
    book = spread * 1.0  # P&L is exactly the spread
    assert mechanism_corr(spread, book) > 0.99


def test_mechanism_corr_near_zero_when_pnl_is_noise():
    rng = np.random.default_rng(7)
    idx = pd.date_range("2021-04-01", periods=400, tz="UTC")
    spread = pd.Series(rng.normal(0, 1, 400), index=idx)
    book = pd.Series(rng.normal(0, 1, 400), index=idx)  # independent
    assert abs(mechanism_corr(spread, book)) < 0.2


def test_quartile_gradient_and_monotone():
    idx = pd.date_range("2021-04-01", periods=40, tz="UTC")
    spread = pd.Series(np.linspace(0, 1, 40), index=idx)
    book = spread.copy()  # monotone by construction
    grad = spread_quartile_gradient(spread, book)
    assert is_monotone_increasing(grad)
    # Reversed P&L ⇒ decreasing ⇒ not monotone-increasing.
    assert not is_monotone_increasing(spread_quartile_gradient(spread, -book))


def test_drop_worst_month():
    idx = pd.date_range("2021-04-01", periods=90, tz="UTC")
    book = pd.Series(1.0, index=idx)
    book.loc["2021-05-15"] = -1000.0  # May is the worst month
    kept, worst = drop_worst_month(book)
    assert worst == "2021-05"
    assert (kept.index.tz_localize(None).to_period("M").astype(str) != "2021-05").all()


def test_book_stats_tail_fields():
    idx = pd.date_range("2021-04-01", periods=20, tz="UTC")
    book = pd.Series([0.1] * 19 + [-5.0], index=idx)
    st = book_stats(book)
    assert st["worst"] == -5.0
    assert st["maxdd"] < 0
    assert st["win"] == 19 / 20


def test_split_is_oos():
    idx = pd.date_range("2023-12-25", periods=14, tz="UTC")
    book = pd.Series(1.0, index=idx)
    is_, oos = split_is_oos(book.tz_localize(None), "2024-01-01")
    assert is_.index.max() < pd.Timestamp("2024-01-01")
    assert oos.index.min() >= pd.Timestamp("2024-01-01")


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #
def _mk_result(book: pd.Series, spread: pd.Series) -> VrpResult:
    return VrpResult(book_ret=book, gross_ret=book, entry_spread=spread,
                     spread_panel=pd.DataFrame())


def test_gate_kills_on_mechanism_null():
    # Positive mean P&L but corr(spread,pnl)≈0 ⇒ short-gamma beta, not VRP ⇒ KILL.
    rng = np.random.default_rng(1)
    idx = pd.date_range("2021-04-01", periods=600, tz="UTC")
    book = pd.Series(rng.normal(0.05, 0.1, 600), index=idx)  # positive, significant
    spread = pd.Series(rng.normal(0, 1, 600), index=idx)     # unrelated to book
    short = _mk_result(book, spread)
    flat = pd.Series(0.0, index=idx)
    placebo = _mk_result(flat, spread)
    gate = evaluate_gate(short, placebo, placebo)
    assert not gate.passed
    assert any("MECHANISM" in r and "FAIL" in r for r in gate.reasons)


def test_gate_kills_on_tail_hinge():
    # Full-sample NEGATIVE but worst-month-removed POSITIVE ⇒ verdict hinges on
    # excluding the tail ⇒ TAIL gate FAIL.
    idx = pd.date_range("2021-04-01", periods=120, tz="UTC")
    book = pd.Series(0.5, index=idx)
    book.loc["2021-05-01":"2021-05-31"] = -50.0  # tail month dominates → full mean<0
    spread = pd.Series(np.linspace(-0.1, 0.1, 120), index=idx)
    short = _mk_result(book, spread)
    flat = _mk_result(pd.Series(0.0, index=idx), spread)
    gate = evaluate_gate(short, flat, flat)
    assert not gate.passed
    assert any("TAIL" in r and "FAIL" in r for r in gate.reasons)


def test_gate_can_pass_a_clean_synthetic_edge():
    # A constructed clean edge: P&L tracks the spread (high corr, monotone),
    # positive every day, stable IS/OOS, no tail-hinge, placebo null.
    idx = pd.date_range("2021-04-01", periods=1100, tz="UTC")
    spread = pd.Series(np.linspace(0.01, 0.3, 1100), index=idx)
    book = (spread * 0.5 + 0.05)  # strictly positive, monotone in spread
    short = _mk_result(book, spread)
    flat = _mk_result(pd.Series(0.0, index=idx), spread)
    gate = evaluate_gate(short, flat, flat)
    assert gate.passed, gate.reasons


# --------------------------------------------------------------------------- #
# DVOL parser / fetch seam (no socket)
# --------------------------------------------------------------------------- #
def test_parse_dvol_payload_keeps_closes():
    body = {"result": {"data": [
        [1640995200000, 75.5, 75.5, 74.9, 74.99],
        [1641081600000, 74.99, 75.0, 74.6, 73.20],
        [1641081600000, 0, 0, 0, 0],          # dup-day junk (non-positive close dropped)
        ["bad", 1, 2, 3, 4],                   # malformed row skipped
    ]}}
    s = parse_dvol_payload(body)
    assert s is not None
    assert s.index.tz is None
    assert np.isclose(s.iloc[0], 74.99)  # we keep the CLOSE (col 4) of first row
    # Second day's close is 73.20 (the non-positive dup row is dropped pre-dedup).
    assert np.isclose(s.iloc[1], 73.20)
    assert len(s) == 2


def test_parse_dvol_payload_empty():
    assert parse_dvol_payload({"result": {"data": []}}) is None
    assert parse_dvol_payload(None) is None
    assert parse_dvol_payload({"error": {"code": 1}}) is None


def test_fetch_dvol_history_paginates_and_clamps():
    from datetime import date

    from trader.catalysts import crypto_vrp_data as cv

    calls: list[dict] = []

    def fake_getter(url, *, params=None):
        calls.append(params)
        # Return one row at the page start so we can see pagination boundaries.
        ts = params["start_timestamp"]
        body = {"result": {"data": [[ts, 60.0, 60.0, 60.0, 60.0]]}}
        return cv.HttpResponse(status_code=200, json_body=body)

    s = cv.fetch_dvol_history("BTC", date(2020, 1, 1), date(2026, 6, 1),
                              http_get=fake_getter)
    assert s is not None
    # start clamped to inception (2021-03-24), not 2020.
    assert s.index.min() >= pd.Timestamp(DVOL_INCEPTION)
    # multiple pages were requested (span >> PAGE_DAYS).
    assert len(calls) >= 2


def test_fetch_dvol_history_bad_status_returns_none():
    from datetime import date

    from trader.catalysts import crypto_vrp_data as cv

    def fake_getter(url, *, params=None):
        return cv.HttpResponse(status_code=429, json_body=None)

    out = cv.fetch_dvol_history("ETH", date(2021, 4, 1), date(2021, 6, 1),
                                http_get=fake_getter)
    assert out is None
