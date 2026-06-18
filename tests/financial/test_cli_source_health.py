from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from trader import cli
from trader.storage.snapshot import NewsItem
from trader.storage.store import Store


def _settings(db_path: Path):
    return SimpleNamespace(
        sqlite_path=db_path,
        trader_ticker="SPY",
        context_tickers=["SPY", "QQQ"],
        sec_tickers=["AAPL"],
    )


def test_cli_source_health_prints_summary(monkeypatch, tmp_path: Path, capsys):
    store = Store(tmp_path / "trader.sqlite")
    fetch_id = store.start_source_fetch("yahoo_news", lookback_days=3)
    store.finish_source_fetch(fetch_id, status="ok", item_count=4, persisted_count=3, latency_ms=12)
    failed = store.start_source_fetch("fed", lookback_days=90)
    store.finish_source_fetch(failed, status="error", item_count=0, persisted_count=0, latency_ms=7, error="boom")
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(store.db_path))

    rc = cli.main(["source-health", "--limit", "10"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "yahoo_news" in out
    assert "status=ok" in out
    assert "persisted=3" in out
    assert "fed" in out
    assert "boom" in out


def test_cli_backfill_events_all_sources_uses_source_tracker(monkeypatch, tmp_path: Path, capsys):
    captured: dict = {}
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path / "trader.sqlite"))

    def fake_fetch_and_persist_events(**kwargs):
        captured.update(kwargs)
        return {"yahoo_news": 2, "fed": 1}

    monkeypatch.setattr(cli, "fetch_and_persist_events", fake_fetch_and_persist_events)

    rc = cli.main(["backfill-events", "--lookback-days", "30"])

    out = capsys.readouterr().out
    assert rc == 0
    assert captured["lookback_days"] == 30
    assert captured["source_tracker"] is not None
    assert "yahoo_news: 2" in out
    assert "fed: 1" in out


def test_cli_backfill_events_one_source_fetches_only_requested_source(monkeypatch, tmp_path: Path, capsys):
    store = Store(tmp_path / "trader.sqlite")
    captured: dict = {}
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(store.db_path))

    def fake_fetch_one_source_news(source, settings, *, lookback_days, source_tracker):
        captured["source"] = source
        captured["lookback_days"] = lookback_days
        source_tracker.start_fetch(source)
        source_tracker.record_fetch(source, item_count=1)
        return {
            "finnhub": [],
            "alpaca_news": [],
            "yahoo_news": [
                NewsItem(
                    headline="SPY rallies",
                    source="Yahoo",
                    published_at=datetime(2026, 5, 18, 12, 0, tzinfo=UTC),
                )
            ],
            "sec_edgar": [],
            "fed": [],
            "web_news": [],
        }

    monkeypatch.setattr(cli, "_fetch_one_source_news", fake_fetch_one_source_news)

    rc = cli.main(["backfill-events", "--source", "yahoo_news", "--lookback-days", "30"])

    out = capsys.readouterr().out
    assert rc == 0
    assert captured == {"source": "yahoo_news", "lookback_days": 30}
    assert "yahoo_news: 1" in out
    assert store.source_fetch_summary(limit=10)[0]["latest_persisted_count"] == 1
