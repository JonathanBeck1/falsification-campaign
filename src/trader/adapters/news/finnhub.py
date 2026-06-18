"""Fetch news from Finnhub. Free tier = 60 req/min."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from trader.config import get_settings
from trader.storage.snapshot import NewsItem


def fetch_news(ticker: str, lookback_days: int = 3, limit: int = 20) -> list[NewsItem]:
    """Company news for `ticker` over the last `lookback_days`.

    For broad-market ETFs (SPY, QQQ), Finnhub's `company_news` returns ETF-tagged
    news (fund flows, sector commentary). For richer macro context, the brain
    also sees FRED data in MacroSnapshot.
    """
    import finnhub  # lazy

    s = get_settings()
    if s.finnhub_api_key is None:
        return []
    client = finnhub.Client(api_key=s.finnhub_api_key.get_secret_value())

    end = date.today()
    start = end - timedelta(days=lookback_days)
    raw = client.company_news(ticker, _from=start.isoformat(), to=end.isoformat()) or []

    items: list[NewsItem] = []
    for r in raw[:limit]:
        ts = r.get("datetime")
        if ts is None:
            continue
        items.append(
            NewsItem(
                headline=(r.get("headline") or "").strip(),
                summary=(r.get("summary") or "").strip(),
                source=(r.get("source") or "").strip(),
                published_at=datetime.fromtimestamp(int(ts), tz=UTC),
                sentiment=None,  # Finnhub free tier doesn't give per-article sentiment
            )
        )
    # Newest first → flip to oldest first for chronological context.
    items.reverse()
    return items
