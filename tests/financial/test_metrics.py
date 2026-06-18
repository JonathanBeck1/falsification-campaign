"""Hand-computed checks for the reusable options metrics + standardized report.

Three trades with known P&L (+100, -50, +30) on a 1,000 starting capital give
deterministic, hand-verifiable metrics. The Sharpe/Sortino/CAGR definitions are
re-derived inline from the documented formula to confirm the wiring.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev

import pytest

from trader.options import metrics as m
from trader.options.metrics import ClosedTrade
from trader.options.reporting import render_metrics_markdown, write_research_report

CAPITAL = 1_000.0


def _trades() -> list[ClosedTrade]:
    return [
        ClosedTrade(pnl=100.0, credit=1.0, entry=datetime(2026, 1, 5, 9, 45), exit=datetime(2026, 1, 6, 9, 45)),
        ClosedTrade(pnl=-50.0, credit=2.0, entry=datetime(2026, 1, 7, 9, 45), exit=datetime(2026, 1, 9, 9, 45)),
        ClosedTrade(pnl=30.0, credit=1.5, entry=datetime(2026, 1, 12, 9, 45), exit=datetime(2026, 1, 12, 9, 45)),
    ]


def test_basic_counts_and_pnl():
    trades = _trades()
    assert m.n_trades(trades) == 3
    assert m.total_pnl(trades) == 80.0
    assert m.total_return(trades, starting_capital=CAPITAL) == pytest.approx(0.08)
    assert m.avg_credit(trades) == pytest.approx(1.5)


def test_win_rate_and_profit_factor():
    trades = _trades()
    assert m.win_rate(trades) == pytest.approx(2 / 3)
    # gains 100 + 30 = 130; losses |-50| = 50; pf = 2.6
    assert m.profit_factor(trades) == pytest.approx(2.6)


def test_equity_curve_and_max_drawdown():
    trades = _trades()
    assert m.equity_curve(trades, starting_capital=CAPITAL) == [1000.0, 1100.0, 1050.0, 1080.0]
    # peak 1100, trough 1050 -> drawdown 50
    assert m.max_drawdown(trades, starting_capital=CAPITAL) == 50.0


def test_avg_hold_days_and_exposure():
    trades = _trades()
    # holds: 1 day, 2 days, 0 days -> mean 1.0
    assert m.avg_hold_days(trades) == pytest.approx(1.0)
    # window 2026-01-05..2026-01-12 = 8 days; open days {05,06,07,08,09,12} = 6 -> 0.75
    assert m.exposure(trades) == pytest.approx(0.75)


def test_sharpe_matches_documented_formula():
    trades = _trades()
    returns = [0.1, -0.05, 0.03]
    expected = mean(returns) / pstdev(returns)
    assert m.sharpe(trades, starting_capital=CAPITAL) == pytest.approx(expected)


def test_sortino_matches_documented_formula():
    trades = _trades()
    returns = [0.1, -0.05, 0.03]
    downside = [min(0.0, r) for r in returns]
    expected = mean(returns) / pstdev(downside)
    assert m.sortino(trades, starting_capital=CAPITAL) == pytest.approx(expected)


def test_cagr_matches_documented_formula():
    trades = _trades()
    # span first-entry 01-05 .. last-exit 01-12 = 7 days; ending = 1080
    expected = (1080.0 / CAPITAL) ** (365.0 / 7) - 1.0
    assert m.cagr(trades, starting_capital=CAPITAL) == pytest.approx(expected)


def test_empty_trades_are_safe():
    assert m.n_trades([]) == 0
    assert m.win_rate([]) == 0.0
    assert m.profit_factor([]) is None
    assert m.max_drawdown([], starting_capital=CAPITAL) == 0.0
    assert m.cagr([], starting_capital=CAPITAL) is None
    assert m.sharpe([], starting_capital=CAPITAL) is None
    assert m.exposure([]) == 0.0


def test_profit_factor_none_when_no_losses():
    winners = [ClosedTrade(pnl=10.0, credit=1.0, entry=datetime(2026, 1, 1), exit=datetime(2026, 1, 2))]
    assert m.profit_factor(winners) is None


def test_compute_metrics_aggregates_all_keys():
    metrics = m.compute_metrics(_trades(), starting_capital=CAPITAL)
    for key in (
        "n_trades",
        "total_pnl",
        "total_return",
        "cagr",
        "win_rate",
        "avg_credit",
        "profit_factor",
        "max_drawdown",
        "sharpe",
        "sortino",
        "exposure",
        "avg_hold_days",
    ):
        assert key in metrics
    assert metrics["n_trades"] == 3
    assert metrics["total_pnl"] == 80.0


def test_render_metrics_markdown_is_standardized():
    metrics = m.compute_metrics(_trades(), starting_capital=CAPITAL)
    report = render_metrics_markdown(metrics, title="SPY Test Strategy", params={"entry_time": "09:45:00"})
    assert "# SPY Test Strategy" in report
    assert "not live-trading evidence" in report
    assert "| trades | 3 |" in report
    assert "| win_rate |" in report
    assert "- entry_time: 09:45:00" in report


def test_write_research_report_emits_md_json_csv(tmp_path: Path):
    trades = _trades()
    metrics = m.compute_metrics(trades, starting_capital=CAPITAL)
    out = tmp_path / "report.md"

    paths = write_research_report(
        output_path=out,
        metrics=metrics,
        trades=trades,
        title="SPY Test Strategy",
        params={"entry_time": "09:45:00"},
    )

    md = Path(paths["md"])
    js = Path(paths["json"])
    csv_path = Path(paths["csv"])
    assert md.exists() and js.exists() and csv_path.exists()
    assert csv_path.name == "report_equity.csv"

    import json

    payload = json.loads(js.read_text())
    assert payload["title"] == "SPY Test Strategy"
    assert payload["metrics"]["total_pnl"] == 80.0
    assert payload["params"]["entry_time"] == "09:45:00"

    csv_lines = csv_path.read_text().strip().splitlines()
    assert csv_lines[0] == "step,equity"
    assert csv_lines[-1] == "3,1080.0"


def test_closed_trades_from_intraday_skips_unclosed():
    class _Trade:
        def __init__(self, pnl, entry_credit, entry_ts, exit_ts):
            self.pnl = pnl
            self.entry_credit = entry_credit
            self.entry_ts = entry_ts
            self.exit_ts = exit_ts

    class _Result:
        def __init__(self):
            self.trades = [
                _Trade(70.0, 1.3, datetime(2026, 1, 5, 9, 45), datetime(2026, 1, 5, 10, 15)),
                _Trade(None, 1.3, datetime(2026, 1, 6, 9, 45), None),
            ]

    converted = m.closed_trades_from_intraday(_Result())
    assert len(converted) == 1
    assert converted[0].pnl == 70.0
    assert converted[0].credit == 1.3
