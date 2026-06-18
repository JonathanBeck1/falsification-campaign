"""Network-free unit tests for the CEF universe spine.

Every HTTP call is replaced by a stub ``HttpGetter`` so no socket is opened. We
cover: org-type-32 filtering (and rejection of other org types), the year-to-year
header-schema drift (2015 vs 2017-lowercase vs 2019+), BOM/banner tolerance,
embedded-comma CSV rows, ticker extraction from ``display_names`` (with co-filer
mis-attribution guard), membership/listing-span assembly, the delisted (absent-
in-final-year) flag, the 2016-gap NOT being treated as a delisting, and the
best-effort fetch wrappers (HTTP error / absent year continue, don't crash).
"""

from __future__ import annotations

import pandas as pd

from trader.catalysts import cef_universe
from trader.catalysts.cef_universe import (
    CefYearRecord,
    HttpResponse,
    TickerInfo,
    attach_ciks,
    build_membership,
    extract_ticker_from_display_names,
    fetch_company_tickers,
    fetch_tiingo_supported_csv,
    fetch_universe_records,
    fetch_year_csv,
    membership_to_dataframe,
    parse_cef_rows,
    parse_company_tickers,
    parse_submissions_identity,
    parse_tiingo_cef_symbols,
    resolve_identities,
    resolve_identity,
    resolve_ticker,
    resolve_tickers,
    tiingo_symbols_to_dataframe,
    tiingo_symbols_to_year_records,
)

# --------------------------------------------------------------------------- #
# CSV fixtures mirroring the real (varying) SEC schemas
# --------------------------------------------------------------------------- #

# 2019+ schema: "CIK Number", "Entity Org Type", quoted name with embedded comma.
CSV_2019 = (
    "Reporting File Number,CIK Number,Entity Name,Entity Org Type,Series ID,"
    "Series Name,Class ID,Class Name,Class Ticker\n"
    "811-001,0000040417,GENERAL AMERICAN INVESTORS,32,S1,Main,C1,Common,[NULL]\n"
    # second class of the SAME fund -> must dedup to one CIK record
    "811-001,0000040417,GENERAL AMERICAN INVESTORS,32,S1,Main,C2,Pref,[NULL]\n"
    # an open-end fund (org type 30) -> excluded
    "811-002,0001605941,\"1290 Funds, Inc.\",30,S2,Bond,C3,Class A,TNFAX\n"
    # another CEF
    "811-003,0000099999,SOME CLOSED FUND,32,S3,Main,C4,Common,[NULL]\n"
)

# 2015 schema: blank banner line first, "CIK"/"Org Type" headers.
CSV_2015 = (
    ",,,,,,,,\n"
    "Reporting File Number,CIK,Name of Registrant,Org Type,Series ID,Series Name,"
    "Class ID,Class Name,Class Ticker\n"
    "811-001,0000040417,GENERAL AMERICAN INVESTORS,32,S1,Main,C1,Common,\n"
    "811-009,0000012345,DEAD CEF TRUST,32,S9,Main,C9,Common,\n"
)

# 2017 schema: banner title line, lowercase "entity_org_type".
CSV_2017 = (
    "Open Gov Series and Class List v final,,,,,,,,\n"
    "rep_file_num,CIK,entity_name,entity_org_type,series_id,series_name,class_id,"
    "class_name,class_ticker_symbol\n"
    "811-001,0000040417,GENERAL AMERICAN INVESTORS,32,S1,Main,C1,Common,[NULL]\n"
)

# 2026 schema with a UTF-8 BOM on the header.
CSV_2026 = (
    "﻿Reporting File Number,CIK Number,Entity Name,Entity Org Type,Series ID,"
    "Series Name,Class ID,Class Name,Class Ticker\n"
    "811-001,0000040417,GENERAL AMERICAN INVESTORS,32,S1,Main,C1,Common,[NULL]\n"
)


# --------------------------------------------------------------------------- #
# parse_cef_rows (pure)
# --------------------------------------------------------------------------- #


