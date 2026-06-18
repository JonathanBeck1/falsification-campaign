"""Aggregator extensions: regime classification, net-edge filter,
min-holding-period lock.

Covers audit problems #7 (overfitting / regime detection) and #8
(transaction costs / churn prevention).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from trader.thesis.aggregator import ThesisAggregator, classify_regime
from trader.thesis.taxonomy import THESIS_TABLE, AggregateInputs, Thesis


def _thesis(bucket: str, created_at: datetime | None = None) -> Thesis:
    return Thesis(
        thesis_id=f"th_{uuid.uuid4().hex[:8]}",
        event_id=f"evt_{uuid.uuid4().hex[:8]}",
        template=THESIS_TABLE[bucket],
        created_at=created_at or datetime.now(UTC),
    )


# ── Regime classification ─────────────────────────────────────────────────


def test_low_vol_regime_when_vix_below_15_and_curve_positive():
    inputs = AggregateInputs(vix=12.0, yield_curve_10y_2y=0.3)
    assert classify_regime(inputs).tag == "LOW_VOL"


def test_normal_regime_when_no_stress_signals():
    inputs = AggregateInputs(vix=18.0, yield_curve_10y_2y=0.1)
    assert classify_regime(inputs).tag == "NORMAL"


def test_high_vol_regime_when_vix_above_25():
    inputs = AggregateInputs(vix=28.0, yield_curve_10y_2y=0.0)
    assert classify_regime(inputs).tag == "HIGH_VOL"


def test_high_vol_regime_when_curve_inverted_below_threshold():
    inputs = AggregateInputs(vix=18.0, yield_curve_10y_2y=-0.6)
    assert classify_regime(inputs).tag == "HIGH_VOL"


def test_crisis_regime_when_vix_above_35():
    inputs = AggregateInputs(vix=40.0, yield_curve_10y_2y=-0.1)
    r = classify_regime(inputs)
    assert r.tag == "CRISIS"
    assert any("vix" in reason for reason in r.reasons)


def test_crisis_regime_when_realized_vol_spikes_above_3x_baseline():
    inputs = AggregateInputs(vix=20.0, realized_vol_20d=0.6)
    r = classify_regime(inputs, baseline_realized_vol=0.15)
    assert r.tag == "CRISIS"


def test_regime_classification_returns_reasons_for_audit():
    inputs = AggregateInputs(vix=40.0)
    r = classify_regime(inputs)
    assert len(r.reasons) > 0


# ── CRISIS regime forces flat ─────────────────────────────────────────────


def test_crisis_regime_forces_target_to_zero_even_with_bullish_theses():
    agg = ThesisAggregator(baseline_pct=0.5)
    bull = [_thesis("fed_dovish_surprise") for _ in range(5)]
    decision = agg.aggregate(bull, AggregateInputs(vix=40.0))
    assert decision.target_pct == 0.0
    assert decision.regime_tag == "CRISIS"
    assert decision.regime_cap == 0.0


def test_crisis_regime_target_zero_even_with_bearish_theses():
    """CRISIS means flat, not short. We don't take leveraged-short
    positions during black swans; capital preservation."""
    agg = ThesisAggregator(baseline_pct=0.5)
    bear = [_thesis("fed_hawkish_surprise") for _ in range(5)]
    decision = agg.aggregate(bear, AggregateInputs(vix=40.0))
    assert decision.target_pct == 0.0
    assert decision.regime_tag == "CRISIS"


# ── Regime tag exposed in normal output ───────────────────────────────────


def test_regime_tag_in_decision_for_low_vol():
    agg = ThesisAggregator(baseline_pct=0.5)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise")],
        AggregateInputs(vix=12.0, yield_curve_10y_2y=0.5),
    )
    assert decision.regime_tag == "LOW_VOL"


def test_regime_tag_in_decision_for_high_vol():
    agg = ThesisAggregator(baseline_pct=0.5)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise")],
        AggregateInputs(vix=28.0),
    )
    assert decision.regime_tag == "HIGH_VOL"


# ── Net-edge / cost filter ────────────────────────────────────────────────


def test_thesis_below_cost_threshold_is_zeroed():
    """A thesis whose expected_magnitude_pct is below the round-trip
    cost should be filtered out, not contribute to direction_sum."""
    agg = ThesisAggregator(baseline_pct=0.5, round_trip_cost_pct=1.0)
    # All thesis templates have magnitudes <1.0% except geopol_escalation_major
    decision = agg.aggregate(
        [_thesis("megacap_earnings_beat_flat_guide")],  # 0.2% expected
        AggregateInputs(vix=15.0),
    )
    assert decision.direction_sum == 0
    assert len(decision.cost_filtered_theses) == 1
    assert len(decision.active_theses) == 0
    assert decision.target_pct == decision.baseline_pct


def test_thesis_above_cost_threshold_passes_filter():
    agg = ThesisAggregator(baseline_pct=0.5, round_trip_cost_pct=0.05)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise")],  # 0.7% expected
        AggregateInputs(vix=15.0),
    )
    assert decision.direction_sum > 0
    assert len(decision.cost_filtered_theses) == 0
    assert decision.target_pct > decision.baseline_pct


def test_cost_filter_only_zeroes_marginal_theses_not_all():
    """Mixed: one strong, one marginal. Only the marginal one is filtered."""
    agg = ThesisAggregator(baseline_pct=0.5, round_trip_cost_pct=0.25)
    decision = agg.aggregate(
        [
            _thesis("fed_dovish_surprise"),  # 0.7% > 0.25%, passes
            _thesis("megacap_earnings_beat_flat_guide"),  # 0.2% < 0.25%, filtered
        ],
        AggregateInputs(vix=15.0),
    )
    assert len(decision.active_theses) == 1
    assert len(decision.cost_filtered_theses) == 1


# ── Min-holding-period lock ───────────────────────────────────────────────


def test_holding_period_lock_prevents_flip_inside_window():
    """Position opened 5 min ago, aggregator now wants to flip — lock holds."""
    agg = ThesisAggregator(baseline_pct=0.5, min_holding_minutes=15)
    now = datetime.now(UTC)
    bear = [_thesis("fed_hawkish_surprise") for _ in range(3)]  # would go short
    decision = agg.aggregate(
        bear,
        AggregateInputs(vix=15.0),
        now=now,
        current_position_pct=0.8,  # currently long
        position_opened_at=now - timedelta(minutes=5),
    )
    # Locked at 0.8, didn't flip to short
    assert decision.target_pct == 0.8
    assert decision.holding_period_locked is True
    assert any("holding_period_lock" in r for r in decision.regime_reasons)


def test_holding_period_lock_allows_same_side_size_change():
    """Already long; new theses make us even more bullish. Lock does NOT
    prevent size adjustments on the same side."""
    agg = ThesisAggregator(baseline_pct=0.5, min_holding_minutes=15)
    now = datetime.now(UTC)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise") for _ in range(3)],
        AggregateInputs(vix=15.0),
        now=now,
        current_position_pct=0.6,
        position_opened_at=now - timedelta(minutes=5),
    )
    # New target > 0.5 (same side as current 0.6 > 0.5) — lock doesn't fire
    assert decision.holding_period_locked is False
    assert decision.target_pct >= decision.baseline_pct


def test_holding_period_lock_doesnt_fire_after_window_expires():
    agg = ThesisAggregator(baseline_pct=0.5, min_holding_minutes=15)
    now = datetime.now(UTC)
    bear = [_thesis("fed_hawkish_surprise") for _ in range(3)]
    decision = agg.aggregate(
        bear,
        AggregateInputs(vix=15.0),
        now=now,
        current_position_pct=0.8,
        position_opened_at=now - timedelta(minutes=30),  # past lock
    )
    assert decision.target_pct < 0.8
    assert decision.holding_period_locked is False


def test_holding_period_with_no_current_position_skipped():
    """If we don't have a current_position_pct, the lock has nothing to
    enforce — the new target applies unchanged."""
    agg = ThesisAggregator(baseline_pct=0.5, min_holding_minutes=15)
    decision = agg.aggregate(
        [_thesis("fed_hawkish_surprise")],
        AggregateInputs(vix=15.0),
        now=datetime.now(UTC),
        current_position_pct=None,
        position_opened_at=None,
    )
    assert decision.holding_period_locked is False


# ── Notes / observability ─────────────────────────────────────────────────


def test_note_includes_regime_tag():
    agg = ThesisAggregator()
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise")],
        AggregateInputs(vix=15.0, yield_curve_10y_2y=0.3),
    )
    assert "regime=" in decision.note


def test_note_lists_cost_filtered_count_when_any():
    agg = ThesisAggregator(baseline_pct=0.5, round_trip_cost_pct=1.0)
    decision = agg.aggregate(
        [_thesis("megacap_earnings_beat_flat_guide")],
        AggregateInputs(vix=15.0),
    )
    assert "theses_cost_filtered=1" in decision.note


# ── Compatibility with existing aggregator behavior ───────────────────────


def test_empty_theses_still_returns_baseline():
    """Regression: no theses → baseline, regardless of new fields."""
    agg = ThesisAggregator(baseline_pct=0.5)
    decision = agg.aggregate([], AggregateInputs())
    assert decision.target_pct == 0.5
    assert decision.regime_tag in {"LOW_VOL", "NORMAL", "HIGH_VOL", "CRISIS"}


def test_deterministic_for_same_inputs():
    """Regression: same inputs → same outputs even with new fields."""
    agg = ThesisAggregator()
    theses = [_thesis("fed_dovish_surprise")]
    inputs = AggregateInputs(vix=15.0, yield_curve_10y_2y=0.3)
    d1 = agg.aggregate(theses, inputs)
    d2 = agg.aggregate(theses, inputs)
    assert d1.target_pct == d2.target_pct
    assert d1.regime_tag == d2.regime_tag
