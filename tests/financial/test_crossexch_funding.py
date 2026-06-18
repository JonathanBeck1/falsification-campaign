"""Network-free unit tests for the T31 cross-exchange funding dispersion core.

Cover the invariants the pre-reg depends on: OKX JSON parses to per-interval
funding (realizedRate preferred), sub-second jitter is floored so the two-venue
join actually matches (the load-bearing alignment), the signed/abs difference and
its sign convention (book harvests |d|), the two-venue round-trip cost arithmetic
(4 taker fills), the break-even-interval kill control, the venue-shuffle placebo,
the IS/OOS split, the gate's decisive dispersion>cost check, and the OKX fetcher's
pagination + never-raise contract behind an injectable HTTP seam.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from trader.catalysts.crossexch_funding import (
    HttpResponse,
    binance_symbol,
    break_even_intervals,
    build_dispersion_panel,
    evaluate_gate,
    fetch_okx_funding_history,
    floor_to_funding_hour,
    harvest_stats,
    okx_inst_id,
    parse_okx_funding,
    round_trip_cost,
    split_is_oos,
    venue_shuffle_signed_mean,
)


# --------------------------------------------------------------------------- #
# Symbol mapping
# --------------------------------------------------------------------------- #
def test_symbol_mapping():
    assert binance_symbol("BTC") == "BTCUSDT"
    assert okx_inst_id("BTC") == "BTC-USDT-SWAP"


# --------------------------------------------------------------------------- #
# OKX parse
# --------------------------------------------------------------------------- #
def _okx_body(rows: list[dict]) -> str:
    return json.dumps({"code": "0", "data": rows})


def test_parse_okx_prefers_realized_rate():
    body = _okx_body([
        {"fundingTime": "1781452800000", "realizedRate": "0.0001", "fundingRate": "0.0009"},
        {"fundingTime": "1781424000000", "realizedRate": "-0.0002", "fundingRate": "0.0"},
    ])
    s = parse_okx_funding(body, "BTC")
    assert s is not None
    assert s.name == "BTCUSDT"
    # ascending by time; realizedRate used (not fundingRate)
    assert np.isclose(s.iloc[-1], 0.0001)
    assert np.isclose(s.iloc[0], -0.0002)


def test_parse_okx_falls_back_to_funding_rate():
    body = _okx_body([{"fundingTime": "1781452800000", "fundingRate": "0.0003"}])
    s = parse_okx_funding(body, "ETH")
    assert s is not None and np.isclose(s.iloc[0], 0.0003)


def test_parse_okx_rejects_bad_code_and_garbage():
    assert parse_okx_funding(json.dumps({"code": "1", "data": []}), "BTC") is None
    assert parse_okx_funding("not json", "BTC") is None
    assert parse_okx_funding("", "BTC") is None
    assert parse_okx_funding(_okx_body([]), "BTC") is None


# --------------------------------------------------------------------------- #
# Alignment — the load-bearing detail
# --------------------------------------------------------------------------- #
def test_floor_to_funding_hour_kills_subsecond_jitter():
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-03-01 00:00:00.005", tz="UTC"),
        pd.Timestamp("2026-03-01 08:00:00", tz="UTC"),
    ])
    s = pd.Series([0.001, 0.002], index=idx, name="BTCUSDT")
    f = floor_to_funding_hour(s)
    assert list(f.index) == [
        pd.Timestamp("2026-03-01 00:00:00", tz="UTC"),
        pd.Timestamp("2026-03-01 08:00:00", tz="UTC"),
    ]


def test_panel_join_matches_despite_jitter():
    # venue A jittered (Binance archive), venue B exact (OKX) — must still join.
    a = pd.Series(
        [0.0010, 0.0005],
        index=pd.DatetimeIndex([
            pd.Timestamp("2026-03-01 00:00:00.005", tz="UTC"),
            pd.Timestamp("2026-03-01 08:00:00.002", tz="UTC"),
        ]),
        name="BTCUSDT",
    )
    b = pd.Series(
        [0.0003, 0.0006],
        index=pd.DatetimeIndex([
            pd.Timestamp("2026-03-01 00:00:00", tz="UTC"),
            pd.Timestamp("2026-03-01 08:00:00", tz="UTC"),
        ]),
        name="BTCUSDT",
    )
    panel = build_dispersion_panel({"BTCUSDT": a}, {"BTCUSDT": b})
    assert panel.n_obs == 2  # both rows matched (not 0)
    # diff = A - B; abs_diff is what the neutral book harvests.
    row0 = panel.long_format.iloc[0]
    assert np.isclose(row0["diff"], 0.0010 - 0.0003)
    assert np.isclose(row0["abs_diff"], abs(0.0010 - 0.0003))


def test_panel_only_symbols_in_both_venues():
    a = pd.Series([0.001], index=pd.DatetimeIndex([pd.Timestamp("2026-03-01", tz="UTC")]), name="BTCUSDT")
    b = pd.Series([0.001], index=pd.DatetimeIndex([pd.Timestamp("2026-03-01", tz="UTC")]), name="ETHUSDT")
    panel = build_dispersion_panel({"BTCUSDT": a}, {"ETHUSDT": b})
    assert panel.n_obs == 0  # no shared symbol


# --------------------------------------------------------------------------- #
# Cost model
# --------------------------------------------------------------------------- #
def test_round_trip_cost_four_taker_fills():
    # 2 venues, each opened AND closed => 4 fills. 5 bps/leg => 20 bps.
    assert np.isclose(round_trip_cost(5.0), 0.0020)
    assert np.isclose(round_trip_cost(10.0), 0.0040)


def test_break_even_intervals():
    # dispersion 1 bp/interval, round trip 20 bps => 20 intervals to break even.
    assert np.isclose(break_even_intervals(0.0001, 0.0020), 20.0)
    assert break_even_intervals(0.0, 0.0020) == float("inf")


# --------------------------------------------------------------------------- #
# Harvest aggregation
# --------------------------------------------------------------------------- #
def _panel_from_diffs(symbol_diffs: dict[str, list[float]], start="2026-03-01"):
    """Build a DispersionPanel directly from per-symbol diff lists (A=B+diff)."""
    a_map, b_map = {}, {}
    for sym, diffs in symbol_diffs.items():
        idx = pd.date_range(start, periods=len(diffs), freq="8h", tz="UTC")
        b = pd.Series([0.0001] * len(diffs), index=idx, name=sym)
        a = pd.Series([0.0001 + d for d in diffs], index=idx, name=sym)
        a_map[sym], b_map[sym] = a, b
    return build_dispersion_panel(a_map, b_map)


def test_harvest_abs_diff_and_cost():
    # constant +2bps diff on one symbol, 30 intervals.
    panel = _panel_from_diffs({"BTCUSDT": [0.0002] * 30})
    hs = harvest_stats(panel, leg_fee_bps=5.0, hold_intervals=21)
    assert np.isclose(hs.mean_abs_diff, 0.0002)
    assert np.isclose(hs.mean_signed_diff, 0.0002)
    # round trip 20bps amortized over 21 intervals ~= 0.95bps/interval.
    assert np.isclose(hs.rt_cost, 0.0020)
    assert np.isclose(hs.after_cost_mean, 0.0002 - 0.0020 / 21)
    # break-even: 20bps / 2bps = 10 intervals.
    assert np.isclose(hs.break_even_intervals, 10.0)
    assert hs.n_timestamps == 30


def test_harvest_empty_panel():
    panel = _panel_from_diffs({})
    hs = harvest_stats(panel)
    assert hs.n_timestamps == 0 and hs.break_even_intervals == float("inf")


# --------------------------------------------------------------------------- #
# Placebo + split
# --------------------------------------------------------------------------- #
def test_venue_shuffle_collapses_signed_mean():
    # Strongly directional signed dispersion (always A>B by 2bps).
    panel = _panel_from_diffs({"BTCUSDT": [0.0002] * 200})
    real_signed = panel.long_format["diff"].mean()
    shuffled = venue_shuffle_signed_mean(panel, seed=7)
    assert np.isclose(real_signed, 0.0002)
    # Shuffling venue labels destroys the directional sign -> toward 0.
    assert abs(shuffled) < abs(real_signed)


def test_venue_shuffle_deterministic_under_seed():
    panel = _panel_from_diffs({"BTCUSDT": [0.0002, -0.0001, 0.0003] * 10})
    a = venue_shuffle_signed_mean(panel, seed=42)
    b = venue_shuffle_signed_mean(panel, seed=42)
    assert a == b


def test_split_is_oos():
    panel = _panel_from_diffs({"BTCUSDT": [0.0002] * 30})  # 8h grid from 2026-03-01
    is_p, oos_p = split_is_oos(panel, "2026-03-05")
    assert is_p.n_obs > 0 and oos_p.n_obs > 0
    assert is_p.long_format["ts"].max() < pd.Timestamp("2026-03-05", tz="UTC")
    assert oos_p.long_format["ts"].min() >= pd.Timestamp("2026-03-05", tz="UTC")


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #
def test_gate_kills_when_dispersion_below_cost():
    # Tiny 0.3 bps dispersion vs 20 bps round trip -> break-even ~67 intervals.
    panel = _panel_from_diffs({"BTCUSDT": [0.00003] * 100})
    full = harvest_stats(panel, leg_fee_bps=5.0, hold_intervals=21)
    is_p, oos_p = split_is_oos(panel, "2026-03-17")
    g = evaluate_gate(
        full,
        harvest_stats(is_p),
        harvest_stats(oos_p),
        placebo_signed_mean=0.0,
    )
    assert not g.passed
    assert any("dispersion>cost" in r and "FAIL" in r for r in g.reasons)
    assert any("after-cost" in r and "FAIL" in r for r in g.reasons)


def test_gate_passes_synthetic_strong_edge():
    # Unrealistically fat 5bps stable dispersion that beats cost (break-even 4).
    panel = _panel_from_diffs({"BTCUSDT": [0.0005] * 120, "ETHUSDT": [0.0005] * 120})
    full = harvest_stats(panel, leg_fee_bps=5.0, hold_intervals=21)
    is_p, oos_p = split_is_oos(panel, "2026-03-21")
    g = evaluate_gate(
        full,
        harvest_stats(is_p),
        harvest_stats(oos_p),
        placebo_signed_mean=1e-9,
    )
    assert g.passed, g.reasons


# --------------------------------------------------------------------------- #
# OKX fetcher — injectable seam, pagination, never-raise
# --------------------------------------------------------------------------- #
class _StubGetter:
    """Serves OKX pages from a fixed list of (rows) chunks keyed by `after`."""

    def __init__(self, pages: list[list[dict]]):
        self.pages = pages
        self.calls = 0

    def __call__(self, url, *, params=None):
        idx = self.calls
        self.calls += 1
        if idx >= len(self.pages):
            return HttpResponse(status_code=200, text=json.dumps({"code": "0", "data": []}))
        return HttpResponse(status_code=200, text=_okx_body(self.pages[idx]))


def test_fetch_okx_paginates_and_concats():
    # two pages of 100 + a short page; older cursor each time.
    base_ms = 1_781_452_800_000
    page1 = [{"fundingTime": str(base_ms - i * 28_800_000), "realizedRate": "0.0001"} for i in range(100)]
    page2 = [{"fundingTime": str(base_ms - (100 + i) * 28_800_000), "realizedRate": "0.0002"} for i in range(100)]
    page3 = [{"fundingTime": str(base_ms - (200 + i) * 28_800_000), "realizedRate": "0.0003"} for i in range(10)]
    getter = _StubGetter([page1, page2, page3])
    s = fetch_okx_funding_history("BTC", http_get=getter)
    assert s is not None
    assert len(s) == 210
    assert s.name == "BTCUSDT"


def test_fetch_okx_never_raises_on_error():
    class _Boom:
        def __call__(self, url, *, params=None):
            raise RuntimeError("network down")

    assert fetch_okx_funding_history("BTC", http_get=_Boom()) is None

    class _Bad:
        def __call__(self, url, *, params=None):
            return HttpResponse(status_code=403, text="")

    assert fetch_okx_funding_history("BTC", http_get=_Bad()) is None
