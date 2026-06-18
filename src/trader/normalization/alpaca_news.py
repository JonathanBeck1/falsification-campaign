"""Normalize Alpaca News items into Event records.

Alpaca News is Benzinga-sourced. The underlying API returns symbols tags per
article, but the current adapter (`adapters/alpaca/news.py`) doesn't propagate
them through `NewsItem` yet. For now we attach the queried symbols as
candidate entities with moderate confidence; we'll tighten this when the
adapter surfaces per-article symbols.

Benzinga's source credibility is generally high (institutional newsroom).
"""

from __future__ import annotations

from datetime import UTC, datetime

from trader.normalization.finnhub import classify_event_type, classify_urgency
from trader.normalization.models import Entity, Event, EvidenceSnippet, stable_event_id
from trader.storage.snapshot import NewsItem


def alpaca_news_to_events(
    items: list[NewsItem],
    *,
    queried_symbols: list[str],
    observed_at: datetime | None = None,
) -> list[Event]:
    """Convert Alpaca News items queried under `queried_symbols` into Event records."""
    now = observed_at or datetime.now(UTC)
    normalized_symbols = sorted({s.upper() for s in queried_symbols})
    out: list[Event] = []
    for item in items:
        event_type = classify_event_type(item.headline, item.summary)
        urgency = classify_urgency(item.headline)
        classified_at = now
        out.append(
            Event(
                # Event identity is independent of `queried_symbols`. The same
                # Benzinga story fetched against ["AAPL"] vs ["AAPL","MSFT"] is
                # one event — dedup must hold across queries. Symbol attribution
                # lives in `entities`, not in the id.
                event_id=stable_event_id("alpaca_news", item.headline, item.published_at),
                source="alpaca_news",
                source_url="",
                title=item.headline,
                summary=item.summary,
                published_at=item.published_at,
                observed_at=now,
                ingested_at=now,
                classified_at=classified_at,
                entities=[Entity(name=t, ticker=t, confidence=0.7, role="mentioned") for t in normalized_symbols],
                asset_scope=["single_name"] if normalized_symbols else ["macro"],
                index_exposure=[t for t in normalized_symbols if t in {"SPY", "QQQ"}],
                event_type=event_type,
                sentiment="neutral",
                sentiment_score=0.0,
                urgency=urgency,
                novelty_score=0.6,
                source_credibility=0.85,  # Benzinga
                evidence=[
                    EvidenceSnippet(
                        text=(item.summary or item.headline)[:300],
                        location="alpaca_news",
                    )
                ],
                model_outputs=[],
                raw_artifact_path="",
            )
        )
    return out
