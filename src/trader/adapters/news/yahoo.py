"""Fetch news headlines from Yahoo Finance via the `yfinance` package.

This is **not** a spider — `yfinance.Ticker(...).news` calls an undocumented JSON
endpoint and returns a list of dicts. No auth, no scraping, no JS rendering.

Quirks:
- yfinance has changed its news dict schema across versions. We handle both the
  legacy flat shape (`title`, `publisher`, `providerPublishTime`) and the newer
  nested `content` shape (`content.title`, `content.provider.displayName`,
  `content.pubDate`).
- There is no point-in-time / historical query. This is "what's on the page now."
  Fine for live paper trading, useless for backtests.
- The endpoint can change or fail at any moment. We never let a failure propagate
  into the trading loop — on error we return an empty list and log a warning.

Backlog (see README): the same `yf.Ticker(...)` object also exposes `.calendar`
(earnings dates), `.recommendations` (analyst ratings), and `.insider_transactions`.
Worth adding if the LLM brains plateau on headlines alone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from trader.storage.snapshot import NewsItem

log = structlog.get_logger()


def _parse_pubdate(raw: Any) -> datetime | None:
    """Tolerate three forms: int unix seconds, ISO-8601 string, or None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(int(raw), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(raw, str):
        # yfinance new schema: "2026-05-18T14:30:00Z"
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _to_news_item(raw: dict[str, Any]) -> NewsItem | None:
    """Map one yfinance news dict to a NewsItem. Returns None if unparseable."""
    # New-schema (yfinance >= 0.2.40-ish) nests under "content"
    content = raw.get("content") if isinstance(raw.get("content"), dict) else None

    if content is not None:
        title = (content.get("title") or "").strip()
        summary = (content.get("summary") or content.get("description") or "").strip()
        provider = content.get("provider") or {}
        source = (provider.get("displayName") if isinstance(provider, dict) else "") or ""
        published = _parse_pubdate(content.get("pubDate"))
    else:
        # Legacy flat schema
        title = (raw.get("title") or "").strip()
        summary = (raw.get("summary") or "").strip()
        source = (raw.get("publisher") or "").strip()
        published = _parse_pubdate(raw.get("providerPublishTime"))

    if not title or published is None:
        return None

    return NewsItem(
        headline=title,
        summary=summary,
        source=source.strip(),
        published_at=published,
        sentiment=None,
    )


def fetch_yahoo_news(tickers: list[str], *, per_ticker_limit: int = 10) -> list[NewsItem]:
    """Fetch recent headlines for each ticker via yfinance. Best-effort.

    Returns a flat, de-duplicated list ordered by `published_at` ascending.
    A failure on any single ticker is logged and skipped — never raised.
    """
    import yfinance as yf  # lazy: keeps unit tests fast

    seen_titles: set[str] = set()
    out: list[NewsItem] = []

    for ticker in tickers:
        try:
            raw_list = yf.Ticker(ticker).news or []
        except Exception as exc:
            log.warning("yahoo_news_fetch_failed", ticker=ticker, error=str(exc))
            continue

        for raw in raw_list[:per_ticker_limit]:
            if not isinstance(raw, dict):
                continue
            item = _to_news_item(raw)
            if item is None:
                continue
            key = item.headline.lower().strip()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            out.append(item)

    out.sort(key=lambda n: n.published_at)
    return out


def merge_news(*sources: list[NewsItem]) -> list[NewsItem]:
    """Merge news from multiple providers (e.g. Finnhub + Yahoo), dedup by headline.

    Earlier sources win on ties (so if both Finnhub and Yahoo have the same headline,
    we keep whichever source was passed first). Output is sorted oldest-first.
    """
    seen: set[str] = set()
    merged: list[NewsItem] = []
    for source in sources:
        for item in source:
            key = item.headline.lower().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    merged.sort(key=lambda n: n.published_at)
    return merged
