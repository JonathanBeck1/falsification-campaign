"""Network-free unit tests for the Tiingo EOD client.

The HTTP layer is replaced by a stub ``HttpGetter`` so no socket is opened. We
exercise: happy-path parse, adjClose preference, the missing-key path, non-200,
empty/malformed bodies, and that the request carries the key + date range.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from trader.catalysts import tiingo
from trader.catalysts.tiingo import HttpResponse, fetch_daily, parse_prices


def _rows() -> list[dict]:
    return [
        {"date": "2023-01-03T00:00:00.000Z", "close": 10.0, "adjClose": 9.5},
        {"date": "2023-01-04T00:00:00.000Z", "close": 11.0, "adjClose": 10.4},
        {"date": "2023-01-05T00:00:00.000Z", "close": 12.0, "adjClose": 11.3},
    ]


# --- parse_prices (pure) -----------------------------------------------------


def test_parse_prefers_adjclose_and_sorts():
    s = parse_prices(_rows(), "XYZ")
    assert s is not None
    assert list(s.values) == [9.5, 10.4, 11.3]
    assert s.name == "XYZ"
    assert s.index.is_monotonic_increasing
    assert s.index[0] == pd.Timestamp("2023-01-03")


def test_parse_falls_back_to_close_when_no_adjclose():
    rows = [{"date": "2023-01-03", "close": 7.0}]
    s = parse_prices(rows, "XYZ")
    assert s is not None
    assert s.iloc[0] == 7.0


def test_parse_dedupes_keeping_last():
    rows = [
        {"date": "2023-01-03", "adjClose": 1.0},
        {"date": "2023-01-03", "adjClose": 2.0},
    ]
    s = parse_prices(rows, "XYZ")
    assert s is not None
    assert len(s) == 1
    assert s.iloc[0] == 2.0


def test_parse_rejects_non_list_and_empty():
    assert parse_prices({}, "XYZ") is None
    assert parse_prices([], "XYZ") is None
    assert parse_prices("nope", "XYZ") is None


def test_parse_skips_malformed_rows():
    rows = [
        {"date": None, "adjClose": 1.0},
        {"date": "2023-01-04", "adjClose": None},
        {"date": "bad-date", "adjClose": "also-bad"},
        {"date": "2023-01-05", "adjClose": 5.0},
    ]
    s = parse_prices(rows, "XYZ")
    assert s is not None
    assert list(s.values) == [5.0]


# --- fetch_daily (injected getter, no network) -------------------------------


def _getter_factory(response: HttpResponse, captured: dict):
    def getter(url, *, params, headers):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return response

    return getter


def test_fetch_daily_returns_series_tuple(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "secret-key")
    captured: dict = {}
    getter = _getter_factory(HttpResponse(200, _rows()), captured)
    out = fetch_daily("DEAD", date(2023, 1, 1), date(2023, 2, 1), http_get=getter)
    assert out is not None
    (series,) = out
    assert list(series.values) == [9.5, 10.4, 11.3]
    # Request carried the key + date range.
    assert captured["params"]["token"] == "secret-key"
    assert captured["params"]["startDate"] == "2023-01-01"
    assert captured["params"]["endDate"] == "2023-02-01"
    assert "DEAD/prices" in captured["url"]
    assert captured["headers"]["Authorization"] == "Token secret-key"


def test_fetch_daily_no_key_returns_none(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    called = {"hit": False}

    def getter(url, *, params, headers):
        called["hit"] = True
        return HttpResponse(200, _rows())

    out = fetch_daily("DEAD", date(2023, 1, 1), date(2023, 2, 1), http_get=getter)
    assert out is None
    assert called["hit"] is False  # never even attempts the request


def test_fetch_daily_non_200_returns_none(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    getter = _getter_factory(HttpResponse(404, {"detail": "Not found"}), {})
    assert fetch_daily("NOPE", date(2023, 1, 1), date(2023, 2, 1), http_get=getter) is None


def test_fetch_daily_empty_body_returns_none(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    getter = _getter_factory(HttpResponse(200, []), {})
    assert fetch_daily("EMPTY", date(2023, 1, 1), date(2023, 2, 1), http_get=getter) is None


def test_fetch_daily_getter_raise_returns_none(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "k")

    def boom(url, *, params, headers):
        raise RuntimeError("network down")

    assert fetch_daily("BOOM", date(2023, 1, 1), date(2023, 2, 1), http_get=boom) is None


def test_default_getter_is_used_when_none_passed(monkeypatch):
    """When no getter is injected, the httpx-backed default is selected. We stub
    the module-level default so no real socket opens."""
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    captured: dict = {}
    monkeypatch.setattr(
        tiingo,
        "_httpx_getter",
        _getter_factory(HttpResponse(200, _rows()), captured),
    )
    out = fetch_daily("DEAD", date(2023, 1, 1), date(2023, 2, 1))
    assert out is not None
    assert captured["params"]["token"] == "k"
