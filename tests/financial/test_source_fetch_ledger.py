from __future__ import annotations

from pathlib import Path

import pytest

from trader.storage.store import Store


def test_source_fetch_lifecycle_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")

    fetch_id = store.start_source_fetch("yahoo_news", lookback_days=3)
    store.finish_source_fetch(
        fetch_id,
        status="ok",
        item_count=8,
        persisted_count=5,
        latency_ms=42,
        error="",
    )

    rows = store.list_source_fetches(limit=5)

    assert len(rows) == 1
    assert rows[0]["fetch_id"] == fetch_id
    assert rows[0]["source"] == "yahoo_news"
    assert rows[0]["status"] == "ok"
    assert rows[0]["item_count"] == 8
    assert rows[0]["persisted_count"] == 5
    assert rows[0]["lookback_days"] == 3
    assert rows[0]["latency_ms"] == 42
    assert rows[0]["finished_at"] is not None


def test_source_fetch_finish_rejects_unknown_status(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    fetch_id = store.start_source_fetch("fed", lookback_days=None)

    with pytest.raises(ValueError, match="Unsupported source fetch status"):
        store.finish_source_fetch(
            fetch_id,
            status="bad",
            item_count=0,
            persisted_count=0,
            latency_ms=0,
            error="",
        )


def test_source_fetch_summary_aggregates_by_source(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")

    first = store.start_source_fetch("yahoo_news", lookback_days=3)
    store.finish_source_fetch(first, status="empty", item_count=0, persisted_count=0, latency_ms=10)
    second = store.start_source_fetch("yahoo_news", lookback_days=7)
    store.finish_source_fetch(second, status="ok", item_count=4, persisted_count=3, latency_ms=11)
    failed = store.start_source_fetch("fed", lookback_days=90)
    store.finish_source_fetch(failed, status="error", item_count=0, persisted_count=0, latency_ms=12, error="boom")

    summary = {row["source"]: row for row in store.source_fetch_summary(limit=20)}

    assert summary["yahoo_news"]["latest_fetch_id"] == second
    assert summary["yahoo_news"]["latest_status"] == "ok"
    assert summary["yahoo_news"]["attempt_count"] == 2
    assert summary["yahoo_news"]["ok_count"] == 1
    assert summary["yahoo_news"]["empty_count"] == 1
    assert summary["yahoo_news"]["error_count"] == 0
    assert summary["yahoo_news"]["latest_persisted_count"] == 3
    assert summary["fed"]["latest_status"] == "error"
    assert summary["fed"]["latest_error"] == "boom"
