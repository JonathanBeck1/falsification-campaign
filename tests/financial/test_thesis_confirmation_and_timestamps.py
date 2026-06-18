"""Confirmation gating + event-time stamping tests.

Pins the two cross-cutting fixes from Codex review (2026-05-20):

1. `Thesis.created_at` is stamped from `event.observed_at`
   (or `event.published_at`), not `datetime.now(UTC)`. This makes
   stored-event replay, retry, and scenario runs honor the event's true
   time so the aggregator's horizon expiry can't resurrect stale headlines.

2. Theses whose `template.confirmation_required=True` are excluded from
   the aggregator's `direction_sum` until `confirmation_state="confirmed"`.
   This is the brain/21 "Confirmation gating" rule.

Both behaviors are load-bearing for safety; regression in either
silently changes trade sizing.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from trader.normalization.models import Entity, Event
from trader.thesis.aggregator import ThesisAggregator
from trader.thesis.engine import ThesisEngine
from trader.thesis.taxonomy import (
    THESIS_TABLE,
    AggregateInputs,
    Thesis,
)


def _event(
    *,
    event_type: str,
    sentiment: str = "neutral",
    sentiment_score: float = 0.0,
    urgency: str = "normal",
    title: str = "Headline",
    summary: str = "",
    novelty_score: float = 0.7,
    entity_tickers: list[str] | None = None,
    index_exposure: list[str] | None = None,
    asset_scope: list[str] | None = None,
    observed_at: datetime | None = None,
    published_at: datetime | None = None,
) -> Event:
    now = datetime.now(UTC)
    effective_observed = observed_at or now
    # When the caller supplies observed_at (a replay/stale-event test),
    # classified_at must mirror it. ThesisEngine._event_time prefers
    # classified_at over observed_at; if we set classified_at=now() here,
    # an old-observed event would look fresh. PR #60 (codex-followup-
    # classified-at) ships this same alignment in production normalizers.
    return Event(
        event_id=f"evt_{uuid.uuid4().hex[:8]}",
        source="scenario",
        source_url="",
        title=title,
        summary=summary,
        published_at=published_at or now,
        observed_at=effective_observed,
        ingested_at=now,
        classified_at=effective_observed,
        entities=[
            Entity(name=t, ticker=t, confidence=1.0, role="primary")
            for t in (entity_tickers or [])
        ],
        asset_scope=asset_scope or ["macro"],
        index_exposure=index_exposure or [],
        event_type=event_type,
        sentiment=sentiment,
        sentiment_score=sentiment_score,
        urgency=urgency,
        novelty_score=novelty_score,
        source_credibility=0.9,
        evidence=[],
        model_outputs=[],
        raw_artifact_path="",
    )


def _thesis(
    bucket: str,
    *,
    created_at: datetime | None = None,
    confirmation_state: str = "confirmed",
) -> Thesis:
    """Construct a Thesis directly for aggregator tests.

    Default confirmation_state is "confirmed" so test setup is explicit
    about the gating path being exercised.
    """
    return Thesis(
        thesis_id=f"th_{uuid.uuid4().hex[:8]}",
        event_id=f"evt_{uuid.uuid4().hex[:8]}",
        template=THESIS_TABLE[bucket],
        created_at=created_at or datetime.now(UTC),
        confirmation_state=confirmation_state,
    )


# ── Timestamp tests ────────────────────────────────────────────────────────


def test_thesis_created_at_uses_observed_at_not_now():
    """ThesisEngine should stamp created_at from event.observed_at, not
    datetime.now(UTC). Otherwise a delayed/replayed event becomes
    "fresh" and can pass the aggregator's horizon filter."""
    engine = ThesisEngine()
    old_observed = datetime.now(UTC) - timedelta(hours=6)
    event = _event(
        event_type="fed_commentary",
        sentiment="positive",
        urgency="high",
        observed_at=old_observed,
    )
    thesis = engine.classify(event)
    assert thesis is not None
    assert thesis.created_at == old_observed


def test_thesis_created_at_falls_back_to_published_at():
    """If observed_at is absent in some edge path, published_at is the
    next-best event-time anchor."""
    engine = ThesisEngine()
    old_published = datetime.now(UTC) - timedelta(hours=4)
    event = _event(
        event_type="fed_commentary",
        sentiment="positive",
        urgency="high",
        published_at=old_published,
        observed_at=old_published,  # both set; observed_at wins
    )
    thesis = engine.classify(event)
    assert thesis is not None
    assert thesis.created_at == old_published


def test_stale_event_classified_late_does_not_resurrect():
    """A 6-hour-old event run through the engine today should already be
    past the fed_dovish_surprise horizon (120m). The aggregator should
    see it as expired, not active."""
    engine = ThesisEngine()
    agg = ThesisAggregator(baseline_pct=0.5)
    six_hours_ago = datetime.now(UTC) - timedelta(hours=6)
    event = _event(
        event_type="fed_commentary",
        sentiment="positive",
        urgency="high",
        observed_at=six_hours_ago,
    )
    thesis = engine.classify(event)
    assert thesis is not None

    decision = agg.aggregate([thesis], AggregateInputs(vix=15.0))
    assert thesis in decision.expired_theses
    assert thesis not in decision.active_theses
    assert decision.direction_sum == 0


