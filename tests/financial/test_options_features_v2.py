"""Tests for pure v2 QQQ option-feature computation."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from trader.mining.options_features_v2 import compute_v2_features

SPOT = 100.0
TRADE_DATE = "2024-01-15"
V2_FIELDS = (
    "gex_depth_proxy",
    "skew_25d",
    "pc_size_ratio",
    "term_curvature",
    "avg_spread_pct",
    "depth_imbalance",
)


def _option_chain() -> pd.DataFrame:
    trade_day = date.fromisoformat(TRADE_DATE)
    rows = []
    for dte in (7, 21, 60):
        expiration = trade_day + timedelta(days=dte)
        for strike in (88.0, 92.0, 96.0, 100.0, 104.0, 108.0, 112.0):
            for call_put in ("Call", "Put"):
                distance = abs(strike - SPOT) / 4.0
                if call_put == "Put":
                    mid = 2.0 + max(SPOT - strike, 0.0) * 0.2 + distance * 0.1
                    bid_size, ask_size = 24.0, 16.0
                else:
                    mid = 1.5 + max(strike - SPOT, 0.0) * 0.05 + distance * 0.05
                    bid_size, ask_size = 6.0, 9.0
                if dte == 21 and strike == 92.0 and call_put == "Put":
                    mid = 5.0
                if dte == 21 and strike == 108.0 and call_put == "Call":
                    mid = 1.0
                rows.append(
                    {
                        "exp": expiration,
                        "strike": strike,
                        "call_put": call_put,
                        "mid": mid,
                        "bid": mid * 0.995,
                        "ask": mid * 1.005,
                        "bid_size": bid_size,
                        "ask_size": ask_size,
                        "dte": dte,
                    }
                )
    return pd.DataFrame(rows)


def test_skew_25d_negative_when_put_premium_higher() -> None:
    result = compute_v2_features(_option_chain(), SPOT, TRADE_DATE)
    assert result["skew_25d"] is not None
    assert result["skew_25d"] > 0


def test_pc_size_ratio_above_one() -> None:
    result = compute_v2_features(_option_chain(), SPOT, TRADE_DATE)
    assert result["pc_size_ratio"] is not None
    assert result["pc_size_ratio"] > 1


def test_gex_depth_proxy_positive() -> None:
    result = compute_v2_features(_option_chain(), SPOT, TRADE_DATE)
    assert result["gex_depth_proxy"] is not None
    assert result["gex_depth_proxy"] > 0


def test_term_curvature_returns_float_when_three_expiries_present() -> None:
    result = compute_v2_features(_option_chain(), SPOT, TRADE_DATE)
    assert isinstance(result["term_curvature"], float)


def test_avg_spread_pct_small() -> None:
    result = compute_v2_features(_option_chain(), SPOT, TRADE_DATE)
    assert result["avg_spread_pct"] is not None
    assert 0 < result["avg_spread_pct"] < 0.1


def test_depth_imbalance_in_minus_one_to_one() -> None:
    result = compute_v2_features(_option_chain(), SPOT, TRADE_DATE)
    assert result["depth_imbalance"] is not None
    assert -1 <= result["depth_imbalance"] <= 1


def test_returns_none_on_empty() -> None:
    result = compute_v2_features(pd.DataFrame(), SPOT, TRADE_DATE)
    assert all(result[field] is None for field in V2_FIELDS)


def test_trade_date_and_spot_passthrough() -> None:
    result = compute_v2_features(_option_chain(), SPOT, TRADE_DATE)
    assert result["trade_date"] == TRADE_DATE
    assert result["spot"] == SPOT
