"""Brain scoring + leaderboard for the paper-trading horse race.

Phase 5 of the horse race plan. Pure-function metrics live in
`metrics.py`; the orchestrator lives in `leaderboard.py`; text/Markdown
renderers live in `rendering.py`.

The leaderboard is M5-prep paper-trading output — NOT M4 backtest
evidence. Display markers (EARLY / DIR / OK / ★) tier rows by days of
observation so consumers don't confuse paper results with edge proof.
"""

from __future__ import annotations

from trader.scoring.leaderboard import (
    LeaderboardRow,
    build_leaderboard,
    build_oos_row,
    confidence_tier_for_days,
)
from trader.scoring.metrics import (
    annualized_return,
    daily_returns,
    hit_rate,
    max_drawdown,
    sharpe_ratio,
    total_return,
)
from trader.scoring.rendering import render_markdown_table, render_text_table

__all__ = [
    "LeaderboardRow",
    "annualized_return",
    "build_leaderboard",
    "build_oos_row",
    "confidence_tier_for_days",
    "daily_returns",
    "hit_rate",
    "max_drawdown",
    "render_markdown_table",
    "render_text_table",
    "sharpe_ratio",
    "total_return",
]
