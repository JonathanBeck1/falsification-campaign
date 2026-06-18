from __future__ import annotations

from trader import cli


def test_fetch_events_command_prints_counts(monkeypatch, capsys):
    monkeypatch.setattr(
        "trader.cli.fetch_and_persist_events",
        lambda **kwargs: {"finnhub": 1, "alpaca_news": 0, "yahoo_news": 0, "sec_edgar": 0, "fed": 1},
        raising=False,
    )

    exit_code = cli.main(["fetch-events"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "finnhub: 1" in captured.out
    assert "fed: 1" in captured.out
