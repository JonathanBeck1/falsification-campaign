"""Deribit DVOL implied-vol index fetch (free, no API key) — T32 crypto VRP.

Thin, best-effort fetch wrapper around Deribit's public REST DVOL endpoint,
mirroring the injectable-``HttpGetter`` seam in ``crypto_data.py`` so every unit
test opens no socket. Network failures log and return ``None``/empty — never
raise.

### Provenance (preregistration §3)

DVOL is Deribit's **model-free 30-day forward implied-volatility index** for
BTC and ETH (their VIX analog), published in annualized vol points. We read
``GET /api/v2/public/get_volatility_index_data`` (daily resolution, OHLC) and
keep the **close** of each UTC day. Verified live: the index history begins
**2021-03-24** for both currencies (it did not exist earlier — the hard data
wall). The endpoint returns at most ~1000 rows per call, so the fetcher
**paginates** backward across the requested span.

The DVOL level is Deribit's own published index — not a derived/parity series —
so it passes the provenance check (taxonomy class 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

import pandas as pd
import structlog

log = structlog.get_logger()

DVOL_URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
DAY_MS = 86_400_000
# Deribit caps a single response near 1000 rows; page below that to be safe.
PAGE_DAYS = 900
# Verified live: DVOL history begins here for both BTC and ETH (the data wall).
DVOL_INCEPTION = date(2021, 3, 24)


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    json_body: dict | None = None


class HttpGetter(Protocol):
    """Injectable seam: ``GET url`` with params -> response (test-friendly)."""

    def __call__(self, url: str, *, params: dict | None = None) -> HttpResponse: ...


def _httpx_getter(url: str, *, params: dict | None = None) -> HttpResponse:
    """Default getter backed by ``httpx`` (imported lazily, only when called)."""

    import httpx

    resp = httpx.get(url, params=params or {}, timeout=60.0, follow_redirects=True)
    body: dict | None
    try:
        body = resp.json()
    except ValueError:
        body = None
    return HttpResponse(status_code=resp.status_code, json_body=body)


# --------------------------------------------------------------------------- #
# PURE parse core
# --------------------------------------------------------------------------- #
def parse_dvol_payload(body: dict | None) -> pd.Series | None:
    """PURE: a Deribit DVOL JSON body -> daily close Series (vol points), or None.

    Body shape: ``{"result": {"data": [[ts_ms, open, high, low, close], ...]}}``.
    We keep the **close** indexed by UTC day (tz-naive, normalized). Empty/
    malformed bodies yield ``None``.
    """

    if not isinstance(body, dict):
        return None
    rows = (body.get("result") or {}).get("data") or []
    times: list[pd.Timestamp] = []
    closes: list[float] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        try:
            ts = int(row[0])
            close = float(row[4])
        except (ValueError, TypeError):
            continue
        if close != close or close <= 0:  # NaN / non-positive guard
            continue
        times.append(pd.Timestamp(ts, unit="ms", tz="UTC").tz_convert("UTC").tz_localize(None).normalize())
        closes.append(close)
    if not closes:
        return None
    s = pd.Series(closes, index=pd.DatetimeIndex(times), name="dvol")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s if not s.empty else None


# --------------------------------------------------------------------------- #
# Thin fetch wrapper (paginated, never raises)
# --------------------------------------------------------------------------- #
def _fetch_page(
    currency: str, start_ms: int, end_ms: int, http_get: HttpGetter | None
) -> pd.Series | None:
    getter = http_get or _httpx_getter
    params = {
        "currency": currency,
        "start_timestamp": start_ms,
        "end_timestamp": end_ms,
        "resolution": "86400",
    }
    try:
        resp = getter(DVOL_URL, params=params)
    except Exception as exc:  # never raise out of the fetch layer
        log.warning("dvol_fetch_failed", currency=currency, error=str(exc))
        return None
    if resp.status_code != 200:
        log.warning("dvol_bad_status", currency=currency, status=resp.status_code)
        return None
    return parse_dvol_payload(resp.json_body)


def fetch_dvol_history(
    currency: str,
    start: date,
    end: date,
    *,
    http_get: HttpGetter | None = None,
) -> pd.Series | None:
    """Fetch the daily DVOL close Series (vol points) for ``currency`` over span.

    Clamps ``start`` to the verified inception (2021-03-24) and paginates in
    ``PAGE_DAYS`` chunks (the endpoint caps ~1000 rows/call). Concatenates,
    de-duplicates, sorts. Returns ``None`` if no page served data. Best-effort.
    """

    lo = max(start, DVOL_INCEPTION)
    if lo > end:
        return None
    parts: list[pd.Series] = []
    cur = lo
    while cur <= end:
        page_end = min(end, cur + timedelta(days=PAGE_DAYS))
        s_ms = int(datetime(cur.year, cur.month, cur.day, tzinfo=UTC).timestamp() * 1000)
        e_ms = int(datetime(page_end.year, page_end.month, page_end.day,
                            tzinfo=UTC).timestamp() * 1000) + DAY_MS
        page = _fetch_page(currency, s_ms, e_ms, http_get)
        if page is not None:
            parts.append(page)
        cur = page_end + timedelta(days=1)
    if not parts:
        return None
    out = pd.concat(parts)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.name = currency
    return out


def utc_today() -> date:
    return datetime.now(UTC).date()