def test_parse_filters_org_type_32_and_dedups_cik():
    recs = parse_cef_rows(CSV_2019, 2019)
    ciks = {r.cik for r in recs}
    assert ciks == {"40417", "99999"}  # the org-30 fund excluded; CIKs zero-stripped
    # the two share classes of 40417 collapse to a single record
    assert sum(1 for r in recs if r.cik == "40417") == 1
    assert all(r.year == 2019 for r in recs)


def test_parse_handles_2015_banner_and_alt_headers():
    recs = parse_cef_rows(CSV_2015, 2015)
    assert {r.cik for r in recs} == {"40417", "12345"}


def test_parse_handles_lowercase_2017_header_and_banner():
    recs = parse_cef_rows(CSV_2017, 2017)
    assert {r.cik for r in recs} == {"40417"}


def test_parse_strips_utf8_bom():
    recs = parse_cef_rows(CSV_2026, 2026)
    assert {r.cik for r in recs} == {"40417"}


def test_parse_keeps_name_from_quoted_field():
    recs = parse_cef_rows(CSV_2019, 2019)
    name = next(r.name for r in recs if r.cik == "40417")
    assert name == "GENERAL AMERICAN INVESTORS"


def test_parse_empty_and_headerless_return_empty():
    assert parse_cef_rows("", 2019) == []
    assert parse_cef_rows("   ", 2019) == []
    assert parse_cef_rows("no,header,here\n1,2,3\n", 2019) == []


# --------------------------------------------------------------------------- #
# ticker extraction (pure)
# --------------------------------------------------------------------------- #


def test_extract_ticker_matches_on_cik_anchor():
    names = ["General American Investors Co Inc  (GAM)  (CIK 0000040417)"]
    assert extract_ticker_from_display_names("40417", names) == "GAM"


def test_extract_ticker_none_when_no_ticker_group():
    names = ["GENERAL AMERICAN INVESTORS CO INC  (CIK 0000040417)"]
    assert extract_ticker_from_display_names("40417", names) is None


def test_extract_ticker_ignores_cofiler_ticker():
    # A co-filer on the same filing carries a ticker, but for a DIFFERENT CIK.
    names = [
        "COOPERMAN LEON G  (CIK 0000898382)",
        "Finance of America Companies Inc.  (FOA)  (CIK 0001828937)",
    ]
    # our fund is 40417 -> must NOT pick up FOA
    assert extract_ticker_from_display_names("40417", names) is None
    # but querying for the co-filer's own CIK resolves correctly
    assert extract_ticker_from_display_names("1828937", names) == "FOA"


def test_extract_ticker_handles_dotted_tickers():
    names = ["Some Fund  (BRK.A)  (CIK 0000000123)"]
    assert extract_ticker_from_display_names("123", names) == "BRK.A"


# --------------------------------------------------------------------------- #
# membership assembly + listing span + delisted flag (pure)
# --------------------------------------------------------------------------- #


def _recs(*pairs):
    # pairs of (cik, year[, name])
    out = []
    for p in pairs:
        cik, year = p[0], p[1]
        name = p[2] if len(p) > 2 else f"FUND {cik}"
        out.append(CefYearRecord(cik=cik, name=name, year=year))
    return out


def test_membership_listing_span_and_years():
    records = _recs(("A", 2015), ("A", 2017), ("A", 2026))
    [m] = build_membership(records, window_end=2026)
    assert m.first_year == 2015
    assert m.last_year == 2026
    assert m.years == (2015, 2017, 2026)
    assert m.delisted is False  # present in final year


def test_membership_flags_delisted_when_absent_in_final_year():
    # Fund present 2015-2018, gone after -> delisted by 2026.
    records = _recs(("DEAD", 2015), ("DEAD", 2016), ("DEAD", 2018))
    [m] = build_membership(records, window_end=2026)
    assert m.first_year == 2015
    assert m.last_year == 2018
    assert m.delisted is True


def test_membership_2016_gap_is_not_a_delisting():
    # The real 2016 file is absent, so a live fund can have a hole there. As long
    # as it is present in the FINAL year it is not flagged delisted.
    records = _recs(("LIVE", 2015), ("LIVE", 2017), ("LIVE", 2026))
    [m] = build_membership(records, window_end=2026)
    assert m.delisted is False


