"""Normalized event records — the bridge between raw source data and signals.

Schema follows `brain/08_news_event_schema.md`. Raw article text is not a
signal. A normalized `Event` may become one once classified and validated.

Status: **v0 skeleton.** Models are defined but no adapter currently emits
`Event` records — they still emit `NewsItem` (see trader.storage.snapshot).
The plan in `brain/13_financial_pipeline_proposal.md` lays out how the existing
news adapters will be wrapped by a normalization layer that produces Events.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from trader.storage.utc import ensure_utc

Role = Literal["primary", "mentioned", "indirect"]
AssetScope = Literal["single_name", "index", "sector", "macro"]
Urgency = Literal["low", "normal", "high", "breaking"]
SentimentLabel = Literal["negative", "neutral", "positive", "mixed"]
EventType = Literal[
    "earnings_surprise",
    "guidance_raise",
    "guidance_lower",
    "mna",
    "regulatory_action",
    "lawsuit",
    "investigation",
    "product_launch",
    "product_failure",
    "macro_surprise",
    "fed_commentary",
    "geopolitical_shock",
    "analyst_upgrade",
    "analyst_downgrade",
    "unusual_social_velocity",
    "other",
]


def _parse_datetime_text(value: str) -> datetime:
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


class Entity(BaseModel):
    name: str
    ticker: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    role: Role = "mentioned"


class EvidenceSnippet(BaseModel):
    text: str
    location: str = ""  # e.g. "paragraph:3"


class ModelOutputMeta(BaseModel):
    """Per `brain/10_llm_agent_boundaries.md`, every LLM-derived output must
    be auditable: model name, prompt version, raw + parsed output, validation
    status, timestamp."""

    classifier: str  # e.g. "finbert-v1" or "claude-haiku-4-5"
    prompt_version: str = "v0"
    raw_output: str | None = None
    validation_status: Literal["unreviewed", "human_reviewed", "auto_passed", "rejected"] = "unreviewed"
    created_at: datetime

    @field_validator("created_at", mode="after")
    @classmethod
    def _normalize_created_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class Event(BaseModel):
    """Normalized event record. See `brain/08_news_event_schema.md`."""

    event_id: str  # "evt_<uuid>"
    source: str  # adapter name, e.g. "alpaca_news", "yahoo_news", "sec_edgar"
    source_url: str = ""
    title: str
    summary: str = ""

    # Timestamps — all UTC.
    published_at: datetime  # what the source says
    observed_at: datetime  # when we saw it
    ingested_at: datetime  # when it entered storage
    classified_at: datetime | None = None  # when the event model processed it

    # Classification.
    entities: list[Entity] = Field(default_factory=list)
    asset_scope: list[AssetScope] = Field(default_factory=list)
    index_exposure: list[str] = Field(default_factory=list)  # e.g. ["SPY","QQQ"]
    event_type: EventType = "other"

    # Sentiment / scoring.
    sentiment: SentimentLabel = "neutral"
    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    urgency: Urgency = "normal"
    novelty_score: float = Field(default=0.0, ge=0.0, le=1.0)
    source_credibility: float = Field(default=0.5, ge=0.0, le=1.0)

    # Provenance.
    evidence: list[EvidenceSnippet] = Field(default_factory=list)
    model_outputs: list[ModelOutputMeta] = Field(default_factory=list)
    raw_artifact_path: str = ""  # pointer to the raw payload on disk

    @field_validator("published_at", "observed_at", "ingested_at", "classified_at", mode="after")
    @classmethod
    def _normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value)


def stable_event_id(source: str, *parts: object) -> str:
    """Create a deterministic event id from source-native identity fields."""
    payload = json.dumps(
        [source, *parts],
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"evt_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def event_from_row(row: dict) -> Event:
    """Reconstruct an Event from a `news_events` row dict (JSON columns as strings)."""
    return Event(
        event_id=row["event_id"],
        source=row["source"],
        source_url=row.get("source_url", "") or "",
        title=row["title"],
        summary=row.get("summary", "") or "",
        published_at=_parse_datetime_text(row["published_at"]),
        observed_at=_parse_datetime_text(row["observed_at"]),
        ingested_at=_parse_datetime_text(row["ingested_at"]),
        classified_at=(_parse_datetime_text(row["classified_at"]) if row.get("classified_at") else None),
        entities=[Entity(**e) for e in json.loads(row.get("entities_json") or "[]")],
        asset_scope=json.loads(row.get("asset_scope_json") or "[]"),
        index_exposure=json.loads(row.get("index_exposure_json") or "[]"),
        event_type=row.get("event_type") or "other",
        sentiment=row.get("sentiment") or "neutral",
        sentiment_score=float(row.get("sentiment_score") or 0.0),
        urgency=row.get("urgency") or "normal",
        novelty_score=float(row.get("novelty_score") or 0.0),
        source_credibility=float(row.get("source_credibility") or 0.5),
        evidence=[EvidenceSnippet(**e) for e in json.loads(row.get("evidence_json") or "[]")],
        model_outputs=[ModelOutputMeta(**m) for m in json.loads(row.get("model_outputs_json") or "[]")],
        raw_artifact_path=row.get("raw_artifact_path") or "",
    )
