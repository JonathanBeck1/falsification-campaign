from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from trader import cli
from trader.normalization.models import Event
from trader.storage.snapshot import Bar
from trader.storage.store import Store


def _bar(ts: datetime, close: float) -> Bar:
    return Bar(timestamp=ts, open=close, high=close, low=close, close=close, volume=1_000)


def _event(
    *,
    event_id: str = "evt_outcome",
    observed_at: datetime,
    published_at: datetime | None = None,
) -> Event:
    return Event(
        event_id=event_id,
        source="demo_news",
        title="Fed comments move SPY",
        summary="Powell says policy is restrictive.",
        published_at=published_at or observed_at,
        observed_at=observed_at,
        ingested_at=observed_at,
        classified_at=observed_at,
        event_type="fed_commentary",
        sentiment="negative",
        sentiment_score=-0.4,
        urgency="high",
    )


def test_cli_outcome_backtest_fetches_yahoo_and_writes_report(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output_path = tmp_path / "outcomes.md"
    store = Store(db_path)
    observed_at = datetime(2026, 5, 20, 12, 5, tzinfo=UTC)
    store.save_news_event(_event(observed_at=observed_at))
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path),
    )
    calls = []

    def fake_yahoo(ticker, start, end, *, minutes):
        calls.append((ticker, start, end, minutes))
        return [
            _bar(datetime(2026, 5, 20, 12, 5, tzinfo=UTC), 100.0),
            _bar(datetime(2026, 5, 20, 12, 10, tzinfo=UTC), 101.0),
            _bar(datetime(2026, 5, 20, 12, 20, tzinfo=UTC), 103.0),
        ]

    monkeypatch.setattr("trader.cli.fetch_yahoo_intraday_bars", fake_yahoo)

    rc = cli.main(
        [
            "outcome-backtest",
            "--benchmark",
            "SPY",
            "--horizons",
            "5m,15m",
            "--output",
            str(output_path),
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert calls == [
        (
            "SPY",
            datetime(2026, 5, 20, 11, 35, tzinfo=UTC),
            datetime(2026, 5, 20, 12, 20, tzinfo=UTC),
            5,
        )
    ]
    assert f"Outcome report written to {output_path}" in out
    report = output_path.read_text()
    assert "# Event Outcome Backtest: SPY" in report
    assert "entry_time: observed_at" in report
    assert "Fed comments move SPY" in report


def test_cli_outcome_backtest_since_offset_is_normalized_to_utc(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    store.save_news_event(_event(observed_at=datetime(2026, 5, 20, 15, 0, tzinfo=UTC)))
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path),
    )
    monkeypatch.setattr(
        "trader.cli.fetch_yahoo_intraday_bars",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Yahoo fetch should not run")),
    )

    rc = cli.main(["outcome-backtest", "--since", "2026-05-20T12:00:00-04:00"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "No events found in the selected window." in out


def test_cli_outcome_backtest_until_offset_is_normalized_to_utc(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output_path = tmp_path / "outcomes.md"
    store = Store(db_path)
    store.save_news_event(_event(observed_at=datetime(2026, 5, 20, 15, 0, tzinfo=UTC)))
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path),
    )
    monkeypatch.setattr(
        "trader.cli.fetch_yahoo_intraday_bars",
        lambda *args, **kwargs: [
            _bar(datetime(2026, 5, 20, 15, 0, tzinfo=UTC), 100.0),
            _bar(datetime(2026, 5, 20, 15, 5, tzinfo=UTC), 101.0),
        ],
    )

    rc = cli.main(
        [
            "outcome-backtest",
            "--until",
            "2026-05-20T12:00:00-04:00",
            "--horizons",
            "5m",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 0
    assert "Outcome report written" in capsys.readouterr().out
    assert "Fed comments move SPY" in output_path.read_text()


def test_cli_outcome_backtest_until_filters_observed_at_not_published_at(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    store.save_news_event(
        _event(
            observed_at=datetime(2026, 5, 20, 15, 0, tzinfo=UTC),
            published_at=datetime(2026, 5, 20, 11, 0, tzinfo=UTC),
        )
    )
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path),
    )
    monkeypatch.setattr(
        "trader.cli.fetch_yahoo_intraday_bars",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Yahoo fetch should not run")),
    )

    rc = cli.main(["outcome-backtest", "--until", "2026-05-20T12:00:00+00:00"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "No events found in the selected window." in out


def test_cli_outcome_backtest_since_filters_observed_at_not_published_at(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "trader.sqlite"
    output_path = tmp_path / "outcomes.md"
    store = Store(db_path)
    store.save_news_event(
        _event(
            observed_at=datetime(2026, 5, 20, 15, 0, tzinfo=UTC),
            published_at=datetime(2026, 5, 20, 11, 0, tzinfo=UTC),
        )
    )
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path),
    )
    monkeypatch.setattr(
        "trader.cli.fetch_yahoo_intraday_bars",
        lambda *args, **kwargs: [
            _bar(datetime(2026, 5, 20, 15, 0, tzinfo=UTC), 100.0),
            _bar(datetime(2026, 5, 20, 15, 5, tzinfo=UTC), 101.0),
        ],
    )

    rc = cli.main(
        [
            "outcome-backtest",
            "--since",
            "2026-05-20T12:00:00+00:00",
            "--horizons",
            "5m",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 0
    assert "Fed comments move SPY" in output_path.read_text()


def test_cli_outcome_backtest_invalid_horizons_returns_readable_error(capsys):
    rc = cli.main(["outcome-backtest", "--horizons", "10x"])
    out = capsys.readouterr().out

    assert rc == 2
    assert "Invalid outcome-backtest arguments:" in out
    assert "Unsupported horizon: 10x" in out


def test_cli_outcome_backtest_invalid_group_by_returns_readable_error(capsys):
    rc = cli.main(["outcome-backtest", "--group-by", "event_type,bad_field"])
    out = capsys.readouterr().out

    assert rc == 2
    assert "Invalid outcome-backtest arguments:" in out
    assert "Unsupported group field: bad_field" in out


def test_cli_outcome_backtest_entry_time_uses_argparse_choices(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["outcome-backtest", "--entry-time", "bad_mode"])

    err = capsys.readouterr().err
    assert excinfo.value.code == 2
    assert "invalid choice: 'bad_mode'" in err
    # Match the choice names without surrounding quotes: Python 3.12 stopped
    # quoting individual argparse choices in "invalid choice" error messages.
    assert "observed_at" in err
    assert "published_at" in err
    assert "classified_at" in err


def test_cli_outcome_backtest_day_horizon_adds_fetch_end_buffer(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "trader.sqlite"
    output_path = tmp_path / "outcomes.md"
    store = Store(db_path)
    observed_at = datetime(2026, 5, 20, 12, 5, tzinfo=UTC)
    store.save_news_event(_event(observed_at=observed_at))
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path),
    )
    calls = []

    def fake_yahoo(ticker, start, end, *, minutes):
        calls.append((ticker, start, end, minutes))
        return [
            _bar(observed_at, 100.0),
            _bar(observed_at + timedelta(days=1), 101.0),
        ]

    monkeypatch.setattr("trader.cli.fetch_yahoo_intraday_bars", fake_yahoo)

    rc = cli.main(
        [
            "outcome-backtest",
            "--horizons",
            "1d",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 0
    assert calls == [
        (
            "SPY",
            datetime(2026, 5, 20, 11, 35, tzinfo=UTC),
            datetime(2026, 5, 25, 12, 5, tzinfo=UTC),
            5,
        )
    ]
    report = output_path.read_text()
    assert "fetch_start: 2026-05-20T11:35:00+00:00" in report
    assert "fetch_end: 2026-05-25T12:05:00+00:00" in report


def test_cli_outcome_backtest_no_bars_returns_error(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    store.save_news_event(_event(observed_at=datetime(2026, 5, 20, 12, 5, tzinfo=UTC)))
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path),
    )
    monkeypatch.setattr("trader.cli.fetch_yahoo_intraday_bars", lambda *args, **kwargs: [])

    rc = cli.main(["outcome-backtest"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "No bars returned from Yahoo." in out


def test_cli_outcome_backtest_no_events_returns_success(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    Store(db_path)
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path),
    )

    rc = cli.main(["outcome-backtest"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "No events found in the selected window." in out
