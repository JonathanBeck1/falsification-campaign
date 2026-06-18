from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from trader import cli
from trader.normalization.models import Event
from trader.storage.store import Store


def _event(event_id: str, ts: datetime) -> Event:
    return Event(
        event_id=event_id,
        source="demo_news",
        title="Demo event",
        published_at=ts,
        observed_at=ts,
        ingested_at=ts,
        event_type="other",
    )


def test_cli_research_cycle_uses_mock_llm_and_writes_manifest(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(
            sqlite_path=db_path,
            trader_ticker="QQQ",
            context_tickers=["QQQ", "SPY"],
            sec_tickers=["AAPL"],
            trader_llm_daily_budget_usd=1.0,
        ),
    )

    def fake_run_research_cycle(*, store, config, deps, notifier=None):
        config.reports_dir.mkdir(parents=True, exist_ok=True)
        manifest = config.reports_dir / "research-cycle-test.md"
        manifest.write_text("# Research Cycle Manifest\n", encoding="utf-8")

        class Result:
            run_id = "run-test"
            status = "succeeded"
            manifest_path = manifest
            error = ""

        return Result()

    monkeypatch.setattr(cli, "run_research_cycle", fake_run_research_cycle, raising=False)

    rc = cli.main(
        [
            "research-cycle",
            "--mock-llm",
            "--benchmark",
            "SPY",
            "--reports-dir",
            str(reports_dir),
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "Research cycle succeeded: run-test" in out
    assert str(reports_dir / "research-cycle-test.md") in out


def test_cli_research_cycle_fails_manifest_when_yahoo_returns_no_bars(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    reports_dir = tmp_path / "reports"
    event_time = datetime(2026, 5, 18, 14, 0, tzinfo=UTC)
    Store(db_path).save_news_event(_event("evt_demo_yahoo_empty", event_time))

    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(
            sqlite_path=db_path,
            trader_ticker="QQQ",
            context_tickers=["QQQ", "SPY"],
            sec_tickers=[],
            trader_llm_daily_budget_usd=1.0,
        ),
    )
    monkeypatch.setattr(cli, "build_notifier", lambda: None)
    monkeypatch.setattr(cli, "enrich_events", lambda **_kwargs: SimpleNamespace(enriched=0, rejected=0))
    monkeypatch.setattr(cli, "fetch_yahoo_intraday_bars", lambda *_args, **_kwargs: [])

    rc = cli.main(
        [
            "research-cycle",
            "--skip-fetch",
            "--mock-llm",
            "--source",
            "demo_news",
            "--benchmark",
            "SPY",
            "--horizons",
            "5m",
            "--reports-dir",
            str(reports_dir),
        ]
    )

    out = capsys.readouterr().out
    manifests = list(reports_dir.glob("research-cycle-*.md"))
    assert rc == 1
    assert "Research cycle failed:" in out
    assert "No bars returned from Yahoo for research-cycle outcome step" in out
    assert len(manifests) == 1
    manifest = manifests[0].read_text(encoding="utf-8")
    assert "failed" in manifest
    assert "No bars returned from Yahoo for research-cycle outcome step" in manifest


def test_cli_research_cycle_records_source_fetch_evidence(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    reports_dir = tmp_path / "reports"

    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(
            sqlite_path=db_path,
            trader_ticker="QQQ",
            context_tickers=["QQQ", "SPY"],
            sec_tickers=[],
            trader_llm_daily_budget_usd=1.0,
        ),
    )
    monkeypatch.setattr(cli, "build_notifier", lambda: None)
    monkeypatch.setattr(cli, "enrich_events", lambda **_kwargs: SimpleNamespace(enriched=0, rejected=0))

    def fake_fetch_and_persist_events(*, source_tracker=None, **_kwargs):
        assert source_tracker is not None
        source_tracker.start_fetch("finnhub")
        source_tracker.record_fetch("finnhub", item_count=0)
        source_tracker.record_persisted_counts({"finnhub": 0})
        return {"finnhub": 0}

    monkeypatch.setattr(cli, "fetch_and_persist_events", fake_fetch_and_persist_events)

    rc = cli.main(
        [
            "research-cycle",
            "--mock-llm",
            "--benchmark",
            "SPY",
            "--horizons",
            "5m",
            "--reports-dir",
            str(reports_dir),
        ]
    )

    capsys.readouterr()
    rows = Store(db_path).list_source_fetches(limit=10)
    assert rc == 0
    assert len(rows) == 1
    assert rows[0]["source"] == "finnhub"
    assert rows[0]["status"] == "empty"