def test_membership_latest_nonempty_name_wins():
    records = _recs(("X", 2015, "OLD NAME"), ("X", 2026, "NEW NAME"))
    [m] = build_membership(records, window_end=2026)
    assert m.name == "NEW NAME"


def test_membership_attaches_tickers_and_records_misses():
    records = _recs(("A", 2026), ("B", 2026))
    out = build_membership(records, window_end=2026, tickers={"A": "GAM", "B": None})
    by_cik = {m.cik: m for m in out}
    assert by_cik["A"].ticker == "GAM"
    assert by_cik["B"].ticker is None


def test_membership_attaches_identities_with_exchange_and_listed():
    records = _recs(("A", 2026), ("B", 2026))
    ids = {
        "A": TickerInfo("GAM", "NYSE", True),
        "B": TickerInfo(None, None, False),
    }
    out = build_membership(records, window_end=2026, identities=ids)
    by_cik = {m.cik: m for m in out}
    assert by_cik["A"].ticker == "GAM"
    assert by_cik["A"].exchange == "NYSE"
    assert by_cik["A"].listed is True
    assert by_cik["B"].ticker is None
    assert by_cik["B"].listed is False


def test_membership_to_dataframe_schema():
    records = _recs(("A", 2015), ("A", 2026), ("DEAD", 2015))
    df = membership_to_dataframe(
        build_membership(
            records,
            window_end=2026,
            identities={"A": TickerInfo("GAM", "NYSE", True)},
        )
    )
    assert list(df.columns) == [
        "cik",
        "name",
        "ticker",
        "exchange",
        "listed",
        "first_year",
        "last_year",
        "n_years",
        "years",
        "delisted",
    ]
    row_a = df[df["cik"] == "A"].iloc[0]
    assert row_a["ticker"] == "GAM"
    assert row_a["exchange"] == "NYSE"
    assert bool(row_a["listed"]) is True
    assert row_a["n_years"] == 2
    assert row_a["years"] == "2015,2026"
    assert bool(row_a["delisted"]) is False
    assert bool(df[df["cik"] == "DEAD"].iloc[0]["delisted"]) is True
    assert isinstance(df, pd.DataFrame)


# --------------------------------------------------------------------------- #
# fetch wrappers (injected getter, no network)
# --------------------------------------------------------------------------- #


def _csv_getter(by_url: dict[str, HttpResponse], captured: dict | None = None):
    def getter(url, *, params=None, headers=None):
        if captured is not None:
            captured.setdefault("calls", []).append((url, params, headers))
        return by_url.get(url, HttpResponse(404, ""))

    return getter


def test_fetch_year_csv_returns_text_and_sets_user_agent():
    url = cef_universe.SEC_YEAR_URLS[2019]
    captured: dict = {}
    getter = _csv_getter({url: HttpResponse(200, CSV_2019)}, captured)
    out = fetch_year_csv(2019, identity="me me@x.com", http_get=getter)
    assert out == CSV_2019
    assert captured["calls"][0][2]["User-Agent"] == "me me@x.com"


def test_fetch_year_csv_absent_year_returns_none():
    # 2016 has no URL -> None without any HTTP call.
    called = {"hit": False}

    def getter(url, *, params=None, headers=None):
        called["hit"] = True
        return HttpResponse(200, CSV_2019)

    assert fetch_year_csv(2016, identity="me", http_get=getter) is None
    assert called["hit"] is False


def test_fetch_year_csv_http_error_returns_none():
    url = cef_universe.SEC_YEAR_URLS[2019]
    getter = _csv_getter({url: HttpResponse(500, "")})
    assert fetch_year_csv(2019, identity="me", http_get=getter) is None


def test_fetch_year_csv_getter_raise_returns_none():
    def boom(url, *, params=None, headers=None):
        raise RuntimeError("network down")

    assert fetch_year_csv(2019, identity="me", http_get=boom) is None


