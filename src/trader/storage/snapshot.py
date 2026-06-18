"""Bundles all data sources into a DailySnapshot — what every brain sees."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from trader.storage.utc import ensure_utc


class Bar(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @field_validator("timestamp", mode="after")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class NewsItem(BaseModel):
    headline: str
    summary: str = ""
    source: str = ""
    published_at: datetime
    sentiment: float | None = None  # -1..1 if provider gave us a score

    @field_validator("published_at", mode="after")
    @classmethod
    def _normalize_published_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class MacroSnapshot(BaseModel):
    """Whatever FRED series we care about. All optional — missing fields don't kill us."""

    vix: float | None = None
    yield_curve_10y_2y: float | None = None  # 10y minus 2y spread
    fed_funds: float | None = None
    cpi_yoy: float | None = None
    unemployment: float | None = None


class DailySnapshot(BaseModel):
    """Everything a brain sees for a single decision."""

    snapshot_id: str
    trade_date: date
    ticker: str

    # Price context
    latest_bar: Bar
    recent_bars: list[Bar] = Field(default_factory=list)  # last ~252 daily bars

    # Derived technicals (computed once so brains share)
    sma_50: float | None = None
    sma_200: float | None = None
    rsi_14: float | None = None
    realized_vol_20d: float | None = None

    # News
    news: list[NewsItem] = Field(default_factory=list)

    # Macro
    macro: MacroSnapshot = Field(default_factory=MacroSnapshot)

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _compute_sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _compute_rsi(closes: list[float], window: int = 14) -> float | None:
    if len(closes) < window + 1:
        return None
    gains, losses = [], []
    for i in range(-window, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(-diff)
    avg_gain = sum(gains) / window if gains else 0.0
    avg_loss = sum(losses) / window if losses else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_realized_vol(closes: list[float], window: int = 20) -> float | None:
    if len(closes) < window + 1:
        return None
    rets = [closes[i] / closes[i - 1] - 1 for i in range(-window, 0)]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    # annualized
    return (var**0.5) * (252**0.5)


def build_snapshot(
    *,
    ticker: str,
    trade_date: date,
    bars: list[Bar],
    news: list[NewsItem],
    macro: MacroSnapshot,
) -> DailySnapshot:
    if not bars:
        raise ValueError("build_snapshot needs at least one bar")
    latest = bars[-1]
    closes = [b.close for b in bars]
    snapshot_id = f"{datetime.now(UTC).isoformat(timespec='seconds')}:{ticker}"
    return DailySnapshot(
        snapshot_id=snapshot_id,
        trade_date=trade_date,
        ticker=ticker,
        latest_bar=latest,
        recent_bars=bars,
        sma_50=_compute_sma(closes, 50),
        sma_200=_compute_sma(closes, 200),
        rsi_14=_compute_rsi(closes, 14),
        realized_vol_20d=_compute_realized_vol(closes, 20),
        news=news,
        macro=macro,
    )
