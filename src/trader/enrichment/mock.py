from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any

from trader.enrichment.schema import PROMPT_TEMPLATE_VERSION, SCHEMA_VERSION
from trader.llm.client import LLMResponse

_FIELD_NAMES = (
    "event_id",
    "heuristic_event_type",
    "heuristic_urgency",
    "allowed_tickers",
    "title",
    "summary",
)

_POSITIVE_EVENT_TYPES = {"guidance_raise", "product_launch", "analyst_upgrade", "earnings_surprise"}
_NEGATIVE_EVENT_TYPES = {
    "guidance_lower",
    "investigation",
    "lawsuit",
    "regulatory_action",
    "macro_surprise",
    "product_failure",
}
_MARKET_INDEX_TICKERS = {"SPY", "QQQ", "DIA", "IWM"}


class DeterministicEnrichmentLLM:
    """Local no-key analyst stub for exercising the enrichment pipeline."""

    def complete(self, **kwargs: Any) -> LLMResponse:
        user = str(kwargs.get("user", ""))
        fields = {name: _tag(user, name) for name in _FIELD_NAMES}
        summary = fields.get("summary") or fields.get("title") or "No article text available."
        quote = _quote(summary)
        event_type = fields.get("heuristic_event_type", "other") or "other"
        sentiment_label, sentiment_score, is_actionable, confidence = _sentiment_for_event_type(event_type)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "event_id": fields.get("event_id", ""),
            "sentiment_label": sentiment_label,
            "sentiment_score": sentiment_score,
            "urgency": fields.get("heuristic_urgency", "normal") or "normal",
            "novelty_score": 0.5,
            "event_type": event_type,
            "key_claims": [
                {
                    "text": quote,
                    "quote": quote,
                    "from_field": "summary" if fields.get("summary") else "title",
                }
            ],
            "tickers_affected": _tickers(fields.get("allowed_tickers", "")),
            "is_actionable": is_actionable,
            "confidence": confidence,
            "abstain_reason": None,
        }
        content = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return LLMResponse(
            content=content,
            parsed=payload,
            model="mock-event-enricher-v1",
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            cache_creation_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
            prompt_hash=hashlib.sha256(user.encode()).hexdigest()[:16],
        )


def _quote(text: str) -> str:
    compact = " ".join(text.split())
    if not compact:
        return "No article text available."
    return compact[:240]


def _sentiment_for_event_type(event_type: str) -> tuple[str, float, bool, float]:
    if event_type in _POSITIVE_EVENT_TYPES:
        return "positive", 0.45, True, 0.68
    if event_type == "fed_commentary":
        return "negative", -0.25, False, 0.58
    if event_type in _NEGATIVE_EVENT_TYPES:
        return "negative", -0.55, True, 0.72
    return "neutral", 0.0, False, 0.45


def _tag(text: str, name: str) -> str:
    match = re.search(rf"<{name}>(.*?)</{name}>", text, flags=re.DOTALL)
    if not match:
        return ""
    return html.unescape(match.group(1).strip())


def _tickers(csv: str) -> list[str]:
    tickers = [item.strip().upper() for item in csv.split(",") if item.strip()]
    single_names = [ticker for ticker in tickers if ticker not in _MARKET_INDEX_TICKERS]
    indexes = [ticker for ticker in tickers if ticker in _MARKET_INDEX_TICKERS]
    return [*single_names, *indexes][:3]