def test_fetch_universe_records_continues_past_failed_years():
    # 2019 OK, every other year 404 -> we still get 2019's records, others recorded.
    url = cef_universe.SEC_YEAR_URLS[2019]
    getter = _csv_getter({url: HttpResponse(200, CSV_2019)})
    res = fetch_universe_records(
        identity="me", years=[2018, 2019, 2020], http_get=getter
    )
    assert res.per_year_ciks == {2019: 2}
    assert set(res.failed_years) == {2018, 2020}
    assert {r.cik for r in res.records} == {"40417", "99999"}


# --------------------------------------------------------------------------- #
# ticker resolution wrapper (injected getter)
# --------------------------------------------------------------------------- #


def _efts_body(*names: str) -> dict:
    return {"hits": {"hits": [{"_source": {"display_names": list(names)}}]}}


def test_resolve_ticker_happy_path():
    body = _efts_body("General American Investors  (GAM)  (CIK 0000040417)")

    def getter(url, *, params=None, headers=None):
        return HttpResponse(200, json_body=body)

    assert resolve_ticker("40417", identity="me", http_get=getter) == "GAM"


def test_resolve_ticker_pads_cik_and_sets_user_agent():
    captured: dict = {}

    def getter(url, *, params=None, headers=None):
        captured["params"] = params
        captured["headers"] = headers
        return HttpResponse(200, json_body=_efts_body())

    resolve_ticker("40417", identity="me me@x.com", http_get=getter)
    assert captured["params"]["ciks"] == "0000040417"
    assert captured["headers"]["User-Agent"] == "me me@x.com"


def test_resolve_ticker_none_on_http_error():
    def getter(url, *, params=None, headers=None):
        return HttpResponse(403, "")

    assert resolve_ticker("40417", identity="me", http_get=getter) is None


def test_resolve_ticker_none_on_getter_raise():
    def boom(url, *, params=None, headers=None):
        raise RuntimeError("boom")

    assert resolve_ticker("40417", identity="me", http_get=boom) is None


def test_resolve_tickers_batch_records_hits_and_misses():
    bodies = {
        "40417": _efts_body("GAI  (GAM)  (CIK 0000040417)"),
        "99999": _efts_body("Dead Fund  (CIK 0000099999)"),  # no ticker
    }

    def getter(url, *, params=None, headers=None):
        cik = params["ciks"].lstrip("0")
        return HttpResponse(200, json_body=bodies.get(cik, _efts_body()))

    out = resolve_tickers(["40417", "99999"], identity="me", http_get=getter)
    assert out == {"40417": "GAM", "99999": None}


# --------------------------------------------------------------------------- #
# submissions identity parsing (pure) + resolve_identity (submissions+EFTS)
# --------------------------------------------------------------------------- #


def test_parse_submissions_picks_listed_ticker():
    body = {"tickers": ["GAM", "GAM-PB"], "exchanges": ["NYSE", "NYSE"]}
    info = parse_submissions_identity(body)
    assert info.ticker == "GAM"
    assert info.exchange == "NYSE"
    assert info.listed is True


def test_parse_submissions_prefers_listed_exchange_over_blank():
    # First ticker has no exchange; a later one is NYSE -> pick the listed one.
    body = {"tickers": ["AAA", "BBB"], "exchanges": ["", "NASDAQ"]}
    info = parse_submissions_identity(body)
    assert info.ticker == "BBB"
    assert info.exchange == "NASDAQ"
    assert info.listed is True


def test_parse_submissions_separate_account_is_not_listed():
    # Variable-annuity separate account: empty tickers/exchanges.
    info = parse_submissions_identity({"tickers": [], "exchanges": []})
    assert info.ticker is None
    assert info.exchange is None
    assert info.listed is False


def test_parse_submissions_ticker_without_known_exchange_not_listed():
    body = {"tickers": ["WEIRD"], "exchanges": ["OTC"]}
    info = parse_submissions_identity(body)
    assert info.ticker == "WEIRD"  # still surfaced as a partial resolution
    assert info.listed is False  # OTC is not a recognized listing venue


