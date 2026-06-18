from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trader.enrichment.schema import (
    ENRICHER_CLASSIFIER,
    PROMPT_TEMPLATE_VERSION,
    SCHEMA_VERSION,
    EnrichmentV1,
    validate_enrichment_for_event,
)
from trader.normalization.models import Entity, Event, EvidenceSnippet


def _event() -> Event:
    now = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    return Event(
        event_id="evt_test",
        source="marketwatch.com",
        title="Fed comments move SPY",
        summary="Powell said the Fed will be patient on interest rates.",
        published_at=now,
        observed_at=now,
        ingested_at=now,
        classified_at=now,
        entities=[Entity(name="Apple Inc.", ticker="AAPL", confidence=0.8, role="mentioned")],
        asset_scope=["index", "macro"],
        index_exposure=["SPY"],
        event_type="fed_commentary",
        sentiment="neutral",
        sentiment_score=0.0,
        urgency="high",
        novelty_score=0.5,
        source_credibility=0.7,
        evidence=[EvidenceSnippet(text="Powell said the Fed will be patient.", location="summary")],
    )


def _payload(**overrides):
    base = {
        "schema_version": SCHEMA_VERSION,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "event_id": "evt_test",
        "sentiment_label": "negative",
        "sentiment_score": -0.4,
        "urgency": "high",
        "novelty_score": 0.8,
        "event_type": "fed_commentary",
        "key_claims": [
            {
                "text": "Powell signaled patience on rates.",
                "quote": "Powell said the Fed will be patient",
                "from_field": "summary",
            }
        ],
        "tickers_affected": ["SPY", "AAPL"],
        "is_actionable": False,
        "confidence": 0.82,
        "abstain_reason": None,
    }
    base.update(overrides)
    return base


def test_valid_enrichment_passes_event_validation():
    enrichment = EnrichmentV1.model_validate(_payload())
    validated = validate_enrichment_for_event(enrichment, _event())

    assert validated.validation_status == "auto_passed"
    assert validated.enrichment.event_id == "evt_test"
    assert validated.enrichment.key_claims[0].quote == "Powell said the Fed will be patient"


def test_event_id_mismatch_rejects():
    enrichment = EnrichmentV1.model_validate(_payload(event_id="evt_wrong"))
    validated = validate_enrichment_for_event(enrichment, _event())
    assert validated.validation_status == "rejected"
    assert "event_id mismatch" in validated.reason


def test_model_cannot_invent_tickers():
    enrichment = EnrichmentV1.model_validate(_payload(tickers_affected=["MSFT"]))
    validated = validate_enrichment_for_event(enrichment, _event())
    assert validated.validation_status == "rejected"
    assert "disallowed tickers" in validated.reason


def test_missing_quote_rejects_when_all_claims_drop():
    enrichment = EnrichmentV1.model_validate(
        _payload(
            key_claims=[
                {
                    "text": "Unsupported claim.",
                    "quote": "not present in title or summary",
                    "from_field": "summary",
                }
            ]
        )
    )
    validated = validate_enrichment_for_event(enrichment, _event())
    assert validated.validation_status == "rejected"
    assert "no supported key_claims" in validated.reason


@pytest.mark.parametrize(
    ("label", "score"),
    [
        ("positive", -0.2),
        ("negative", 0.2),
        ("neutral", 0.3),
    ],
)
def test_sentiment_label_score_mismatch_fails_pydantic(label: str, score: float):
    with pytest.raises(ValidationError):
        EnrichmentV1.model_validate(_payload(sentiment_label=label, sentiment_score=score))


def test_constants_are_versioned():
    assert ENRICHER_CLASSIFIER == "event-enricher-v1"
    assert SCHEMA_VERSION == "v1"
    assert PROMPT_TEMPLATE_VERSION == "tmpl-v1"
