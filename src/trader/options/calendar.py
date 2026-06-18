"""NYSE trading-day iteration for backfill scheduling.

Uses `exchange_calendars` (a declared dependency) so the backfill only spends
ThetaData's rate budget on real sessions, never weekends or market holidays.
"""

from __future__ import annotations

from datetime import date


def trading_days(start: date, end: date, *, calendar: str = "XNYS") -> list[date]:
    """Return NYSE (or `calendar`) trading days in [start, end] inclusive."""
    if start > end:
        return []
    import exchange_calendars as xcals

    cal = xcals.get_calendar(calendar)
    sessions = cal.sessions_in_range(start.isoformat(), end.isoformat())
    return [session.date() if hasattr(session, "date") else date.fromisoformat(str(session)[:10]) for session in sessions]