def test_parse_submissions_handles_garbage():
    assert parse_submissions_identity(None).ticker is None
    assert parse_submissions_identity({"tickers": "x"}).ticker is None


def test_resolve_identity_submissions_primary():
    sub_body = {"tickers": ["GAM"], "exchanges": ["NYSE"]}

    def getter(url, *, params=None, headers=None):
        assert "submissions" in url  # never reaches EFTS when submissions resolves
        return HttpResponse(200, json_body=sub_body)

    info = resolve_identity("40417", identity="me", http_get=getter)
    assert info.ticker == "GAM"
    assert info.listed is True


def test_resolve_identity_falls_back_to_efts_for_dead_fund():
    # Submissions returns empty (dead fund tickers stripped); EFTS recovers it.
    def getter(url, *, params=None, headers=None):
        if "submissions" in url:
            return HttpResponse(200, json_body={"tickers": [], "exchanges": []})
        # EFTS display_names path
        return HttpResponse(
            200,
            json_body=_efts_body(
                "TORTOISE ENERGY INDEPENDENCE FUND  (NDP)  (CIK 0001547158)"
            ),
        )

    info = resolve_identity("1547158", identity="me", http_get=getter)
    assert info.ticker == "NDP"
    assert info.listed is False  # submissions had no exchange for the dead fund


def test_resolve_identity_all_none_when_neither_source_resolves():
    def getter(url, *, params=None, headers=None):
        if "submissions" in url:
            return HttpResponse(200, json_body={"tickers": [], "exchanges": []})
        return HttpResponse(200, json_body=_efts_body("No Ticker Co  (CIK 0000000999)"))

    info = resolve_identity("999", identity="me", http_get=getter)
    assert info == TickerInfo(None, None, False)


def test_resolve_identity_submissions_http_error_then_efts():
    def getter(url, *, params=None, headers=None):
        if "submissions" in url:
            return HttpResponse(500, "")
        return HttpResponse(200, json_body=_efts_body("X  (XYZ)  (CIK 0000000123)"))

    info = resolve_identity("123", identity="me", http_get=getter)
    assert info.ticker == "XYZ"


def test_resolve_identity_efts_fallback_disabled_skips_efts():
    calls = {"efts": 0}

    def getter(url, *, params=None, headers=None):
        if "submissions" in url:
            return HttpResponse(200, json_body={"tickers": [], "exchanges": []})
        calls["efts"] += 1
        return HttpResponse(200, json_body=_efts_body("X  (XYZ)  (CIK 0000000123)"))

    info = resolve_identity(
        "123", identity="me", http_get=getter, efts_fallback=False
    )
    assert info.ticker is None  # EFTS not consulted
    assert calls["efts"] == 0


def test_resolve_identities_batch_counts_listed():
    bodies = {
        "submissions/CIK0000040417": {"tickers": ["GAM"], "exchanges": ["NYSE"]},
        "submissions/CIK0000099999": {"tickers": [], "exchanges": []},
    }

    def getter(url, *, params=None, headers=None):
        for key, body in bodies.items():
            if key in url:
                return HttpResponse(200, json_body=body)
        # EFTS fallback: nothing
        return HttpResponse(200, json_body=_efts_body())

    out = resolve_identities(["40417", "99999"], identity="me", http_get=getter)
    assert out["40417"].listed is True
    assert out["99999"].ticker is None
    assert out["99999"].listed is False


# --------------------------------------------------------------------------- #
# Tiingo NMFQS identity path (pure parse + join) — the corrected CEF anchor
# --------------------------------------------------------------------------- #

