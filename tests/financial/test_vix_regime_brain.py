"""VIXRegimeBrain deterministic threshold tests.

Covers every band of both Conservative and Aggressive profiles, the missing-VIX
fallback, edge values at band boundaries, constructor validation, and
deterministic behavior. Per brain/decisions/2026-05-21-horse-race-phase-1.md.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from trader.signals.vix_regime import (
    AGGRESSIVE_CRISIS_TARGET,
    CONSERVATIVE_CRISIS_TARGET,
    THRESHOLDS_AGGRESSIVE,
    THRESHOLDS_CONSERVATIVE,
    VIXRegimeBrain,
    VIXThresholdBand,
    vix_regime_aggressive,
    vix_regime_conservative,
)
from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot


def _snapshot(vix: float | None) -> DailySnapshot:
    bar = Bar(
        timestamp=datetime(2026, 5, 18, 20, 0, tzinfo=UTC),
        open=400.0,
        high=400.0,
        low=400.0,
        close=400.0,
        volume=1_000_000,
    )
    return DailySnapshot(
        snapshot_id="vix-test",
        trade_date=date(2026, 5, 18),
        ticker="QQQ",
        latest_bar=bar,
        recent_bars=[bar],
        sma_50=400.0,
        sma_200=400.0,
        rsi_14=50.0,
        realized_vol_20d=0.1,
        news=[],
        macro=MacroSnapshot(vix=vix),
    )


# ── Conservative profile ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "vix,expected_target",
    [
        (5.0, 1.00),   # well below 13
        (12.9, 1.00),  # just below 13
        (13.0, 0.70),  # at 13 boundary -> next band
        (15.0, 0.70),
        (16.99, 0.70),
        (17.0, 0.40),  # at 17 boundary
        (20.0, 0.40),
        (22.0, 0.20),  # at 22 boundary
        (25.0, 0.20),
        (27.99, 0.20),
        (28.0, 0.00),  # crisis floor
        (40.0, 0.00),  # well above crisis
    ],
)
def test_conservative_thresholds(vix: float, expected_target: float):
    brain = vix_regime_conservative()
    decision = brain.decide(_snapshot(vix=vix))
    assert decision.target_pct == expected_target, f"VIX={vix} -> {decision.target_pct}"


# ── Aggressive profile ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "vix,expected_target",
    [
        (10.0, 1.00),
        (17.99, 1.00),
        (18.0, 0.70),  # at 18 boundary
        (24.0, 0.70),
        (24.99, 0.70),
        (25.0, 0.40),  # at 25 boundary
        (30.0, 0.40),
        (31.99, 0.40),
        (32.0, 0.00),  # crisis floor (later than Conservative)
        (50.0, 0.00),
    ],
)
def test_aggressive_thresholds(vix: float, expected_target: float):
    brain = vix_regime_aggressive()
    decision = brain.decide(_snapshot(vix=vix))
    assert decision.target_pct == expected_target


# ── Missing data ─────────────────────────────────────────────────────────


def test_missing_vix_returns_hold():
    brain = vix_regime_conservative()
    decision = brain.decide(_snapshot(vix=None))
    assert decision.action == "HOLD"
    assert decision.confidence < 0.5
    assert "VIX missing" in decision.reasoning


# ── Action assignment ────────────────────────────────────────────────────


def test_full_target_emits_buy():
    decision = vix_regime_conservative().decide(_snapshot(vix=10.0))
    assert decision.action == "BUY"
    assert decision.target_pct == 1.00


def test_zero_target_emits_sell():
    decision = vix_regime_conservative().decide(_snapshot(vix=35.0))
    assert decision.action == "SELL"
    assert decision.target_pct == 0.00


def test_mid_band_emits_buy_so_fresh_portfolio_reaches_target():
    decision = vix_regime_conservative().decide(_snapshot(vix=15.0))
    assert decision.action == "BUY"
    assert decision.target_pct == 0.70


# ── Determinism ──────────────────────────────────────────────────────────


def test_deterministic_same_inputs_same_output():
    snap = _snapshot(vix=20.0)
    d1 = vix_regime_conservative().decide(snap)
    d2 = vix_regime_conservative().decide(snap)
    assert d1.target_pct == d2.target_pct
    assert d1.action == d2.action
    assert d1.reasoning == d2.reasoning


# ── Constructor / config validation ──────────────────────────────────────


def test_constructor_rejects_empty_thresholds():
    with pytest.raises(ValueError, match="non-empty"):
        VIXRegimeBrain(thresholds=(), crisis_target=0.0, name="x")


def test_constructor_rejects_non_ascending_thresholds():
    with pytest.raises(ValueError, match="ascending"):
        VIXRegimeBrain(
            thresholds=(VIXThresholdBand(vix_lt=20.0, target_pct=0.5), VIXThresholdBand(vix_lt=10.0, target_pct=0.3)),
            crisis_target=0.0,
            name="x",
        )


def test_constructor_rejects_target_out_of_range():
    with pytest.raises(ValueError, match=r"target_pct must be in \[0, 1\]"):
        VIXRegimeBrain(
            thresholds=(VIXThresholdBand(vix_lt=20.0, target_pct=1.5),),
            crisis_target=0.0,
            name="x",
        )


def test_constructor_rejects_crisis_target_out_of_range():
    with pytest.raises(ValueError, match=r"crisis_target must be in \[0, 1\]"):
        VIXRegimeBrain(
            thresholds=(VIXThresholdBand(vix_lt=20.0, target_pct=0.5),),
            crisis_target=-0.1,
            name="x",
        )


def test_profile_constants_are_sensible():
    # Conservative de-risks earlier (lower top band) than Aggressive
    assert THRESHOLDS_CONSERVATIVE[-1].vix_lt < THRESHOLDS_AGGRESSIVE[-1].vix_lt
    assert CONSERVATIVE_CRISIS_TARGET == 0.0
    assert AGGRESSIVE_CRISIS_TARGET == 0.0
