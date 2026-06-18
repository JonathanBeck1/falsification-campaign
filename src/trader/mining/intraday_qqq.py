"""Intraday QQQ data loading, daily features, and mining variants."""

from __future__ import annotations

from datetime import time
from pathlib import Path

import pandas as pd
import structlog

from trader.config import intraday_lake_root
from trader.mining.strategies import Variant

log = structlog.get_logger(__name__)

# Override via TRADER_LAKE_ROOT; repo-relative default (lake not shipped).
LAKE_DEFAULT = intraday_lake_root()
CACHE_PATH = (
    Path(__file__).resolve().parents[3]
    / "output"
    / "catalysts"
    / "qqq_intraday_minute.parquet"
)

_FEATURE_COLUMNS = [
    "open",
    "close",
    "first30_open",
    "first30_close",
    "last30_open",
    "lunch_start_px",
    "lunch_end_px",
    "open_to_close_ret",
    "open_to_first30_ret",
    "last30_to_close_ret",
    "lunchtime_ret",
    "overnight_ret",
    "first30_to_close_ret",
    "post_lunch_ret",
]


def _empty_minute_frame() -> pd.DataFrame:
    frame = pd.DataFrame({"px": pd.Series(dtype=float)})
    frame.index = pd.DatetimeIndex([], name="ts")
    return frame


def _normalize_minute_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return _empty_minute_frame()
    normalized = frame.copy()
    if "ts" in normalized.columns:
        normalized["ts"] = pd.to_datetime(normalized["ts"])
        normalized = normalized.set_index("ts")
    normalized.index = pd.DatetimeIndex(normalized.index, name="ts")
    normalized["px"] = pd.to_numeric(normalized["px"], errors="coerce")
    return normalized[["px"]].dropna().sort_index()


