"""Fetch news from Alpaca's News REST API. Benzinga-sourced, free with paper acct.

Endpoint: https://data.alpaca.markets/v1beta1/news (paginated, Benzinga-sourced).
We use the `alpaca-py` SDK's NewsClient.

The free tier is sufficient for daily polling. Real-time WebSocket streaming
exists but is gated behind paid market-data tiers — out of scope for v0.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from trader.config import get_settings
from trader.storage.snapshot import NewsItem

log = structlog.get_logger()


def fetch_alpaca_news(
    symbols: list[str],
    *,
    lookback_days: int = 3,
    limit: int = 30,
) -> list[NewsItem]:
    """Pull recent news for the given symbols. Best-effort — never raises."""
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest

    s = get_settings()
    try:
        client = NewsClient(s.alpaca_key_id, s.alpaca_secret_key)
    except Exception as exc:
        log.warning("alpaca_news_client_init_failed", error=str(exc))
        return []

    end = datetime.now(UTC)
    start = end - timedelta(days=lookback_days)
    # alpaca-py wants symbols as a comma-separated string, not a list.
    req = NewsRequest(
        symbols=",".join(symbols),
        start=start,
        end=end,
        limit=limit,
        include_content=False,
        exclude_contentless=False,
    )

    try:
        resp = client.get_news(req)
    except Exception as exc:
        log.warning("alpaca_news_fetch_failed", symbols=symbols, error=str(exc))
        return []

    items: list[NewsItem] = []
    raw_news = getattr(resp, "news", None) or getattr(resp, "data", None) or []
    # The response can be a NewsSet (with .news), or a dict keyed by symbol, or a list.
    if isinstance(raw_news, dict):
        flat: list = []
        for v in raw_news.values():
            if isinstance(v, list):
                flat.extend(v)
        raw_news = flat

    seen: set[str] = set()
    for n in raw_news:
        headline = (getattr(n, "headline", "") or "").strip()
        created = getattr(n, "created_at", None)
        if not headline or created is None:
            continue
        # Normalize tz
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        key = headline.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            NewsItem(
                headline=headline,
                summary=(getattr(n, "summary", "") or "").strip(),
                source=(getattr(n, "source", "") or "").strip(),
                published_at=created,
                sentiment=None,
            )
        )
    items.sort(key=lambda n: n.published_at)
    return items
