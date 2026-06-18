"""Cross-asset signal families for the strategy-mining lab."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

import pandas as pd
import structlog

from trader.mining.strategies import Variant

logger = structlog.get_logger(__name__)

TARGETS = ("SPY", "QQQ")
_THRESHOLDS = (0.5, 1.0)


@dataclass(frozen=True)
class SignalSpec:
    name: str
    family: str
    target: str
    required: tuple[str, ...]


def _align(*series: pd.Series) -> pd.DataFrame:
    """Outer-join series on their date indexes and retain complete rows."""
    return pd.concat(series, axis=1, join="outer").dropna()


def _zscore(s: pd.Series, window: int) -> pd.Series:
    mean = s.rolling(window).mean()
    sd = s.rolling(window).std(ddof=0)
    return (s - mean) / sd.replace(0.0, float("nan"))


def _realized_vol(close: pd.Series, window: int = 20) -> pd.Series:
    rets = (close / close.shift(1)).apply(
        lambda x: math.log(x) if x and x > 0 else float("nan")
    )
    return rets.rolling(window).std(ddof=0) * math.sqrt(252)


def _apply_position(target_close: pd.Series, position: pd.Series) -> pd.Series:
    """Apply yesterday's signal position to today's target return."""
    asset_ret = target_close.pct_change()
    pos_aligned = position.reindex(target_close.index).ffill().fillna(0.0)
    return (pos_aligned.shift(1) * asset_ret).dropna()


def _load_required(
    prices: dict[str, pd.Series],
    spec: SignalSpec,
) -> pd.DataFrame | None:
    missing = tuple(ticker for ticker in spec.required if ticker not in prices)
    if missing:
        logger.debug("multi_asset_signal_skipped", signal=spec.name, missing=missing)
        return None
    aligned = _align(*(prices[ticker].rename(ticker) for ticker in spec.required))
    if len(aligned) < 260:
        logger.debug(
            "multi_asset_signal_skipped",
            signal=spec.name,
            aligned_rows=len(aligned),
        )
        return None
    return aligned


def _threshold_position(
    signal: pd.Series,
    threshold: float,
    *,
    high_position: float,
) -> pd.Series:
    valid = signal.dropna()
    position = pd.Series(0.0, index=valid.index)
    position.loc[valid > threshold] = high_position
    position.loc[valid < -threshold] = -high_position
    return position


def _returns_from_signal(target_close: pd.Series, position: pd.Series) -> pd.Series:
    return _apply_position(target_close.reindex(position.index), position)


def _threshold_suffix(threshold: float) -> str:
    return "" if threshold == 0.5 else "_t1"


def _ratio_z_variants(
    prices: dict[str, pd.Series],
    *,
    spec: SignalSpec,
    numerator: str,
    denominator: str,
    windows: tuple[int, ...],
    styles: tuple[tuple[str, float], ...],
    name_prefix: str,
) -> Iterator[Variant]:
    aligned = _load_required(prices, spec)
    if aligned is None:
        return
    ratio = (aligned[numerator] / aligned[denominator]).rename("ratio")
    for window in windows:
        z = _zscore(ratio, window)
        for style, high_position in styles:
            for threshold in _THRESHOLDS:
                position = _threshold_position(
                    z,
                    threshold,
                    high_position=high_position,
                )
                style_suffix = f"_{style}" if style else ""
                name = (
                    f"{name_prefix}_z{window}{style_suffix}_{spec.target}"
                    f"{_threshold_suffix(threshold)}"
                )
                yield Variant(
                    name,
                    spec.target,
                    spec.family,
                    _returns_from_signal(aligned[spec.target], position),
                )


def _bonds_equity_variants(
    prices: dict[str, pd.Series],
) -> Iterator[Variant]:
    spec = SignalSpec(
        "bonds_equity_ratio",
        "bonds_equity_ratio",
        "SPY",
        ("TLT", "SPY"),
    )
    yield from _ratio_z_variants(
        prices,
        spec=spec,
        numerator="TLT",
        denominator="SPY",
        windows=(60, 120, 252),
        styles=(("trend", -1.0), ("contra", 1.0)),
        name_prefix="bonds_eq",
    )


def _gold_equity_variants(
    prices: dict[str, pd.Series],
) -> Iterator[Variant]:
    spec = SignalSpec(
        "gold_equity_ratio",
        "gold_equity_ratio",
        "SPY",
        ("GLD", "SPY"),
    )
    yield from _ratio_z_variants(
        prices,
        spec=spec,
        numerator="GLD",
        denominator="SPY",
        windows=(60, 120, 252),
        styles=(("trend", -1.0), ("contra", 1.0)),
        name_prefix="gold_eq",
    )


def _vix_regime_variants(
    prices: dict[str, pd.Series],
) -> Iterator[Variant]:
    spy_spec = SignalSpec("vix_median", "vix_regime", "SPY", ("VIX", "SPY"))
    aligned = _load_required(prices, spy_spec)
    if aligned is not None:
        for window in (60, 252):
            median = aligned["VIX"].rolling(window).median()
            valid = median.dropna().index
            position = (aligned.loc[valid, "VIX"] < median.loc[valid]).astype(float)
            yield Variant(
                f"vix_below_med{window}_SPY",
                "SPY",
                "vix_regime",
                _returns_from_signal(aligned["SPY"], position),
            )

    qqq_spec = SignalSpec("vix_z252_low", "vix_regime", "QQQ", ("VIX", "QQQ"))
    aligned = _load_required(prices, qqq_spec)
    if aligned is not None:
        z = _zscore(aligned["VIX"].rename("VIX"), 252)
        valid = z.dropna()
        position = (valid < 0.0).astype(float)
        yield Variant(
            "vix_z252_low_QQQ",
            "QQQ",
            "vix_regime",
            _returns_from_signal(aligned["QQQ"], position),
        )


def _credit_variants(
    prices: dict[str, pd.Series],
) -> Iterator[Variant]:
    for denominator, prefix in (("IEF", "hyg_ief"), ("LQD", "hyg_lqd")):
        spec = SignalSpec(
            prefix,
            "credit_risk",
            "SPY",
            ("HYG", denominator, "SPY"),
        )
        yield from _ratio_z_variants(
            prices,
            spec=spec,
            numerator="HYG",
            denominator=denominator,
            windows=(60, 252),
            styles=(("", 1.0),),
            name_prefix=prefix,
        )


def _yield_curve_variants(
    prices: dict[str, pd.Series],
) -> Iterator[Variant]:
    spec = SignalSpec(
        "yield_curve_proxy",
        "yield_curve_proxy",
        "SPY",
        ("TLT", "IEF", "SPY"),
    )
    yield from _ratio_z_variants(
        prices,
        spec=spec,
        numerator="TLT",
        denominator="IEF",
        windows=(60, 252),
        styles=(("trend", -1.0), ("contra", 1.0)),
        name_prefix="yc_proxy",
    )


def _vix_term_variants(
    prices: dict[str, pd.Series],
) -> Iterator[Variant]:
    spec = SignalSpec(
        "vix_termstructure",
        "vix_termstructure",
        "SPY",
        ("VIXY", "SPY"),
    )
    aligned = _load_required(prices, spec)
    if aligned is None:
        return
    denom = _realized_vol(aligned["SPY"], 20)
    ratio = (aligned["VIXY"] / (denom * 100.0 + 1e-9)).rename("ratio")
    for window in (60, 252):
        z = _zscore(ratio, window)
        for threshold in _THRESHOLDS:
            position = _threshold_position(z, threshold, high_position=-1.0)
            name = f"vix_term_z{window}_SPY{_threshold_suffix(threshold)}"
            yield Variant(
                name,
                "SPY",
                spec.family,
                _returns_from_signal(aligned["SPY"], position),
            )


def _dollar_variants(
    prices: dict[str, pd.Series],
) -> Iterator[Variant]:
    qqq_spec = SignalSpec("dollar_equity_qqq", "dollar_equity", "QQQ", ("UUP", "QQQ"))
    aligned = _load_required(prices, qqq_spec)
    if aligned is not None:
        for window in (60, 252):
            z = _zscore(aligned["UUP"].rename("UUP"), window)
            for threshold in _THRESHOLDS:
                position = _threshold_position(z, threshold, high_position=-1.0)
                name = f"dollar_z{window}_QQQ{_threshold_suffix(threshold)}"
                yield Variant(
                    name,
                    "QQQ",
                    qqq_spec.family,
                    _returns_from_signal(aligned["QQQ"], position),
                )

    spy_spec = SignalSpec("dollar_equity_spy", "dollar_equity", "SPY", ("UUP", "SPY"))
    aligned = _load_required(prices, spy_spec)
    if aligned is not None:
        z = _zscore(aligned["UUP"].rename("UUP"), 252)
        for threshold in _THRESHOLDS:
            position = _threshold_position(z, threshold, high_position=-1.0)
            name = f"dollar_z252_SPY{_threshold_suffix(threshold)}"
            yield Variant(
                name,
                "SPY",
                spy_spec.family,
                _returns_from_signal(aligned["SPY"], position),
            )


def generate_multi_asset_variants(
    prices: dict[str, pd.Series],
) -> Iterator[Variant]:
    """Generate variants whose signals and traded assets can differ."""
    builders = (
        _bonds_equity_variants,
        _gold_equity_variants,
        _vix_regime_variants,
        _credit_variants,
        _yield_curve_variants,
        _vix_term_variants,
        _dollar_variants,
    )
    for builder in builders:
        yield from builder(prices)
