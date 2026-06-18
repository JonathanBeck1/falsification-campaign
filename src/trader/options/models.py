"""Option data models used by research-only backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

OptionSide = Literal["Call", "Put"]


@dataclass(frozen=True)
class OptionQuote:
    """One EOD option quote/Greek row for a listed contract."""

    trade_date: date
    ticker: str
    expiration: date
    strike: float
    call_put: OptionSide
    bid: float | None
    ask: float | None
    implied_vol: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    rho: float | None

    @property
    def dte(self) -> int:
        return (self.expiration - self.trade_date).days

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return round((self.bid + self.ask) / 2.0, 4)

    @property
    def has_executable_quote(self) -> bool:
        return self.bid is not None and self.ask is not None and self.bid >= 0 and self.ask >= self.bid


@dataclass(frozen=True)
class VolatilityHistoryRow:
    """DoltHub volatility_history row normalized to the fields we need first."""

    trade_date: date
    ticker: str
    hv_current: float | None = None
    hv_week_ago: float | None = None
    hv_month_ago: float | None = None
    hv_year_high: float | None = None
    hv_year_low: float | None = None
    iv_current: float | None = None
    iv_week_ago: float | None = None
    iv_month_ago: float | None = None
    iv_year_high: float | None = None
    iv_year_low: float | None = None


@dataclass(frozen=True)
class OptionContract:
    """One listed option contract discovered from a provider contract list."""

    ticker: str
    expiration: date
    strike: float
    call_put: OptionSide

    def dte_on(self, trade_date: date) -> int:
        return (self.expiration - trade_date).days


@dataclass(frozen=True)
class OptionQuoteBar:
    """One provider-neutral intraday NBBO quote bar for a listed option contract."""

    timestamp: datetime
    ticker: str
    expiration: date
    strike: float
    call_put: OptionSide
    bid: float | None
    ask: float | None
    underlying_price: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    bid_exchange: int | None = None
    ask_exchange: int | None = None
    bid_condition: int | None = None
    ask_condition: int | None = None
    source: str = "unknown"

    @property
    def trade_date(self) -> date:
        return self.timestamp.date()

    @property
    def dte(self) -> int:
        return (self.expiration - self.trade_date).days

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return round((self.bid + self.ask) / 2.0, 4)

    @property
    def has_executable_quote(self) -> bool:
        return self.bid is not None and self.ask is not None and self.bid >= 0 and self.ask >= self.bid


@dataclass(frozen=True)
class UnderlyingQuoteBar:
    """One intraday NBBO quote bar for the underlying symbol."""

    timestamp: datetime
    ticker: str
    bid: float | None
    ask: float | None
    bid_size: int | None = None
    ask_size: int | None = None
    source: str = "unknown"

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        if self.bid < 0 or self.ask < self.bid:
            return None
        return round((self.bid + self.ask) / 2.0, 4)
