"""UTC normalization helpers for timestamp storage boundaries."""

from __future__ import annotations

from datetime import UTC, datetime


def ensure_utc(dt: datetime) -> datetime:
    """Return a timezone-aware UTC datetime.

    Naive inputs are treated as already-UTC for backwards compatibility with
    older local rows and source adapters that omitted offsets.
    """
    if dt is None:
        raise ValueError("datetime value cannot be None")
    if dt.tzinfo is None or dt.utcoffset() is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_iso_z(dt: datetime) -> str:
    """Serialize a datetime as canonical UTC ISO-8601 text for SQLite."""
    return ensure_utc(dt).isoformat(timespec="microseconds")
