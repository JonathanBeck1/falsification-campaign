from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from trader import cli
from trader.normalization.fed import fed_news_to_events
from trader.storage.snapshot import Bar, NewsItem
from trader.storage.store import Store


def _bar(ts: datetime, close: float) -> Bar:
    return Bar(timestamp=ts, open=close, high=close, low=close, close=close, volume=1_000)


def test_research_events_defaults_to_yahoo_market_data(monkeypatch, capsys):
    store = Store(Path("data/trader.sqlite"))
    event = fed_news_to_events(
        [
            NewsItem(
                headline="Fed holds rates",
                source="federalreserve.gov",
                published_at=datetime(2026, 5, 18, 14, 0, tzinfo=UTC),
            )
        ]
    )[0]
    store.save_news_event(event)

    calls = []

    def fake_yahoo(ticker, start, end, *, minutes):
        calls.append((ticker, minutes))
        return [
            _bar(datetime(2026, 5, 18, 14, 0, tzinfo=UTC), 100.0),
            _bar(datetime(2026, 5, 18, 14, 5, tzinfo=UTC), 101.0),
        ]

    monkeypatch.setattr("trader.cli.fetch_yahoo_intraday_bars", fake_yahoo)

    exit_code = cli.main(["research-events", "--benchmark", "SPY"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls == [("SPY", 5)]
    assert "via yahoo" in captured.out


def test_research_events_can_use_alpaca_market_data(monkeypatch):
    store = Store(Path("data/trader.sqlite"))
    event = fed_news_to_events(
        [
            NewsItem(
                headline="Fed holds rates",
                source="federalreserve.gov",
                published_at=datetime(2026, 5, 18, 14, 0, tzinfo=UTC),
            )
        ]
    )[0]
    store.save_news_event(event)

    calls = []

    def fake_alpaca(ticker, start, end, *, minutes):
        calls.append((ticker, minutes))
        return [
            _bar(datetime(2026, 5, 18, 14, 0, tzinfo=UTC), 100.0),
            _bar(datetime(2026, 5, 18, 14, 5, tzinfo=UTC), 101.0),
        ]

    monkeypatch.setattr("trader.cli.fetch_alpaca_intraday_bars", fake_alpaca)

    exit_code = cli.main(["research-events", "--benchmark", "SPY", "--data-provider", "alpaca"])

    assert exit_code == 0
    assert calls == [("SPY", 5)]


def test_research_events_passes_as_of_to_store(monkeypatch):
    as_of = datetime(2026, 5, 18, 14, 1, tzinfo=UTC)
    observed_at = datetime(2026, 5, 18, 14, 0, tzinfo=UTC)
    event = fed_news_to_events(
        [
            NewsItem(
                headline="Fed holds rates",
                source="federalreserve.gov",
                published_at=observed_at - timedelta(hours=1),
            )
        ]
    )[0].model_copy(
        update={
            "observed_at": observed_at,
            "ingested_at": observed_at,
            "classified_at": observed_at,
        }
    )
    captured = {}

    def fake_get_news_events_parsed(self, **kwargs):
        captured.update(kwargs)
        return [event]

    def fake_yahoo(ticker, start, end, *, minutes):
        return [
            _bar(observed_at, 100.0),
            _bar(observed_at + timedelta(minutes=5), 101.0),
        ]

    monkeypatch.setattr(Store, "get_news_events_parsed", fake_get_news_events_parsed)
    monkeypatch.setattr("trader.cli.fetch_yahoo_intraday_bars", fake_yahoo)

    exit_code = cli.main(["research-events", "--benchmark", "SPY", "--as-of", as_of.isoformat()])

    assert exit_code == 0
    assert captured["as_of"] == as_of
