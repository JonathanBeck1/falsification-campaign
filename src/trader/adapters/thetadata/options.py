"""ThetaData options adapter.

The adapter intentionally normalizes ThetaData's Python-client dataframes into
small provider-neutral dataclasses. Backtests and storage should not depend on
ThetaData column casing, pandas/polars, or credential mechanics.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from math import isnan
from typing import Any

from trader.options.models import OptionContract, OptionQuoteBar, OptionSide, UnderlyingQuoteBar


class ThetaDataOptionsClient:
    """Small wrapper around `thetadata.ThetaClient` for option contract and quote pulls."""

    def __init__(self, *, client: Any | None = None, dataframe_type: str = "pandas", creds_file: str | None = None):
        if client is not None:
            self._client = client
            return
        try:
            from thetadata import ThetaClient
        except ImportError as exc:  # pragma: no cover - exercised only when optional dependency is absent.
            raise RuntimeError(
                "ThetaData support requires the optional `thetadata` package. "
                "Install it with `.venv/bin/python -m pip install thetadata`."
            ) from exc
        resolved_creds = (
            creds_file
            or os.environ.get("THETADATA_CREDENTIALS_FILE")
            or os.path.expanduser("~/.thetadata/creds.txt")
        )
        kwargs: dict[str, Any] = {"dataframe_type": dataframe_type}
        if resolved_creds:
            kwargs["creds_file"] = resolved_creds
        self._client = ThetaClient(**kwargs)

    def fetch_contracts(self, ticker: str, *, trade_date: date, max_dte: int) -> list[OptionContract]:
        """List contracts quoted on `trade_date`, bounded by max DTE."""
        symbol = ticker.strip().upper()
        frame = self._client.option_list_contracts(
            request_type="quote",
            symbol=symbol,
            date=trade_date,
            max_dte=max_dte,
        )
        return sorted(
            [
                OptionContract(
                    ticker=str(_row_get(row, "symbol", symbol)).upper(),
                    expiration=_parse_date(_row_get(row, "expiration")),
                    strike=float(_row_get(row, "strike")),
                    call_put=_parse_side(_row_get(row, "right")),
                )
                for row in _records(frame)
            ],
            key=lambda contract: (contract.expiration, contract.strike, contract.call_put),
        )

    def fetch_quote_history(
        self,
        ticker: str,
        *,
        trade_date: date,
        expiration: date,
        start_time: str,
        end_time: str,
        interval: str = "1m",
        strike_range: int,
        right: str = "both",
        strike: str = "*",
        max_dte: int | None = None,
    ) -> list[OptionQuoteBar]:
        """Fetch intraday NBBO quote bars for one underlying/date/expiration."""
        symbol = ticker.strip().upper()
        frame = self._client.option_history_quote(
            symbol=symbol,
            expiration=expiration,
            date=trade_date,
            interval=interval,
            strike=strike,
            right=right,
            start_time=start_time,
            end_time=end_time,
            max_dte=max_dte,
            strike_range=strike_range,
        )
        rows = [
            OptionQuoteBar(
                timestamp=_parse_datetime(_row_get(row, "timestamp")),
                ticker=str(_row_get(row, "symbol", symbol)).upper(),
                expiration=_parse_date(_row_get(row, "expiration")),
                strike=float(_row_get(row, "strike")),
                call_put=_parse_side(_row_get(row, "right")),
                bid=_optional_float(_row_get(row, "bid")),
                ask=_optional_float(_row_get(row, "ask")),
                bid_size=_optional_int(_row_get(row, "bid_size")),
                ask_size=_optional_int(_row_get(row, "ask_size")),
                bid_exchange=_optional_int(_row_get(row, "bid_exchange")),
                ask_exchange=_optional_int(_row_get(row, "ask_exchange")),
                bid_condition=_optional_int(_row_get(row, "bid_condition")),
                ask_condition=_optional_int(_row_get(row, "ask_condition")),
                source="thetadata",
            )
            for row in _records(frame)
        ]
        return sorted(rows, key=lambda quote: (quote.timestamp, quote.expiration, quote.strike, quote.call_put))

    def fetch_underlying_quote_history(
        self,
        ticker: str,
        *,
        trade_date: date,
        start_time: str,
        end_time: str,
        interval: str = "1m",
    ) -> list[UnderlyingQuoteBar]:
        """Fetch intraday NBBO quote bars for the underlying ticker."""
        symbol = ticker.strip().upper()
        frame = self._client.stock_history_quote(
            symbol=symbol,
            date=trade_date,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
        )
        rows = [
            UnderlyingQuoteBar(
                timestamp=_parse_datetime(_row_get(row, "timestamp")),
                ticker=str(_row_get(row, "symbol", symbol)).upper(),
                bid=_optional_float(_row_get(row, "bid")),
                ask=_optional_float(_row_get(row, "ask")),
                bid_size=_optional_int(_row_get(row, "bid_size")),
                ask_size=_optional_int(_row_get(row, "ask_size")),
                source="thetadata",
            )
            for row in _records(frame)
        ]
        return sorted(rows, key=lambda quote: quote.timestamp)


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if isinstance(frame, list):
        return frame
    to_dicts = getattr(frame, "to_dicts", None)
    if callable(to_dicts):
        return list(to_dicts())
    to_dict = getattr(frame, "to_dict", None)
    if callable(to_dict):
        return list(to_dict("records"))
    raise TypeError(f"Unsupported ThetaData dataframe type: {type(frame)!r}")


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    get = getattr(row, "get", None)
    if callable(get):
        return get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _parse_side(value: Any) -> OptionSide:
    raw = str(value).strip().lower()
    if raw in {"call", "c"}:
        return "Call"
    if raw in {"put", "p"}:
        return "Put"
    raise ValueError(f"Unsupported option right: {value!r}")


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if isnan(parsed) else parsed


def _optional_int(value: Any) -> int | None:
    parsed = _optional_float(value)
    return None if parsed is None else int(parsed)
