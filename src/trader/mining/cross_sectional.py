"""Cross-sectional and relative-value strategy families for the mining lab."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pandas as pd
import structlog

from trader.mining.strategies import Variant

log = structlog.get_logger()

PAIRS: tuple[tuple[str, str], ...] = (
    ("SPY", "IVV"),
    ("QQQ", "XLK"),
    ("IWM", "IJR"),
    ("XLF", "KRE"),
    ("XLE", "XOP"),
    ("GLD", "SLV"),
    ("EFA", "VEA"),
    ("HYG", "JNK"),
    ("TLT", "IEF"),
    ("EWZ", "EEM"),
)
SECTORS: tuple[str, ...] = (
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
)
PAIRS_LEAD: tuple[tuple[str, str], ...] = (
    ("XLK", "QQQ"),
    ("XLF", "KRE"),
    ("IYT", "SPY"),
    ("XLE", "XOP"),
)


def _apply_position(pos: pd.Series, ret: pd.Series) -> pd.Series:
    return (pos.shift(1) * ret).dropna()


def _aligned_prices(prices: dict[str, pd.Series], tickers: Sequence[str]) -> pd.DataFrame | None:
    missing = [ticker for ticker in tickers if ticker not in prices or prices[ticker] is None]
    if missing:
        log.warning("cross_sectional_missing_tickers", tickers=missing)
        return None

    frame = pd.concat(
        [prices[ticker].rename(ticker) for ticker in tickers],
        axis=1,
        join="inner",
    ).dropna()
    if frame.empty:
        log.warning("cross_sectional_no_common_prices", tickers=list(tickers))
        return None
    frame.index = pd.DatetimeIndex(frame.index)
    return frame.sort_index()


def _held_position(signal: pd.Series, hold: int) -> pd.Series:
    position = pd.Series(0.0, index=signal.index, dtype=float)
    current = 0.0
    remaining = 0
    for date, value in signal.items():
        if value != 0.0:
            current = float(value)
            remaining = hold
        if remaining > 0:
            position.loc[date] = current
            remaining -= 1
        else:
            current = 0.0
    return position


def _pair_zscore_returns(
    first: pd.Series,
    second: pd.Series,
    *,
    window: int,
    threshold: float,
    hold: int,
) -> pd.Series:
    frame = pd.concat(
        [first.rename("first"), second.rename("second")],
        axis=1,
        join="inner",
    ).dropna()
    ratio = frame["first"] / frame["second"]
    mean = ratio.rolling(window).mean()
    std = ratio.rolling(window).std(ddof=0).replace(0.0, float("nan"))
    zscore = (ratio - mean) / std
    entry = pd.Series(0.0, index=frame.index, dtype=float)
    entry.loc[zscore > threshold] = -1.0
    entry.loc[zscore < -threshold] = 1.0
    first_position = _held_position(entry, hold)
    returns = frame.pct_change(fill_method=None)
    pnl = _apply_position(first_position, returns["first"])
    pnl = pnl.add(_apply_position(-first_position, returns["second"]), fill_value=0.0)
    return pnl.replace([float("inf"), float("-inf")], float("nan")).dropna()


def _generate_pair_variants(prices: dict[str, pd.Series]) -> Iterator[Variant]:
    for first, second in PAIRS:
        frame = _aligned_prices(prices, (first, second))
        if frame is None:
            continue
        for window in (20, 60, 120):
            for threshold in (1.0, 1.5, 2.0):
                for hold in (5, 10, 20):
                    daily_returns = _pair_zscore_returns(
                        frame[first],
                        frame[second],
                        window=window,
                        threshold=threshold,
                        hold=hold,
                    )
                    yield Variant(
                        name=f"pair_{first}_{second}_W{window}_z{threshold}_h{hold}",
                        ticker=f"PAIR:{first}/{second}",
                        family="pair_zscore",
                        daily_returns=daily_returns,
                    )


def _sector_positions(
    prices: pd.DataFrame,
    *,
    lookback: int,
    long_short: bool,
) -> pd.DataFrame:
    momentum = prices.pct_change(lookback, fill_method=None)
    month_ends = prices.groupby(prices.index.to_period("M")).tail(1).index
    rebalances = pd.DataFrame(float("nan"), index=prices.index, columns=prices.columns)

    for date in month_ends:
        ranked = momentum.loc[date].dropna().sort_values()
        if len(ranked) < 6:
            continue
        weights = pd.Series(0.0, index=prices.columns, dtype=float)
        weights.loc[ranked.index[-3:]] = 1.0 / 3.0
        if long_short:
            weights.loc[ranked.index[:3]] = -1.0 / 3.0
        rebalances.loc[date] = weights

    return rebalances.ffill().fillna(0.0)


def _portfolio_returns(positions: pd.DataFrame, prices: pd.DataFrame) -> pd.Series:
    returns = prices.pct_change(fill_method=None)
    pnl = (positions.shift(1) * returns).sum(axis=1, min_count=1)
    return pnl.replace([float("inf"), float("-inf")], float("nan")).dropna()


def _generate_sector_rotation_variants(prices: dict[str, pd.Series]) -> Iterator[Variant]:
    frame = _aligned_prices(prices, SECTORS)
    if frame is None:
        return

    for months in (3, 6, 12):
        lookback = 21 * months
        long_short_positions = _sector_positions(frame, lookback=lookback, long_short=True)
        yield Variant(
            name=f"sector_rot_LS_N{months}m",
            ticker="SECTORS",
            family="sector_rotation_ls",
            daily_returns=_portfolio_returns(long_short_positions, frame),
        )
        long_only_positions = _sector_positions(frame, lookback=lookback, long_short=False)
        yield Variant(
            name=f"sector_rot_LO_N{months}m",
            ticker="SECTORS",
            family="sector_rotation_lo",
            daily_returns=_portfolio_returns(long_only_positions, frame),
        )


def _lead_lag_pairs(prices: dict[str, pd.Series]) -> tuple[tuple[str, str], ...]:
    if "USO" not in prices:
        return PAIRS_LEAD
    return (*PAIRS_LEAD[:-1], ("XLE", "USO"))


def _generate_lead_lag_variants(prices: dict[str, pd.Series]) -> Iterator[Variant]:
    for leader, follower in _lead_lag_pairs(prices):
        frame = _aligned_prices(prices, (leader, follower))
        if frame is None:
            continue
        leader_return = frame[leader].pct_change(fill_method=None)
        follower_return = frame[follower].pct_change(fill_method=None)
        for lag in (1, 3, 5):
            signal = leader_return.shift(lag - 1)
            position = (signal > 0.0).astype(float)
            yield Variant(
                name=f"leadlag_{leader}_to_{follower}_L{lag}",
                ticker=f"LEADLAG:{leader}->{follower}",
                family="lead_lag",
                daily_returns=_apply_position(position, follower_return),
            )


def _generate_dispersion_variants(prices: dict[str, pd.Series]) -> Iterator[Variant]:
    if "QQQ" not in prices:
        log.warning("cross_sectional_missing_tickers", tickers=["QQQ"])
        return
    sector_prices = _aligned_prices(prices, SECTORS)
    if sector_prices is None:
        return

    sector_returns = sector_prices.pct_change(fill_method=None)
    dispersion = sector_returns.std(axis=1, ddof=1)
    rolling_mean = dispersion.rolling(60).mean()
    rolling_std = dispersion.rolling(60).std(ddof=0).replace(0.0, float("nan"))
    zscore = (dispersion - rolling_mean) / rolling_std
    frame = pd.concat(
        [prices["QQQ"].rename("QQQ"), zscore.rename("zscore")],
        axis=1,
        join="inner",
    ).dropna()
    qqq_return = frame["QQQ"].pct_change(fill_method=None)

    for name, position in (
        ("disp_low_QQQ", (frame["zscore"] < -1.0).astype(float)),
        ("disp_high_QQQ", (frame["zscore"] > 1.0).astype(float)),
    ):
        yield Variant(
            name=name,
            ticker="DISP:QQQ",
            family="dispersion_timing",
            daily_returns=_apply_position(position, qqq_return),
        )


def generate_cross_sectional_variants(prices: dict[str, pd.Series]) -> Iterator[Variant]:
    """Yield all available pair, rotation, lead-lag, and dispersion variants."""
    yield from _generate_pair_variants(prices)
    yield from _generate_sector_rotation_variants(prices)
    yield from _generate_lead_lag_variants(prices)
    yield from _generate_dispersion_variants(prices)
