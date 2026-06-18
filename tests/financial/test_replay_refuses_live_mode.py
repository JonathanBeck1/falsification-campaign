from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from trader import cli
from trader.storage.store import Store

SAFE_BRAINS = {
    "BuyAndHoldBrain",
    "ClassicalBrain",
    "ClassicalConservative",
    "ClassicalAggressive",
    "VIXRegimeConservative",
    "VIXRegimeAggressive",
}


def _settings(db_path: Path):
    return SimpleNamespace(
        sqlite_path=db_path,
        trader_live=True,
        trader_ticker="QQQ",
        trader_starting_cash=100_000.0,
        trader_max_position_pct=0.95,
        trader_max_daily_loss_pct=0.03,
        kill_switch_path=db_path.parent / ".kill",
    )


def test_replay_refuses_live_mode_before_writing_equity(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    rc = cli.main(
        [
            "replay",
            "--ticker",
            "QQQ",
            "--since",
            "2025-01-01",
            "--until",
            "2025-12-31",
        ]
    )

    err = capsys.readouterr().err
    assert rc == 2
    assert "live mode" in err
    assert store.get_historical_bars("QQQ") == []
    for brain in SAFE_BRAINS:
        assert store.get_equity_curve(brain) == []
