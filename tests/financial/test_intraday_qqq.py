"""Tests for the intraday QQQ mining lab."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from trader.mining.intraday_qqq import (
    compute_daily_features,
    generate_intraday_variants,
    load_intraday_qqq,
)


def _make_synthetic_minute_df(
    dates: list[str],
    tz: str = "America/New_York",
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    opens = (400.0, 410.0, 407.0)
    for day_index, date_str in enumerate(dates):
        start = pd.Timestamp(f"{date_str} 09:30", tz=tz)
        for minute in range(391):
            ts = start + pd.Timedelta(minutes=minute)
            price = opens[day_index] + minute * 0.01
            if 120 <= minute <= 240:
                price -= (minute - 120) * 0.021
            elif minute > 240:
                price -= 2.52
            rows.append({"ts": ts, "px": price})
    return pd.DataFrame(rows).set_index("ts")


def test_compute_daily_features_basic() -> None:
    minute_df = _make_synthetic_minute_df(["2024-01-02", "2024-01-03"])

    features = compute_daily_features(minute_df)

    expected_columns = {
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
    }
    assert expected_columns == set(features.columns)
    day_one = pd.Timestamp("2024-01-02")
    day_two = pd.Timestamp("2024-01-03")
    assert features.loc[day_two, "overnight_ret"] == pytest.approx(
        features.loc[day_two, "open"] / features.loc[day_one, "close"] - 1.0
    )
    assert features.loc[day_one, "lunchtime_ret"] == pytest.approx(
        features.loc[day_one, "lunch_end_px"]
        / features.loc[day_one, "lunch_start_px"]
        - 1.0
    )
    assert features.loc[day_one, "last30_to_close_ret"] == pytest.approx(
        features.loc[day_one, "close"] / features.loc[day_one, "last30_open"]
        - 1.0
    )
    assert features.loc[day_one, "lunchtime_ret"] < -0.003
    assert features.loc[day_two, "overnight_ret"] > 0.005


def test_generate_intraday_variants_no_lookahead() -> None:
    minute_df = _make_synthetic_minute_df(
        ["2024-01-02", "2024-01-03", "2024-01-04"]
    )
    features = compute_daily_features(minute_df)

    variants = generate_intraday_variants(features)
    families = {variant.family for variant in variants}

    assert {
        "overnight",
        "intraday_short",
        "first30_momentum_reversal",
        "last30_momentum_overnight",
        "lunchtime_reversion",
        "open_gap_fade",
    } <= families

    overnight = next(
        variant
        for variant in variants
        if variant.name == "overnight_long_qqq_QQQ"
    )
    pd.testing.assert_series_equal(
        overnight.daily_returns,
        features["overnight_ret"].dropna().astype(float),
        check_names=False,
    )

    shifted = next(
        variant
        for variant in variants
        if variant.name == "last30_mom_overnight_0.000_QQQ"
    )
    first_day = features.index[0]
    assert pd.isna(shifted.daily_returns.reindex([first_day]).iloc[0])
    expected = (
        (features["last30_to_close_ret"] > 0.0).astype(float).shift(1)
        * features["overnight_ret"]
    ).dropna()
    pd.testing.assert_series_equal(
        shifted.daily_returns,
        expected.astype(float),
        check_names=False,
    )

    for variant in variants:
        assert isinstance(variant.daily_returns, pd.Series)
        assert pd.api.types.is_float_dtype(variant.daily_returns.dtype)
        assert isinstance(variant.daily_returns.index, pd.DatetimeIndex)


def test_load_intraday_qqq_missing_lake_returns_empty(
    tmp_path: Path,
) -> None:
    result = load_intraday_qqq(
        lake=tmp_path / "missing-lake",
        cache=tmp_path / "missing-cache.parquet",
    )

    assert result.empty
    assert list(result.columns) == ["px"]
    assert isinstance(result.index, pd.DatetimeIndex)
