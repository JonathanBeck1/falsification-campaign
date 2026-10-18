"""Tiingo EOD price client — fetches daily closes including for DELISTED tickers.

The whole reason this exists: yfinance *purges* delisted symbols, which are
exactly the resolved CEF "winners" (liquidated / merged / open-ended funds) that
a discount-capture backtest most needs. Tiingo **retains** delisted tickers'
historical EOD, so it is the price provider of last resort for the survivors.

Contract mirrors ``catalysts/prices.py``: ``fetch_daily(ticker, start, end)``
returns ``(adj_close, ...)`` or ``None``. Best-effort throughout — any failure
(no key, HTTP error, empty body, bad shape) logs a warning and returns ``None``
so the caller can fall back or skip the name without crashing.

The API key is read from ``TIINGO_API_KEY`` at call time. It is **never**
hardcoded; with no key we log once and return ``None`` (the backtest then runs on
yfinance-only coverage and says so). The HTTP call sits behind an injectable
``HttpGetter`` seam so unit tests are fully network-free.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd
import structlog

log = structlog.get_logger()

TIINGO_BASE = "https://api.tiingo.com/tiingo/daily"
_ENV_KEY = "TIINGO_API_KEY"


@dataclass(frozen=True)
class HttpResponse:
    """Minimal HTTP response shape the client depends on (test-friendly)."""

    status_code: int
    json_body: object


class HttpGetter(Protocol):
    """Injectable seam: ``GET url`` with query params + headers -> response.

    The real implementation wraps ``httpx``; tests pass a stub so no socket is
    ever opened. Implementations must not raise — they translate failures into a
    non-200 ``HttpResponse`` (or the client treats raises as a fetch failure).
    """

    def __call__(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> HttpResponse: ...


def _httpx_getter(
    url: str,
    *,
    params: dict[str, str],
    headers: dict[str, str],
) -> HttpResponse:
    """Default getter backed by ``httpx`` (only imported when actually called)."""

    import httpx

    resp = httpx.get(url, params=params, headers=headers, timeout=30.0)
    try:
        body: object = resp.json()
    except Exception:
        body = None
    return HttpResponse(status_code=resp.status_code, json_body=body)


def _api_key() -> str | None:
    key = os.environ.get(_ENV_KEY, "").strip()
    return key or None


def parse_prices(rows: object, ticker: str) -> pd.Series | None:
    """PURE: turn Tiingo's JSON array into an adjusted-close Series, or ``None``.

    Tiingo returns a list of ``{"date": "...T00:00:00.000Z", "adjClose": ...}``
    dicts (plus raw ``close`` and other fields). We prefer ``adjClose`` (split &
    dividend adjusted — correct for return math) and fall back to ``close`` only
    if ``adjClose`` is absent. Output is indexed by date, ascending, named
    ``ticker``; empty/malformed input yields ``None``.
    """

    if not isinstance(rows, list) or not rows:
        return None

    dates: list[pd.Timestamp] = []
    values: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_date = row.get("date")
        price = row.get("adjClose", row.get("close"))
        if raw_date is None or price is None:
            continue
        try:
            ts = pd.Timestamp(raw_date)
            val = float(price)
        except (ValueError, TypeError):
            continue
        if ts is None or val != val:  # NaT / NaN guard
            continue
        # Tiingo timestamps are midnight-UTC; normalize to a tz-naive date.
        dates.append(ts.tz_localize(None).normalize() if ts.tzinfo else ts.normalize())
        values.append(val)

    if not values:
        return None

    series = pd.Series(values, index=pd.DatetimeIndex(dates), name=ticker)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series if not series.empty else None


def parse_raw_close(rows: object, ticker: str) -> pd.Series | None:
    """PURE: ``parse_prices`` on raw ``close`` only; ``adjClose`` is back-adjusted for distributions, skewing price/NAV."""

    if not isinstance(rows, list):
        return None
    close_only = [{"date": r.get("date"), "close": r.get("close")} for r in rows if isinstance(r, dict)]
    return parse_prices(close_only, ticker)


def fetch_daily(
    ticker: str,
    start: date,
    end: date,
    *,
    http_get: HttpGetter | None = None,
) -> tuple[pd.Series] | None:
    """Return ``(adj_close,)`` daily series for ``ticker`` in ``[start, end]``.

    ``None`` when the key is missing, the request fails, or the body is empty /
    malformed. Returned as a 1-tuple to mirror ``prices.fetch_daily``'s
    multi-series contract and leave room for volume later without a breaking
    change. The series is indexed by date, ascending, named ``ticker``.
    """

    key = _api_key()
    if key is None:
        log.warning(
            "tiingo_no_api_key",
            ticker=ticker,
            hint="get a free key at tiingo.com, then `export TIINGO_API_KEY=...`",
        )
        return None

    getter = http_get or _httpx_getter
    url = f"{TIINGO_BASE}/{ticker}/prices"
    params = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "format": "json",
        "token": key,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {key}",
    }

    try:
        resp = getter(url, params=params, headers=headers)
    except Exception as exc:  # best-effort: never propagate a fetch failure
        log.warning("tiingo_fetch_failed", ticker=ticker, error=str(exc))
        return None

    if resp.status_code != 200:
        log.warning("tiingo_bad_status", ticker=ticker, status=resp.status_code)
        return None

    series = parse_prices(resp.json_body, ticker)
    if series is None:
        log.warning("tiingo_empty_or_malformed", ticker=ticker)
        return None

    log.info("tiingo_fetched", ticker=ticker, rows=len(series))
    return (series,)
