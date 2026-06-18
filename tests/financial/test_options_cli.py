from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from trader import cli
from trader.options.models import OptionQuote, VolatilityHistoryRow
from trader.storage.store import Store


def _settings(db_path: Path):
    return SimpleNamespace(sqlite_path=db_path, trader_live=False)


def _quote(
    trade_date: date,
    strike: float,
    call_put: str,
    delta: float,
    bid: float,
    ask: float,
    *,
    expiration: date,
) -> OptionQuote:
    return OptionQuote(
        trade_date=trade_date,
        ticker="SPY",
        expiration=expiration,
        strike=strike,
        call_put=call_put,
        bid=bid,
        ask=ask,
        implied_vol=0.18,
        delta=delta,
        gamma=None,
        theta=None,
        vega=None,
        rho=None,
    )


class FakeDoltHubOptionsClient:
    calls: ClassVar[list[tuple[str, str, str, int]]] = []

    def fetch_option_chain(self, ticker: str, *, start: str, end: str, limit: int):
        self.calls.append(("chain", ticker, start, limit))
        trade_date = date.fromisoformat(start)
        expiration = trade_date + timedelta(days=35)
        return [
            _quote(trade_date, 555, "Put", -0.10, 0.50, 0.55, expiration=expiration),
            _quote(trade_date, 560, "Put", -0.16, 1.20, 1.30, expiration=expiration),
            _quote(trade_date, 610, "Call", 0.16, 1.20, 1.30, expiration=expiration),
            _quote(trade_date, 615, "Call", 0.10, 0.50, 0.55, expiration=expiration),
        ]

    def fetch_volatility_history(self, ticker: str, *, start: str, end: str, limit: int):
        self.calls.append(("vol", ticker, start, limit))
        return [
            VolatilityHistoryRow(
                trade_date=date.fromisoformat(start),
                ticker=ticker,
                hv_current=0.11,
                iv_current=0.14,
                iv_year_high=0.26,
                iv_year_low=0.10,
            )
        ]


def test_cli_options_backfill_dolthub_persists_chain_and_vol_history(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    FakeDoltHubOptionsClient.calls = []
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))
    monkeypatch.setattr(cli, "DoltHubOptionsClient", FakeDoltHubOptionsClient, raising=False)

    rc = cli.main(
        [
            "options-backfill-dolthub",
            "--ticker",
            "SPY",
            "--start",
            "2026-05-01",
            "--end",
            "2026-05-01",
        ]
    )

    out = capsys.readouterr().out
    store = Store(db_path)
    assert rc == 0
    assert "option_chain_rows=4" in out
    assert len(store.get_option_chain_eod("SPY")) == 4
    assert len(store.get_option_volatility_history("SPY")) == 1


def test_cli_options_backfill_dolthub_chunks_multi_day_ranges(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    FakeDoltHubOptionsClient.calls = []
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))
    monkeypatch.setattr(cli, "DoltHubOptionsClient", FakeDoltHubOptionsClient, raising=False)

    rc = cli.main(
        [
            "options-backfill-dolthub",
            "--ticker",
            "SPY",
            "--start",
            "2026-05-01",
            "--end",
            "2026-05-03",
            "--chunk-days",
            "1",
        ]
    )

    out = capsys.readouterr().out
    chain_calls = [call for call in FakeDoltHubOptionsClient.calls if call[0] == "chain"]
    assert rc == 0
    assert [call[2] for call in chain_calls] == ["2026-05-01", "2026-05-02", "2026-05-03"]
    assert "chunks=3" in out


