"""ThesisAggregator behavior tests.

Pins how multiple theses combine into a target_pct, and how the macro
regime overlay caps maximum exposure.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from trader.thesis.aggregator import ThesisAggregator
from trader.thesis.taxonomy import THESIS_TABLE, AggregateInputs, Thesis


def _thesis(bucket: str, created_at: datetime | None = None) -> Thesis:
    return Thesis(
        thesis_id=f"th_{uuid.uuid4().hex[:8]}",
        event_id=f"evt_{uuid.uuid4().hex[:8]}",
        template=THESIS_TABLE[bucket],
        created_at=created_at or datetime.now(UTC),
    )


def test_no_theses_returns_baseline():
    agg = ThesisAggregator(baseline_pct=0.5)
    decision = agg.aggregate([], AggregateInputs())
    assert decision.target_pct == 0.5
    assert decision.direction_sum == 0
    assert decision.active_theses == []


def test_single_bullish_high_confidence_thesis_pushes_long():
    agg = ThesisAggregator(baseline_pct=0.5)
    decision = agg.aggregate([_thesis("fed_dovish_surprise")], AggregateInputs(vix=15.0))
    assert decision.target_pct > 0.5
    assert decision.direction_sum > 0
    assert decision.regime_cap == 1.0


def test_single_bearish_high_confidence_thesis_pushes_short():
    agg = ThesisAggregator(baseline_pct=0.5)
    decision = agg.aggregate([_thesis("fed_hawkish_surprise")], AggregateInputs(vix=15.0))
    assert decision.target_pct < 0.5
    assert decision.direction_sum < 0


def test_opposing_theses_cancel_toward_baseline():
    agg = ThesisAggregator(baseline_pct=0.5)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise"), _thesis("fed_hawkish_surprise")],
        AggregateInputs(vix=15.0),
    )
    assert abs(decision.target_pct - 0.5) < 1e-9
    assert decision.direction_sum == 0


def test_expired_theses_excluded_from_active():
    """A thesis whose horizon has passed should appear in expired, not active."""
    agg = ThesisAggregator(baseline_pct=0.5)
    now = datetime.now(UTC)
    old = _thesis("fed_dovish_surprise", created_at=now - timedelta(hours=10))
    fresh = _thesis("fed_hawkish_surprise", created_at=now - timedelta(minutes=5))
    decision = agg.aggregate([old, fresh], AggregateInputs(vix=15.0), now=now)
    assert len(decision.active_theses) == 1
    assert decision.active_theses[0].template.bucket == "fed_hawkish_surprise"
    assert len(decision.expired_theses) == 1


def test_high_vix_caps_position_below_max():
    """VIX > 30 should cap target_pct at vix_stress_cap * max_position_pct."""
    agg = ThesisAggregator(baseline_pct=0.5, max_position_pct=1.0, vix_stress_cap=0.5)
    bull_theses = [_thesis("fed_dovish_surprise") for _ in range(5)]
    decision = agg.aggregate(bull_theses, AggregateInputs(vix=35.0))
    assert decision.target_pct <= 0.5  # capped
    assert decision.regime_cap == 0.5
    assert any("VIX" in r for r in decision.regime_reasons)


def test_deep_curve_inversion_caps_position():
    """10y-2y < -0.5 triggers the inversion cap."""
    agg = ThesisAggregator(baseline_pct=0.5, max_position_pct=1.0, yield_curve_stress_cap=0.5)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise") for _ in range(3)],
        AggregateInputs(vix=15.0, yield_curve_10y_2y=-0.8),
    )
    assert decision.regime_cap == 0.5
    assert any("10y-2y" in r for r in decision.regime_reasons)


def test_realized_vol_stress_caps_position():
    """Realized vol > 2x baseline triggers vol cap. Stay under the 3x
    CRISIS threshold so the cap (not full crisis-flat) is what we see."""
    agg = ThesisAggregator(baseline_pct=0.5, max_position_pct=1.0, realized_vol_stress_cap=0.5)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise") for _ in range(3)],
        AggregateInputs(vix=15.0, realized_vol_20d=0.4),  # 2.67x baseline -> cap, not CRISIS
        baseline_realized_vol=0.15,
    )
    assert decision.regime_cap == 0.5
    assert any("realized_vol" in r for r in decision.regime_reasons)


def test_minimum_of_caps_applies_when_multiple_triggered():
    """If both VIX and curve trigger different caps, the smaller cap wins."""
    agg = ThesisAggregator(
        baseline_pct=0.5,
        max_position_pct=1.0,
        vix_stress_cap=0.4,
        yield_curve_stress_cap=0.7,
    )
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise") for _ in range(3)],
        AggregateInputs(vix=35.0, yield_curve_10y_2y=-0.8),
    )
    assert decision.regime_cap == 0.4  # the stricter of the two
    assert len(decision.regime_reasons) == 2


def test_target_pct_clamped_to_unit_interval():
    """Even with many bullish theses, target_pct must stay in [0, 1]."""
    agg = ThesisAggregator(baseline_pct=0.5)
    decision = agg.aggregate(
        [_thesis("fed_dovish_surprise") for _ in range(20)],
        AggregateInputs(vix=15.0),
    )
    assert 0.0 <= decision.target_pct <= 1.0


def test_deterministic_for_same_inputs():
    agg = ThesisAggregator(baseline_pct=0.5)
    theses = [_thesis("fed_dovish_surprise"), _thesis("megacap_earnings_beat_and_raise")]
    inputs = AggregateInputs(vix=15.0)
    d1 = agg.aggregate(theses, inputs)
    d2 = agg.aggregate(theses, inputs)
    assert d1.target_pct == d2.target_pct
    assert d1.direction_sum == d2.direction_sum
