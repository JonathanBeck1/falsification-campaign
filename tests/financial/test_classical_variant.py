"""ClassicalBrain variant tests — Conservative + Aggressive dial behavior.

Pins that the Phase 4 constructor kwargs actually flow into decision logic
(not just stored) and that the factory helpers set the expected dial values.
See `brain/decisions/2026-05-21-horse-race-phase-4.md`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from trader.signals.classical import (
    ClassicalBrain,
    classical_aggressive,
    classical_conservative,
)
from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot


def _snapshot(
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
        ticker="QQQ",
        latest_bar=bar,
        recent_bars=[bar],
        sma_50=None,
        sma_200=sma200,
        rsi_14=rsi,
        realized_vol_20d=0.15,
        news=[],
        macro=MacroSnapshot(vix=vix, yield_curve_10y_2y=curve),
    )


# ── Conservative dial behavior ──────────────────────────────────────────────


def test_conservative_requires_sma_buffer():
    """Price exactly at SMA200 must NOT trigger BUY when sma_buffer_pct > 0."""
    brain = classical_conservative()
    decision = brain.decide(_snapshot(price=480.0, sma200=480.0, rsi=55, vix=15))
    assert decision.action != "BUY"


def test_conservative_buys_when_clear_buffer():
    """Price above SMA200 by > 1% should pass the buffer and BUY at long_target=0.70."""
    brain = classical_conservative()
    decision = brain.decide(_snapshot(price=500.0, sma200=480.0, rsi=55, vix=15))
    assert decision.action == "BUY"
    assert decision.target_pct == 0.70


def test_conservative_trims_at_rsi_65():
    """Conservative rsi_overbought=65 should trip where default 75 wouldn't."""
    brain = classical_conservative()
    decision = brain.decide(_snapshot(price=500.0, sma200=480.0, rsi=70.0, vix=15))
    assert decision.action == "SELL"
    assert decision.target_pct == 0.30


def test_conservative_flat_at_vix_25():
    """Conservative goes flat (target=0.0) when VIX > 25."""
    brain = classical_conservative()
    decision = brain.decide(_snapshot(vix=26.0))
    assert decision.action == "SELL"
    assert decision.target_pct == 0.0


def test_conservative_flat_at_curve_minus_25():
    """Conservative reacts to shallower curve inversions (curve < -0.25)."""
    brain = classical_conservative()
    decision = brain.decide(_snapshot(curve=-0.3))
    assert decision.action == "SELL"
    assert decision.target_pct == 0.0


# ── Aggressive dial behavior ────────────────────────────────────────────────


def test_aggressive_long_target_full():
    """Aggressive long_target stays at 1.0."""
    brain = classical_aggressive()
    decision = brain.decide(_snapshot(price=500.0, sma200=480.0, rsi=55, vix=15))
    assert decision.action == "BUY"
    assert decision.target_pct == 1.0


def test_aggressive_tolerates_rsi_70():
    """Aggressive rsi_overbought=80 should NOT trip at RSI=70."""
    brain = classical_aggressive()
    decision = brain.decide(_snapshot(price=500.0, sma200=480.0, rsi=70.0, vix=15))
    assert decision.action == "BUY"


def test_aggressive_trims_at_rsi_82():
    """Aggressive rsi_overbought=80 trips at RSI > 80, trims to 0.7."""
    brain = classical_aggressive()
    decision = brain.decide(_snapshot(price=500.0, sma200=480.0, rsi=82.0, vix=15))
    assert decision.action == "SELL"
    assert decision.target_pct == 0.7


def test_aggressive_holds_vix_28():
    """Aggressive vix_crisis_threshold=35, so VIX=28 should not trigger crisis mode."""
    brain = classical_aggressive()
    decision = brain.decide(_snapshot(vix=28.0))
    # Not a crisis: should pass through to normal decision (BUY at long_target=1.0)
    assert decision.action == "BUY"
    assert decision.target_pct == 1.0


def test_aggressive_curve_default_unchanged():
    """Aggressive uses default curve_inversion_threshold = -0.5."""
    brain = classical_aggressive()
    decision = brain.decide(_snapshot(curve=-0.3))
    # -0.3 > -0.5, so no curve trigger; passes through to normal
    assert decision.action == "BUY"


# ── Factory helpers wire expected dial values ───────────────────────────────


def test_classical_conservative_factory_values():
    brain = classical_conservative(name="X")
    assert brain.name == "X"
    assert brain._sma_buffer_pct == 0.01
    assert brain._rsi_overbought == 65.0
    assert brain._rsi_overbought_target == 0.30
    assert brain._vix_crisis_threshold == 25.0
    assert brain._vix_crisis_target == 0.0
    assert brain._curve_inversion_threshold == -0.25
    assert brain._curve_inversion_target == 0.0
    assert brain._long_target == 0.70


def test_classical_aggressive_factory_values():
    brain = classical_aggressive(name="Y")
    assert brain.name == "Y"
    assert brain._rsi_overbought == 80.0
    assert brain._rsi_overbought_target == 0.7
    assert brain._vix_crisis_threshold == 35.0
    # Other knobs default
    assert brain._sma_buffer_pct == 0.0
    assert brain._long_target == 1.0


# ── Constructor validation ──────────────────────────────────────────────────


def test_negative_sma_buffer_rejected():
    with pytest.raises(ValueError, match="sma_buffer_pct"):
        ClassicalBrain(sma_buffer_pct=-0.01)


@pytest.mark.parametrize("bad", [0.0, 100.0, -10.0, 150.0])
def test_rsi_overbought_out_of_range_rejected(bad: float):
    with pytest.raises(ValueError, match="rsi_overbought"):
        ClassicalBrain(rsi_overbought=bad)


@pytest.mark.parametrize("bad", [-0.1, 1.1, -5.0, 5.0])
def test_target_pct_out_of_range_rejected(bad: float):
    with pytest.raises(ValueError, match="long_target"):
        ClassicalBrain(long_target=bad)


def test_vix_threshold_zero_rejected():
    with pytest.raises(ValueError, match="vix_crisis_threshold"):
        ClassicalBrain(vix_crisis_threshold=0.0)


# ── Backward-compat: default constructor preserves original behavior ────────


def test_default_constructor_matches_original_hardcoded_behavior():
    """Calling ClassicalBrain() with no kwargs should produce the same
    decisions as the pre-Phase-4 implementation."""
    brain = ClassicalBrain()
    # Original would BUY at 1.0 here.
    decision = brain.decide(_snapshot(price=500.0, sma200=480.0, rsi=55, vix=15))
    assert decision.action == "BUY"
    assert decision.target_pct == 1.0
    # Original trimmed to 0.5 at RSI > 75.
    decision = brain.decide(_snapshot(rsi=76.0))
    assert decision.action == "SELL"
    assert decision.target_pct == 0.5
    # Original defensive 0.30 at VIX > 30.
    decision = brain.decide(_snapshot(vix=31.0))
    assert decision.target_pct == 0.30
    # Original flat at curve < -0.5.
    decision = brain.decide(_snapshot(curve=-0.6))
    assert decision.target_pct == 0.30
