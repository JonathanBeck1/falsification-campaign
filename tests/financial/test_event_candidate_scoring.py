from __future__ import annotations

from datetime import UTC, datetime

from trader.enrichment.schema import ENRICHER_CLASSIFIER, PROMPT_TEMPLATE_VERSION
from trader.normalization.models import Entity, Event, ModelOutputMeta
from trader.research.event_candidates import score_event_candidate, score_events


def _event(raw_output: str | None, *, event_id: str = "evt_score") -> Event:
    now = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    event = Event(
        event_id=event_id,
        source="demo_news",
        title="Apple raises guidance",
        summary="Apple raised guidance after services strength.",
        published_at=now,
        observed_at=now,
        ingested_at=now,
        classified_at=now,
        entities=[Entity(name="Apple Inc.", ticker="AAPL", confidence=0.95, role="primary")],
        event_type="guidance_raise",
        urgency="high",
        source_credibility=0.7,
        novelty_score=0.5,
    )
    if raw_output is not None:
        event.model_outputs.append(
            ModelOutputMeta(
                classifier=ENRICHER_CLASSIFIER,
                prompt_version=PROMPT_TEMPLATE_VERSION,
                raw_output=raw_output,
                validation_status="auto_passed",
                created_at=now,
            )
        )
    return event


def _raw(sentiment_score: float = 0.5, *, label: str = "positive", actionable: bool = True) -> str:
    return (
        '{"schema_version":"v1","prompt_template_version":"tmpl-v1",'
        '"event_id":"evt_score",'
        f'"sentiment_label":"{label}","sentiment_score":{sentiment_score},'
        '"urgency":"high","novelty_score":0.7,"event_type":"guidance_raise",'
        '"key_claims":[{"text":"Apple raised guidance.",'
        '"quote":"Apple raised guidance","from_field":"summary"}],'
        '"tickers_affected":["AAPL"],'
        f'"is_actionable":{str(actionable).lower()},'
        '"confidence":0.76,"abstain_reason":null}'
    )


def test_score_event_candidate_requires_enrichment():
    assert score_event_candidate(_event(None)) is None


def test_score_event_candidate_scores_positive_actionable_event():
    candidate = score_event_candidate(_event(_raw()))

    assert candidate is not None
    assert candidate.event_id == "evt_score"
    assert candidate.ticker == "AAPL"
    assert candidate.direction == "bullish"
    assert candidate.score > 50
    assert candidate.confidence == 0.76
    assert any("sentiment" in reason for reason in candidate.reasons)


def test_score_event_candidate_scores_negative_event():
    candidate = score_event_candidate(_event(_raw(-0.6, label="negative")))

    assert candidate is not None
    assert candidate.direction == "bearish"
    assert candidate.score < -50


def test_score_events_sorts_by_absolute_score():
    weak = _event(_raw(0.2), event_id="evt_weak")
    weak.model_outputs[0].raw_output = weak.model_outputs[0].raw_output.replace('"evt_score"', '"evt_weak"')
    strong = _event(_raw(-0.8, label="negative"), event_id="evt_strong")
    strong.model_outputs[0].raw_output = strong.model_outputs[0].raw_output.replace('"evt_score"', '"evt_strong"')

    candidates = score_events([weak, strong])

    assert [candidate.event_id for candidate in candidates] == ["evt_strong", "evt_weak"]
