"""Parameter sweeps for the EOD iron-condor research harness."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from itertools import product

from trader.options.backtest import IronCondorBacktestConfig, run_iron_condor_backtest
from trader.options.intraday_sweep import expectancy_stats
from trader.options.iron_condor import IronCondorConfig
from trader.options.models import OptionQuote


@dataclass(frozen=True)
class IronCondorSweepRow:
    rank: int
    wing_width: float
    target_delta: float
    profit_target_pct: float
    stop_loss_credit_multiple: float
    trade_count: int
    win_rate: float
    total_pnl: float
    average_pnl: float
    # Per-trade after-friction expectancy (mean realized P&L) and its t-stat.
    # The t-stat is the primary ranking key (audit A4): it rewards a positive
    # per-trade edge that is statistically real, and penalizes high-win-rate /
    # high-total-P&L configs whose edge is just noise or sample size.
    expectancy: float
    expectancy_tstat: float | None
    max_drawdown: float
    profit_factor: float | None


def run_iron_condor_sweep(
    quotes: list[OptionQuote],
    *,
    ticker: str,
    start: date,
    end: date,
    wing_widths: list[float],
    target_deltas: list[float],
    profit_targets: list[float],
    stop_loss_multiples: list[float],
    min_dte: int = 30,
    max_dte: int = 45,
    exit_dte: int = 21,
    commission_per_contract: float = 0.65,
    slippage_per_contract: float = 0.02,
    underlying_closes: Mapping[date, float] | None = None,
) -> list[IronCondorSweepRow]:
    rows: list[IronCondorSweepRow] = []
    for wing_width, target_delta, profit_target, stop_mult in product(
        wing_widths,
        target_deltas,
        profit_targets,
        stop_loss_multiples,
    ):
        result = run_iron_condor_backtest(
            quotes,
            IronCondorBacktestConfig(
                ticker=ticker.strip().upper(),
                start=start,
                end=end,
                selector=IronCondorConfig(
                    min_dte=min_dte,
                    max_dte=max_dte,
                    target_delta=target_delta,
                    wing_width=wing_width,
                ),
                profit_target_pct=profit_target,
                stop_loss_credit_multiple=stop_mult,
                exit_dte=exit_dte,
                max_concurrent_trades=1,
                commission_per_contract=commission_per_contract,
                slippage_per_contract=slippage_per_contract,
            ),
            underlying_closes=underlying_closes,
        )
        expectancy, expectancy_tstat = expectancy_stats(result)
        rows.append(
            IronCondorSweepRow(
                rank=0,
                wing_width=wing_width,
                target_delta=target_delta,
                profit_target_pct=profit_target,
                stop_loss_credit_multiple=stop_mult,
                trade_count=result.summary.trade_count,
                win_rate=result.summary.win_rate,
                total_pnl=result.summary.total_pnl,
                average_pnl=result.summary.average_pnl,
                expectancy=expectancy,
                expectancy_tstat=expectancy_tstat,
                max_drawdown=result.summary.max_drawdown,
                profit_factor=result.summary.profit_factor,
            )
        )
    # Rank by per-trade after-friction expectancy t-stat (statistically-real
    # edge), NOT total_pnl or win_rate (audit A4 -- the win-rate trap). Rows with
    # zero closed trades carry no evidence and sink to the bottom. Among trade
    # rows, a valid t-stat ranks above none (n<2 or zero variance); ties break on
    # raw expectancy then trade count (more = more evidence).
    ranked = sorted(
        rows,
        key=lambda row: (
            row.trade_count > 0,
            row.expectancy_tstat is not None,
            row.expectancy_tstat if row.expectancy_tstat is not None else float("-inf"),
            row.expectancy,
            row.trade_count,
        ),
        reverse=True,
    )
    return [row.__class__(rank=index, **{k: v for k, v in row.__dict__.items() if k != "rank"}) for index, row in enumerate(ranked, start=1)]


def format_iron_condor_sweep_report(rows: list[IronCondorSweepRow], *, ticker: str) -> str:
    lines = [
        f"# {ticker.strip().upper()} Iron Condor Parameter Sweep",
        "",
        "Ranked by per-trade after-friction expectancy t-stat (statistically-real edge), not total P&L / win rate.",
        "",
        "| rank | wing | delta | profit_target | stop_mult | trades | win_rate | expectancy | t_stat | total_pnl | avg_pnl | max_dd | profit_factor |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        profit_factor = f"{row.profit_factor:.2f}" if row.profit_factor is not None else "inf"
        tstat = f"{row.expectancy_tstat:.2f}" if row.expectancy_tstat is not None else "n/a"
        lines.append(
            f"| {row.rank} | {row.wing_width:.2f} | {row.target_delta:.2f} | "
            f"{row.profit_target_pct:.0%} | {row.stop_loss_credit_multiple:.2f} | "
            f"{row.trade_count} | {row.win_rate:.0%} | {row.expectancy:.2f} | {tstat} | "
            f"{row.total_pnl:.2f} | {row.average_pnl:.2f} | {row.max_drawdown:.2f} | {profit_factor} |"
        )
    return "\n".join(lines) + "\n"
