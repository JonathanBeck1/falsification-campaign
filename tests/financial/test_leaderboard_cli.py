"""End-to-end CLI test for the `trader-daily leaderboard` subcommand.

Uses the standard test pattern of monkey-patching `cli.get_settings` so
the CLI reads from a tmp SQLite the test seeds.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from trader import cli
from trader.storage.store import Store


def _settings(db_path: Path):
    return SimpleNamespace(
        sqlite_path=db_path,
        trader_live=False,
        trader_starting_cash=100_000.0,
        trader_max_position_pct=0.95,
        trader_max_daily_loss_pct=0.03,
        kill_switch_path=db_path.parent / ".kill",
    )


def _seed(store: Store, brain: str, equities: list[float], *, start: date | None = None) -> None:
    start = start or date(2026, 1, 1)
    for i, eq in enumerate(equities):
        store.record_equity(brain, (start + timedelta(days=i)).isoformat(), eq)


def test_leaderboard_stdout_includes_brain_names_and_tiers(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    _seed(store, "BuyAndHoldBrain", [100.0, 101.0, 102.0, 103.0, 104.0])
    _seed(store, "WinnerBrain", [100.0, 103.0, 106.0, 109.0, 112.0])
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    exit_code = cli.main(["leaderboard"])
    assert exit_code == 0

    out = capsys.readouterr().out
    assert "HORSE-RACE LEADERBOARD" in out
    assert "WinnerBrain" in out
    assert "BuyAndHoldBrain" in out
    assert "EARLY" in out
    assert "NOT M4 backtest evidence" in out


def test_leaderboard_output_writes_markdown(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    _seed(store, "BuyAndHoldBrain", [100.0, 101.0, 102.0, 103.0, 104.0])
    _seed(store, "BrainA", [100.0, 105.0, 108.0, 110.0, 112.0])
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    out_file = tmp_path / "out" / "leaderboard.md"
    exit_code = cli.main(["leaderboard", "--output", str(out_file)])
    assert exit_code == 0

    captured = capsys.readouterr().out
    assert f"Leaderboard written to {out_file}" in captured

    md = out_file.read_text(encoding="utf-8")
    assert md.startswith("# Horse-Race Leaderboard")
    assert "BrainA" in md
    assert "| # | Brain |" in md


def test_leaderboard_since_until_filter_applied(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    _seed(
        store,
        "BuyAndHoldBrain",
        [100.0 + i for i in range(10)],
        start=date(2026, 1, 1),
    )
    _seed(
        store,
        "BrainA",
        [100.0, 105.0, 110.0, 115.0, 120.0, 125.0, 130.0, 135.0, 140.0, 145.0],
        start=date(2026, 1, 1),
    )
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    exit_code = cli.main(
        ["leaderboard", "--since", "2026-01-03", "--until", "2026-01-07"]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "2026-01-03 → 2026-01-07" in out
    assert "(5 days)" in out


def test_leaderboard_missing_baseline_does_not_crash(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    _seed(store, "OnlyBrain", [100.0, 105.0, 110.0, 115.0, 120.0])
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    exit_code = cli.main(["leaderboard", "--baseline", "DoesNotExist"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "DoesNotExist" in out


def test_leaderboard_min_days_filters_insufficient_rows(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    _seed(store, "BuyAndHoldBrain", [100.0, 101.0, 102.0, 103.0, 104.0])
    _seed(store, "VeteranBrain", [100.0, 105.0, 110.0, 115.0, 120.0])
    _seed(store, "NewbieBrain", [100.0, 110.0])
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    exit_code = cli.main(["leaderboard", "--min-days", "5"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "VeteranBrain" in out
    assert "NewbieBrain" not in out


def test_leaderboard_bad_date_exits(tmp_path, monkeypatch):
    db_path = tmp_path / "trader.sqlite"
    Store(db_path)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    with pytest.raises(SystemExit):
        cli.main(["leaderboard", "--since", "not-a-date"])