def _filter_window(
    frame: pd.DataFrame,
    since: str | None,
    until: str | None,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    dates = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    mask = pd.Series(True, index=frame.index)
    if since is not None:
        mask &= dates >= pd.Timestamp(since).normalize()
    if until is not None:
        mask &= dates <= pd.Timestamp(until).normalize()
    return frame.loc[mask.to_numpy()]


def _cache_covers_window(
    frame: pd.DataFrame,
    since: str | None,
    until: str | None,
) -> bool:
    if frame.empty:
        return False
    dates = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    starts_early_enough = since is None or dates.min() <= pd.Timestamp(since).normalize()
    ends_late_enough = until is None or dates.max() >= pd.Timestamp(until).normalize()
    return starts_early_enough and ends_late_enough


def _extract_one_day(date_str: str, lake: Path) -> pd.DataFrame:
    """Return minute underlying prices for one lake trade-date partition."""
    import duckdb

    # BUG FIX: a single option contract can have a stale `underlying_price`
    # stamped at the open minute (e.g. 535.79 vs true ~483 on QQQ 2024-09-19),
    # which max() picks up — producing fake +14% overnight gaps and impossible
    # Sharpe ratios in any strategy using `open` price. Use median per minute,
    # which is robust to per-contract outliers.
    q = (
        "select cast(quote_ts as timestamp) ts, "
        "quantile_cont(underlying_price, 0.5) px "
        f"from read_parquet('{lake}/trade_date={date_str}/*.parquet') "
        "where underlying_price is not null group by quote_ts order by quote_ts"
    )
    return duckdb.sql(q).df()


def load_intraday_qqq(
    since: str | None = None,
    until: str | None = None,
    lake: Path = LAKE_DEFAULT,
    cache: Path = CACHE_PATH,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Load minute QQQ underlying prices from cache or the option-quote lake."""
    cached = _empty_minute_frame()
    if use_cache and cache.exists():
        try:
            cached = _normalize_minute_frame(pd.read_parquet(cache))
            if _cache_covers_window(cached, since, until):
                return _filter_window(cached, since, until)
        except Exception as exc:
            log.warning(
                "intraday_qqq_cache_read_failed",
                path=str(cache),
                error=str(exc),
            )
            cached = _empty_minute_frame()

    if not lake.exists():
        log.warning("intraday_qqq_lake_missing", path=str(lake))
        return _filter_window(cached, since, until)

    try:
        date_dirs = sorted(
            path
            for path in lake.glob("trade_date=????-??-??")
            if path.is_dir()
        )
    except Exception as exc:
        log.warning(
            "intraday_qqq_lake_scan_failed",
            path=str(lake),
            error=str(exc),
        )
        return _filter_window(cached, since, until)

    start = pd.Timestamp(since).date() if since is not None else None
    end = pd.Timestamp(until).date() if until is not None else None
    frames: list[pd.DataFrame] = []
    for date_dir in date_dirs:
        date_str = date_dir.name.removeprefix("trade_date=")
        try:
            trade_date = pd.Timestamp(date_str).date()
        except ValueError:
            log.warning("intraday_qqq_invalid_partition", path=str(date_dir))
            continue
        if start is not None and trade_date < start:
            continue
        if end is not None and trade_date > end:
            continue
        try:
            day = _extract_one_day(date_str, lake)
            if not day.empty:
                frames.append(day)
        except Exception as exc:
            log.warning(
                "intraday_qqq_day_failed",
                date=date_str,
                error=str(exc),
            )

    if not frames:
        return _filter_window(cached, since, until)

    extracted = _normalize_minute_frame(pd.concat(frames, ignore_index=True))
    combined = _normalize_minute_frame(pd.concat([cached, extracted]))
    combined = combined[~combined.index.duplicated(keep="last")]
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(cache)
    except Exception as exc:
        log.warning(
            "intraday_qqq_cache_write_failed",
            path=str(cache),
            error=str(exc),
        )
    return _filter_window(combined, since, until)


def _localize_index(index: pd.DatetimeIndex, tz: str) -> pd.DatetimeIndex:
    if index.tz is not None:
        return index.tz_convert(tz)
    try:
        return index.tz_localize(
            tz,
            ambiguous="infer",
            nonexistent="shift_forward",
        )
    except Exception as exc:
        log.warning(
            "intraday_qqq_localize_failed",
            timezone=tz,
            error=str(exc),
        )
        return index.tz_localize("UTC").tz_convert(tz)


def _price_near(
    session: pd.Series,
    target: time,
    *,
    tolerance_minutes: int = 5,
) -> float:
    target_ts = session.index[0].normalize() + pd.Timedelta(
        hours=target.hour,
        minutes=target.minute,
    )
    distances = (session.index - target_ts).to_series(index=session.index).abs()
    nearest = distances.idxmin()
    if distances.loc[nearest] > pd.Timedelta(minutes=tolerance_minutes):
        return float("nan")
    return float(session.loc[nearest])


def _safe_return(end: float, start: float) -> float:
    if pd.isna(start) or pd.isna(end) or start == 0:
        return float("nan")
    return end / start - 1.0


def compute_daily_features(
    minute_df: pd.DataFrame,
    *,
    tz: str = "America/New_York",
) -> pd.DataFrame:
    """Compute daily intraday-window returns from minute QQQ prices."""
    if minute_df.empty or "px" not in minute_df.columns:
        return pd.DataFrame(
            columns=_FEATURE_COLUMNS,
            index=pd.DatetimeIndex([], name="session_date"),
            dtype=float,
        )

    frame = minute_df[["px"]].copy()
    frame.index = _localize_index(pd.DatetimeIndex(frame.index), tz)
    frame["px"] = pd.to_numeric(frame["px"], errors="coerce")
    frame = frame.dropna().sort_index()
    if frame.empty:
        return pd.DataFrame(
            columns=_FEATURE_COLUMNS,
            index=pd.DatetimeIndex([], name="session_date"),
            dtype=float,
        )

    rows: list[dict[str, float | pd.Timestamp]] = []
    for session_date, group in frame.groupby(frame.index.date):
        session = group.loc[
            (group.index.time >= time(9, 30))
            & (group.index.time <= time(16, 0)),
            "px",
        ]
        if session.empty:
            continue
        open_px = float(session.iloc[0])
        close_px = float(session.iloc[-1])
        first30_close = _price_near(session, time(10, 0))
        lunch_start = _price_near(session, time(11, 30))
        lunch_end = _price_near(session, time(13, 30))
        last30_open = _price_near(session, time(15, 30))
        rows.append(
            {
                "session_date": pd.Timestamp(session_date),
                "open": open_px,
                "close": close_px,
                "first30_open": open_px,
                "first30_close": first30_close,
                "last30_open": last30_open,
                "lunch_start_px": lunch_start,
                "lunch_end_px": lunch_end,
                "open_to_close_ret": _safe_return(close_px, open_px),
                "open_to_first30_ret": _safe_return(first30_close, open_px),
                "last30_to_close_ret": _safe_return(close_px, last30_open),
                "lunchtime_ret": _safe_return(lunch_end, lunch_start),
                "first30_to_close_ret": _safe_return(close_px, first30_close),
                "post_lunch_ret": _safe_return(close_px, lunch_end),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=_FEATURE_COLUMNS,
            index=pd.DatetimeIndex([], name="session_date"),
            dtype=float,
        )

    features = pd.DataFrame(rows).set_index("session_date").sort_index()
    features["overnight_ret"] = features["open"] / features["close"].shift(1) - 1.0
    return features[_FEATURE_COLUMNS].astype(float)


def _variant_returns(returns: pd.Series) -> pd.Series:
    daily = pd.to_numeric(returns, errors="coerce").astype(float).dropna()
    daily.index = pd.DatetimeIndex(daily.index)
    return daily


def generate_intraday_variants(
    features: pd.DataFrame,
    *,
    ticker: str = "QQQ",
) -> list[Variant]:
    """Build same-day and next-day daily-return variants without look-ahead."""
    variants = [
        Variant(
            f"overnight_long_qqq_{ticker}",
            ticker,
            "overnight",
            _variant_returns(features["overnight_ret"]),
        ),
        Variant(
            f"intraday_short_qqq_{ticker}",
            ticker,
            "intraday_short",
            _variant_returns(-features["open_to_close_ret"]),
        ),
    ]

    first30_signal = features["open_to_first30_ret"]
    first30_future = features["first30_to_close_ret"]
    for threshold in (0.0, 0.003, 0.005):
        momentum = (first30_signal > threshold).astype(float)
        reversal = (first30_signal < -threshold).astype(float)
        variants.extend(
            [
                Variant(
                    f"first30_mom_{threshold:.3f}_{ticker}",
                    ticker,
                    "first30_momentum_reversal",
                    _variant_returns(momentum * first30_future),
                ),
                Variant(
                    f"first30_rev_{threshold:.3f}_{ticker}",
                    ticker,
                    "first30_momentum_reversal",
                    _variant_returns(reversal * first30_future),
                ),
            ]
        )

    overnight = features["overnight_ret"]
    last30_signal = features["last30_to_close_ret"]
    for threshold in (0.0, 0.002, 0.005):
        position = (last30_signal > threshold).astype(float)
        variants.append(
            Variant(
                f"last30_mom_overnight_{threshold:.3f}_{ticker}",
                ticker,
                "last30_momentum_overnight",
                _variant_returns(position.shift(1) * overnight),
            )
        )

    for threshold in (-0.003, -0.005, -0.008):
        position = (features["lunchtime_ret"] < threshold).astype(float)
        variants.append(
            Variant(
                f"lunch_rev_{threshold:.3f}_{ticker}",
                ticker,
                "lunchtime_reversion",
                _variant_returns(position * features["post_lunch_ret"]),
            )
        )

    overnight_sign = features["overnight_ret"].apply(
        lambda value: 1.0 if value > 0 else (-1.0 if value < 0 else 0.0)
    )
    for threshold in (0.005, 0.010, 0.015):
        position = -overnight_sign.where(
            features["overnight_ret"].abs() > threshold,
            0.0,
        )
        variants.append(
            Variant(
                f"gap_fade_{threshold:.3f}_{ticker}",
                ticker,
                "open_gap_fade",
                _variant_returns(position * features["open_to_close_ret"]),
            )
        )

    return variants
