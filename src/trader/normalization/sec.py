"""Normalize SEC EDGAR 8-K filings into Event records.

The SEC adapter currently emits items with headlines prefixed `[SEC 8-K]
{TICKER}: {filing title}`. We parse the ticker back out of the headline and
attach it as the primary entity with very high confidence.

All 8-K filings carry event_type=`regulatory_action` by default, but the
filing title often hints at a more specific category (e.g. "Item 2.02
Results of Operations" -> earnings_surprise). A future improvement is to
parse the actual Item references from the filing body; for now we use
keyword heuristics on the title text.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from trader.normalization.models import Entity, Event, EventType, EvidenceSnippet, Urgency, stable_event_id
from trader.storage.snapshot import NewsItem

_HEADLINE_PATTERN = re.compile(r"^\[SEC 8-K\] (?P<ticker>[A-Z][A-Z0-9\-.]*): (?P<title>.+)$")


def _parse_headline(headline: str) -> tuple[str | None, str]:
    """Return (ticker, filing_title) parsed from the prefixed headline."""
    m = _HEADLINE_PATTERN.match(headline)
    if not m:
        return None, headline
    return m.group("ticker"), m.group("title")


_ITEM_KEYWORDS: tuple[tuple[EventType, tuple[str, ...]], ...] = (
    ("earnings_surprise", ("results of operations", "item 2.02")),
    ("guidance_raise", ("revised outlook", "raises outlook")),
    ("guidance_lower", ("withdraws guidance", "lowers outlook")),
    ("mna", ("merger", "acquisition", "item 1.01", "material definitive agreement")),
    ("regulatory_action", ("settles", "consent order")),
)


def classify_event_type(filing_title: str) -> EventType:
    text = filing_title.lower()
    for event_type, keywords in _ITEM_KEYWORDS:
        if any(kw in text for kw in keywords):
            return event_type
    return "regulatory_action"  # default for any 8-K


def classify_urgency(filing_title: str) -> Urgency:
    text = filing_title.lower()
    if any(kw in text for kw in ("bankruptcy", "going concern", "delisting", "material weakness")):
        return "breaking"
    if any(kw in text for kw in ("results of operations", "agreement", "departure")):
        return "high"
    return "normal"


def sec_news_to_events(
    items: list[NewsItem],
    *,
    observed_at: datetime | None = None,
) -> list[Event]:
    """Convert SEC EDGAR NewsItems into Event records."""
    now = observed_at or datetime.now(UTC)
    out: list[Event] = []
    for item in items:
        ticker, filing_title = _parse_headline(item.headline)
        event_type = classify_event_type(filing_title)
        urgency = classify_urgency(filing_title)
        classified_at = now
        out.append(
            Event(
                event_id=stable_event_id("sec_edgar", ticker or "", filing_title, item.published_at),
                source="sec_edgar",
                source_url="https://www.sec.gov/cgi-bin/browse-edgar",
                title=filing_title,
                summary=item.summary,
                published_at=item.published_at,
                observed_at=now,
                ingested_at=now,
                classified_at=classified_at,
                entities=([Entity(name=ticker, ticker=ticker, confidence=0.98, role="primary")] if ticker else []),
                asset_scope=["single_name"],
                index_exposure=[],
                event_type=event_type,
                sentiment="neutral",
                sentiment_score=0.0,
                urgency=urgency,
                novelty_score=0.9,  # filings are first-publication of material events
                source_credibility=1.0,  # SEC is canonical
                evidence=[
                    EvidenceSnippet(
                        text=(item.summary or filing_title)[:300],
                        location="sec_8k",
                    )
                ],
                model_outputs=[],
                raw_artifact_path="",
            )
        )
    return out
