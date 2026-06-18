"""Tests for technical indicator math in build_snapshot."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from trader.storage.snapshot import Bar, MacroSnapshot, build_snapshot


def make_bars(closes: list[float]) -> list[Bar]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar(timestamp=base + timedelta(days=i), open=c, high=c, low=c, close=c, volume=1_000_000)
        for i, c in enumerate(closes)
    ]


def test_sma_computed_when_enough_bars():
    closes = list(range(1, 251))  # 250 bars: 1..250
    snap = build_snapshot(
        ticker="X",
        trade_date=date(2026, 5, 1),
        bars=make_bars(closes),
        news=[],
        macro=MacroSnapshot(),
    )
    # SMA-50 = avg of last 50 = (201 + 250) / 2 = 225.5
    assert snap.sma_50 == 225.5
    # SMA-200 = avg of last 200 = (51 + 250) / 2 = 150.5
    assert snap.sma_200 == 150.5


def test_sma_200_none_when_too_few_bars():
    closes = list(range(1, 51))  # only 50 bars
    snap = build_snapshot(
        ticker="X",
        trade_date=date(2026, 5, 1),
        bars=make_bars(closes),
        news=[],
        macro=MacroSnapshot(),
    )
    assert snap.sma_50 is not None
    assert snap.sma_200 is None


def test_rsi_at_100_when_all_gains():
    closes = [100 + i for i in range(20)]  # monotonically rising
    snap = build_snapshot(
        ticker="X",
        trade_date=date(2026, 5, 1),
        bars=make_bars(closes),
        news=[],
        macro=MacroSnapshot(),
    )
    assert snap.rsi_14 == 100.0


def test_realized_vol_finite():
    closes = [100 + (i % 3) * 0.5 for i in range(30)]
    snap = build_snapshot(
        ticker="X",
        trade_date=date(2026, 5, 1),
        bars=make_bars(closes),
        news=[],
        macro=MacroSnapshot(),
    )
    assert snap.realized_vol_20d is not None
    assert snap.realized_vol_20d > 0


def test_build_snapshot_requires_bars():
    import pytest

    with pytest.raises(ValueError):
        build_snapshot(ticker="X", trade_date=date(2026, 5, 1), bars=[], news=[], macro=MacroSnapshot())
