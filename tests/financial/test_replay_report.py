from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from trader import cli
from trader.research.replay_report import ReplayReportConfig, build_replay_report, format_replay_report
from trader.storage.store import Store


def _settings(db_path: Path):
    return SimpleNamespace(sqlite_path=db_path, trader_ticker="QQQ", trader_starting_cash=100_000.0)


def _seed_equity(store: Store, brain: str, values: list[float], *, start: date) -> None:
    for i, value in enumerate(values):
        store.record_equity(brain, (start + timedelta(days=i)).isoformat(), value)


def _seed_filled_order(store: Store, *, brain: str, trade_date: date, notional: float) -> None:
    snapshot_id = f"snap-{brain}-{trade_date.isoformat()}"
    store.save_snapshot(snapshot_id, trade_date.isoformat(), "QQQ", {"trade_date": trade_date.isoformat()})
    decision_id = store.save_decision(snapshot_id, brain, "BUY", 0.5, 0.8, "test")
    client_order_id = f"order-{brain}-{trade_date.isoformat()}"
    store.record_order(client_order_id, decision_id, brain, "QQQ", "buy", 10.0, "market", None, None)
    store.update_order_status(client_order_id, "filled")
    store.record_fill(client_order_id, 10.0, notional / 10.0, f"{trade_date.isoformat()}T21:00:00+00:00")


def _seed_bars(store: Store, *, start: date, count: int = 10) -> None:
    rows = []
    for i in range(count):
        trade_date = start + timedelta(days=i)
        rows.append(
            {
                "trade_date": trade_date.isoformat(),
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 1_000_000 + i,
                "vix_close": 18.0,
                "yield_curve_10y_2y": None,
            }
        )
    store.upsert_historical_bars("QQQ", rows)


def test_replay_report_builds_full_train_test_windows_with_cost_drag(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    start = date(2026, 1, 1)
    _seed_bars(store, start=start)
    _seed_equity(store, "BuyAndHoldBrain", [100_000, 101_000, 102_000, 103_000, 104_000, 105_000], start=start)
    _seed_equity(store, "ClassicalBrain", [100_000, 102_000, 104_000, 106_000, 108_000, 110_000], start=start)
    _seed_filled_order(store, brain="ClassicalBrain", trade_date=start + timedelta(days=2), notional=50_000.0)
    _seed_filled_order(store, brain="ClassicalBrain", trade_date=start + timedelta(days=4), notional=25_000.0)

    report = build_replay_report(
        store,
        ReplayReportConfig(
            ticker="QQQ",
            since=start,
            until=start + timedelta(days=5),
            train_until=start + timedelta(days=3),
            cost_bps=10.0,
            baseline="BuyAndHoldBrain",
            min_days=1,
            starting_cash=100_000.0,
        ),
    )

    assert [window.name for window in report.windows] == ["full", "train", "test"]
    full_rows = {row.brain: row for row in report.windows[0].rows}
    assert full_rows["ClassicalBrain"].trades == 2
    assert full_rows["ClassicalBrain"].filled_notional == 75_000.0
    assert full_rows["ClassicalBrain"].estimated_cost_usd == 75.0
    assert full_rows["ClassicalBrain"].net_total_return < full_rows["ClassicalBrain"].gross_total_return


def test_format_replay_report_includes_data_coverage_and_caveats(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    start = date(2026, 1, 1)
    _seed_bars(store, start=start)
    _seed_equity(store, "BuyAndHoldBrain", [100_000, 101_000, 102_000], start=start)

    report = build_replay_report(
        store,
        ReplayReportConfig(
            ticker="QQQ",
            since=start,
            until=start + timedelta(days=2),
            train_until=None,
            cost_bps=5.0,
            baseline="BuyAndHoldBrain",
            min_days=1,
            starting_cash=100_000.0,
        ),
    )
    rendered = format_replay_report(report)

    assert rendered.startswith("# Historical Replay Report")
    assert "## Replay Windows" in rendered
    assert "## Data Coverage" in rendered
    assert "not proof of edge" in rendered


def test_replay_report_cli_writes_markdown(tmp_path: Path, monkeypatch, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    start = date(2026, 1, 1)
    _seed_bars(store, start=start)
    _seed_equity(store, "BuyAndHoldBrain", [100_000, 101_000, 102_000], start=start)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    out_path = tmp_path / "reports" / "replay-report.md"
    rc = cli.main(
        [
            "replay-report",
            "--ticker",
            "QQQ",
            "--since",
            start.isoformat(),
            "--until",
            (start + timedelta(days=2)).isoformat(),
            "--cost-bps",
            "5",
            "--min-days",
            "1",
            "--output",
            str(out_path),
        ]
    )

    assert rc == 0
    assert f"Replay report written to {out_path}" in capsys.readouterr().out
    assert out_path.read_text(encoding="utf-8").startswith("# Historical Replay Report")
