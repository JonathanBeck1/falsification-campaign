"""Fetch historical bars from Yahoo Finance's chart endpoint.

This is a free, no-auth fallback for early research. It is good enough to
exercise event-window reports before paying for consolidated SIP market data.
It is not a production execution feed.

Robustness notes: Yahoo's unauth chart endpoint will occasionally serve a
Cloudflare HTML challenge page on 5xx/503 or rate-limit on 429. We keep
`response.json()` inside the try/except so a non-JSON body returns `[]`
instead of crashing the runner — `cmd_research_events` defaults to the
yahoo provider, so a hard crash here breaks the entire research path.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from trader.storage.snapshot import Bar

log = structlog.get_logger()


# Retry policy for transient Yahoo failures (429 rate-limit, 5xx, network).
# More aggressive looks like abuse; less leaves us vulnerable to a single
# Cloudflare blip mid-research-run.
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _value_at(values: list[Any], index: int, default: float | None = None) -> float | None:
    try:
        value = values[index]
    except IndexError:
        return default
    if value is None:
        return default
    return float(value)


def _sleep(seconds: float) -> None:
    """Indirection so tests can patch out the sleep without timing flakes."""
    time.sleep(seconds)


def fetch_intraday_bars(
    ticker: str,
    start: datetime,
    end: datetime,
    *,
    minutes: int = 5,
    timeout: float = 15.0,
) -> list[Bar]:
    """Return intraday bars from Yahoo Finance ordered by timestamp.

    Best-effort: returns `[]` on any failure (timeout, non-JSON body,
    Cloudflare challenge page, rate-limit exhaustion) rather than raising.
    Retries up to `_MAX_ATTEMPTS` on 429 / 5xx with exponential backoff.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
    params = {
        "period1": int(start.timestamp()),
        "period2": int(end.timestamp()),
        "interval": f"{minutes}m",
        "includePrePost": "false",
        "events": "history",
    }
    headers = {"User-Agent": "trader research/0.1"}

    payload: dict | None = None
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            for attempt in range(_MAX_ATTEMPTS):
                response = client.get(url, params=params)
                if response.status_code in _RETRYABLE_STATUS:
                    log.warning(
                        "yahoo_chart_retryable_status",
                        ticker=ticker,
                        status_code=response.status_code,
                        attempt=attempt + 1,
                    )
                    if attempt + 1 < _MAX_ATTEMPTS:
                        _sleep(_BACKOFF_BASE_SECONDS * (2**attempt))
                        continue
                    log.warning("yahoo_chart_retries_exhausted", ticker=ticker, attempts=_MAX_ATTEMPTS)
                    return []
                response.raise_for_status()
                # `.json()` lives inside the try because Cloudflare's HTML
                # challenge page returns 200 with a non-JSON body. Crashing
                # the runner here used to kill the whole research-events run.
                payload = response.json()
                break
    except Exception as exc:
        log.warning("yahoo_chart_fetch_failed", ticker=ticker, error=str(exc))
        return []

    if payload is None:
        return []

    chart = payload.get("chart", {}) if isinstance(payload, dict) else {}
    if chart.get("error"):
        log.warning("yahoo_chart_error", ticker=ticker, error=chart.get("error"))
        return []
    results = chart.get("result") or []
    if not results:
        return []

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]

    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    bars: list[Bar] = []
    for index, ts in enumerate(timestamps):
        close = _value_at(closes, index)
        if close is None:
            continue
        open_ = _value_at(opens, index, close)
        high = _value_at(highs, index, close)
        low = _value_at(lows, index, close)
        volume = _value_at(volumes, index, 0.0) or 0.0
        bars.append(
            Bar(
                timestamp=datetime.fromtimestamp(int(ts), tz=UTC),
                open=open_ if open_ is not None else close,
                high=high if high is not None else close,
                low=low if low is not None else close,
                close=close,
                volume=volume,
            )
        )
    bars.sort(key=lambda bar: bar.timestamp)
    return bars
