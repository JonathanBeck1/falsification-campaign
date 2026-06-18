"""Network-free unit tests for T34 stablecoin depeg mean-reversion.

Pre-registration: ``research/stablecoin_depeg_preregistration.md``.

The tests pin the behaviour that makes T34 honest:

* the event detector **re-arms** (one multi-day depeg = ONE event, not one per
  day below peg — otherwise a single corpse manufactures dozens of events);
* a position whose price series **terminates** in the window is marked to the
  last available close (UST's death books an ~80% loss, NOT silently dropped);
* the survivorship split reports mean WITH vs WITHOUT dead coins, and the gate
  KILLS when including the corpses flips a survivor-only positive to <= 0.

Two synthetic series stand in for the real archive (no socket opens): a USDC-like
recovery (dips to 0.96, re-pegs) and a UST-like death (dips and runs to ~0.18,
then the series ends).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from trader.catalysts import crypto_data as cd
from trader.catalysts.crypto_data import HttpResponse
from trader.catalysts.stablecoin_depeg import (
    DepegEvent,
    build_events,
    distribution_summary,
    drop_worst,
    evaluate_gate,
    find_depeg_events,
    is_oos_split,
    placebo_stats,
    survivorship_split,
    t_stat,
)


def _series(prices: list[float], start: str = "2023-03-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(prices), freq="D", tz="UTC")
    return pd.Series(prices, index=idx, name="X")


# A USDC-like survivor: pegged, dips to 0.96, recovers above 0.995, holds.
USDC_LIKE = _series(
    [1.000, 1.000, 0.985, 0.960, 0.972, 0.990, 0.997, 1.000, 1.000, 1.000]
    + [1.000] * 30
)

# A UST-like death: pegged, breaks, slides to ~0.18, then the SERIES ENDS.
UST_LIKE = _series(
    [1.000, 0.994, 0.754, 0.799, 0.760, 0.363, 0.246, 0.180],
    start="2022-05-06",
)


# --------------------------------------------------------------------------- #
# Event detection + re-arming
# --------------------------------------------------------------------------- #
def test_find_depeg_events_basic_break():
    evts = find_depeg_events(USDC_LIKE)
    assert len(evts) == 1
    # first close strictly < 0.98 is 0.960 on day 3 (0.985 is still >= 0.98)
    assert evts[0].date() == date(2023, 3, 4)


def test_rearm_prevents_one_depeg_counting_many_times():
    # Three consecutive days below peg, no recovery between -> ONE event.
    s = _series([1.0, 0.97, 0.96, 0.95, 0.999, 1.0])
    assert len(find_depeg_events(s)) == 1


def test_rearm_allows_a_second_distinct_event_after_recovery():
    s = _series([1.0, 0.96, 0.999, 1.0, 0.95, 1.0])  # recovers, then breaks again
    assert len(find_depeg_events(s)) == 2


def test_nan_closes_are_skipped():
    s = _series([1.0, float("nan"), 0.96, 1.0])
    assert len(find_depeg_events(s)) == 1


# --------------------------------------------------------------------------- #
# Terminal death is REALIZED, not dropped (the whole point)
# --------------------------------------------------------------------------- #
def test_dead_coin_books_terminal_loss_not_dropped():
    evts = build_events(UST_LIKE, "USTUSDT", is_dead_coin=True)
    assert len(evts) == 1
    e = evts[0]
    assert e.terminal is True
    # Entry at 0.754 (first close < 0.98), exit at last available close 0.180.
    assert e.entry == 0.754
    assert e.exit_30d == 0.180
    assert e.ret_30d < -0.7  # ~ -76% realized loss, not dropped
    assert e.recovered is False


def test_survivor_recovers_to_peg_with_small_positive_return():
    evts = build_events(USDC_LIKE, "USDCUSDT", is_dead_coin=False)
    assert len(evts) == 1
    e = evts[0]
    assert e.recovered is True
    assert e.entry == 0.960  # first close < 0.98
    assert e.ret_30d > 0  # re-pegged to ~1.0 from 0.960
    assert 0.0 < e.ret_30d < 0.06  # a small re-peg win


def test_ret_to_peg_exits_on_first_recovery():
    evts = build_events(USDC_LIKE, "USDCUSDT", is_dead_coin=False)
    e = evts[0]
    # entry 0.960; first close >= 0.995 after t0 is 0.997 -> ret_to_peg
    assert e.exit_to_peg == 0.997
    assert abs(e.ret_to_peg - (0.997 / 0.960 - 1.0)) < 1e-9


# --------------------------------------------------------------------------- #
# Survivorship split + gate: corpses flip the sign -> KILL
# --------------------------------------------------------------------------- #
def _mixed_universe() -> list[DepegEvent]:
    # Many small survivor wins + one catastrophic death (the steamroller).
    evs = build_events(USDC_LIKE, "USDCUSDT", is_dead_coin=False) * 6
    evs += build_events(UST_LIKE, "USTUSDT", is_dead_coin=True)
    return evs


def test_survivorship_split_dead_coin_drags_mean_down():
    split = survivorship_split(_mixed_universe(), window="ret_30d")
    assert split["survivor_only"]["mean"] > 0  # survivors look great
    # With the death included, the mean is dragged down hard (sign may flip).
    assert split["with_dead"]["mean"] < split["survivor_only"]["mean"]
    assert split["n_dead_events"] == 1
    assert split["n_terminal_events"] == 1


def test_gate_kills_when_corpses_flip_the_sign():
    gate = evaluate_gate(_mixed_universe(), window="ret_30d")
    # survivor-only positive but with-dead <= 0 -> survivorship_ok False -> KILL
    assert gate["survivor_only_mean"] > 0
    assert gate["with_dead_mean"] <= 0
    assert gate["survivorship_ok"] is False
    assert gate["survives"] is False


def test_gate_fails_small_n():
    gate = evaluate_gate(
        build_events(USDC_LIKE, "USDCUSDT", is_dead_coin=False), window="ret_30d"
    )
    assert gate["n_ok"] is False
    assert gate["survives"] is False


def test_drop_worst_removes_the_single_catastrophe():
    evs = _mixed_universe()
    kept = drop_worst(evs, window="ret_30d")
    assert len(kept) == len(evs) - 1
    assert all(not e.terminal for e in kept)  # the terminal death is gone


# --------------------------------------------------------------------------- #
# Distribution / tail stats
# --------------------------------------------------------------------------- #
def test_distribution_summary_flags_short_vol_signature():
    rets = np.array([0.01] * 9 + [-0.8])  # 9 small wins + 1 disaster
    d = distribution_summary(rets)
    assert d["n"] == 10
    assert d["median"] > d["mean"]  # short-vol tell: median >> mean
    assert d["min"] == -0.8
    assert d["win_rate"] == 0.9  # wins often...
    assert d["skew"] < 0  # ...but fat LEFT tail

def test_t_stat_zero_variance_and_small_n():
    assert t_stat(np.array([0.01, 0.01, 0.01])) == 0.0
    assert t_stat(np.array([0.01])) == 0.0


def test_is_oos_split_partitions_on_t0():
    evs = build_events(USDC_LIKE, "USDCUSDT", is_dead_coin=False)  # 2023 -> OOS
    evs += build_events(UST_LIKE, "USTUSDT", is_dead_coin=True)  # 2022 -> IS
    split = is_oos_split(evs, window="ret_30d")
    assert split["is"]["n"] == 1  # UST 2022
    assert split["oos"]["n"] == 1  # USDC 2023


def test_placebo_on_non_event_days_is_near_zero():
    # A flat pegged series: random non-event entries -> 0 GROSS return, so the
    # after-cost mean is exactly the round-trip cost (no spurious signal).
    flat = {"PEG": _series([1.0] * 60)}
    d = placebo_stats(flat, n_per_symbol=10, seed=7)
    assert abs(d["mean"] - (-0.0020)) < 1e-9


# --------------------------------------------------------------------------- #
# Spot fetch wrapper (stubbed HTTP — no socket)
# --------------------------------------------------------------------------- #
def _zip_bytes(csv_text: str, member: str) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, csv_text)
    return buf.getvalue()


def test_fetch_spot_kline_month_parses_stub():
    csv_text = (
        "1651795200000,1.0,1.0,0.75,0.754,1000,1651881599999,1000,5,1,1,0\n"
    )
    payload = _zip_bytes(csv_text, "USTUSDT-1d-2022-05.csv")

    def stub(url: str, *, params=None) -> HttpResponse:
        assert "data/spot/monthly/klines/USTUSDT/1d/" in url
        return HttpResponse(status_code=200, content=payload)

    df = cd.fetch_spot_kline_month("USTUSDT", 2022, 5, http_get=stub)
    assert df is not None
    assert float(df["close"].iloc[0]) == 0.754


def test_fetch_spot_kline_month_non_200_returns_none():
    def stub(url: str, *, params=None) -> HttpResponse:
        return HttpResponse(status_code=404)

    assert cd.fetch_spot_kline_month("USTUSDT", 1999, 1, http_get=stub) is None
