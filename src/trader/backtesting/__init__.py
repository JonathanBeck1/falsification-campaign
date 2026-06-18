"""Research and backtesting workflows."""

from trader.backtesting.event_window import (
    DEFAULT_HORIZONS,
    HorizonStats,
    WindowResult,
    aggregate_by_type,
    compute_event_returns,
    format_report,
)

__all__ = [
    "DEFAULT_HORIZONS",
    "HorizonStats",
    "WindowResult",
    "aggregate_by_type",
    "compute_event_returns",
    "format_report",
]
