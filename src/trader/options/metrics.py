"""Reusable, I/O-free performance metrics for options backtests.

Every function here is pure: it takes a sequence of closed trades (or a derived
equity curve) and returns a number. No file access, no database, no globals.
That keeps the definitions auditable and lets every strategy (iron condor,
short put, ...) report results the same way.

Definitions are deliberately simple and hand-checkable. These are research
diagnostics, not live-trading evidence:

- ``equity_curve`` is ``starting_capital`` plus the running sum of trade P&L,
  ordered by exit time.
- ``max_drawdown`` is the largest peak-to-trough drop of that curve, in currency.
- ``total_return`` is net P&L divided by ``starting_capital``.
- ``cagr`` annualizes total return over the calendar span first-entry..last-exit.
- ``sharpe``/``sortino`` operate on the per-trade return series
  (``pnl / starting_capital``) using the population standard deviation. They are
  NOT annualized by default (``annualization_factor=1.0``); pass a factor such as
  ``sqrt(trades_per_year)`` if you want an annualized figure.
- ``exposure`` is the fraction of calendar days in the window on which at least
  one position was open (union of holding intervals / window length).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean, pstdev

DEFAULT_STARTING_CAPITAL = 10_000.0


@dataclass(frozen=True)
class ClosedTrade:
    """Strategy-neutral closed-trade record consumed by the metric functions."""

    pnl: float
    credit: float
    entry: datetime | date
    exit: datetime | date


def n_trades(trades: Sequence[ClosedTrade]) -> int:
    return len(trades)


def total_pnl(trades: Sequence[ClosedTrade]) -> float:
    return round(sum(trade.pnl for trade in trades), 2)


def win_rate(trades: Sequence[ClosedTrade]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for trade in trades if trade.pnl > 0)
    return wins / len(trades)


def avg_credit(trades: Sequence[ClosedTrade]) -> float:
    if not trades:
        return 0.0
    return round(mean(trade.credit for trade in trades), 4)


def profit_factor(trades: Sequence[ClosedTrade]) -> float | None:
    gains = sum(trade.pnl for trade in trades if trade.pnl > 0)
    losses = sum(trade.pnl for trade in trades if trade.pnl < 0)
    if losses == 0:
        return None
    return round(gains / abs(losses), 4)


def equity_curve(
    trades: Sequence[ClosedTrade],
    *,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
) -> list[float]:
    """Running equity (``starting_capital`` + cumulative P&L), ordered by exit."""
    equity = starting_capital
    curve = [starting_capital]
    for trade in _sorted_by_exit(trades):
        equity += trade.pnl
        curve.append(round(equity, 4))
    return curve


def max_drawdown(
    trades: Sequence[ClosedTrade],
    *,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
) -> float:
    """Largest peak-to-trough drop of the equity curve, in currency (>= 0)."""
    curve = equity_curve(trades, starting_capital=starting_capital)
    peak = curve[0]
    max_dd = 0.0
    for value in curve:
        peak = max(peak, value)
        max_dd = min(max_dd, value - peak)
    return round(abs(max_dd), 4)


def total_return(
    trades: Sequence[ClosedTrade],
    *,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
) -> float:
    if starting_capital <= 0:
        raise ValueError("starting_capital must be positive")
    return round(total_pnl(trades) / starting_capital, 6)


def cagr(
    trades: Sequence[ClosedTrade],
    *,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
) -> float | None:
    """Annualized growth rate over the calendar span first-entry..last-exit.

    Returns None when the span is under a day (can't annualize a single point)
    or the ending equity is non-positive.
    """
    if not trades:
        return None
    span_days = _span_days(trades)
    if span_days < 1:
        return None
    ending = starting_capital + total_pnl(trades)
    if ending <= 0:
        return None
    return round((ending / starting_capital) ** (365.0 / span_days) - 1.0, 6)


def _per_trade_returns(
    trades: Sequence[ClosedTrade],
    *,
    starting_capital: float,
) -> list[float]:
    return [trade.pnl / starting_capital for trade in _sorted_by_exit(trades)]


def sharpe(
    trades: Sequence[ClosedTrade],
    *,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
    risk_free_per_trade: float = 0.0,
    annualization_factor: float = 1.0,
) -> float | None:
    """Mean/stdev of per-trade excess returns (population stdev). None if < 2 trades."""
    returns = _per_trade_returns(trades, starting_capital=starting_capital)
    if len(returns) < 2:
        return None
    excess = [r - risk_free_per_trade for r in returns]
    sigma = pstdev(excess)
    if sigma == 0:
        return None
    return round((mean(excess) / sigma) * annualization_factor, 6)


def sortino(
    trades: Sequence[ClosedTrade],
    *,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
    risk_free_per_trade: float = 0.0,
    annualization_factor: float = 1.0,
) -> float | None:
    """Mean excess return / downside deviation (population, over negative excess)."""
    returns = _per_trade_returns(trades, starting_capital=starting_capital)
    if len(returns) < 2:
        return None
    excess = [r - risk_free_per_trade for r in returns]
    downside = [min(0.0, r) for r in excess]
    downside_dev = pstdev(downside)
    if downside_dev == 0:
        return None
    return round((mean(excess) / downside_dev) * annualization_factor, 6)


def avg_hold_days(trades: Sequence[ClosedTrade]) -> float:
    if not trades:
        return 0.0
    return round(mean(_hold_days(trade) for trade in trades), 4)


def exposure(
    trades: Sequence[ClosedTrade],
    *,
    window_start: date | None = None,
    window_end: date | None = None,
) -> float:
    """Fraction of calendar days in the window with at least one open position."""
    if not trades:
        return 0.0
    start = window_start or min(_as_date(trade.entry) for trade in trades)
    end = window_end or max(_as_date(trade.exit) for trade in trades)
    total_days = (end - start).days + 1
    if total_days <= 0:
        return 0.0
    open_days: set[date] = set()
    for trade in trades:
        day = max(_as_date(trade.entry), start)
        last = min(_as_date(trade.exit), end)
        while day <= last:
            open_days.add(day)
            day += timedelta(days=1)
    return round(len(open_days) / total_days, 6)


def compute_metrics(
    trades: Sequence[ClosedTrade],
    *,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
    window_start: date | None = None,
    window_end: date | None = None,
    annualization_factor: float = 1.0,
) -> dict[str, float | int | None]:
    """Aggregate every metric into one machine-readable dict."""
    return {
        "n_trades": n_trades(trades),
        "total_pnl": total_pnl(trades),
        "total_return": total_return(trades, starting_capital=starting_capital),
        "cagr": cagr(trades, starting_capital=starting_capital),
        "win_rate": round(win_rate(trades), 6),
        "avg_credit": avg_credit(trades),
        "profit_factor": profit_factor(trades),
        "max_drawdown": max_drawdown(trades, starting_capital=starting_capital),
        "sharpe": sharpe(
            trades,
            starting_capital=starting_capital,
            annualization_factor=annualization_factor,
        ),
        "sortino": sortino(
            trades,
            starting_capital=starting_capital,
            annualization_factor=annualization_factor,
        ),
        "exposure": exposure(trades, window_start=window_start, window_end=window_end),
        "avg_hold_days": avg_hold_days(trades),
        "starting_capital": starting_capital,
    }


def closed_trades_from_intraday(result: object) -> list[ClosedTrade]:
    """Adapt an intraday iron-condor result into ``ClosedTrade`` records.

    Skips unclosed trades (``pnl is None``). Lives here so reporting and other
    consumers share one conversion. Duck-typed on the public trade attributes so
    it works for any strategy with the same shape.
    """
    trades: list[ClosedTrade] = []
    for trade in getattr(result, "trades", []):
        if getattr(trade, "pnl", None) is None or trade.exit_ts is None:
            continue
        trades.append(
            ClosedTrade(
                pnl=float(trade.pnl),
                credit=float(trade.entry_credit),
                entry=trade.entry_ts,
                exit=trade.exit_ts,
            )
        )
    return trades


def _sorted_by_exit(trades: Sequence[ClosedTrade]) -> list[ClosedTrade]:
    return sorted(trades, key=lambda trade: _as_datetime(trade.exit))


def _span_days(trades: Sequence[ClosedTrade]) -> int:
    first_entry = min(_as_datetime(trade.entry) for trade in trades)
    last_exit = max(_as_datetime(trade.exit) for trade in trades)
    return (last_exit - first_entry).days


def _hold_days(trade: ClosedTrade) -> float:
    delta = _as_datetime(trade.exit) - _as_datetime(trade.entry)
    return delta.total_seconds() / 86_400.0


def _as_datetime(value: datetime | date) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime(value.year, value.month, value.day)


def _as_date(value: datetime | date) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value