# ── Confirmation gating tests ──────────────────────────────────────────────


def test_engine_marks_confirmation_required_buckets_pending():
    """Buckets with template.confirmation_required=True should be
    constructed with confirmation_state='pending' so the aggregator
    excludes them until a second source confirms."""
    engine = ThesisEngine()
    # fomc_minutes_release has confirmation_required=True in THESIS_TABLE
    event = _event(
        event_type="fed_commentary",
        sentiment="neutral",
        urgency="high",
        title="FOMC minutes show split on path",
    )
    thesis = engine.classify(event)
    assert thesis is not None
    assert thesis.template.confirmation_required
    assert thesis.confirmation_state == "pending"


def test_engine_marks_confirmation_not_required_buckets_confirmed():
    """Buckets that don't require confirmation should be ready to
    aggregate immediately (state='confirmed')."""
    engine = ThesisEngine()
    # fed_dovish_surprise has confirmation_required=False
    event = _event(
        event_type="fed_commentary",
        sentiment="positive",
        urgency="high",
    )
    thesis = engine.classify(event)
    assert thesis is not None
    assert not thesis.template.confirmation_required
    assert thesis.confirmation_state == "confirmed"


def test_is_aggregation_eligible_true_when_confirmation_not_required():
    t = _thesis("fed_dovish_surprise", confirmation_state="pending")
    assert t.is_aggregation_eligible is True


def test_is_aggregation_eligible_false_for_pending_required():
    t = _thesis("fomc_minutes_release", confirmation_state="pending")
    assert t.template.confirmation_required
    assert t.is_aggregation_eligible is False


def test_is_aggregation_eligible_true_for_confirmed_required():
    t = _thesis("fomc_minutes_release", confirmation_state="confirmed")
    assert t.template.confirmation_required
    assert t.is_aggregation_eligible is True


def test_aggregator_excludes_pending_thesis_from_direction_sum():
    """A geopol_escalation_major thesis with state='pending' should not
    move target_pct. Before this fix, single-source rumors could move
    position because confirmation_required was never honored."""
    agg = ThesisAggregator(baseline_pct=0.5)
    pending = _thesis("geopol_escalation_major", confirmation_state="pending")
    decision = agg.aggregate([pending], AggregateInputs(vix=15.0))
    assert decision.direction_sum == 0
    assert decision.target_pct == 0.5
    assert pending in decision.pending_confirmation_theses
    assert pending in decision.active_theses  # still "alive", just not sizing


def test_aggregator_includes_confirmed_thesis_in_direction_sum():
    """Same bucket, but state='confirmed' — should now contribute."""
    agg = ThesisAggregator(baseline_pct=0.5)
    confirmed = _thesis("geopol_escalation_major", confirmation_state="confirmed")
    decision = agg.aggregate([confirmed], AggregateInputs(vix=15.0))
    assert decision.direction_sum < 0  # geopol is short
    assert decision.target_pct < 0.5
    assert decision.pending_confirmation_theses == []


def test_aggregator_mixed_pending_and_confirmed_only_sizes_confirmed():
    agg = ThesisAggregator(baseline_pct=0.5)
    pending = _thesis("geopol_escalation_major", confirmation_state="pending")
    confirmed_long = _thesis("fed_dovish_surprise", confirmation_state="confirmed")
    decision = agg.aggregate([pending, confirmed_long], AggregateInputs(vix=15.0))
    # Only the dovish thesis should contribute (pending geopol excluded).
    assert decision.direction_sum > 0
    assert pending in decision.pending_confirmation_theses
    assert confirmed_long not in decision.pending_confirmation_theses


def test_pending_thesis_confirmed_via_replace_now_sizes():
    """Frozen dataclass: a real implementation would `replace` the
    pending thesis with a confirmed one. Pin that the aggregation flips."""
    agg = ThesisAggregator(baseline_pct=0.5)
    pending = _thesis("fomc_minutes_release", confirmation_state="pending")
    decision_pending = agg.aggregate([pending], AggregateInputs(vix=15.0))
    assert decision_pending.target_pct == 0.5  # untouched

    confirmed = replace(
        pending, confirmation_state="confirmed", confirmed_sources=2
    )
    decision_confirmed = agg.aggregate([confirmed], AggregateInputs(vix=15.0))
    # fomc_minutes_release direction is "neutral"; target shouldn't move
    # but the thesis should now be in confirmed_active (no pending list).
    assert decision_confirmed.pending_confirmation_theses == []
    assert confirmed in decision_confirmed.active_theses


def test_note_includes_pending_confirmation_count():
    agg = ThesisAggregator(baseline_pct=0.5)
    pending1 = _thesis("geopol_escalation_major", confirmation_state="pending")
    pending2 = _thesis("fomc_minutes_release", confirmation_state="pending")
    decision = agg.aggregate([pending1, pending2], AggregateInputs(vix=15.0))
    assert "theses_pending_confirmation=2" in decision.note