# Synthetic Tiingo supported_tickers.csv mirroring the real schema. File "as-of"
# (max endDate) is 2026-06-12, so a fund ending 2026-06-12 is LIVE and one ending
# 2025-04-30 is DELISTED. Covers: a live CEF (GAM, X-symbol XGAMX, also trades on
# NYSE), a dead CEF (NDP, ends 2025-04-30, traded NYSE), an X-symbol whose inner
# ticker does NOT trade anywhere (XZZZX -> ZZZ, NMFQS-only), a non-CEF mutual-fund
# NMFQS symbol that is NOT X…X (AAAGX -> must be ignored), and an X…X duplicate
# row (placeholder + dated) that must merge to the widest span.
TIINGO_CSV = (
    "ticker,exchange,assetType,priceCurrency,startDate,endDate\n"
    "GAM,NYSE,Stock,USD,1980-01-02,2026-06-12\n"
    "XGAMX,NMFQS,Mutual Fund,USD,1999-05-14,2026-06-12\n"
    "NDP,NYSE,Stock,USD,2012-07-31,2025-04-30\n"
    "XNDPX,NMFQS,Mutual Fund,USD,,\n"  # placeholder row (no dates) -> must merge
    "XNDPX,NMFQS,Mutual Fund,USD,2012-07-31,2025-04-30\n"
    "XZZZX,NMFQS,Mutual Fund,USD,2018-01-02,2026-06-11\n"  # inner ZZZ never traded
    "AAAGX,NMFQS,Mutual Fund,USD,1999-10-29,2026-06-12\n"  # open-end MF, not X…X
)

COMPANY_TICKERS = {
    "0": {"cik_str": 40417, "ticker": "GAM", "title": "GENERAL AMERICAN INVESTORS"},
    "1": {"cik_str": 1547158, "ticker": "NDP", "title": "Tortoise Energy"},
    # ZZZ is absent -> XZZZX must resolve to a null CIK (the dead-fund miss case).
}


def test_parse_tiingo_picks_x_symbols_and_derives_price_ticker():
    syms = parse_tiingo_cef_symbols(TIINGO_CSV)
    by_sym = {s.nmfqs_symbol: s for s in syms}
    # only the three X…X NMFQS symbols; the open-end AAAGX and the bare NYSE rows out
    assert set(by_sym) == {"XGAMX", "XNDPX", "XZZZX"}
    assert by_sym["XGAMX"].price_ticker == "GAM"  # strip leading + trailing X
    assert by_sym["XNDPX"].price_ticker == "NDP"


def test_parse_tiingo_merges_duplicate_rows_to_widest_span():
    syms = parse_tiingo_cef_symbols(TIINGO_CSV)
    ndp = next(s for s in syms if s.nmfqs_symbol == "XNDPX")
    # placeholder row had no dates; merged span comes from the dated row
    assert ndp.start_date == "2012-07-31"
    assert ndp.end_date == "2025-04-30"


def test_parse_tiingo_delisted_flag_from_end_date():
    syms = parse_tiingo_cef_symbols(TIINGO_CSV)
    by_sym = {s.nmfqs_symbol: s for s in syms}
    assert by_sym["XGAMX"].delisted is False  # ends at file max -> live
    assert by_sym["XNDPX"].delisted is True  # ends 2025-04-30, well before max
    assert by_sym["XZZZX"].delisted is False  # ends 2026-06-11, within 30d gap


def test_parse_tiingo_price_ticker_traded_flag():
    syms = parse_tiingo_cef_symbols(TIINGO_CSV)
    by_sym = {s.nmfqs_symbol: s for s in syms}
    assert by_sym["XGAMX"].price_ticker_traded is True  # GAM trades on NYSE
    assert by_sym["XNDPX"].price_ticker_traded is True  # NDP trades on NYSE
    assert by_sym["XZZZX"].price_ticker_traded is False  # ZZZ only as NMFQS NAV sym


def test_parse_tiingo_empty_returns_empty():
    assert parse_tiingo_cef_symbols("") == []
    assert parse_tiingo_cef_symbols("   ") == []
    assert parse_tiingo_cef_symbols("ticker,exchange,assetType\n") == []


def test_parse_company_tickers_builds_upper_map():
    m = parse_company_tickers(COMPANY_TICKERS)
    assert m["GAM"] == "40417"  # zero-stripped
    assert m["NDP"] == "1547158"
    assert "ZZZ" not in m


def test_parse_company_tickers_accepts_json_string_and_garbage():
    import json

    m = parse_company_tickers(json.dumps(COMPANY_TICKERS))
    assert m["GAM"] == "40417"
    assert parse_company_tickers(None) == {}
    assert parse_company_tickers([1, 2, 3]) == {}


