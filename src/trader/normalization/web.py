"""Normalize web-news adapter items into Event records.

The web adapter (`adapters/news/web.py`) hands us `NewsItem` rows whose `.source`
field is the publisher's host (e.g. "marketwatch.com"). Items have already been
filtered for SPY/QQQ relevance upstream, so we tag asset_scope as index/macro
and attach SPY/QQQ as `mentioned` entities with low confidence — the article
text is the real evidence, not the ticker tagging.

Event-type classification reuses the conservative keyword rules from the Yahoo
normalizer, since the input shape is the same (broad-market headlines, no
guaranteed entity tags).
"""

from __future__ import annotations

from datetime import UTC, datetime

from trader.normalization.models import Entity, Event, EvidenceSnippet, stable_event_id
from trader.normalization.yahoo import classify_yahoo_event_type, classify_yahoo_urgency
from trader.storage.snapshot import NewsItem

# Per-source credibility scores. Items whose `source` isn't in this map fall
# back to a conservative default. Matches the credibility ladder Jonathan
# defined in brain/17.
_SOURCE_CREDIBILITY: dict[str, float] = {
    "marketwatch.com": 0.7,
    "cnbc.com": 0.7,
    "reuters.com": 0.85,
    "bloomberg.com": 0.85,
    "wsj.com": 0.85,
    "ft.com": 0.85,
}


def web_news_to_events(
    items: list[NewsItem],
    *,
    queried_tickers: list[str],
    observed_at: datetime | None = None,
) -> list[Event]:
    """Convert web-news NewsItems into Event records.

    `queried_tickers` is the broad-market context (e.g. ["SPY","QQQ"]) — same
    convention as the Yahoo normalizer.
    """
    now = observed_at or datetime.now(UTC)
    normalized_tickers = sorted({t.upper() for t in queried_tickers})
    index_exposure = [t for t in normalized_tickers if t in {"SPY", "QQQ"}]

    out: list[Event] = []
    for item in items:
        host = item.source or "unknown.web"
        event_type = classify_yahoo_event_type(item.headline, item.summary)
        urgency = classify_yahoo_urgency(item.headline, item.summary)
        classified_at = now
        out.append(
            Event(
                event_id=stable_event_id("web_news", host, item.headline, item.published_at),
                source=host,
                source_url="",
                title=item.headline,
                summary=item.summary,
                published_at=item.published_at,
                observed_at=now,
                ingested_at=now,
                classified_at=classified_at,
                entities=[Entity(name=t, ticker=t, confidence=0.4, role="mentioned") for t in normalized_tickers],
                asset_scope=["index", "macro"],
                index_exposure=index_exposure,
                event_type=event_type,
                sentiment="neutral",
                sentiment_score=0.0,
                urgency=urgency,
                novelty_score=0.5,
                source_credibility=_SOURCE_CREDIBILITY.get(host, 0.55),
                evidence=[
                    EvidenceSnippet(
                        text=(item.summary or item.headline)[:300],
                        location="rss_description",
                    )
                ],
                model_outputs=[],
                raw_artifact_path="",
            )
        )
    return out
