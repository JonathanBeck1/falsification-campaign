"""Fetch daily OHLCV bars from Alpaca."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from trader.config import get_settings
from trader.storage.snapshot import Bar


def fetch_daily_bars(ticker: str, lookback_days: int = 300) -> list[Bar]:
    """Return up to `lookback_days` daily bars ending at the most recent trading day.

    Uses alpaca-py's StockHistoricalDataClient. Free Alpaca data is sufficient for
    EOD bars on ETFs like SPY/QQQ.
    """
    # Imported lazily so unit tests can mock without needing the dep installed.
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    s = get_settings()
    client = StockHistoricalDataClient(s.alpaca_key_id, s.alpaca_secret_key)

    end = datetime.now(UTC)
    start = end - timedelta(days=int(lookback_days * 1.5))  # buffer for weekends/holidays
    req = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    resp = client.get_stock_bars(req)
    raw = resp.data.get(ticker, [])
    bars = [
        Bar(
            timestamp=b.timestamp,
            open=float(b.open),
            high=float(b.high),
            low=float(b.low),
            close=float(b.close),
            volume=float(b.volume),
        )
        for b in raw
    ]
    return bars[-lookback_days:]


def latest_close(ticker: str) -> tuple[date, float]:
    """Convenience for execution: last close price + its date."""
    bars = fetch_daily_bars(ticker, lookback_days=5)
    if not bars:
        raise RuntimeError(f"No bars for {ticker}")
    last = bars[-1]
    return last.timestamp.date(), last.close


def fetch_intraday_bars(
    ticker: str,
    start: datetime,
    end: datetime,
    *,
    minutes: int = 5,
) -> list[Bar]:
    """Return minute-bars (default 5-minute) between [start, end].

    Used by the event-window research harness in `trader.backtesting.event_window`.
    Alpaca's free data tier serves IEX-feed intraday with delay; sufficient for
    historical research, NOT for live intraday signals.
    """
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    s = get_settings()
    client = StockHistoricalDataClient(s.alpaca_key_id, s.alpaca_secret_key)
    req = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame(minutes, TimeFrameUnit.Minute),
        start=start,
        end=end,
    )
    resp = client.get_stock_bars(req)
    raw = resp.data.get(ticker, [])
    return [
        Bar(
            timestamp=b.timestamp,
            open=float(b.open),
            high=float(b.high),
            low=float(b.low),
            close=float(b.close),
            volume=float(b.volume),
        )
        for b in raw
    ]
