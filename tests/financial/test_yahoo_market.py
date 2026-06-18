from __future__ import annotations

from datetime import UTC, datetime

from trader.adapters.yahoo import market as yahoo_market
from trader.adapters.yahoo.market import fetch_intraday_bars


class _FakeResponse:
    def __init__(self, payload, *, status_code: int = 200, json_raises: Exception | None = None):
        self._payload = payload
        self.status_code = status_code
        self._json_raises = json_raises

    def raise_for_status(self):
        return None

    def json(self):
        if self._json_raises is not None:
            raise self._json_raises
        return self._payload


class _FakeClient:
    def __init__(self, payload, *, status_code: int = 200, json_raises: Exception | None = None):
        self.payload = payload
        self.status_code = status_code
        self.json_raises = json_raises
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, url, params):
        self.requests.append((url, params))
        return _FakeResponse(self.payload, status_code=self.status_code, json_raises=self.json_raises)


class _SequenceClient:
    """Returns a different response per call — for testing retry behavior."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, url, params):
        self.requests.append((url, params))
        resp = self._responses.pop(0)
        return resp


def test_fetch_intraday_bars_from_yahoo_chart(monkeypatch):
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1_800_000_000, 1_800_000_300],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0, 101.0],
                                "high": [101.0, 102.0],
                                "low": [99.0, 100.0],
                                "close": [100.5, 101.5],
                                "volume": [1000, 1200],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    fake_client = _FakeClient(payload)
    monkeypatch.setattr("httpx.Client", lambda **kwargs: fake_client)

    bars = fetch_intraday_bars(
        "SPY",
        datetime(2026, 1, 15, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 15, 15, 30, tzinfo=UTC),
        minutes=5,
    )

    assert len(bars) == 2
    assert bars[0].timestamp == datetime.fromtimestamp(1_800_000_000, tz=UTC)
    assert bars[0].close == 100.5
    assert bars[1].volume == 1200.0
    assert fake_client.requests[0][0].endswith("/v8/finance/chart/SPY")
    assert fake_client.requests[0][1]["interval"] == "5m"


def test_fetch_intraday_bars_skips_missing_close(monkeypatch):
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1_800_000_000, 1_800_000_300],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0, 101.0],
                                "high": [101.0, 102.0],
                                "low": [99.0, 100.0],
                                "close": [None, 101.5],
                                "volume": [1000, 1200],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    monkeypatch.setattr("httpx.Client", lambda **kwargs: _FakeClient(payload))

    bars = fetch_intraday_bars(
        "SPY",
        datetime(2026, 1, 15, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 15, 15, 30, tzinfo=UTC),
    )

    assert len(bars) == 1
    assert bars[0].close == 101.5


def test_fetch_intraday_bars_returns_empty_on_chart_error(monkeypatch):
    monkeypatch.setattr("httpx.Client", lambda **kwargs: _FakeClient({"chart": {"result": None, "error": {}}}))

    bars = fetch_intraday_bars(
        "SPY",
        datetime(2026, 1, 15, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 15, 15, 30, tzinfo=UTC),
    )

    assert bars == []


def test_fetch_intraday_bars_returns_empty_on_non_json_body(monkeypatch):
    """Cloudflare's challenge page returns 200 with an HTML body. The old
    code called response.json() outside the try/except and crashed the runner."""
    import json

    monkeypatch.setattr(
        "httpx.Client",
        lambda **kwargs: _FakeClient(
            payload=None,
            json_raises=json.JSONDecodeError("not json", "<!doctype html>", 0),
        ),
    )
    monkeypatch.setattr(yahoo_market, "_sleep", lambda _seconds: None)

    bars = fetch_intraday_bars(
        "SPY",
        datetime(2026, 1, 15, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 15, 15, 30, tzinfo=UTC),
    )
    assert bars == []


def test_fetch_intraday_bars_retries_on_429_then_succeeds(monkeypatch):
    """First 429, then real payload → should retry and return the bars."""
    success_payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1_800_000_000],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0],
                                "high": [101.0],
                                "low": [99.0],
                                "close": [100.5],
                                "volume": [1000],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    responses = [
        _FakeResponse(payload=None, status_code=429),
        _FakeResponse(payload=success_payload, status_code=200),
    ]
    seq_client = _SequenceClient(responses)
    monkeypatch.setattr("httpx.Client", lambda **kwargs: seq_client)
    sleep_calls: list[float] = []
    monkeypatch.setattr(yahoo_market, "_sleep", lambda s: sleep_calls.append(s))

    bars = fetch_intraday_bars(
        "SPY",
        datetime(2026, 1, 15, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 15, 15, 30, tzinfo=UTC),
    )

    assert len(bars) == 1
    assert bars[0].close == 100.5
    assert len(seq_client.requests) == 2
    assert sleep_calls == [0.5]  # one backoff between attempt 1 and 2


def test_fetch_intraday_bars_returns_empty_after_retries_exhausted(monkeypatch):
    """Three consecutive 503s → return [] instead of raising."""
    responses = [
        _FakeResponse(payload=None, status_code=503),
        _FakeResponse(payload=None, status_code=503),
        _FakeResponse(payload=None, status_code=503),
    ]
    seq_client = _SequenceClient(responses)
    monkeypatch.setattr("httpx.Client", lambda **kwargs: seq_client)
    sleep_calls: list[float] = []
    monkeypatch.setattr(yahoo_market, "_sleep", lambda s: sleep_calls.append(s))

    bars = fetch_intraday_bars(
        "SPY",
        datetime(2026, 1, 15, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 15, 15, 30, tzinfo=UTC),
    )

    assert bars == []
    assert len(seq_client.requests) == 3
    # Exponential backoff: 0.5, 1.0 between attempts 1→2 and 2→3.
    assert sleep_calls == [0.5, 1.0]
