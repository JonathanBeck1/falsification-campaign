"""Buy-and-hold benchmark / alpha checks on a tiny price series."""

from __future__ import annotations

import pytest

from trader.backtesting.baselines.buy_and_hold import buy_and_hold_return
from trader.options.benchmark import (
    buy_and_hold_benchmark,
    closes_from_historical_bars,
    compare,
)
from trader.options.reporting import render_metrics_markdown


def test_buy_and_hold_return_simple():
    # 100 -> 110 over the window = +10%
    assert buy_and_hold_return([100.0, 105.0, 110.0]) == pytest.approx(0.10)


def test_buy_and_hold_return_edge_cases():
    assert buy_and_hold_return([100.0]) is None
    assert buy_and_hold_return([]) is None
    assert buy_and_hold_return([0.0, 110.0]) is None


def test_closes_from_historical_bars_filters_and_orders():
    bars = [
        {"trade_date": "2026-01-03", "close": 110.0},
        {"trade_date": "2026-01-01", "close": 100.0},
        {"trade_date": "2026-01-02", "close": 105.0},
        {"trade_date": "2025-12-31", "close": 99.0},  # before window
    ]
    closes = closes_from_historical_bars(bars, since="2026-01-01", until="2026-01-03")
    assert closes == [100.0, 105.0, 110.0]


def test_buy_and_hold_benchmark_and_alpha():
    # benchmark +10%, strategy +8% -> alpha -2%
    result = buy_and_hold_benchmark([100.0, 110.0], strategy_return=0.08)
    assert result["benchmark_return"] == pytest.approx(0.10)
    assert result["alpha"] == pytest.approx(-0.02)


def test_compare_dataclass():
    comparison = compare([100.0, 120.0], strategy_return=0.05)
    assert comparison.strategy_return == 0.05
    assert comparison.benchmark_return == pytest.approx(0.20)
    assert comparison.alpha == pytest.approx(-0.15)


def test_alpha_none_when_no_benchmark():
    result = buy_and_hold_benchmark([100.0], strategy_return=0.08)
    assert result["benchmark_return"] is None
    assert result["alpha"] is None


def test_report_shows_strategy_benchmark_and_alpha():
    metrics = {
        "n_trades": 3,
        "total_pnl": 80.0,
        "total_return": 0.08,
        **buy_and_hold_benchmark([100.0, 110.0], strategy_return=0.08),
        "win_rate": 0.6667,
    }
    report = render_metrics_markdown(metrics, title="SPY Iron Condor vs Buy-and-Hold")
    assert "| total_return | 8.00% |" in report
    assert "| benchmark_return | 10.00% |" in report
    assert "| alpha (excess) | -2.00% |" in report
