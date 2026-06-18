"""Normalize Finnhub company-news items into Event records.

Finnhub's `company_news(ticker)` returns items tagged to ONE ticker — the
ticker we queried. So the primary entity is unambiguous; we attach it with
high confidence.

Heuristic event_type from keyword scan of headline; sentiment left neutral
(Finnhub free tier does not score per-article sentiment).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from trader.normalization.models import Entity, Event, EventType, EvidenceSnippet, Urgency, stable_event_id
from trader.storage.snapshot import NewsItem

_KEYWORDS: tuple[tuple[EventType, tuple[str, ...]], ...] = (
    (
        "earnings_surprise",
        (
            "earnings beat",
            "earnings miss",
            "tops estimates",
            "missed estimates",
            "beats estimates",
            "misses estimates",
            "q1 earnings",
            "q2 earnings",
            "q3 earnings",
            "q4 earnings",
            "quarterly earnings",
        ),
    ),
    ("guidance_raise", ("raises guidance", "raised guidance", "guidance higher", "lifts outlook")),
    ("guidance_lower", ("cuts guidance", "lowers guidance", "guidance lower", "warns on outlook")),
    ("mna", ("acquires", "acquisition", "merger", "to buy", "takeover", "tender offer")),
    ("regulatory_action", ("sec ", "regulator", "settles charges", "consent decree", "antitrust")),
    ("lawsuit", ("lawsuit", "sued", "class action", "files suit")),
    ("investigation", ("investigation", "probe", "subpoena")),
    ("product_launch", ("launches", "unveils", "introduces", "announces new")),
    ("product_failure", ("recall", "withdrawal", "halts production", "outage")),
    ("analyst_upgrade", ("upgraded", "upgrade to buy", "raises price target", "outperform rating")),
    ("analyst_downgrade", ("downgraded", "downgrade to sell", "cuts price target", "underperform rating")),
)

# Regex patterns catch "X beats/misses Q2 estimates" style headlines where the
# quarter or amount sits between the verb and the noun.
_PATTERNS: tuple[tuple[EventType, re.Pattern[str]], ...] = (
    ("earnings_surprise", re.compile(r"\b(beats|misses|tops)\s+\S+\s+estimates\b")),
)


def classify_event_type(headline: str, summary: str = "") -> EventType:
    text = (headline + " " + summary).lower()
    for event_type, pattern in _PATTERNS:
        if pattern.search(text):
            return event_type
    for event_type, keywords in _KEYWORDS:
        if any(kw in text for kw in keywords):
            return event_type
    return "other"


def classify_urgency(headline: str) -> Urgency:
    text = headline.lower()
    if any(kw in text for kw in ("breaking", "halted", "recall", "investigation")):
        return "high"
    return "normal"


def finnhub_news_to_events(
    items: list[NewsItem],
    *,
    ticker: str,
    observed_at: datetime | None = None,
) -> list[Event]:
    """Convert Finnhub NewsItems queried under `ticker` into Event records."""
    now = observed_at or datetime.now(UTC)
    out: list[Event] = []
    for item in items:
        event_type = classify_event_type(item.headline, item.summary)
        urgency = classify_urgency(item.headline)
        classified_at = now
        out.append(
            Event(
                event_id=stable_event_id("finnhub", ticker.upper(), item.headline, item.published_at),
                source="finnhub",
                source_url="",
                title=item.headline,
                summary=item.summary,
                published_at=item.published_at,
                observed_at=now,
                ingested_at=now,
                classified_at=classified_at,
                entities=[
                    Entity(name=ticker, ticker=ticker, confidence=0.95, role="primary"),
                ],
                asset_scope=["single_name"] + (["index"] if ticker in {"SPY", "QQQ"} else []),
                index_exposure=["SPY", "QQQ"] if ticker in {"SPY", "QQQ"} else [],
                event_type=event_type,
                sentiment="neutral",
                sentiment_score=0.0,
                urgency=urgency,
                novelty_score=0.5,
                source_credibility=0.75,
                evidence=[
                    EvidenceSnippet(
                        text=(item.summary or item.headline)[:300],
                        location="finnhub.summary",
                    )
                ],
                model_outputs=[],
                raw_artifact_path="",
            )
        )
    return out