def test_attach_ciks_hit_and_miss():
    syms = parse_tiingo_cef_symbols(TIINGO_CSV)
    m = parse_company_tickers(COMPANY_TICKERS)
    joined = {s.nmfqs_symbol: s for s in attach_ciks(syms, m)}
    assert joined["XGAMX"].cik == "40417"  # hit
    assert joined["XNDPX"].cik == "1547158"  # hit (live in company_tickers here)
    assert joined["XZZZX"].cik is None  # miss -> recorded null, not guessed


def test_tiingo_symbols_to_dataframe_schema():
    syms = attach_ciks(parse_tiingo_cef_symbols(TIINGO_CSV), parse_company_tickers(COMPANY_TICKERS))
    df = tiingo_symbols_to_dataframe(syms)
    assert list(df.columns) == [
        "nmfqs_symbol",
        "price_ticker",
        "cik",
        "start_date",
        "end_date",
        "delisted",
        "price_ticker_traded",
        "cik_resolved",
    ]
    row = df[df["nmfqs_symbol"] == "XZZZX"].iloc[0]
    assert row["cik"] is None
    assert bool(row["cik_resolved"]) is False


def test_tiingo_year_records_feed_membership_machinery():
    syms = attach_ciks(parse_tiingo_cef_symbols(TIINGO_CSV), parse_company_tickers(COMPANY_TICKERS))
    records, identities = tiingo_symbols_to_year_records(syms, year_start=2015, year_end=2026)
    memberships = build_membership(records, window_end=2026, identities=identities)
    by_cik = {m.cik: m for m in memberships}
    # live CEF keyed on CIK, present through 2026 -> not delisted
    gam = by_cik["40417"]
    assert gam.delisted is False
    assert gam.last_year == 2026
    assert gam.ticker == "GAM"
    assert gam.listed is True  # price ticker trades on an exchange
    # dead CEF keyed on CIK, history ends 2025 -> absent in 2026 -> delisted
    ndp = by_cik["1547158"]
    assert ndp.delisted is True
    assert ndp.last_year == 2025
    # CIK-less dead-fund anchor falls back to the NMFQS symbol as the key
    zzz = by_cik["XZZZX"]
    assert zzz.ticker == "ZZZ"
    assert zzz.listed is False  # inner ticker never trades


def _tiingo_zip_bytes(csv_text: str, name: str = "supported_tickers.csv") -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, csv_text)
    return buf.getvalue()


def test_fetch_tiingo_unzips_csv():
    payload = _tiingo_zip_bytes(TIINGO_CSV)

    def getter(url, *, params=None, headers=None):
        return HttpResponse(200, content=payload)

    out = fetch_tiingo_supported_csv(http_get=getter)
    assert out is not None
    assert out.startswith("ticker,exchange,assetType")
    assert parse_tiingo_cef_symbols(out)  # round-trips through the parser


def test_fetch_tiingo_bad_status_returns_none():
    def getter(url, *, params=None, headers=None):
        return HttpResponse(500, content=b"")

    assert fetch_tiingo_supported_csv(http_get=getter) is None


def test_fetch_tiingo_bad_zip_returns_none():
    def getter(url, *, params=None, headers=None):
        return HttpResponse(200, content=b"not a zip")

    assert fetch_tiingo_supported_csv(http_get=getter) is None


def test_fetch_tiingo_getter_raise_returns_none():
    def boom(url, *, params=None, headers=None):
        raise RuntimeError("network down")

    assert fetch_tiingo_supported_csv(http_get=boom) is None


def test_fetch_company_tickers_parses_json_body():
    def getter(url, *, params=None, headers=None):
        return HttpResponse(200, json_body=COMPANY_TICKERS)

    m = fetch_company_tickers(identity="me me@x.com", http_get=getter)
    assert m["GAM"] == "40417"


def test_fetch_company_tickers_bad_status_returns_empty():
    def getter(url, *, params=None, headers=None):
        return HttpResponse(403)

    assert fetch_company_tickers(identity="me", http_get=getter) == {}
