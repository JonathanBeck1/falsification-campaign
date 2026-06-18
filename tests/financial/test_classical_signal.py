"""ClassicalBrain tests — verifies deterministic regime logic."""

from __future__ import annotations

from datetime import UTC, date, datetime

from trader.signals.classical import ClassicalBrain
from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot


def make_snapshot(
    *,
    price: float = 500.0,
    sma200: float | None = 480.0,
    rsi: float | None = 55.0,
    vix: float | None = 18.0,
    curve: float | None = 0.5,
) -> DailySnapshot:
    bar = Bar(
        timestamp=datetime.now(UTC),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=1_000_000,
    )
    return DailySnapshot(
        snapshot_id="test",
        trade_date=date.today(),
        ticker="TEST",
        latest_bar=bar,
        recent_bars=[bar],
        sma_50=None,
        sma_200=sma200,
        rsi_14=rsi,
        realized_vol_20d=0.15,
        news=[],
        macro=MacroSnapshot(vix=vix, yield_curve_10y_2y=curve),
    )


def test_clean_uptrend_goes_long():
    d = ClassicalBrain().decide(make_snapshot(price=500, sma200=480, rsi=55, vix=15))
    assert d.action == "BUY"
    assert d.target_pct == 1.0


def test_downtrend_goes_flat():
    d = ClassicalBrain().decide(make_snapshot(price=450, sma200=480))
    assert d.action == "SELL"
    assert d.target_pct == 0.0


def test_high_vix_caps_at_30pct():
    d = ClassicalBrain().decide(make_snapshot(vix=35))
    assert d.action == "SELL"
    assert d.target_pct == 0.30


def test_overbought_trims_to_half():
    d = ClassicalBrain().decide(make_snapshot(rsi=80))
    assert d.action == "SELL"
    assert d.target_pct == 0.5


def test_inverted_curve_defensive():
    d = ClassicalBrain().decide(make_snapshot(curve=-0.7))
    assert d.action == "SELL"
    assert d.target_pct == 0.30


def test_insufficient_history_holds():
    d = ClassicalBrain().decide(make_snapshot(sma200=None))
    assert d.action == "HOLD"


def test_high_vix_overrides_uptrend():
    """Crisis regime should take precedence over a bullish trend."""
    d = ClassicalBrain().decide(make_snapshot(price=500, sma200=480, rsi=55, vix=35))
    assert d.target_pct == 0.30
