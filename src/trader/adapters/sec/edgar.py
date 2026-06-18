"""Fetch recent 8-K filings from SEC EDGAR for tracked tickers.

8-K is the "material event" form: earnings releases, M&A, dilutions, exec changes.
For broad-market ETFs (QQQ/SPY), the highest-signal SEC content is 8-Ks from the
top index constituents (AAPL, MSFT, NVDA, etc.).

SEC requirements (https://www.sec.gov/os/accessing-edgar-data):
- Must send a `User-Agent` header identifying yourself + contact email.
- Soft cap of 10 req/sec. We send one request per ticker, sequentially.
- Free, no auth.

We use SEC's per-company Atom feed:
    https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany
      &CIK={cik}&type=8-K&dateb=&owner=include&count=10&output=atom
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

import httpx
import structlog

from trader.config import get_settings
from trader.storage.snapshot import NewsItem
from trader.storage.utc import ensure_utc

log = structlog.get_logger()

# Hardcoded CIKs for the default tracked set. Adding a ticker not listed here is
# fine — it'll be skipped with a warning. Source: SEC EDGAR company search.
_CIK_MAP: dict[str, str] = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "AMZN": "0001018724",
    "META": "0001326801",
    "GOOGL": "0001652044",
    "GOOG": "0001652044",
    "TSLA": "0001318605",
    "AVGO": "0001730168",
    "BRK-B": "0001067983",
    "BRK.B": "0001067983",
    "JPM": "0000019617",
    "V": "0001403161",
    "UNH": "0000731766",
    "XOM": "0000034088",
    "JNJ": "0000200406",
    "WMT": "0000104169",
}

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _parse_atom_feed(xml_text: str, ticker: str) -> list[NewsItem]:
    """Parse SEC's Atom-XML response into NewsItems."""
    items: list[NewsItem] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("sec_edgar_parse_failed", ticker=ticker, error=str(exc))
        return items

    for entry in root.findall(f"{_ATOM_NS}entry"):
        title_el = entry.find(f"{_ATOM_NS}title")
        updated_el = entry.find(f"{_ATOM_NS}updated")
        summary_el = entry.find(f"{_ATOM_NS}summary")
        if title_el is None or updated_el is None:
            continue
        title = (title_el.text or "").strip()
        updated_raw = (updated_el.text or "").strip()
        if not title or not updated_raw:
            continue
        try:
            # SEC publishes ISO-8601 with offset, e.g. "2026-05-18T10:00:00-04:00"
            published = ensure_utc(datetime.fromisoformat(updated_raw.replace("Z", "+00:00")))
        except ValueError:
            continue
        summary_txt = (summary_el.text or "").strip() if summary_el is not None else ""
        items.append(
            NewsItem(
                headline=f"[SEC 8-K] {ticker}: {title}",
                summary=summary_txt[:500],
                source="SEC EDGAR",
                published_at=published,
                sentiment=None,
            )
        )
    return items


def fetch_sec_8k_filings(
    tickers: list[str] | None = None,
    *,
    count_per_ticker: int = 5,
    timeout: float = 10.0,
) -> list[NewsItem]:
    """Pull recent 8-K filings for `tickers`. Best-effort — never raises."""
    s = get_settings()
    user_agent = s.trader_sec_user_agent
    if not user_agent or "your-email@example.com" in user_agent:
        log.warning(
            "sec_edgar_user_agent_not_set",
            note="set TRADER_SEC_USER_AGENT='<name> <email>' or SEC may rate-limit/block",
        )
    target_tickers = tickers or s.sec_tickers
    headers = {"User-Agent": user_agent, "Accept": "application/atom+xml"}

    out: list[NewsItem] = []
    seen: set[str] = set()
    with httpx.Client(timeout=timeout, headers=headers) as client:
        for ticker in target_tickers:
            cik = _CIK_MAP.get(ticker.upper())
            if cik is None:
                log.info("sec_edgar_ticker_skipped_no_cik", ticker=ticker)
                continue
            url = (
                "https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&CIK={cik}&type=8-K"
                f"&dateb=&owner=include&count={count_per_ticker}&output=atom"
            )
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                log.warning("sec_edgar_fetch_failed", ticker=ticker, error=str(exc))
                continue
            for item in _parse_atom_feed(resp.text, ticker.upper()):
                key = item.headline.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(item)

    out.sort(key=lambda n: n.published_at)
    return out
