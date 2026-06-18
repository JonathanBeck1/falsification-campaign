"""Fetch monetary-policy press releases from the Federal Reserve RSS feed.

Why it matters: FOMC statements, Fed-chair remarks, and rate-decision releases
move the entire market. The Fed publishes them as RSS — free, no auth, near
real-time (typically within minutes of release).

Feed used:
    https://www.federalreserve.gov/feeds/press_monetary.xml

Format is RSS 2.0. We use stdlib XML parsing — no new dependency.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
import structlog

from trader.storage.snapshot import NewsItem

log = structlog.get_logger()

_FEED_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"


def _parse_rss(xml_text: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("fed_rss_parse_failed", error=str(exc))
        return items

    channel = root.find("channel")
    if channel is None:
        return items

    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        pub_raw = (item.findtext("pubDate") or "").strip()
        desc = (item.findtext("description") or "").strip()
        if not title or not pub_raw:
            continue
        try:
            # RFC 2822 date format ("Wed, 18 May 2026 14:00:00 EST")
            published = parsedate_to_datetime(pub_raw)
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            continue
        items.append(
            NewsItem(
                headline=f"[Federal Reserve] {title}",
                summary=desc[:500],
                source="federalreserve.gov",
                published_at=published,
                sentiment=None,
            )
        )
    return items


def fetch_fed_press(
    *,
    lookback_days: int | None = None,
    timeout: float = 10.0,
) -> list[NewsItem]:
    """Fetch the Fed monetary-policy press feed. Best-effort, never raises.

    If `lookback_days` is set, filter to entries within that window.
    """
    headers = {"User-Agent": "trader (https://github.com/jonathanbeck1/falsification-campaign)"}
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            resp = client.get(_FEED_URL)
            resp.raise_for_status()
    except Exception as exc:
        log.warning("fed_rss_fetch_failed", error=str(exc))
        return []

    items = _parse_rss(resp.text)
    if lookback_days is not None and lookback_days > 0:
        cutoff = datetime.now(UTC).timestamp() - lookback_days * 86_400
        items = [i for i in items if i.published_at.timestamp() >= cutoff]
    items.sort(key=lambda n: n.published_at)
    return items
