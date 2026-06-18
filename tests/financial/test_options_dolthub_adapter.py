from __future__ import annotations

from datetime import date

from trader.adapters.dolthub.options import DoltHubOptionsClient, normalize_option_chain_rows


def test_normalize_option_chain_rows_converts_dolthub_strings_to_quotes():
    rows = [
        {
            "date": "2026-05-22",
            "act_symbol": "SPY",
            "expiration": "2026-06-26",
            "strike": "560.00",
            "call_put": "Put",
            "bid": "1.20",
            "ask": "1.30",
            "vol": "0.1800",
            "delta": "-0.1600",
            "gamma": "0.0100",
            "theta": "-0.0200",
            "vega": "0.1500",
            "rho": "-0.0100",
        }
    ]

    quotes = normalize_option_chain_rows(rows)

    assert len(quotes) == 1
    quote = quotes[0]
    assert quote.trade_date == date(2026, 5, 22)
    assert quote.ticker == "SPY"
    assert quote.expiration == date(2026, 6, 26)
    assert quote.strike == 560.0
    assert quote.call_put == "Put"
    assert quote.bid == 1.2
    assert quote.ask == 1.3
    assert quote.mid == 1.25
    assert quote.delta == -0.16


def test_dolthub_client_builds_bounded_option_chain_query(monkeypatch):
    captured: list[str] = []

    def fake_query(self, sql: str):
        captured.append(sql)
        return []

    monkeypatch.setattr(DoltHubOptionsClient, "query", fake_query)
    client = DoltHubOptionsClient()

    quotes = client.fetch_option_chain("spy", start="2026-05-01", end="2026-05-22", limit=123)

    assert quotes == []
    sql = captured[0]
    assert "FROM option_chain" in sql
    assert "act_symbol = 'SPY'" in sql
    assert "date >= '2026-05-01'" in sql
    assert "date <= '2026-05-22'" in sql
    assert "LIMIT 123" in sql
