from __future__ import annotations

from datetime import date

import pandas as pd

from trader.adapters.thetadata.options import ThetaDataOptionsClient


class FakeThetaClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def option_list_contracts(self, **kwargs):
        self.calls.append(("option_list_contracts", kwargs))
        return pd.DataFrame(
            [
                {"symbol": "SPY", "expiration": date(2026, 6, 26), "strike": 560.0, "right": "PUT"},
                {"symbol": "SPY", "expiration": "2026-06-26", "strike": 610.0, "right": "CALL"},
            ]
        )

    def option_history_quote(self, **kwargs):
        self.calls.append(("option_history_quote", kwargs))
        return pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "expiration": date(2026, 6, 26),
                    "strike": 560.0,
                    "right": "PUT",
                    "timestamp": pd.Timestamp("2026-05-22 09:45:00-04:00"),
                    "bid_size": 10,
                    "bid_exchange": 22,
                    "bid": 1.2,
                    "bid_condition": 50,
                    "ask_size": 12,
                    "ask_exchange": 73,
                    "ask": 1.3,
                    "ask_condition": 50,
                },
                {
                    "symbol": "SPY",
                    "expiration": "2026-06-26",
                    "strike": 610.0,
                    "right": "CALL",
                    "timestamp": "2026-05-22T09:45:00-04:00",
                    "bid_size": 8,
                    "bid_exchange": 22,
                    "bid": None,
                    "bid_condition": 0,
                    "ask_size": 9,
                    "ask_exchange": 73,
                    "ask": 1.4,
                    "ask_condition": 50,
                },
            ]
        )

    def stock_history_quote(self, **kwargs):
        self.calls.append(("stock_history_quote", kwargs))
        return pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "timestamp": pd.Timestamp("2026-05-22 09:45:00-04:00"),
                    "bid": 586.10,
                    "ask": 586.14,
                    "bid_size": 20,
                    "ask_size": 25,
                }
            ]
        )


def test_thetadata_options_client_normalizes_contracts_and_quote_bars():
    fake = FakeThetaClient()
    client = ThetaDataOptionsClient(client=fake)

    contracts = client.fetch_contracts("spy", trade_date=date(2026, 5, 22), max_dte=60)
    quotes = client.fetch_quote_history(
        "spy",
        trade_date=date(2026, 5, 22),
        expiration=date(2026, 6, 26),
        start_time="09:45:00",
        end_time="09:46:00",
        interval="1m",
        strike_range=30,
    )

    assert contracts[0].ticker == "SPY"
    assert contracts[0].call_put == "Put"
    assert contracts[1].call_put == "Call"
    assert contracts[0].dte_on(date(2026, 5, 22)) == 35

    assert len(quotes) == 2
    assert quotes[0].ticker == "SPY"
    assert quotes[0].trade_date == date(2026, 5, 22)
    assert quotes[0].call_put == "Put"
    assert quotes[0].has_executable_quote is True
    assert quotes[0].mid == 1.25
    assert quotes[1].call_put == "Call"
    assert quotes[1].has_executable_quote is False

    quote_call = fake.calls[-1]
    assert quote_call == (
        "option_history_quote",
        {
            "symbol": "SPY",
            "expiration": date(2026, 6, 26),
            "date": date(2026, 5, 22),
            "interval": "1m",
            "strike": "*",
            "right": "both",
            "start_time": "09:45:00",
            "end_time": "09:46:00",
            "max_dte": None,
            "strike_range": 30,
        },
    )


def test_thetadata_options_client_fetches_underlying_quotes():
    fake = FakeThetaClient()
    client = ThetaDataOptionsClient(client=fake)

    quotes = client.fetch_underlying_quote_history(
        "spy",
        trade_date=date(2026, 5, 22),
        start_time="09:45:00",
        end_time="09:46:00",
        interval="1m",
    )

    assert len(quotes) == 1
    assert quotes[0].ticker == "SPY"
    assert quotes[0].timestamp.isoformat() == "2026-05-22T09:45:00-04:00"
    assert quotes[0].mid == 586.12
    assert fake.calls[-1] == (
        "stock_history_quote",
        {
            "symbol": "SPY",
            "date": date(2026, 5, 22),
            "interval": "1m",
            "start_time": "09:45:00",
            "end_time": "09:46:00",
        },
    )
