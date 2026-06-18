"""Parameter sweeps for the intraday iron-condor research harness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import product
from statistics import mean, stdev

from trader.options.intraday import (
    IntradayIronCondorBacktestConfig,
    IntradayIronCondorSelectorConfig,
    SelectionMode,
    build_intraday_quote_replay_data,
    run_intraday_iron_condor_backtest,
)
from trader.options.models import OptionQuoteBar


@dataclass(frozen=True)
class IntradayIronCondorSweepRow:
    rank: int
    entry_time: str
    selection_mode: SelectionMode
    wing_width: float
    target_delta: float | None
    target_short_bid: float | None
    profit_target_pct: float
    stop_loss_credit_multiple: float
    trade_count: int
    win_rate: float
    total_pnl: float
    average_pnl: float
    # Per-trade expectancy (mean realized P&L) and its t-statistic
    # (expectancy / standard error). The t-stat is the primary ranking key: it
    # rewards a positive per-trade edge that is statistically real, and penalizes
    # high-win-rate / high-total-P&L configs whose edge is just noise or sample size.
    expectancy: float
    expectancy_tstat: float | None
    max_drawdown: float
    profit_factor: float | None


def expectancy_stats(result) -> tuple[float, float | None]:
    """Per-trade expectancy and its t-stat from realized (closed) trade P&Ls.

    Shared by the intraday and EOD sweeps (audit A4): per-trade after-friction
    expectancy -- not total P&L or win rate -- is the primary ranking key.
    t = mean / (stdev / sqrt(n)). Returns (0.0, None) with no closed trades, and
    a None t-stat when n < 2 or the P&L variance is zero (t undefined)."""

    pnls = [trade.pnl for trade in result.trades if trade.pnl is not None]
    n = len(pnls)
    if n == 0:
        return 0.0, None
    expectancy = mean(pnls)
    if n < 2:
        return round(expectancy, 4), None
    sd = stdev(pnls)
    if sd == 0.0:
        return round(expectancy, 4), None
    tstat = expectancy / (sd / (n**0.5))
    return round(expectancy, 4), round(tstat, 4)


def run_intraday_iron_condor_sweep(
    quote_bars: list[OptionQuoteBar],
    *,
    ticker: str,
    start: date,
    end: date,
    entry_times: list[str],
    selection_mode: SelectionMode,
    wing_widths: list[float],
    profit_targets: list[float],
    stop_loss_multiples: list[float],
    target_deltas: list[float] | None = None,
    target_short_bids: list[float] | None = None,
    min_dte: int = 30,
    max_dte: int = 45,
    max_wing_width: float = 20.0,
    max_delta_deviation: float = 0.08,
    min_credit: float = 0.05,
    exit_dte: int = 21,
    commission_per_contract: float = 0.65,
    slippage_per_contract: float = 0.02,
    exit_decision_time: str = "15:55:00",
    min_credit_to_wing_ratio: float = 0.10,
    risk_free_rate: float = 0.04,
    dividend_yield: float = 0.0,
) -> list[IntradayIronCondorSweepRow]:
    deltas = target_deltas or [0.16]
    bids = target_short_bids or [1.0]
    rows: list[IntradayIronCondorSweepRow] = []
    replay_data = build_intraday_quote_replay_data(
        quote_bars,
        IntradayIronCondorBacktestConfig(ticker=ticker.strip().upper(), start=start, end=end),
    )
    for entry_time, wing_width, target_delta, target_short_bid, profit_target, stop_mult in product(
        entry_times,
        wing_widths,
        deltas if selection_mode == "delta" else [None],
        bids if selection_mode == "premium" else [None],
        profit_targets,
        stop_loss_multiples,
    ):
        result = run_intraday_iron_condor_backtest(
            replay_data,
            IntradayIronCondorBacktestConfig(
                ticker=ticker.strip().upper(),
                start=start,
                end=end,
                selector=IntradayIronCondorSelectorConfig(
                    min_dte=min_dte,
                    max_dte=max_dte,
                    wing_width=wing_width,
                    max_wing_width=max_wing_width,
                    selection_mode=selection_mode,
                    target_delta=target_delta if target_delta is not None else 0.16,
                    target_short_bid=target_short_bid if target_short_bid is not None else 1.0,
                    max_delta_deviation=max_delta_deviation,
                    min_credit=min_credit,
                    min_credit_to_wing_ratio=min_credit_to_wing_ratio,
                    risk_free_rate=risk_free_rate,
                    dividend_yield=dividend_yield,
                ),
                entry_time=entry_time,
                profit_target_pct=profit_target,
                stop_loss_credit_multiple=stop_mult,
                exit_dte=exit_dte,
                max_concurrent_trades=1,
                commission_per_contract=commission_per_contract,
                slippage_per_contract=slippage_per_contract,
                exit_decision_time=exit_decision_time,
            ),
        )
        expectancy, expectancy_tstat = expectancy_stats(result)
        rows.append(
            IntradayIronCondorSweepRow(
                rank=0,
                entry_time=entry_time,
                selection_mode=selection_mode,
                wing_width=wing_width,
                target_delta=target_delta,
                target_short_bid=target_short_bid,
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
    # Rank by per-trade expectancy t-stat (statistically-real edge), NOT total_pnl
    # or win_rate. Rows with zero closed trades carry no evidence and sink to the
    # bottom regardless of their (vacuous) 0.0 expectancy. Among trade rows, a
    # valid t-stat ranks above none (n<2 or zero variance); ties break on raw
    # expectancy then trade count (more = more evidence).
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


def format_intraday_iron_condor_sweep_report(rows: list[IntradayIronCondorSweepRow], *, ticker: str) -> str:
    lines = [
        f"# {ticker.strip().upper()} Intraday Iron Condor Parameter Sweep",
        "",
        "Ranked by per-trade expectancy t-stat (statistically-real edge), not total P&L / win rate.",
        "",
        "| rank | entry_time | mode | wing | delta | short_bid | profit_target | stop_mult | trades | win_rate | expectancy | t_stat | total_pnl | max_dd | profit_factor |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        profit_factor = f"{row.profit_factor:.2f}" if row.profit_factor is not None else "inf"
        target_delta = f"{row.target_delta:.2f}" if row.target_delta is not None else ""
        target_short_bid = f"{row.target_short_bid:.2f}" if row.target_short_bid is not None else ""
        tstat = f"{row.expectancy_tstat:.2f}" if row.expectancy_tstat is not None else "n/a"
        lines.append(
            f"| {row.rank} | {row.entry_time} | {row.selection_mode} | {row.wing_width:.2f} | "
            f"{target_delta} | {target_short_bid} | {row.profit_target_pct:.0%} | "
            f"{row.stop_loss_credit_multiple:.2f} | {row.trade_count} | {row.win_rate:.0%} | "
            f"{row.expectancy:.2f} | {tstat} | {row.total_pnl:.2f} | {row.max_drawdown:.2f} | {profit_factor} |"
        )
    return "\n".join(lines) + "\n"
