from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

from trader.storage.migrations import latest_version
from trader.storage.store import Store


def test_store_migrates_legacy_news_events_without_last_seen_at(tmp_path: Path):
    db_path = tmp_path / "legacy.sqlite"
    observed_at = "2026-05-20T12:01:00+00:00"
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        schema_sql = resources.files("trader.storage").joinpath("schema.sql").read_text()
        schema_sql = "\n".join(line for line in schema_sql.splitlines() if "last_seen_at" not in line)
        conn.executescript(schema_sql)
        assert "last_seen_at" not in {row[1] for row in conn.execute("PRAGMA table_info(news_events)").fetchall()}
        conn.execute(
            """
            INSERT INTO news_events(event_id, source, title, published_at, observed_at)
            VALUES ('evt-legacy', 'legacy', 'Legacy headline', '2026-05-20T12:00:00+00:00', ?)
            """,
            (observed_at,),
        )
    finally:
        conn.close()

    Store(db_path)

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(news_events)").fetchall()}
        row = conn.execute(
            "SELECT observed_at, last_seen_at FROM news_events WHERE event_id = 'evt-legacy'"
        ).fetchone()
        version = conn.execute("PRAGMA user_version").fetchone()[0]

        assert "last_seen_at" in columns
        assert row == (observed_at, observed_at)
        assert version == latest_version()
    finally:
        conn.close()
