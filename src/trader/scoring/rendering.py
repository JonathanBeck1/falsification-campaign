"""Text + Markdown renderers for the horse-race leaderboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from trader.scoring.leaderboard import LeaderboardRow

_TIER_MARKER = {
    "insufficient": "—",
    "early_read": "EARLY",
    "directional": "DIR",
    "useful": "OK",
    "m4_grade": "★",
}


@dataclass(frozen=True)
class WindowSummary:
    since: date | None
    until: date | None
    days_span: int


@dataclass(frozen=True)
class BaselineSummary:
    brain: str
    total_return: float | None  # None when baseline missing/insufficient
    days: int


def _format_pct(value: float, *, sign: bool = True) -> str:
    if sign:
        return f"{value * 100:+.2f}%"
    return f"{value * 100:.2f}%"


def _format_pp(value: float) -> str:
    return f"{value:+.2f}pp"


def _format_int(value: int) -> str:
    return str(value)


def _format_window(window: WindowSummary) -> str:
    if window.since is None and window.until is None:
        return "window: all available data"
    since = window.since.isoformat() if window.since else "—"
    until = window.until.isoformat() if window.until else "—"
    return f"window: {since} → {until}  ({window.days_span} days)"


def _format_baseline(baseline: BaselineSummary) -> str:
    if baseline.total_return is None:
        return (
            f"baseline: {baseline.brain}  total_return: N/A (insufficient data)"
        )
    return (
        f"baseline: {baseline.brain}  total_return: "
        f"{_format_pct(baseline.total_return)}"
    )


def _tier_marker(row: LeaderboardRow) -> str:
    return _TIER_MARKER[row.confidence_tier]


_LEGEND = (
    "Tier legend: EARLY (5-19d) / DIR (20-29d) / OK (30-99d) / ★ M4-grade (100+d)\n"
    "M5-prep horse race. NOT M4 backtest evidence — see brain/16 for the edge gate."
)


def render_text_table(
    rows: list[LeaderboardRow],
    *,
    window: WindowSummary,
    baseline: BaselineSummary,
) -> str:
    """Plain-text fixed-width table for stdout."""
    header = (
        f"HORSE-RACE LEADERBOARD  —  {_format_window(window)}\n"
        f"{_format_baseline(baseline)}\n\n"
        f"{'#':>2}  {'Brain':<35}  {'Tier':<5}  {'Days':>4}  "
        f"{'TotRet':>8}  {'Ann.Ret':>9}  {'Sharpe':>7}  "
        f"{'MaxDD':>7}  {'Hit%':>5}  {'Trades':>6}  {'vs B&H':>8}"
    )
    sep = "─" * len(header.splitlines()[-1])
    lines = [header, sep]
    if not rows:
        lines.append("  (no brains with equity data in this window)")
        lines.append("")
        lines.append(_LEGEND)
        return "\n".join(lines)

    for idx, row in enumerate(rows, start=1):
        rank = "—" if row.confidence_tier == "insufficient" else f"{idx}"
        lines.append(
            f"{rank:>2}  {row.brain[:35]:<35}  {_tier_marker(row):<5}  "
            f"{row.days:>4}  {_format_pct(row.total_return):>8}  "
            f"{_format_pct(row.annualized_return):>9}  {row.sharpe:>7.2f}  "
            f"{_format_pct(row.max_drawdown, sign=False):>7}  "
            f"{row.hit_rate * 100:>4.0f}%  {_format_int(row.trade_count):>6}  "
            f"{_format_pp(row.vs_buy_and_hold_pp):>8}"
        )
    lines.append("")
    lines.append(_LEGEND)
    return "\n".join(lines)


def render_markdown_table(
    rows: list[LeaderboardRow],
    *,
    window: WindowSummary,
    baseline: BaselineSummary,
) -> str:
    """Pipe-separated Markdown table with the same data as the text format."""
    lines = [
        "# Horse-Race Leaderboard",
        "",
        f"- {_format_window(window)}",
        f"- {_format_baseline(baseline)}",
        "",
        "| # | Brain | Tier | Days | TotRet | Ann.Ret | Sharpe | MaxDD | Hit% | Trades | vs B&H |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    if not rows:
        lines.append("| — | (no brains with equity data in this window) | | | | | | | | | |")
    for idx, row in enumerate(rows, start=1):
        rank = "—" if row.confidence_tier == "insufficient" else str(idx)
        lines.append(
            f"| {rank} | {row.brain} | {_tier_marker(row)} | {row.days} | "
            f"{_format_pct(row.total_return)} | "
            f"{_format_pct(row.annualized_return)} | {row.sharpe:.2f} | "
            f"{_format_pct(row.max_drawdown, sign=False)} | "
            f"{row.hit_rate * 100:.0f}% | {row.trade_count} | "
            f"{_format_pp(row.vs_buy_and_hold_pp)} |"
        )
    lines.append("")
    lines.append("Tier legend: EARLY (5-19d) / DIR (20-29d) / OK (30-99d) / ★ M4-grade (100+d).")
    lines.append("")
    lines.append("M5-prep horse race. **NOT M4 backtest evidence** — see `brain/16` for the edge gate.")
    return "\n".join(lines)
