"""Fetch macro indicators from FRED. Free, no rate limit worth caring about."""

from __future__ import annotations

from trader.config import get_settings
from trader.storage.snapshot import MacroSnapshot

# FRED series IDs
_SERIES = {
    "vix": "VIXCLS",
    "yield_10y_2y": "T10Y2Y",
    "fed_funds": "DFF",
    "cpi_yoy": "CPIAUCSL",  # we'll compute YoY in fetch
    "unemployment": "UNRATE",
}


def _latest(client, series_id: str) -> float | None:
    try:
        s = client.get_series_latest_release(series_id).dropna()
        return float(s.iloc[-1]) if len(s) else None
    except Exception:
        return None


def _latest_yoy(client, series_id: str) -> float | None:
    try:
        s = client.get_series_latest_release(series_id).dropna()
        if len(s) < 13:
            return None
        return float((s.iloc[-1] / s.iloc[-13] - 1) * 100)
    except Exception:
        return None


def fetch_macro() -> MacroSnapshot:
    """Pull latest values for our macro series. Returns an empty snapshot on failure."""
    s = get_settings()
    if s.fred_api_key is None:
        return MacroSnapshot()

    from fredapi import Fred  # lazy

    client = Fred(api_key=s.fred_api_key.get_secret_value())

    return MacroSnapshot(
        vix=_latest(client, _SERIES["vix"]),
        yield_curve_10y_2y=_latest(client, _SERIES["yield_10y_2y"]),
        fed_funds=_latest(client, _SERIES["fed_funds"]),
        cpi_yoy=_latest_yoy(client, _SERIES["cpi_yoy"]),
        unemployment=_latest(client, _SERIES["unemployment"]),
    )