def test_cli_options_backtest_iron_condor_writes_report(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output = tmp_path / "iron-condor.md"
    store = Store(db_path)
    d0 = date(2026, 5, 1)
    expiration = d0 + timedelta(days=35)
    store.upsert_option_chain_eod(
        "SPY",
        [
            _quote(d0, 555, "Put", -0.10, 0.50, 0.55, expiration=expiration),
            _quote(d0, 560, "Put", -0.16, 1.20, 1.30, expiration=expiration),
            _quote(d0, 610, "Call", 0.16, 1.20, 1.30, expiration=expiration),
            _quote(d0, 615, "Call", 0.10, 0.50, 0.55, expiration=expiration),
            _quote(d0 + timedelta(days=1), 555, "Put", -0.10, 0.35, 0.40, expiration=expiration),
            _quote(d0 + timedelta(days=1), 560, "Put", -0.16, 0.60, 0.65, expiration=expiration),
            _quote(d0 + timedelta(days=1), 610, "Call", 0.16, 0.60, 0.65, expiration=expiration),
            _quote(d0 + timedelta(days=1), 615, "Call", 0.10, 0.35, 0.40, expiration=expiration),
        ],
    )
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    rc = cli.main(
        [
            "options-backtest-iron-condor",
            "--ticker",
            "SPY",
            "--start",
            "2026-05-01",
            "--end",
            "2026-05-02",
            # The CLI defaults to realistic friction (0.65 commission / 0.02
            # slippage); zero it here to keep this fixture's frictionless
            # profit-target exit. Friction math is covered by the library tests.
            "--commission-per-contract",
            "0",
            "--slippage-per-contract",
            "0",
            "--output",
            str(output),
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert f"Iron condor report written to {output}" in out
    report = output.read_text()
    assert "# SPY Iron Condor Backtest" in report
    assert "trade_count: 1" in report
    assert "profit_target" in report


def test_cli_options_coverage_report_writes_dataset_diagnostics(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output = tmp_path / "coverage.md"
    store = Store(db_path)
    d0 = date(2026, 5, 1)
    expiration = d0 + timedelta(days=35)
    store.upsert_option_chain_eod("SPY", [_quote(d0, 560, "Put", -0.16, 1.20, 1.30, expiration=expiration)])
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    rc = cli.main(
        [
            "options-coverage-report",
            "--ticker",
            "SPY",
            "--start",
            "2026-05-01",
            "--end",
            "2026-05-01",
            "--output",
            str(output),
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert f"Options coverage report written to {output}" in out
    report = output.read_text()
    assert "# SPY Options Coverage" in report
    assert "option_rows: 1" in report


def test_cli_options_sweep_iron_condor_writes_ranked_report(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output = tmp_path / "sweep.md"
    store = Store(db_path)
    d0 = date(2026, 5, 1)
    expiration = d0 + timedelta(days=35)
    store.upsert_option_chain_eod(
        "SPY",
        [
            _quote(d0, 555, "Put", -0.10, 0.50, 0.55, expiration=expiration),
            _quote(d0, 560, "Put", -0.16, 1.20, 1.30, expiration=expiration),
            _quote(d0, 610, "Call", 0.16, 1.20, 1.30, expiration=expiration),
            _quote(d0, 615, "Call", 0.10, 0.50, 0.55, expiration=expiration),
            _quote(d0 + timedelta(days=1), 555, "Put", -0.10, 0.35, 0.40, expiration=expiration),
            _quote(d0 + timedelta(days=1), 560, "Put", -0.16, 0.60, 0.65, expiration=expiration),
            _quote(d0 + timedelta(days=1), 610, "Call", 0.16, 0.60, 0.65, expiration=expiration),
            _quote(d0 + timedelta(days=1), 615, "Call", 0.10, 0.35, 0.40, expiration=expiration),
        ],
    )
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    rc = cli.main(
        [
            "options-sweep-iron-condor",
            "--ticker",
            "SPY",
            "--start",
            "2026-05-01",
            "--end",
            "2026-05-02",
            "--wing-widths",
            "5",
            "--target-deltas",
            "0.16",
            "--profit-targets",
            "0.50,0.75",
            "--stop-loss-multiples",
            "2",
            "--output",
            str(output),
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert f"Iron condor sweep report written to {output}" in out
    report = output.read_text()
    assert "# SPY Iron Condor Parameter Sweep" in report
    assert "| 1 | 5.00 | 0.16 |" in report


def test_cli_options_export_parquet_lake_writes_manifest(monkeypatch, tmp_path: Path, capsys):
    import json
    from datetime import datetime

    pytest.importorskip("duckdb")
    from trader.options.models import OptionQuoteBar
    from trader.storage.parquet_lake import ParquetLake

    db_path = tmp_path / "trader.sqlite"
    out_dir = tmp_path / "lake"
    store = Store(db_path)
    bars = [
        OptionQuoteBar(
            timestamp=datetime(2021, 6, 1, 9, 30 + i),
            ticker="QQQ",
            expiration=date(2021, 7, 16),
            strike=300 + i,
            call_put="C" if i % 2 else "P",
            bid=1.2,
            ask=1.3,
            underlying_price=350.0,
            bid_size=10,
            ask_size=12,
            bid_exchange=1,
            ask_exchange=1,
            bid_condition=0,
            ask_condition=0,
            source="theta",
        )
        for i in range(5)
    ]
    store.upsert_option_quote_bars_1m("QQQ", bars)

    rc = cli.main(
        [
            "options-export-parquet-lake",
            "--db",
            str(db_path),
            "--out",
            str(out_dir),
            "--ticker",
            "QQQ",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    manifest = json.loads(out)
    assert manifest["table"] == "option_quote_bars_1m"
    assert manifest["rows"] == 5
    assert manifest["days"] == 1

    lake = ParquetLake(str(out_dir))
    assert lake.get_option_quote_bars_1m("QQQ", trade_date="2021-06-01") == store.get_option_quote_bars_1m(
        "QQQ", trade_date="2021-06-01"
    )


def test_cli_options_export_parquet_lake_help_works(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["options-export-parquet-lake", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--out" in out
    assert "Parquet lake" in out
