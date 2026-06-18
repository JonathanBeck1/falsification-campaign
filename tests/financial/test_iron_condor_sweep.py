from __future__ import annotations

from datetime import date, timedelta

from trader.options.models import OptionQuote
from trader.options.sweep import format_iron_condor_sweep_report, run_iron_condor_sweep


def _quote(
    trade_date: date,
    strike: float,
    call_put: str,
    delta: float,
    bid: float,
    ask: float,
    *,
    expiration: date,
) -> OptionQuote:
    return OptionQuote(
        trade_date=trade_date,
        ticker="SPY",
        expiration=expiration,
        strike=strike,
        call_put=call_put,
        bid=bid,
        ask=ask,
        implied_vol=0.18,
        delta=delta,
        gamma=None,
        theta=None,
        vega=None,
        rho=None,
    )


def _two_day_quotes() -> list[OptionQuote]:
    d0 = date(2026, 5, 1)
    expiration = d0 + timedelta(days=35)
    return [
        _quote(d0, 555, "Put", -0.10, 0.50, 0.55, expiration=expiration),
        _quote(d0, 560, "Put", -0.16, 1.20, 1.30, expiration=expiration),
        _quote(d0, 610, "Call", 0.16, 1.20, 1.30, expiration=expiration),
        _quote(d0, 615, "Call", 0.10, 0.50, 0.55, expiration=expiration),
        _quote(d0 + timedelta(days=1), 555, "Put", -0.10, 0.35, 0.40, expiration=expiration),
        _quote(d0 + timedelta(days=1), 560, "Put", -0.16, 0.60, 0.65, expiration=expiration),
        _quote(d0 + timedelta(days=1), 610, "Call", 0.16, 0.60, 0.65, expiration=expiration),
        _quote(d0 + timedelta(days=1), 615, "Call", 0.10, 0.35, 0.40, expiration=expiration),
    ]


def test_run_iron_condor_sweep_returns_one_row_per_parameter_combo():
    rows = run_iron_condor_sweep(
        _two_day_quotes(),
        ticker="SPY",
        start=date(2026, 5, 1),
        end=date(2026, 5, 2),
        wing_widths=[5.0],
        target_deltas=[0.16],
        profit_targets=[0.50, 0.75],
        stop_loss_multiples=[2.0],
        # The sweep defaults to realistic friction; zero it so this fixture's
        # frictionless expectations hold.
        commission_per_contract=0.0,
        slippage_per_contract=0.0,
    )

    assert len(rows) == 2
    assert {row.profit_target_pct for row in rows} == {0.50, 0.75}
    assert rows[0].trade_count == 1
    assert rows[0].total_pnl == 70.0
    assert rows[0].expectancy == 70.0


def test_run_iron_condor_sweep_ranks_by_expectancy_tstat_not_win_rate_or_total_pnl():
    """Audit A4: the win-rate / total-PnL trap. A config with a 100% win rate
    and the higher total P&L but only one trade (no t-stat) must rank BELOW a
    config whose per-trade edge is supported by more evidence."""

    d0 = date(2026, 5, 1)
    d1 = d0 + timedelta(days=1)
    d2 = d0 + timedelta(days=2)
    expiration = d0 + timedelta(days=35)
    quotes = [
        # d0: entry chain (credit 1.30).
        _quote(d0, 555, "Put", -0.10, 0.50, 0.55, expiration=expiration),
        _quote(d0, 560, "Put", -0.16, 1.20, 1.30, expiration=expiration),
        _quote(d0, 610, "Call", 0.16, 1.20, 1.30, expiration=expiration),
        _quote(d0, 615, "Call", 0.10, 0.50, 0.55, expiration=expiration),
        # d1: profit-target mark for PT=0.50 (debit 0.60) and re-entry chain (credit 0.40).
        _quote(d1, 555, "Put", -0.10, 0.35, 0.40, expiration=expiration),
        _quote(d1, 560, "Put", -0.16, 0.60, 0.65, expiration=expiration),
        _quote(d1, 610, "Call", 0.16, 0.60, 0.65, expiration=expiration),
        _quote(d1, 615, "Call", 0.10, 0.35, 0.40, expiration=expiration),
        # d2: final marks (debit 0.50).
        _quote(d2, 555, "Put", -0.10, 0.05, 0.10, expiration=expiration),
        _quote(d2, 560, "Put", -0.16, 0.25, 0.30, expiration=expiration),
        _quote(d2, 610, "Call", 0.16, 0.25, 0.30, expiration=expiration),
        _quote(d2, 615, "Call", 0.10, 0.05, 0.10, expiration=expiration),
    ]

    rows = run_iron_condor_sweep(
        quotes,
        ticker="SPY",
        start=d0,
        end=d2,
        wing_widths=[5.0],
        target_deltas=[0.16],
        profit_targets=[0.50, 0.75],
        stop_loss_multiples=[2.0],
        commission_per_contract=0.0,
        slippage_per_contract=0.0,
    )

    assert len(rows) == 2
    top, bottom = rows
    # PT=0.50 trades twice ([+70, -10]): valid t-stat -> ranks first.
    assert top.profit_target_pct == 0.50
    assert top.trade_count == 2
    assert top.expectancy == 30.0
    assert top.expectancy_tstat is not None
    # PT=0.75 holds to the final mark: one trade, +80 total, 100% win rate, no t-stat.
    assert bottom.profit_target_pct == 0.75
    assert bottom.trade_count == 1
    assert bottom.expectancy_tstat is None
    # The dethroned config wins on BOTH win rate and total P&L -- the old keys.
    assert bottom.win_rate > top.win_rate
    assert bottom.total_pnl > top.total_pnl


def test_run_iron_condor_sweep_ranks_no_trade_rows_last():
    rows = run_iron_condor_sweep(
        _two_day_quotes(),
        ticker="SPY",
        start=date(2026, 5, 1),
        end=date(2026, 5, 2),
        # 5.0 produces a trade; 50.0 cannot find wings in the fixture chain.
        wing_widths=[5.0, 50.0],
        target_deltas=[0.16],
        profit_targets=[0.50],
        stop_loss_multiples=[2.0],
        commission_per_contract=0.0,
        slippage_per_contract=0.0,
    )

    assert len(rows) == 2
    assert rows[0].trade_count > 0
    assert rows[-1].trade_count == 0


def test_format_iron_condor_sweep_report_renders_ranked_table():
    rows = run_iron_condor_sweep(
        _two_day_quotes(),
        ticker="SPY",
        start=date(2026, 5, 1),
        end=date(2026, 5, 2),
        wing_widths=[5.0],
        target_deltas=[0.16],
        profit_targets=[0.50],
        stop_loss_multiples=[2.0],
        commission_per_contract=0.0,
        slippage_per_contract=0.0,
    )

    report = format_iron_condor_sweep_report(rows, ticker="SPY")

    assert "# SPY Iron Condor Parameter Sweep" in report
    assert "Ranked by per-trade after-friction expectancy t-stat" in report
    assert "| rank | wing | delta | profit_target | stop_mult | trades | win_rate | expectancy | t_stat | total_pnl |" in report
    assert "| 1 | 5.00 | 0.16 | 50%" in report
