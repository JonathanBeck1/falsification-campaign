"""Best-effort daily price fetch for catalyst event studies (via yfinance).

Returns split/dividend-adjusted closes (correct for return calculations) and raw
volume. Network-bound and best-effort: any failure logs a warning and returns
``None`` so the study can skip the name and keep going.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import structlog

log = structlog.get_logger()


def fetch_daily(ticker: str, start: date, end: date) -> tuple[pd.Series, pd.Series] | None:
    """Return ``(adj_close, volume)`` daily series for ``ticker`` in ``[start, end]``.

    ``None`` if the download fails or yields no rows. Series are indexed by date,
    ascending, named ``ticker``.
    """

    try:
        import yfinance as yf

        df = yf.download(
            ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        log.warning("prices_fetch_failed", ticker=ticker, error=str(exc))
        return None

    if df is None or df.empty:
        return None

    # yfinance may return MultiIndex columns (field, ticker) even for one symbol.
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(axis=1, level=1)

    if "Close" not in df.columns or "Volume" not in df.columns:
        log.warning("prices_unexpected_columns", ticker=ticker, columns=list(df.columns))
        return None

    close = df["Close"].dropna()
    volume = df["Volume"].reindex(close.index)
    close = close.sort_index()
    close.name = ticker
    volume = volume.sort_index()
    volume.name = ticker
    if close.empty:
        return None
    return close, volume
