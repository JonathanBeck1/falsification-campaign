"""DoltHub `post-no-preference/options` adapter."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

from trader.options.models import OptionQuote, VolatilityHistoryRow

_SAFE_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,15}$")


class DoltHubOptionsClient:
    """Small SQL API client for the free DoltHub options dataset."""

    def __init__(
        self,
        *,
        endpoint: str = "https://www.dolthub.com/api/v1alpha1/post-no-preference/options/master",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def query(self, sql: str) -> list[dict[str, Any]]:
        url = f"{self.endpoint}?{urllib.parse.urlencode({'q': sql})}"
        with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        status = payload.get("query_execution_status")
        if status != "Success":
            message = payload.get("query_execution_message") or "unknown DoltHub SQL error"
            raise RuntimeError(f"DoltHub query failed: {message}")
        return list(payload.get("rows") or [])

    def fetch_option_chain(self, ticker: str, *, start: str, end: str, limit: int = 100_000) -> list[OptionQuote]:
        symbol = _normalize_symbol(ticker)
        _validate_date(start, "--start")
        _validate_date(end, "--end")
        if limit < 1:
            raise ValueError("limit must be positive")
        sql = (
            "SELECT date, act_symbol, expiration, strike, call_put, bid, ask, vol, delta, gamma, theta, vega, rho "
            "FROM option_chain "
            f"WHERE act_symbol = '{symbol}' AND date >= '{start}' AND date <= '{end}' "
            "ORDER BY date, expiration, strike, call_put "
            f"LIMIT {int(limit)}"
        )
        return normalize_option_chain_rows(self.query(sql))

    def fetch_volatility_history(
        self,
        ticker: str,
        *,
        start: str,
        end: str,
        limit: int = 100_000,
    ) -> list[VolatilityHistoryRow]:
        symbol = _normalize_symbol(ticker)
        _validate_date(start, "--start")
        _validate_date(end, "--end")
        if limit < 1:
            raise ValueError("limit must be positive")
        sql = (
            "SELECT * FROM volatility_history "
            f"WHERE act_symbol = '{symbol}' AND date >= '{start}' AND date <= '{end}' "
            "ORDER BY date "
            f"LIMIT {int(limit)}"
        )
        return normalize_volatility_history_rows(self.query(sql))


def normalize_option_chain_rows(rows: list[dict[str, Any]]) -> list[OptionQuote]:
    quotes: list[OptionQuote] = []
    for row in rows:
        quotes.append(
            OptionQuote(
                trade_date=date.fromisoformat(str(row["date"])),
                ticker=str(row["act_symbol"]).upper(),
                expiration=date.fromisoformat(str(row["expiration"])),
                strike=float(row["strike"]),
                call_put=_normalize_call_put(row["call_put"]),
                bid=_optional_float(row.get("bid")),
                ask=_optional_float(row.get("ask")),
                implied_vol=_optional_float(row.get("vol")),
                delta=_optional_float(row.get("delta")),
                gamma=_optional_float(row.get("gamma")),
                theta=_optional_float(row.get("theta")),
                vega=_optional_float(row.get("vega")),
                rho=_optional_float(row.get("rho")),
            )
        )
    return quotes


def normalize_volatility_history_rows(rows: list[dict[str, Any]]) -> list[VolatilityHistoryRow]:
    return [
        VolatilityHistoryRow(
            trade_date=date.fromisoformat(str(row["date"])),
            ticker=str(row["act_symbol"]).upper(),
            hv_current=_optional_float(row.get("hv_current")),
            hv_week_ago=_optional_float(row.get("hv_week_ago")),
            hv_month_ago=_optional_float(row.get("hv_month_ago")),
            hv_year_high=_optional_float(row.get("hv_year_high")),
            hv_year_low=_optional_float(row.get("hv_year_low")),
            iv_current=_optional_float(row.get("iv_current")),
            iv_week_ago=_optional_float(row.get("iv_week_ago")),
            iv_month_ago=_optional_float(row.get("iv_month_ago")),
            iv_year_high=_optional_float(row.get("iv_year_high")),
            iv_year_low=_optional_float(row.get("iv_year_low")),
        )
        for row in rows
    ]


def _normalize_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not _SAFE_TICKER_RE.match(symbol):
        raise ValueError(f"Unsupported ticker: {value!r}")
    return symbol


def _validate_date(value: str, label: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD") from exc


def _normalize_call_put(value: Any) -> str:
    side = str(value).strip().title()
    if side not in {"Call", "Put"}:
        raise ValueError(f"Unsupported call_put value: {value!r}")
    return side


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return float(text)
