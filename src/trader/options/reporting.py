"""Markdown reports for research-only options backtests."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from trader.options.backtest import IronCondorBacktestResult
from trader.options.metrics import ClosedTrade, equity_curve

_METRIC_LABELS: tuple[tuple[str, str, str], ...] = (
    # (key, label, format spec; "d" => int, "" => str())
    ("n_trades", "trades", "d"),
    ("total_pnl", "total_pnl", ".2f"),
    ("total_return", "total_return", ".2%"),
    ("benchmark_return", "benchmark_return", ".2%"),
    ("alpha", "alpha (excess)", ".2%"),
    ("cagr", "cagr", ".2%"),
    ("win_rate", "win_rate", ".1%"),
    ("avg_credit", "avg_credit", ".4f"),
    ("profit_factor", "profit_factor", ".2f"),
    ("max_drawdown", "max_drawdown", ".2f"),
    ("sharpe", "sharpe", ".3f"),
    ("sortino", "sortino", ".3f"),
    ("exposure", "exposure", ".1%"),
    ("avg_hold_days", "avg_hold_days", ".2f"),
)

_RESEARCH_DISCLAIMER = (
    "Research-only backtest on historical quotes. This is not live-trading "
    "evidence; results from synthetic fixtures are not research conclusions."
)


def _format_metric(value: object, fmt: str) -> str:
    if value is None:
        return "n/a"
    if fmt == "d":
        return str(int(value))
    return format(value, fmt)


def render_metrics_markdown(
    metrics: Mapping[str, object],
    *,
    title: str,
    params: Mapping[str, object] | None = None,
) -> str:
    """Render a standardized markdown report from a metrics dict.

    Strategy-neutral: any backtest that produces a ``compute_metrics`` dict
    renders the same table, so reports are comparable across strategies.
    """
    lines = [
        f"# {title}",
        "",
        _RESEARCH_DISCLAIMER,
        "",
    ]
    if params:
        lines += ["## Parameters", ""]
        lines += [f"- {key}: {value}" for key, value in params.items()]
        lines += [""]
    lines += [
        "## Metrics",
        "",
        "| metric | value |",
        "|---|---:|",
    ]
    for key, label, fmt in _METRIC_LABELS:
        if key in metrics:
            lines.append(f"| {label} | {_format_metric(metrics[key], fmt)} |")
    # Surface any extra metrics (e.g. benchmark/alpha added by later phases).
    known = {key for key, _, _ in _METRIC_LABELS} | {"starting_capital"}
    for key, value in metrics.items():
        if key not in known:
            lines.append(f"| {key} | {value} |")
    return "\n".join(lines) + "\n"


def write_research_report(
    *,
    output_path: str | Path,
    metrics: Mapping[str, object],
    trades: Sequence[ClosedTrade],
    title: str,
    params: Mapping[str, object] | None = None,
    starting_capital: float | None = None,
) -> dict[str, str]:
    """Write the markdown report plus machine-readable JSON and an equity CSV.

    Emits three sibling files next to ``output_path``:
    ``<stem>.md``, ``<stem>.json`` (the metrics dict + params), and
    ``<stem>_equity.csv`` (step, equity). Returns the written paths.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    md_path = output.with_suffix(".md")
    json_path = output.with_suffix(".json")
    csv_path = output.with_name(f"{output.stem}_equity.csv")

    md_path.write_text(render_metrics_markdown(metrics, title=title, params=params), encoding="utf-8")
    json_path.write_text(
        json.dumps({"title": title, "params": dict(params or {}), "metrics": dict(metrics)}, indent=2, default=str),
        encoding="utf-8",
    )

    capital = starting_capital if starting_capital is not None else float(metrics.get("starting_capital", 0.0) or 0.0)
    curve = equity_curve(trades, starting_capital=capital) if capital > 0 else [0.0]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["step", "equity"])
        for step, value in enumerate(curve):
            writer.writerow([step, value])

    return {"md": str(md_path), "json": str(json_path), "csv": str(csv_path)}


def format_iron_condor_report(result: IronCondorBacktestResult) -> str:
    summary = result.summary
    lines = [
        f"# {result.config.ticker} Iron Condor Backtest",
        "",
        "Research-only EOD replay. This is not live-trading evidence; intraday NBBO validation is still required.",
        "",
        "## Summary",
        "",
        f"- run_id: {result.run_id}",
        f"- ticker: {result.config.ticker}",
        f"- start: {result.config.start}",
        f"- end: {result.config.end}",
        f"- opened_count: {summary.opened_count}",
        f"- closed_count: {summary.closed_count}",
        f"- unclosed_count: {summary.unclosed_count}",
        f"- trade_count: {summary.trade_count}",
        f"- win_rate: {summary.win_rate:.1%}",
        f"- total_pnl: {summary.total_pnl:.2f}",
        f"- average_pnl: {summary.average_pnl:.2f}",
        f"- average_holding_days: {summary.average_holding_days:.2f}",
        f"- max_drawdown: {summary.max_drawdown:.2f}",
        f"- profit_factor: {summary.profit_factor if summary.profit_factor is not None else 'inf'}",
        "",
        "## Trades",
        "",
        "| entry | exit | reason | expiration | short_put | long_put | short_call | long_call | credit | debit | pnl |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for trade in result.trades:
        exit_debit = f"{trade.exit_debit:.2f}" if trade.exit_debit is not None else ""
        pnl = f"{trade.pnl:.2f}" if trade.pnl is not None else ""
        lines.append(
            f"| {trade.entry_date} | {trade.exit_date or ''} | {trade.exit_reason} | {trade.expiration} | "
            f"{trade.short_put_strike:.2f} | {trade.long_put_strike:.2f} | "
            f"{trade.short_call_strike:.2f} | {trade.long_call_strike:.2f} | "
            f"{trade.entry_credit:.2f} | {exit_debit} | {pnl} |"
        )
    return "\n".join(lines) + "\n"
