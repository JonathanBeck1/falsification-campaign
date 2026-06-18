from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from trader import cli, runner
from trader.storage.store import Store

SAFE_BRAINS = {
    "BuyAndHoldBrain",
    "ClassicalBrain",
    "ClassicalConservative",
    "ClassicalAggressive",
    "VIXRegimeConservative",
    "VIXRegimeAggressive",
}


class _NullNotifier:
    def send(self, title: str, body: str, *, error: bool = False) -> None:
        pass


def _settings(db_path: Path, *, live: bool = False):
    return SimpleNamespace(
        sqlite_path=db_path,
        trader_live=live,
        trader_ticker="QQQ",
        trader_starting_cash=100_000.0,
        trader_max_position_pct=0.95,
        trader_max_daily_loss_pct=0.03,
        trader_llm_daily_budget_usd=0.0,
        trader_max_llm_calls_per_cycle=0,
        anthropic_api_key=None,
        openai_api_key=None,
        kill_switch_path=db_path.parent / ".kill",
    )


def _seed_bars(store: Store, *, ticker: str = "QQQ", count: int = 250) -> tuple[date, date]:
    first = date(2025, 1, 1)
    rows = []
    for i in range(count):
        trade_date = first + timedelta(days=i)
        close = 100.0 + (i * 0.25)
        rows.append(
            {
                "trade_date": trade_date.isoformat(),
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000.0 + i,
                "vix_close": 15.0,
                "yield_curve_10y_2y": 0.3,
            }
        )
    store.upsert_historical_bars(ticker, rows)
    return first, first + timedelta(days=count - 1)


def test_replay_runs_every_safe_brain_and_records_equity(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    first, last = _seed_bars(store)
    settings = _settings(db_path)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "build_notifier", lambda: _NullNotifier())

    rc = cli.main(
        [
            "replay",
            "--ticker",
            "QQQ",
            "--since",
            (first + timedelta(days=200)).isoformat(),
            "--until",
            last.isoformat(),
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "Replay summary:" in out
    checked = Store(db_path)
    for brain in SAFE_BRAINS:
        assert checked.get_equity_curve(brain), brain


def test_replay_rejects_unsafe_brain(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    Store(db_path)
    settings = _settings(db_path)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    rc = cli.main(
        [
            "replay",
            "--ticker",
            "QQQ",
            "--since",
            "2025-01-01",
            "--until",
            "2025-12-31",
            "--brains",
            "HybridHaikuConservative",
        ]
    )

    err = capsys.readouterr().err
    assert rc == 2
    assert "HybridHaikuConservative" in err
    assert "replay-safe" in err
