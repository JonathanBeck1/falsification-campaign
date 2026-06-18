"""Strict, validated output the LLM is allowed to produce in HybridBrain.

Per `brain/10_llm_agent_boundaries.md` and the ADR in `brain/20`, the LLM
extracts STRUCTURED FEATURES with bounded vocabularies. It never emits free
floats that directly become positions. All sizing is done by a versioned
deterministic `SizingPolicy` that consumes these features.

A hallucinated label has bounded blast radius (one bucket up or down, not
an arbitrary float).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SentimentLabel = Literal["bullish", "bearish", "neutral", "mixed"]
EventTag = Literal["fomc", "earnings", "macro_release", "geopolitical", "none"]
SeverityBucket = Literal["low", "medium", "high", "breaking"]

SCHEMA_VERSION = "hybrid-features-v1"


class LLMFeatures(BaseModel):
    """Strict feature schema. No free numerics that become positions."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["hybrid-features-v1"] = "hybrid-features-v1"
    sentiment_label: SentimentLabel
    event_tags: list[EventTag] = Field(default_factory=list, max_length=5)
    severity_bucket: SeverityBucket
    abstain_reason: str | None = Field(default=None, max_length=200)

    @classmethod
    def safe_default(cls) -> LLMFeatures:
        """Returned when the LLM response is unparseable. Treats the day as
        neutral/low-severity so the deterministic base decision passes through
        unchanged."""
        return cls(
            sentiment_label="neutral",
            event_tags=["none"],
            severity_bucket="low",
            abstain_reason="llm_response_unparseable",
        )
