from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from trader import cli
from trader.normalization.models import Event, ModelOutputMeta
from trader.research.data_coverage import build_data_coverage, format_data_coverage
from trader.storage.store import Store


def _event(
    event_id: str,
    *,
    source: str,
    event_type: str,
    classified: bool = False,
) -> Event:
    now = datetime(2026, 5, 20, 14, 0, tzinfo=UTC)
    return Event(
        event_id=event_id,
        source=source,
        source_url=f"https://example.com/{event_id}",
        title=f"{event_type} headline",
        published_at=now,
        observed_at=now,
        ingested_at=now,
        classified_at=now if classified else None,
        event_type=event_type,
        index_exposure=["SPY"],
        model_outputs=(
            [
                ModelOutputMeta(
                    classifier="deterministic-test",
                    prompt_version="v1",
                    validation_status="auto_passed",
                    created_at=now,
                )
            ]
            if classified
            else []
        ),
    )


def _settings(db_path: Path):
    return SimpleNamespace(sqlite_path=db_path)


def test_data_coverage_summarizes_prices_events_and_source_fetches(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    store.upsert_historical_bars(
        "QQQ",
        [
            {
                "trade_date": "2026-01-02",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1_000_000,
                "vix_close": 18.0,
                "yield_curve_10y_2y": None,
            },
            {
                "trade_date": "2026-01-03",
                "open": 101.0,
                "high": 102.0,
                "low": 100.0,
                "close": 101.5,
                "volume": 1_100_000,
                "vix_close": None,
                "yield_curve_10y_2y": None,
            },
        ],
    )
    store.save_news_event(_event("evt_fed", source="fed", event_type="fed_commentary", classified=True))
    store.save_news_event(_event("evt_yahoo", source="yahoo_news", event_type="earnings_surprise"))
    fetch_id = store.start_source_fetch("yahoo_news", lookback_days=3)
    store.finish_source_fetch(fetch_id, status="ok", item_count=7, persisted_count=2, latency_ms=123)

    coverage = build_data_coverage(store)

    assert coverage.historical_bars[0].ticker == "QQQ"
    assert coverage.historical_bars[0].rows == 2
    assert coverage.historical_bars[0].vix_rows == 1
    assert {(row.source, row.event_type, row.rows) for row in coverage.news_events} == {
        ("fed", "fed_commentary", 1),
        ("yahoo_news", "earnings_surprise", 1),
    }
    assert coverage.total_news_events == 2
    assert coverage.enriched_news_events == 1
    assert coverage.source_fetches[0].source == "yahoo_news"


def test_format_data_coverage_calls_out_missing_historical_news(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")

    rendered = format_data_coverage(build_data_coverage(store))

    assert rendered.startswith("# Data Coverage Report")
    assert "Historical Bars" in rendered
    assert "News Events" in rendered
    assert "No historical news backfill is present" in rendered


def test_data_status_cli_writes_markdown(tmp_path: Path, monkeypatch, capsys):
    db_path = tmp_path / "trader.sqlite"
    Store(db_path)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    out_path = tmp_path / "reports" / "data-status.md"
    rc = cli.main(["data-status", "--output", str(out_path)])

    assert rc == 0
    assert f"Data coverage written to {out_path}" in capsys.readouterr().out
    assert out_path.read_text(encoding="utf-8").startswith("# Data Coverage Report")
