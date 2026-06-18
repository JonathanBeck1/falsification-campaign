"""LLMFeatures schema validation tests.

The schema is the LLM/trader contract. Floats are not allowed; only enum labels.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from trader.signals.llm_features import LLMFeatures


def test_valid_minimal_features():
    f = LLMFeatures(
        sentiment_label="bullish",
        severity_bucket="medium",
        event_tags=["earnings"],
    )
    assert f.sentiment_label == "bullish"
    assert f.severity_bucket == "medium"
    assert f.event_tags == ["earnings"]
    assert f.abstain_reason is None
    assert f.schema_version == "hybrid-features-v1"


def test_rejects_unknown_sentiment_label():
    with pytest.raises(ValidationError):
        LLMFeatures(sentiment_label="euphoric", severity_bucket="high", event_tags=[])


def test_rejects_unknown_severity_bucket():
    with pytest.raises(ValidationError):
        LLMFeatures(sentiment_label="neutral", severity_bucket="apocalyptic", event_tags=[])


def test_rejects_unknown_event_tag():
    with pytest.raises(ValidationError):
        LLMFeatures(
            sentiment_label="neutral", severity_bucket="low", event_tags=["aliens_landed"]
        )


def test_rejects_free_float_in_payload():
    """The whole point of the refactor: no free floats sneaking through."""
    with pytest.raises(ValidationError):
        LLMFeatures.model_validate(
            {
                "sentiment_label": "bullish",
                "severity_bucket": "high",
                "event_tags": [],
                "regime_sentiment": -0.73,  # would silently halve target in old code
            }
        )


def test_event_tags_cap_enforced():
    with pytest.raises(ValidationError):
        LLMFeatures(
            sentiment_label="neutral",
            severity_bucket="low",
            event_tags=["fomc", "earnings", "macro_release", "geopolitical", "none", "fomc"],
        )


def test_safe_default_is_neutral_low_abstain():
    f = LLMFeatures.safe_default()
    assert f.sentiment_label == "neutral"
    assert f.severity_bucket == "low"
    assert f.event_tags == ["none"]
    assert f.abstain_reason == "llm_response_unparseable"


def test_abstain_reason_length_capped():
    with pytest.raises(ValidationError):
        LLMFeatures(
            sentiment_label="neutral",
            severity_bucket="low",
            event_tags=["none"],
            abstain_reason="x" * 500,
        )
