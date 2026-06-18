"""General web news adapter — broad-market RSS discovery with optional stealth article extraction.

Fills the gap in `brain/03_data_sources.md`: a real web news layer for SPY/QQQ
beyond the narrow `yfinance` slice. See `brain/17_news_web_spider_proposal.md`
for the design discussion.

Two-stage flow per source:
  1. Pull RSS with Scrapling's plain `Fetcher` (no stealth — RSS is public).
  2. Optionally enrich each item by fetching the article page with
     `StealthyFetcher` (Camoufox-backed). Off by default; opt in per source via
     `SourceConfig.fetch_full_article=True`.

Polite-scraping rules (per the brain doc):
  - identify ourselves via the `TRADER_SEC_USER_AGENT` contact email
  - log every fetch
  - any source-level failure returns [] and never breaks a run
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import structlog

from trader.storage.snapshot import NewsItem

log = structlog.get_logger()


# Keywords used to decide an article is broad-market relevant. Lowercase match
# on title + summary. Tuned for SPY/QQQ scope; not for single-name news.
INDEX_KEYWORDS: tuple[str, ...] = (
    "spy",
    "qqq",
    "s&p 500",
    "s&p500",
    "sp 500",
    "nasdaq",
    "dow jones",
    "the dow",
    "stock market",
    "wall street",
    "u.s. stocks",
    "us stocks",
    "treasur",  # treasuries / treasury yields
    "vix",
    "yield curve",
    "fed ",
    "federal reserve",
    "fomc",
    "rate cut",
    "rate hike",
    "interest rates",
    "interest-rate",
    "inflation",
    "cpi",
    "jobs report",
    "nonfarm payroll",
)


@dataclass(frozen=True)
class SourceConfig:
    """One RSS-discoverable news source."""

    name: str  # short slug, used in logs and as source domain
    rss_url: str
    credibility: float = 0.6  # 0..1 — published sources sit between social (0.2) and regulators (0.95)
    fetch_full_article: bool = False  # if True, enrich items via StealthyFetcher
    article_selectors: tuple[str, ...] = field(default_factory=tuple)  # CSS selectors tried in order


# v0 source list. Broad-market RSS feeds only. Tweak via PR review.
DEFAULT_SOURCES: tuple[SourceConfig, ...] = (
    SourceConfig(
        name="marketwatch.com",
        rss_url="https://feeds.content.dowjones.io/public/rss/mw_topstories",
        credibility=0.7,
    ),
    SourceConfig(
        name="cnbc.com",
        rss_url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147",
        credibility=0.7,
    ),
)


def _user_agent() -> str:
    """Identify ourselves the same way the SEC adapter does."""
    from trader.config import get_settings

    try:
        ua = get_settings().sec_user_agent
    except Exception:
        ua = None
    return ua or "trader (research)"


def _is_relevant(title: str, summary: str) -> bool:
    blob = f"{title} {summary}".lower()
    return any(k in blob for k in INDEX_KEYWORDS)


def _parse_rss(xml_text: str) -> list[tuple[str, str, str, datetime]]:
    """Parse RSS 2.0 channel into (title, link, description, published_at) tuples."""
    out: list[tuple[str, str, str, datetime]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("web_rss_parse_failed", error=str(exc))
        return out

    channel = root.find("channel")
    if channel is None:
        return out

    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub_raw = (item.findtext("pubDate") or "").strip()
        if not title or not pub_raw:
            continue
        try:
            published = parsedate_to_datetime(pub_raw)
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            continue
        out.append((title, link, desc, published))
    return out


def _fetch_rss(source: SourceConfig, timeout: float = 10.0) -> str | None:
    """Pull the RSS feed. Returns the XML text, or None on any failure.

    NOTE: Scrapling parses RSS as HTML and `resp.text` returns the root-element
    text (empty for XML). The raw XML lives in `resp.body` as bytes — decode it.
    """
    from scrapling import Fetcher  # lazy — keeps import light at module load

    try:
        resp = Fetcher.get(source.rss_url, timeout=timeout, headers={"User-Agent": _user_agent()})
        if getattr(resp, "status", 0) != 200:
            log.warning("web_rss_bad_status", source=source.name, status=getattr(resp, "status", None))
            return None
        body = getattr(resp, "body", None)
        if isinstance(body, bytes):
            return body.decode("utf-8", errors="replace")
        if isinstance(body, str):
            return body
        text = getattr(resp, "text", None)
        return text or None
    except Exception as exc:
        log.warning("web_rss_fetch_failed", source=source.name, error=str(exc))
        return None


def _fetch_article_body(url: str, selectors: tuple[str, ...]) -> str:
    """Stealth-fetch the article URL and extract main text. Returns '' on any failure."""
    from scrapling.fetchers import StealthyFetcher  # lazy — Camoufox is a heavy import

    try:
        page = StealthyFetcher.fetch(url, headless=True, disable_resources=True, timeout=30)
        if getattr(page, "status", 0) != 200:
            log.warning("web_article_bad_status", url=url, status=getattr(page, "status", None))
            return ""
        for sel in selectors or ("article", "main", "[itemprop='articleBody']"):
            try:
                node = page.css_first(sel)
            except Exception:
                node = None
            if node is not None:
                text = (getattr(node, "text", "") or "").strip()
                if text:
                    return text
        return ""
    except Exception as exc:
        log.warning("web_article_fetch_failed", url=url, error=str(exc))
        return ""


def fetch_web_news(
    sources: tuple[SourceConfig, ...] | None = None,
    *,
    lookback_days: int | None = 3,
    per_source_limit: int = 30,
) -> list[NewsItem]:
    """Fetch broad-market news from the configured RSS sources.

    Best-effort: any one source failing returns [] for that source and the run
    continues. Items are deduplicated by (host, title) within this call.
    """
    sources = sources or DEFAULT_SOURCES
    cutoff_ts = None
    if lookback_days is not None and lookback_days > 0:
        cutoff_ts = datetime.now(UTC).timestamp() - lookback_days * 86_400

    seen: set[tuple[str, str]] = set()
    items: list[NewsItem] = []
    ua = _user_agent()

    for source in sources:
        xml_text = _fetch_rss(source)
        if xml_text is None:
            continue
        rows = _parse_rss(xml_text)
        log.info("web_rss_parsed", source=source.name, count=len(rows), user_agent=ua)
        kept = 0
        for title, link, desc, published in rows:
            if cutoff_ts is not None and published.timestamp() < cutoff_ts:
                continue
            if not _is_relevant(title, desc):
                continue
            host = urlparse(link).netloc or source.name
            dedup_key = (host, title.lower())
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            body = desc
            if source.fetch_full_article and link:
                extracted = _fetch_article_body(link, source.article_selectors)
                if extracted:
                    body = extracted

            items.append(
                NewsItem(
                    headline=title,
                    summary=body[:1000],
                    source=source.name,
                    published_at=published,
                    sentiment=None,
                )
            )
            kept += 1
            if kept >= per_source_limit:
                break
        log.info("web_rss_kept", source=source.name, kept=kept)

    items.sort(key=lambda n: n.published_at)
    return items
