from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from zoneinfo import ZoneInfo

from trader import cli
from trader.options.models import OptionContract, OptionQuoteBar, UnderlyingQuoteBar
from trader.storage.store import Store


def _settings(db_path: Path):
    return SimpleNamespace(
        sqlite_path=db_path,
        trader_live=False,
        thetadata_credentials_file=None,
        thetadata_email=None,
        thetadata_password=None,
    )


def _bar(
    timestamp: datetime,
    strike: float,
    call_put: str,
    bid: float,
    ask: float,
    *,
    expiration: date,
) -> OptionQuoteBar:
    return OptionQuoteBar(
        timestamp=timestamp,
        ticker="SPY",
        expiration=expiration,
        strike=strike,
        call_put=call_put,
        bid=bid,
        ask=ask,
        bid_size=10,
        ask_size=10,
        bid_exchange=22,
        ask_exchange=73,
        bid_condition=50,
        ask_condition=50,
        source="fake-thetadata",
    )


class FakeThetaDataOptionsClient:
    calls: ClassVar[list[tuple[str, dict]]] = []

    def __init__(self, **kwargs):
        # Mirror the real client's constructor (creds_file/email/password) so the
        # CLI can build it without caring which auth path is configured.
        self.init_kwargs = kwargs

    def fetch_contracts(self, ticker: str, *, trade_date: date, max_dte: int):
        self.calls.append(("contracts", {"ticker": ticker, "trade_date": trade_date, "max_dte": max_dte}))
        return [
            OptionContract(ticker=ticker, expiration=trade_date + timedelta(days=35), strike=560.0, call_put="Put"),
            OptionContract(ticker=ticker, expiration=trade_date + timedelta(days=35), strike=610.0, call_put="Call"),
            OptionContract(ticker=ticker, expiration=trade_date + timedelta(days=42), strike=560.0, call_put="Put"),
        ]

    def fetch_quote_history(
        self,
        ticker: str,
        *,
        trade_date: date,
        expiration: date,
        start_time: str,
        end_time: str,
        interval: str,
        strike_range: int,
        right: str = "both",
        strike: str = "*",
        max_dte: int | None = None,
    ):
        self.calls.append(
            (
                "quotes",
                {
                    "ticker": ticker,
                    "trade_date": trade_date,
                    "expiration": expiration,
                    "start_time": start_time,
                    "end_time": end_time,
                    "interval": interval,
                    "strike_range": strike_range,
                    "right": right,
                    "strike": strike,
                    "max_dte": max_dte,
                },
            )
        )
        eastern = ZoneInfo("America/New_York")
        timestamp = datetime.combine(trade_date, datetime.strptime(start_time, "%H:%M:%S").time(), tzinfo=eastern)
        return [
            _bar(timestamp, 560, "Put", 1.2, 1.3, expiration=expiration),
            _bar(timestamp, 610, "Call", 1.2, 1.3, expiration=expiration),
        ]

    def fetch_underlying_quote_history(
        self,
        ticker: str,
        *,
        trade_date: date,
        start_time: str,
        end_time: str,
        interval: str,
    ):
        self.calls.append(
            (
                "underlying",
                {
                    "ticker": ticker,
                    "trade_date": trade_date,
                    "start_time": start_time,
                    "end_time": end_time,
                    "interval": interval,
                },
            )
        )
        eastern = ZoneInfo("America/New_York")
        timestamp = datetime.combine(trade_date, datetime.strptime(start_time, "%H:%M:%S").time(), tzinfo=eastern)
        return [
            UnderlyingQuoteBar(
                timestamp=timestamp,
                ticker=ticker,
                bid=586.10,
                ask=586.14,
                bid_size=20,
                ask_size=25,
                source="fake-thetadata",
            )
        ]


def test_cli_options_backfill_thetadata_quotes_discovers_expirations_and_persists_bars(
    monkeypatch, tmp_path: Path, capsys
):
    db_path = tmp_path / "trader.sqlite"
    FakeThetaDataOptionsClient.calls = []
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))
    monkeypatch.setattr(cli, "ThetaDataOptionsClient", FakeThetaDataOptionsClient, raising=False)

    rc = cli.main(
        [
            "options-backfill-thetadata-quotes",
            "--ticker",
            "SPY",
            "--start",
            "2026-05-22",
            "--end",
            "2026-05-22",
            "--min-dte",
            "30",
            "--max-dte",
            "45",
            "--start-time",
            "09:45:00",
            "--end-time",
            "09:46:00",
            "--strike-range",
            "30",
            "--underlying-source",
            "stock",
        ]
    )

    out = capsys.readouterr().out
    store = Store(db_path)
    assert rc == 0
    assert "ThetaData quote backfill" in out
    assert "rows=4" in out
    assert len(store.get_option_quote_bars_1m("SPY", trade_date="2026-05-22")) == 4
    assert store.get_option_quote_bars_1m("SPY", trade_date="2026-05-22")[0].underlying_price == 586.12
    quote_calls = [call for call in FakeThetaDataOptionsClient.calls if call[0] == "quotes"]
    underlying_calls = [call for call in FakeThetaDataOptionsClient.calls if call[0] == "underlying"]
    assert len(quote_calls) == 2  # both in-window expirations pulled (no per-day cap)
    assert len(underlying_calls) == 1
    assert quote_calls[0][1]["expiration"] == date(2026, 6, 26)


