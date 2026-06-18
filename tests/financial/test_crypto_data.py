"""Network-free unit tests for the survivorship-aware crypto data foundation.

Every HTTP call is replaced by a stub ``HttpGetter`` so no socket opens. We cover:
funding-CSV parse (header-skip, NaN/short-row tolerance, UTC index), kline-CSV
parse (both the legacy headerless form AND the recent header form), month-list and
symbol-list XML parsing, universe assembly RETAINING delisted symbols, the
delisted-flag derivation (a symbol whose archive stops before the frontier is
delisted; a live symbol tracking the frontier is not), and the best-effort fetch
wrappers (bad zip / non-200 / month-concat) — none of which may raise.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd

from trader.catalysts import crypto_data as cd
from trader.catalysts.crypto_data import (
    HttpResponse,
    SymbolSpan,
    assemble_universe,
    derive_delisted,
    fetch_funding_history,
    fetch_funding_month,
    fetch_kline_month,
    list_perp_symbols,
    parse_funding_csv,
    parse_kline_csv,
    parse_month_list,
    parse_symbol_list,
    survivorship_summary,
)

# --------------------------------------------------------------------------- #
# Real-shape fixtures (verified live against data.binance.vision)
# --------------------------------------------------------------------------- #
FUNDING_CSV = (
    "calc_time,funding_interval_hours,last_funding_rate\n"
    "1609459200002,8,0.00035335\n"
    "1609488000006,8,0.00083995\n"
    "1609516800003,8,-0.00012000\n"
)

# Legacy headerless 12-col kline (pre-2025 dumps).
KLINE_CSV_LEGACY = (
    "1610668800000,1.7007,1.7567,1.4945,1.7142,15848964,1610755199999,"
    "26132512.2031,151056,7277321,12011540.2235,0\n"
    "1610755200000,1.7142,1.8000,1.7000,1.7800,1000000,1610841599999,"
    "1780000,5000,500000,890000,0\n"
)

# Recent dumps prepend a header row.
KLINE_CSV_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore\n"
) + KLINE_CSV_LEGACY


def _zip_bytes(filename: str, body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, body)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Funding parse
# --------------------------------------------------------------------------- #
def test_parse_funding_csv_basic():
    s = parse_funding_csv(FUNDING_CSV, "SRMUSDT")
    assert s is not None
    assert list(s.values) == [0.00035335, 0.00083995, -0.00012000]
    assert s.name == "SRMUSDT"
    # UTC-indexed, ascending.
    assert str(s.index.tz) == "UTC"
    assert s.index.is_monotonic_increasing
    assert s.index[0] == pd.Timestamp("2021-01-01 00:00:00.002", tz="UTC")


def test_parse_funding_csv_skips_header_and_bad_rows():
    text = FUNDING_CSV + "notanumber,8,0.1\n123\n"  # short + non-numeric rows
    s = parse_funding_csv(text, "X")
    assert s is not None and len(s) == 3  # only the 3 good rows survive


def test_parse_funding_csv_empty_returns_none():
    assert parse_funding_csv("", "X") is None
    assert parse_funding_csv("calc_time,funding_interval_hours,last_funding_rate\n", "X") is None


# --------------------------------------------------------------------------- #
# Kline parse — both eras
# --------------------------------------------------------------------------- #
def test_parse_kline_csv_legacy_headerless():
    df = parse_kline_csv(KLINE_CSV_LEGACY, "SRMUSDT")
    assert df is not None
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["close"].iloc[0] == 1.7142
    assert df.index[0] == pd.Timestamp("2021-01-15", tz="UTC")


def test_parse_kline_csv_with_header_row():
    df = parse_kline_csv(KLINE_CSV_HEADER, "X")
    assert df is not None and len(df) == 2  # header skipped, 2 data rows
    assert df["close"].iloc[1] == 1.7800


def test_parse_kline_csv_microsecond_epoch_2025_dumps():
    # Regression: Binance switched open_time to MICROSECONDS (16 digits) in
    # 2025+ dumps. The old hardcoded unit="ms" mapped these to the year ~52,000,
    # which pandas wrapped into 1970 — corrupting every 2025-2026 bar. The unit
    # must auto-detect. 1735689600000000 us == 2025-01-01.
    micro = (
        "1735689600000000,1.0001,1.0002,0.9999,1.0000,123456,1735775999999000,"
        "1,1,1,1,0\n"
    )
    df = parse_kline_csv(micro, "USDCUSDT")
    assert df is not None
    assert df.index[0] == pd.Timestamp("2025-01-01", tz="UTC")
    assert df["close"].iloc[0] == 1.0000


def test_parse_funding_csv_microsecond_epoch():
    # Same microsecond switch can hit funding calc_time; auto-detect it too.
    micro = (
        "calc_time,funding_interval_hours,last_funding_rate\n"
        "1735689600000000,8,0.0001\n"
    )
    s = parse_funding_csv(micro, "X")
    assert s is not None
    assert s.index[0] == pd.Timestamp("2025-01-01", tz="UTC")


def test_parse_kline_csv_empty_returns_none():
    assert parse_kline_csv("", "X") is None


# --------------------------------------------------------------------------- #
# Listing XML parse
# --------------------------------------------------------------------------- #
def test_parse_month_list():
    xml = (
        "<ListBucketResult>"
        "<Contents><Key>data/.../SRMUSDT/SRMUSDT-fundingRate-2020-09.zip</Key></Contents>"
        "<Contents><Key>data/.../SRMUSDT/SRMUSDT-fundingRate-2020-09.zip.CHECKSUM</Key></Contents>"
        "<Contents><Key>data/.../SRMUSDT/SRMUSDT-fundingRate-2021-01.zip</Key></Contents>"
        "</ListBucketResult>"
    )
    months = parse_month_list(xml)
    assert months == [date(2020, 9, 1), date(2021, 1, 1)]  # CHECKSUM ignored, dedup


def test_parse_symbol_list():
    xml = (
        "<ListBucketResult>"
        "<CommonPrefixes><Prefix>data/.../fundingRate/BTCUSDT/</Prefix></CommonPrefixes>"
        "<CommonPrefixes><Prefix>data/.../fundingRate/SRMUSDT/</Prefix></CommonPrefixes>"
        "</ListBucketResult>"
    )
    assert parse_symbol_list(xml) == ["BTCUSDT", "SRMUSDT"]


# --------------------------------------------------------------------------- #
# Survivorship: delisted flag + universe assembly
# --------------------------------------------------------------------------- #
def test_derive_delisted():
    frontier = date(2026, 5, 1)
    # Live: last month tracks frontier (within slack).
    assert derive_delisted(date(2026, 4, 1), frontier) is False
    assert derive_delisted(date(2026, 5, 1), frontier) is False
    # Delisted: archive stops well before frontier.
    assert derive_delisted(date(2024, 7, 1), frontier) is True
    assert derive_delisted(date(2025, 1, 1), frontier) is True


def test_assemble_universe_retains_delisted():
    # SRM (dead, ends 2024-07), BTC (alive to frontier), a fresh listing.
    spans = [
        ("SRMUSDT", [date(2020, 9, 1), date(2024, 7, 1)]),
        ("BTCUSDT", [date(2020, 1, 1), date(2026, 5, 1)]),
        ("NEWUSDT", [date(2025, 1, 1), date(2026, 5, 1)]),
        ("EMPTYUSDT", []),  # dropped
    ]
    uni = assemble_universe(spans, frontier=date(2026, 5, 1))
    by = {s.symbol: s for s in uni}
    assert "EMPTYUSDT" not in by  # no months -> dropped
    # The corpse is RETAINED and flagged — that retention is the whole point.
    assert by["SRMUSDT"].delisted is True
    assert by["SRMUSDT"].is_alt is True
    assert by["SRMUSDT"].first_month == date(2020, 9, 1)
    assert by["BTCUSDT"].delisted is False
    assert by["BTCUSDT"].is_alt is False  # BTC is a major, not the alt tail
    assert by["NEWUSDT"].delisted is False


def test_assemble_universe_frontier_defaults_to_max():
    spans = [("A", [date(2024, 1, 1)]), ("B", [date(2026, 5, 1)])]
    uni = assemble_universe(spans)  # frontier inferred = 2026-05
    by = {s.symbol: s for s in uni}
    assert by["A"].delisted is True  # A stopped 16 months before B's frontier
    assert by["B"].delisted is False


def test_survivorship_summary_counts():
    uni = [
        SymbolSpan("BTCUSDT", date(2020, 1, 1), date(2026, 5, 1), False, False),
        SymbolSpan("SRMUSDT", date(2020, 9, 1), date(2024, 7, 1), True, True),
        SymbolSpan("FOOUSDT", date(2021, 1, 1), date(2026, 5, 1), False, True),
    ]
    s = survivorship_summary(uni)
    assert s == {"total": 3, "delisted": 1, "live": 2, "alt": 2, "alt_delisted": 1}


# --------------------------------------------------------------------------- #
# Best-effort fetch wrappers (stubbed HTTP, never raise)
# --------------------------------------------------------------------------- #
def test_fetch_funding_month_unzips_and_parses():
    payload = _zip_bytes("SRMUSDT-fundingRate-2021-01.csv", FUNDING_CSV)

    def stub(url, *, params=None):
        return HttpResponse(status_code=200, content=payload)

    s = fetch_funding_month("SRMUSDT", 2021, 1, http_get=stub)
    assert s is not None and len(s) == 3


def test_fetch_kline_month_unzips_and_parses():
    payload = _zip_bytes("SRMUSDT-1d-2021-01.csv", KLINE_CSV_LEGACY)

    def stub(url, *, params=None):
        return HttpResponse(status_code=200, content=payload)

    df = fetch_kline_month("SRMUSDT", 2021, 1, http_get=stub)
    assert df is not None and len(df) == 2


def test_fetch_non_200_returns_none_no_raise():
    def stub(url, *, params=None):
        return HttpResponse(status_code=404)

    assert fetch_funding_month("X", 2021, 1, http_get=stub) is None


def test_fetch_bad_zip_returns_none_no_raise():
    def stub(url, *, params=None):
        return HttpResponse(status_code=200, content=b"not a zip")

    assert fetch_funding_month("X", 2021, 1, http_get=stub) is None


def test_fetch_raising_getter_is_caught():
    def stub(url, *, params=None):
        raise ConnectionError("boom")

    assert fetch_funding_month("X", 2021, 1, http_get=stub) is None
    assert list_perp_symbols(http_get=stub) == []


def test_fetch_funding_history_concats_months_and_dedups():
    jan = _zip_bytes("X-fundingRate-2021-01.csv", FUNDING_CSV)
    # Feb: one new row at a later timestamp.
    feb_body = ("calc_time,funding_interval_hours,last_funding_rate\n"
                "1612137600000,8,0.00050000\n")
    feb = _zip_bytes("X-fundingRate-2021-02.csv", feb_body)

    def stub(url, *, params=None):
        if "2021-01" in url:
            return HttpResponse(status_code=200, content=jan)
        if "2021-02" in url:
            return HttpResponse(status_code=200, content=feb)
        return HttpResponse(status_code=404)

    s = fetch_funding_history("X", date(2021, 1, 1), date(2021, 2, 28), http_get=stub)
    assert s is not None and len(s) == 4  # 3 from Jan + 1 from Feb
    assert s.index.is_monotonic_increasing


def test_list_perp_symbols_parses_listing():
    xml = (
        "<ListBucketResult>"
        "<CommonPrefixes><Prefix>data/futures/um/monthly/fundingRate/BTCUSDT/</Prefix></CommonPrefixes>"
        "<CommonPrefixes><Prefix>data/futures/um/monthly/fundingRate/SRMUSDT/</Prefix></CommonPrefixes>"
        "</ListBucketResult>"
    )

    def stub(url, *, params=None):
        return HttpResponse(status_code=200, text=xml)

    assert list_perp_symbols(http_get=stub) == ["BTCUSDT", "SRMUSDT"]


def test_months_between_inclusive():
    assert cd._months_between(date(2021, 11, 1), date(2022, 2, 1)) == [
        (2021, 11), (2021, 12), (2022, 1), (2022, 2),
    ]
