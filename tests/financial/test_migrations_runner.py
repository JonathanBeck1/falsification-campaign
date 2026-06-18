from __future__ import annotations

import sqlite3
from importlib import resources

import pytest

from trader.storage.migrations import Migration, get_user_version, latest_version, run_migrations


def _apply_baseline_schema(conn: sqlite3.Connection) -> None:
    schema_sql = resources.files("trader.storage").joinpath("schema.sql").read_text()
    conn.executescript(schema_sql)


def test_fresh_in_memory_db_migrates_to_latest_version():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        _apply_baseline_schema(conn)
        run_migrations(conn)

        assert get_user_version(conn) == latest_version()
    finally:
        conn.close()


def test_user_version_zero_db_gets_migrated_up_correctly():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        _apply_baseline_schema(conn)
        conn.execute(
            """
            INSERT INTO news_events(event_id, source, title, published_at, observed_at)
            VALUES ('evt-1', 'test', 'Headline', '2026-05-20T12:00:00+00:00', '2026-05-20T12:01:00+00:00')
            """
        )

        run_migrations(conn)

        columns = {row[1] for row in conn.execute("PRAGMA table_info(news_events)").fetchall()}
        row = conn.execute("SELECT observed_at, last_seen_at FROM news_events WHERE event_id = 'evt-1'").fetchone()
        assert "last_seen_at" in columns
        assert row[1] == row[0]
        assert get_user_version(conn) == latest_version()
    finally:
        conn.close()


def test_already_migrated_db_does_not_rerun_migrations():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    calls = {"n": 0}

    def migration(conn: sqlite3.Connection) -> None:
        calls["n"] += 1

    try:
        conn.execute("PRAGMA user_version = 1")
        run_migrations(conn, [Migration(version=1, name="m0001_test", run=migration)])

        assert calls["n"] == 0
        assert get_user_version(conn) == 1
    finally:
        conn.close()


def test_failed_migration_rolls_back_transaction():
    conn = sqlite3.connect(":memory:", isolation_level=None)

    def migration(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO items(value) VALUES ('partial')")
        raise RuntimeError("boom")

    try:
        conn.execute("CREATE TABLE items(value TEXT NOT NULL)")

        with pytest.raises(RuntimeError, match="boom"):
            run_migrations(conn, [Migration(version=1, name="m0001_fails", run=migration)])

        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
        assert get_user_version(conn) == 0
    finally:
        conn.close()
