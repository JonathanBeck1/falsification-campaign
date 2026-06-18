"""Normalize Federal Reserve RSS items into Event records.

The Fed feed (`adapters/macro/fed.py`) returns `NewsItem` objects sourced from
`https://www.federalreserve.gov/feeds/press_monetary.xml`. This normalizer:

- Classifies the event_type (always within the `fed_commentary` family for now).
- Heuristic urgency: FOMC statements + rate decisions = breaking, press
  conferences = high, everything else = normal.
- Tags asset scope as macro/index and index_exposure as SPY/QQQ — Fed releases
  move the whole market, not specific tickers.
- Source credibility = 0.95 (Fed releases are authoritative).
- Sentiment is left neutral here; a downstream LLM/FinBERT classifier can fill
  it in via `model_outputs`.

There is no ticker-ambiguity problem with Fed releases — that's why this is the
first adapter we normalize.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trader.normalization.models import Event, EventType, EvidenceSnippet, Urgency, stable_event_id
from trader.storage.snapshot import NewsItem

_FED_FEED_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"


def _classify_urgency(headline: str, summary: str = "") -> Urgency:
    text = f"{headline} {summary}".lower()
    if "fomc statement" in text or "rate decision" in text or "rate cut" in text or "rate hike" in text:
        return "breaking"
    if "press conference" in text or ("powell" in text and ("remarks" in text or "speech" in text)):
        return "high"
    return "normal"


def _classify_event_type(headline: str) -> EventType:
    # Per brain/08, Fed-related categories are "fed_commentary" or "macro_surprise".
    # We default to fed_commentary for the monetary-policy feed since the feed
    # itself filters to monetary-policy items.
    return "fed_commentary"


def fed_news_to_events(items: list[NewsItem], *, observed_at: datetime | None = None) -> list[Event]:
    """Convert Fed RSS NewsItems to Event records."""
    now = observed_at or datetime.now(UTC)
    events: list[Event] = []
    for item in items:
        # Strip the "[Federal Reserve] " prefix the adapter added so the
        # normalized title is the raw RSS title.
        title = item.headline
        prefix = "[Federal Reserve] "
        if title.startswith(prefix):
            title = title[len(prefix) :]

        event_type = _classify_event_type(title)
        urgency = _classify_urgency(title, item.summary)
        classified_at = now
        events.append(
            Event(
                event_id=stable_event_id("federalreserve.gov", _FED_FEED_URL, title, item.published_at),
                source="federalreserve.gov",
                source_url=_FED_FEED_URL,
                title=title,
                summary=item.summary,
                published_at=item.published_at,
                observed_at=now,
                ingested_at=now,
                classified_at=classified_at,
                entities=[],  # macro event; no specific company entities
                asset_scope=["macro", "index"],
                index_exposure=["SPY", "QQQ"],
                event_type=event_type,
                sentiment="neutral",
                sentiment_score=0.0,
                urgency=urgency,
                novelty_score=0.7,  # Fed releases are usually high-novelty
                source_credibility=0.95,
                evidence=[
                    EvidenceSnippet(
                        text=(item.summary or title)[:300],
                        location="rss_description",
                    )
                ],
                model_outputs=[],
                raw_artifact_path="",  # raw artifact storage is a future addition
            )
        )
    return events
