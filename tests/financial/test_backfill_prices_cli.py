from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import yfinance

from trader import cli
from trader.storage.store import Store


def _settings(db_path: Path):
    return SimpleNamespace(sqlite_path=db_path)


def _history_frame(*, base: float) -> pd.DataFrame:
    index = pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04"])
    return pd.DataFrame(
        {
            "Open": [base, base + 1.0, base + 2.0],
            "High": [base + 2.0, base + 3.0, base + 4.0],
            "Low": [base - 2.0, base - 1.0, base],
            "Close": [base + 0.5, base + 1.5, base + 2.5],
            "Volume": [1_000, 1_100, 1_200],
        },
        index=index,
    )


def test_backfill_prices_writes_ticker_rows_with_vix_close(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    Store(db_path)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, *, start: str, end: str, auto_adjust: bool = False):
            assert start == "2026-01-01"
            assert end == "2026-01-05"
            assert auto_adjust is False
            if self.symbol == "^VIX":
                return _history_frame(base=20.0)
            return _history_frame(base=100.0)

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)

    rc = cli.main(
        [
            "backfill-prices",
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-05",
            "--tickers",
            "QQQ",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "QQQ: 3 rows" in out
    rows = Store(db_path).get_historical_bars("QQQ")
    assert [row["trade_date"] for row in rows] == ["2026-01-02", "2026-01-03", "2026-01-04"]
    assert [row["vix_close"] for row in rows] == [20.5, 21.5, 22.5]
