"""Pacing-clip tests (audit problem #13).

The aggregator caps how far `target_pct` can move from the prior cycle's
target in one step. Closes the second half of the averaging-down
spiral protection (the first half — drawdown freeze — landed in
PR #35's RiskGate).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from trader.thesis.aggregator import ThesisAggregator
from trader.thesis.taxonomy import THESIS_TABLE, AggregateInputs, Thesis


def _thesis(bucket: str, created_at: datetime | None = None) -> Thesis:
    return Thesis(
        thesis_id=f"th_{uuid.uuid4().hex[:8]}",
        event_id=f"evt_{uuid.uuid4().hex[:8]}",
        template=THESIS_TABLE[bucket],
        created_at=created_at or datetime.now(UTC),
    )


# ── No prior target ──────────────────────────────────────────────────────


def test_no_prior_target_skips_pacing_check():
    """First cycle of the day -- no prior target -> no clip, no flag."""
    agg = ThesisAggregator(baseline_pct=0.5, max_target_change_per_cycle=0.20)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise") for _ in range(3)],
        AggregateInputs(vix=15.0),
        prior_target_pct=None,
    )
    assert decision.pacing_clipped is False


# ── Clipped when above range ─────────────────────────────────────────────


def test_clip_caps_increase_to_prior_plus_max_change():
    """Prior target 0.3; aggregator wants 0.8; max_change 0.20.
    Should clip to 0.30 + 0.20 = 0.50."""
    agg = ThesisAggregator(baseline_pct=0.5, max_target_change_per_cycle=0.20)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise") for _ in range(5)],
        AggregateInputs(vix=15.0),
        prior_target_pct=0.30,
    )
    assert decision.pacing_clipped is True
    assert decision.target_pct == 0.50
    assert any("pacing_clip" in r for r in decision.regime_reasons)


def test_clip_caps_decrease_to_prior_minus_max_change():
    """Prior target 0.8; aggregator wants 0.1; max_change 0.20.
    Should clip to 0.80 - 0.20 = 0.60."""
    agg = ThesisAggregator(baseline_pct=0.5, max_target_change_per_cycle=0.20)
    decision = agg.aggregate(
        [_thesis("fed_hawkish_surprise") for _ in range(5)],
        AggregateInputs(vix=15.0),
        prior_target_pct=0.80,
    )
    assert decision.pacing_clipped is True
    assert decision.target_pct == 0.60


# ── Allowed when within range ────────────────────────────────────────────


def test_change_within_range_passes_unchanged():
    """Prior target 0.5; aggregator wants 0.55. Delta 0.05 << 0.20 cap."""
    agg = ThesisAggregator(baseline_pct=0.5, max_target_change_per_cycle=0.20)
    decision = agg.aggregate(
        [_thesis("megacap_earnings_beat_flat_guide")],  # small thesis
        AggregateInputs(vix=15.0),
        prior_target_pct=0.50,
    )
    assert decision.pacing_clipped is False


def test_change_exactly_at_max_is_allowed():
    """Edge case: delta exactly equals max_change. Should NOT clip
    (the clip fires only on strict-greater-than)."""
    agg = ThesisAggregator(baseline_pct=0.5, max_target_change_per_cycle=0.20)
    # Manually construct: with 5 fed_dovish, baseline 0.5, the raw
    # target would be > 0.5. We need to find a setup where the delta
    # is exactly 0.20. Easiest: set prior_target to (raw_target - 0.20).
    raw_decision = agg.aggregate(
        [_thesis("fed_dovish_surprise") for _ in range(5)],
        AggregateInputs(vix=15.0),
        prior_target_pct=None,
    )
    raw_target = raw_decision.target_pct
    prior = raw_target - 0.20
    # With this prior, delta is exactly 0.20; clip should NOT fire.
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise") for _ in range(5)],
        AggregateInputs(vix=15.0),
        prior_target_pct=prior,
    )
    assert decision.pacing_clipped is False
    assert decision.target_pct == raw_target


# ── Direction-flip with pacing ───────────────────────────────────────────


def test_clip_prevents_full_flip_in_one_cycle():
    """Going from full-long (0.9) to full-flat (0.0) in one cycle would
    cross the entire range. With max_change=0.20, we only move to 0.70."""
    agg = ThesisAggregator(baseline_pct=0.5, max_target_change_per_cycle=0.20)
    decision = agg.aggregate(
        [_thesis("fed_hawkish_surprise") for _ in range(5)],
        AggregateInputs(vix=15.0),
        prior_target_pct=0.90,
    )
    assert decision.target_pct == 0.70
    assert decision.pacing_clipped


# ── Interaction with regime cap (CRISIS) ─────────────────────────────────


def test_crisis_regime_overrides_pacing_clip():
    """CRISIS forces flat. Pacing-clip is not applied in CRISIS — the
    crisis-flat code path returns before the clip check."""
    agg = ThesisAggregator(baseline_pct=0.5, max_target_change_per_cycle=0.20)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise") for _ in range(5)],
        AggregateInputs(vix=40.0),  # CRISIS
        prior_target_pct=0.90,
    )
    # CRISIS goes to 0.0 regardless of pacing
    assert decision.target_pct == 0.0
    assert decision.regime_tag == "CRISIS"
    assert decision.pacing_clipped is False  # didn't even reach pacing


# ── Interaction with holding-period lock ─────────────────────────────────


def test_pacing_clip_runs_before_holding_lock():
    """Aggregator pacing happens first; holding-period lock then checks
    whether the *clipped* target would still flip the position."""
    agg = ThesisAggregator(
        baseline_pct=0.5, max_target_change_per_cycle=0.20, min_holding_minutes=15
    )
    now = datetime.now(UTC)
    bear = [_thesis("fed_hawkish_surprise") for _ in range(5)]
    decision = agg.aggregate(
        bear,
        AggregateInputs(vix=15.0),
        now=now,
        prior_target_pct=0.80,
        current_position_pct=0.80,
        position_opened_at=now,  # fresh position
    )
    # Pacing clips 0.80 -> 0.60 (delta -0.20 max)
    # 0.60 > 0.5 baseline = still long-side -> no holding flip -> no lock
    assert decision.pacing_clipped is True
    assert decision.target_pct == 0.60
    assert decision.holding_period_locked is False


# ── Configuration ────────────────────────────────────────────────────────


def test_max_change_setting_of_one_effectively_disables_clip():
    """max_target_change_per_cycle=1.0 means 'no cap' (a 100pp jump
    is allowed)."""
    agg = ThesisAggregator(baseline_pct=0.5, max_target_change_per_cycle=1.0)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise") for _ in range(5)],
        AggregateInputs(vix=15.0),
        prior_target_pct=0.0,
    )
    # Even with prior at 0, the raw target is allowed.
    assert decision.pacing_clipped is False


def test_constructor_rejects_zero_or_negative_max_change():
    """0 or negative max_change is nonsensical and would brick the system."""
    with pytest.raises(ValueError, match="max_target_change_per_cycle"):
        ThesisAggregator(max_target_change_per_cycle=0.0)
    with pytest.raises(ValueError, match="max_target_change_per_cycle"):
        ThesisAggregator(max_target_change_per_cycle=-0.1)


def test_constructor_rejects_max_change_above_one():
    with pytest.raises(ValueError, match="max_target_change_per_cycle"):
        ThesisAggregator(max_target_change_per_cycle=1.5)


def test_custom_smaller_max_change_clips_tighter():
    """A user setting max_change=0.05 should see tighter clips."""
    agg = ThesisAggregator(baseline_pct=0.5, max_target_change_per_cycle=0.05)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise") for _ in range(5)],
        AggregateInputs(vix=15.0),
        prior_target_pct=0.50,
    )
    # Aggressive bullish theses would push toward 1.0; clipped to 0.55
    assert decision.target_pct == 0.55
    assert decision.pacing_clipped is True


# ── Determinism ──────────────────────────────────────────────────────────


def test_deterministic_with_prior_target():
    """Same inputs (including prior_target_pct) -> same output."""
    agg = ThesisAggregator()
    theses = [_thesis("fed_dovish_surprise")]
    inputs = AggregateInputs(vix=15.0)
    d1 = agg.aggregate(theses, inputs, prior_target_pct=0.3)
    d2 = agg.aggregate(theses, inputs, prior_target_pct=0.3)
    assert d1.target_pct == d2.target_pct
    assert d1.pacing_clipped == d2.pacing_clipped
