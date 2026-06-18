"""Strict feature schema for EarningsToneBrain (Phase 3 horse race).

Same boundary pattern as `LLMFeatures`: the LLM emits a bounded vocabulary
of labels, never floats. A deterministic `EarningsTonePolicy` consumes the
labels and decides position size.

Per `brain/decisions/2026-05-21-horse-race-phase-3.md`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "earnings-tone-v1"

AggregateTone = Literal["bullish", "bearish", "mixed", "neutral"]
GuidanceSignal = Literal["raised", "unchanged", "lowered", "mixed", "none_visible"]
Breadth = Literal["all_aligned", "majority_aligned", "split", "single_name_only"]
Confidence = Literal["high", "medium", "low"]


class EarningsToneFeatures(BaseModel):
    """Strict feature schema for aggregate earnings tone across top-10 QQQ 8-Ks."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["earnings-tone-v1"] = "earnings-tone-v1"
    aggregate_tone: AggregateTone
    guidance_signal: GuidanceSignal
    breadth: Breadth
    confidence: Confidence
    abstain_reason: str | None = None
