"""Persistence interfaces for evidence, features, and signals.

For v0 we use SQLite (see `schema.sql`). This module is intended to grow into
the raw evidence + normalized event store described in
`brain/01_system_architecture.md` and `brain/08_news_event_schema.md`.
"""

from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot, NewsItem, build_snapshot
from trader.storage.store import Store

__all__ = ["Bar", "DailySnapshot", "MacroSnapshot", "NewsItem", "Store", "build_snapshot"]