def test_cli_options_backtest_intraday_iron_condor_writes_report(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output = tmp_path / "intraday-condor.md"
    store = Store(db_path)
    eastern = ZoneInfo("America/New_York")
    d0 = date(2026, 5, 22)
    expiration = date(2026, 6, 26)
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    exit_ts = datetime(2026, 5, 22, 10, 15, tzinfo=eastern)
    store.upsert_option_quote_bars_1m(
        "SPY",
        [
            _bar(entry_ts, 555, "Put", 0.50, 0.55, expiration=expiration),
            _bar(entry_ts, 560, "Put", 1.20, 1.30, expiration=expiration),
            _bar(entry_ts, 610, "Call", 1.20, 1.30, expiration=expiration),
            _bar(entry_ts, 615, "Call", 0.50, 0.55, expiration=expiration),
            _bar(exit_ts, 555, "Put", 0.35, 0.40, expiration=expiration),
            _bar(exit_ts, 560, "Put", 0.60, 0.65, expiration=expiration),
            _bar(exit_ts, 610, "Call", 0.60, 0.65, expiration=expiration),
            _bar(exit_ts, 615, "Call", 0.35, 0.40, expiration=expiration),
        ],
    )
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    rc = cli.main(
        [
            "options-backtest-intraday-iron-condor",
            "--ticker",
            "SPY",
            "--start",
            d0.isoformat(),
            "--end",
            d0.isoformat(),
            "--entry-time",
            "09:45:00",
            "--target-short-bid",
            "1.20",
            "--selection-mode",
            "premium",
            # Pin friction off and use every-minute exits so this test exercises the
            # profit-target mechanic deterministically, independent of the CLI's
            # realistic research defaults (commission/slippage/daily exit cadence).
            "--commission-per-contract",
            "0",
            "--slippage-per-contract",
            "0",
            "--exit-decision-time",
            "",
            "--output",
            str(output),
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert f"Intraday iron condor report written to {output}" in out
    report = output.read_text()
    assert "# SPY Intraday Iron Condor Backtest" in report
    assert "trade_count: 1" in report
    assert "total_pnl: 70.0" in report
    assert "profit_target" in report

    # Realistic defaults (no friction flags) must apply commission + slippage and
    # the once-a-day exit cadence -- the trustworthy-by-default CLI behavior. This
    # pins that the realism is actually wired and not a silent no-op.
    realistic_output = output.with_name("realistic.md")
    rc_realistic = cli.main(
        [
            "options-backtest-intraday-iron-condor",
            "--ticker",
            "SPY",
            "--start",
            d0.isoformat(),
            "--end",
            d0.isoformat(),
            "--entry-time",
            "09:45:00",
            "--target-short-bid",
            "1.20",
            "--selection-mode",
            "premium",
            "--output",
            str(realistic_output),
        ]
    )
    assert rc_realistic == 0
    realistic_report = realistic_output.read_text()
    assert "trade_count: 1" in realistic_report
    # 70.0 gross - 5.20 commission - 16.0 round-trip slippage = 48.80.
    assert "total_pnl: 48.8" in realistic_report
    assert "48.80" in realistic_report


def test_cli_options_diagnose_intraday_iron_condor_writes_report(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output = tmp_path / "diagnostics.md"
    store = Store(db_path)
    eastern = ZoneInfo("America/New_York")
    d0 = date(2026, 5, 22)
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    store.upsert_option_quote_bars_1m(
        "SPY",
        [
            _bar(entry_ts, 93, "Put", 1.20, 1.30, expiration=date(2026, 6, 26)),
            _bar(entry_ts, 107, "Call", 1.20, 1.30, expiration=date(2026, 6, 26)),
        ],
    )
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    rc = cli.main(
        [
            "options-diagnose-intraday-iron-condor",
            "--ticker",
            "SPY",
            "--start",
            d0.isoformat(),
            "--end",
            d0.isoformat(),
            "--entry-time",
            "09:45:00",
            "--selection-mode",
            "delta",
            "--output",
            str(output),
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert f"Intraday selection diagnostics written to {output}" in out
    report = output.read_text()
    assert "# SPY Intraday Selection Diagnostics" in report
    assert "missing_underlying_price" in report


def test_cli_options_sweep_intraday_iron_condor_writes_report(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output = tmp_path / "intraday-sweep.md"
    store = Store(db_path)
    eastern = ZoneInfo("America/New_York")
    d0 = date(2026, 5, 22)
    expiration = date(2026, 6, 26)
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    exit_ts = datetime(2026, 5, 22, 10, 15, tzinfo=eastern)
    store.upsert_option_quote_bars_1m(
        "SPY",
        [
            _bar(entry_ts, 555, "Put", 0.50, 0.55, expiration=expiration),
            _bar(entry_ts, 560, "Put", 1.20, 1.30, expiration=expiration),
            _bar(entry_ts, 610, "Call", 1.20, 1.30, expiration=expiration),
            _bar(entry_ts, 615, "Call", 0.50, 0.55, expiration=expiration),
            _bar(exit_ts, 555, "Put", 0.35, 0.40, expiration=expiration),
            _bar(exit_ts, 560, "Put", 0.60, 0.65, expiration=expiration),
            _bar(exit_ts, 610, "Call", 0.60, 0.65, expiration=expiration),
            _bar(exit_ts, 615, "Call", 0.35, 0.40, expiration=expiration),
        ],
    )
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    rc = cli.main(
        [
            "options-sweep-intraday-iron-condor",
            "--ticker",
            "SPY",
            "--start",
            d0.isoformat(),
            "--end",
            d0.isoformat(),
            "--entry-times",
            "09:45:00",
            "--selection-mode",
            "premium",
            "--target-short-bids",
            "1.20",
            "--wing-widths",
            "5",
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
    assert f"Intraday iron condor sweep report written to {output}" in out
    report = output.read_text()
    assert "# SPY Intraday Iron Condor Parameter Sweep" in report
    assert "| 1 | 09:45:00 | premium | 5.00 |" in report
