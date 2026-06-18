"""Network-free unit tests for the multi-filer CEF event-detection core.

Every test exercises the PURE parse/dedup/classify/chunk logic or drives the thin
fetch wrappers through a fake ``HttpGetter`` — no socket is opened.
"""

from __future__ import annotations

import itertools
from datetime import date

from trader.catalysts.cef_events import (
    ACTIVIST_FILERS,
    EVENT_ACTIVIST_ENTRY,
    EVENT_DELISTING,
    EVENT_DEREGISTRATION,
    EVENT_LIQUIDATION,
    EVENT_MERGER,
    ActivistFiler,
    CefEvent,
    HttpResponse,
    build_cef_event_cohort,
    build_cohort,
    cohort_to_dataframe,
    date_chunks,
    dedup_campaigns,
    dedup_termination_events,
    efts_search,
    fetch_activist_events,
    looks_like_fund_name,
    parse_activist_hits,
    parse_liquidation_proxy_hits,
    parse_target_from_display,
    parse_termination_hits,
)

# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _hit(form, file_date, display_names, ciks):
    return {"_source": {"form": form, "file_date": file_date, "display_names": display_names, "ciks": ciks}}


def _body(hits, total=None):
    total = len(hits) if total is None else total
    return {"hits": {"total": {"value": total}, "hits": hits}}


SABA = "0001510281"
NPFD = "Nuveen Variable Rate Preferred & Income Fund  (NPFD)  (CIK 0001865389)"
SABA_DN = "Saba Capital Management, L.P.  (CIK 0001510281)"


# --------------------------------------------------------------------------- #
# parse_target_from_display
# --------------------------------------------------------------------------- #


def test_parse_target_with_ticker():
    tkr, cik, name = parse_target_from_display(NPFD)
    assert tkr == "NPFD"
    assert cik == "1865389"  # zero-stripped
    assert "Nuveen" in name


def test_parse_target_ticker_less():
    tkr, cik, name = parse_target_from_display("Some Dead Fund  (CIK 0000123456)")
    assert tkr is None
    assert cik == "123456"
    assert name == "Some Dead Fund"


def test_parse_target_no_cik_returns_raw():
    tkr, cik, name = parse_target_from_display("Garbage with no anchor")
    assert tkr is None and cik is None
    assert name == "Garbage with no anchor"


# --------------------------------------------------------------------------- #
# looks_like_fund_name
# --------------------------------------------------------------------------- #


def test_fund_name_heuristic():
    assert looks_like_fund_name("BlackRock Innovation & Growth Term Trust")
    assert looks_like_fund_name("Nuveen Municipal Income Fund")
    assert not looks_like_fund_name("Apple Inc")
    assert not looks_like_fund_name("Caterpillar")


# --------------------------------------------------------------------------- #
# parse_activist_hits
# --------------------------------------------------------------------------- #


def test_activist_hit_keeps_initial_and_amendment():
    body = _body(
        [
            _hit("SC 13D", "2024-01-18", [NPFD, SABA_DN], ["0001865389", SABA]),
            _hit("SC 13D/A", "2024-02-10", [NPFD, SABA_DN], ["0001865389", SABA]),
        ]
    )
    evs = parse_activist_hits(body, [SABA])
    assert len(evs) == 2
    assert {e.form for e in evs} == {"SC 13D", "SC 13D/A"}
    assert all(e.event_type == EVENT_ACTIVIST_ENTRY for e in evs)
    assert all(e.target_cik == "1865389" for e in evs)
    assert all(e.filer_cik == SABA.lstrip("0") for e in evs)


def test_activist_hit_drops_non_13d_forms():
    # The root-form query can return an SC 13G; we keep only 13D/13D/A.
    body = _body([_hit("SC 13G", "2024-01-18", [NPFD, SABA_DN], ["0001865389", SABA])])
    assert parse_activist_hits(body, [SABA]) == []


def test_activist_hit_requires_filer_is_party():
    # Filer CIK not in the hit's ciks list -> not actually a party -> skip.
    body = _body([_hit("SC 13D", "2024-01-18", [NPFD], ["0001865389"])])
    assert parse_activist_hits(body, [SABA]) == []


def test_activist_hit_target_is_non_filer_party():
    body = _body([_hit("SC 13D", "2024-12-16",
                       ["BlackRock Innovation & Growth Term Trust  (BIGZ)  (CIK 0001836057)", SABA_DN],
                       ["0001836057", SABA])])
    evs = parse_activist_hits(body, [SABA])
    assert len(evs) == 1
    assert evs[0].target_ticker == "BIGZ"
    assert evs[0].target_cik == "1836057"
    assert evs[0].is_fund_name is True


# --------------------------------------------------------------------------- #
# dedup_campaigns
# --------------------------------------------------------------------------- #


SABA_NUM = SABA.lstrip("0")


def _entry(cik, fdate, filer_cik=SABA_NUM, slug="saba", tkr="AAA", name="Some Fund Trust"):
    return CefEvent(
        event_type=EVENT_ACTIVIST_ENTRY,
        target_cik=cik,
        target_ticker=tkr,
        target_name=name,
        filing_date=fdate,
        form="SC 13D",
        filer_slug=slug,
        filer_cik=filer_cik,
    )


def test_dedup_keeps_earliest_per_filer_target():
    evs = [
        _entry("111", date(2023, 5, 1)),
        _entry("111", date(2023, 1, 1)),  # earliest
        _entry("111", date(2023, 9, 1)),
    ]
    out = dedup_campaigns(evs)
    assert len(out) == 1
    assert out[0].filing_date == date(2023, 1, 1)
    assert out[0].cik == "111"


def test_dedup_splits_distinct_filers_on_same_target():
    evs = [
        _entry("111", date(2023, 1, 1), filer_cik="1510281", slug="saba"),
        _entry("111", date(2023, 3, 1), filer_cik="1017918", slug="karpus"),
    ]
    out = dedup_campaigns(evs)
    assert len(out) == 2
    assert {c.filer_slug for c in out} == {"saba", "karpus"}


def test_dedup_uses_amendment_when_no_initial_13d_in_window():
    # Only a 13D/A is observed (initial predates window). It still anchors.
    e = CefEvent(EVENT_ACTIVIST_ENTRY, "222", "BBB", "Muni Income Fund", date(2024, 6, 1),
                 "SC 13D/A", filer_slug="saba", filer_cik="1510281")
    out = dedup_campaigns([e])
    assert len(out) == 1
    assert out[0].filing_date == date(2024, 6, 1)


def test_dedup_ignores_non_activist_events():
    term = CefEvent(EVENT_DEREGISTRATION, "333", None, "Dead Fund", date(2023, 1, 1), "N-8F")
    assert dedup_campaigns([term]) == []


# --------------------------------------------------------------------------- #
# parse_termination_hits
# --------------------------------------------------------------------------- #


def test_termination_form_to_event_mapping():
    body = _body(
        [
            _hit("N-8F", "2023-09-01", ["Old Income Fund  (CIK 0000111111)"], ["0000111111"]),
            _hit("25-NSE", "2023-05-10", ["Dead Trust  (CIK 0000222222)"], ["0000222222"]),
            _hit("N-14 8C", "2023-04-01", ["Merging Fund  (MRG)  (CIK 0000333333)"], ["0000333333"]),
        ]
    )
    evs = parse_termination_hits(body)
    by_type = {e.event_type for e in evs}
    assert by_type == {EVENT_DEREGISTRATION, EVENT_DELISTING, EVENT_MERGER}


def test_termination_skips_unmapped_forms():
    # Root-form query for "25" can also pull a "25-NSE/A" or unrelated form; only
    # mapped exact forms survive.
    body = _body([_hit("8-K", "2023-01-01", ["Whatever Corp  (CIK 0000999999)"], ["0000999999"])])
    assert parse_termination_hits(body) == []


def test_termination_captures_ticker_less_dead_fund():
    body = _body([_hit("N-8F", "2022-03-15", ["Ghost Municipal Trust  (CIK 0000444444)"], ["0000444444"])])
    evs = parse_termination_hits(body)
    assert len(evs) == 1
    assert evs[0].target_ticker is None
    assert evs[0].target_cik == "444444"
    assert evs[0].event_type == EVENT_DEREGISTRATION


def test_termination_25nse_picks_issuer_not_exchange():
    # 25-NSE lists the issuer first, the listing exchange (Nasdaq, CIK 1354457) second.
    body = _body(
        [
            _hit(
                "25-NSE",
                "2023-06-30",
                ["Some Income Fund  (SIF)  (CIK 0000800001)", "Nasdaq Stock Market LLC  (CIK 0001354457)"],
                ["0000800001", "0001354457"],
            )
        ]
    )
    evs = parse_termination_hits(body)
    assert len(evs) == 1
    assert evs[0].target_cik == "800001"  # the issuer, never the exchange
    assert evs[0].target_ticker == "SIF"


def test_termination_skips_when_only_exchange_party():
    # Degenerate: only the exchange CIK present -> no valid target -> skip.
    body = _body([_hit("25-NSE", "2023-06-30", ["Nasdaq Stock Market LLC  (CIK 0001354457)"], ["0001354457"])])
    assert parse_termination_hits(body) == []


# --------------------------------------------------------------------------- #
# parse_liquidation_proxy_hits
# --------------------------------------------------------------------------- #


def test_liquidation_proxy_parse():
    body = _body([_hit("DEF 14A", "2023-07-01", ["Winding Down Fund  (WDF)  (CIK 0000555555)"], ["0000555555"])])
    evs = parse_liquidation_proxy_hits(body)
    assert len(evs) == 1
    assert evs[0].event_type == EVENT_LIQUIDATION
    assert evs[0].target_ticker == "WDF"


def test_liquidation_proxy_skips_non_def():
    body = _body([_hit("10-K", "2023-07-01", ["Some Co  (CIK 0000666666)"], ["0000666666"])])
    assert parse_liquidation_proxy_hits(body) == []


# --------------------------------------------------------------------------- #
# dedup_termination_events
# --------------------------------------------------------------------------- #


def test_dedup_termination_earliest_per_target_type():
    evs = [
        CefEvent(EVENT_DELISTING, "777", None, "F", date(2023, 6, 1), "25-NSE"),
        CefEvent(EVENT_DELISTING, "777", None, "F", date(2023, 1, 1), "25-NSE"),  # earliest
        CefEvent(EVENT_DEREGISTRATION, "777", None, "F", date(2023, 9, 1), "N-8F"),
    ]
    out = dedup_termination_events(evs)
    # One delisting (earliest) + one deregistration — distinct signals on same fund.
    assert len(out) == 2
    delist = next(e for e in out if e.event_type == EVENT_DELISTING)
    assert delist.filing_date == date(2023, 1, 1)


# --------------------------------------------------------------------------- #
# build_cohort + dataframe
# --------------------------------------------------------------------------- #


def test_build_cohort_merges_and_sorts():
    from trader.catalysts.cef_events import CefCampaign

    camps = [CefCampaign("AAA", "111", "Alpha Fund", date(2023, 3, 1), filer_slug="saba", filer_cik="1510281")]
    terms = [CefEvent(EVENT_DEREGISTRATION, "222", None, "Beta Trust", date(2023, 1, 1), "N-8F")]
    cohort = build_cohort(camps, terms)
    assert len(cohort) == 2
    # sorted by filing_date: the Jan deregistration comes first.
    assert cohort[0].filing_date == date(2023, 1, 1)
    assert cohort[0].event_type == EVENT_DEREGISTRATION
    assert cohort[1].event_type == EVENT_ACTIVIST_ENTRY


def test_cohort_to_dataframe_schema():
    camps = []
    terms = [CefEvent(EVENT_MERGER, "222", "MRG", "Merging Income Fund", date(2023, 1, 1), "DEFM14A")]
    df = cohort_to_dataframe(build_cohort(camps, terms))
    assert list(df.columns) == [
        "event_type", "filer_slug", "filer_cik", "target_cik", "target_ticker",
        "target_name", "filing_date", "form", "is_fund_name",
    ]
    assert df.iloc[0]["event_type"] == EVENT_MERGER
    assert df.iloc[0]["filing_date"] == "2023-01-01"


def test_cohort_to_dataframe_empty():
    df = cohort_to_dataframe([])
    assert df.empty
    assert "event_type" in df.columns


# --------------------------------------------------------------------------- #
# date_chunks
# --------------------------------------------------------------------------- #


def test_date_chunks_partition_is_complete_and_disjoint():
    chunks = date_chunks(date(2024, 1, 1), date(2024, 12, 31), step_days=90)
    # First chunk starts at since, last ends at until.
    assert chunks[0][0] == date(2024, 1, 1)
    assert chunks[-1][1] == date(2024, 12, 31)
    # Disjoint + contiguous: each chunk starts the day after the previous ends.
    for prev, nxt in itertools.pairwise(chunks):
        assert prev[1] < nxt[0]
        assert (nxt[0] - prev[1]).days == 1


def test_date_chunks_single_window_when_step_exceeds_span():
    chunks = date_chunks(date(2024, 1, 1), date(2024, 1, 15), step_days=90)
    assert chunks == [(date(2024, 1, 1), date(2024, 1, 15))]


# --------------------------------------------------------------------------- #
# efts_search retry/backoff (fake getter, no real sleep)
# --------------------------------------------------------------------------- #


class _FakeGetter:
    """Replays a queued list of (status, body) tuples; records call count."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def __call__(self, url, *, params=None, headers=None):
        self.calls += 1
        status, body = self._responses.pop(0) if self._responses else (500, None)
        return HttpResponse(status_code=status, json_body=body)


def test_efts_search_retries_then_succeeds():
    getter = _FakeGetter([(500, None), (500, None), (200, _body([], total=5))])
    res = efts_search({"q": "x"}, identity="id", http_get=getter, sleep=lambda _s: None)
    assert res is not None
    assert res.total == 5
    assert getter.calls == 3


def test_efts_search_returns_none_after_exhaustion():
    getter = _FakeGetter([(500, None)] * 10)
    res = efts_search({"q": "x"}, identity="id", http_get=getter, max_retries=3, sleep=lambda _s: None)
    assert res is None
    assert getter.calls == 3


def test_efts_search_flags_overflow():
    getter = _FakeGetter([(200, _body([], total=250))])
    res = efts_search({"q": "x"}, identity="id", http_get=getter, sleep=lambda _s: None)
    assert res is not None
    assert res.overflowed is True


# --------------------------------------------------------------------------- #
# fetch_activist_events drives chunking + parsing through the fake getter
# --------------------------------------------------------------------------- #


def test_fetch_activist_events_walks_chunks():
    # One filer, a 1-CIK list, a span that yields 2 chunks at step=90.
    filer = ActivistFiler("saba", "Saba Capital", (SABA,))
    body = _body([_hit("SC 13D", "2024-01-18", [NPFD, SABA_DN], ["0001865389", SABA])])
    # Same body for every chunk (the fake getter ignores params); 2 chunks -> 2 hits.
    getter = _FakeGetter([(200, body), (200, body)])
    evs = fetch_activist_events(
        filer, date(2024, 1, 1), date(2024, 5, 1),
        identity="id", http_get=getter, step_days=90, throttle=0, sleep=lambda _s: None,
    )
    assert getter.calls == 2
    assert len(evs) == 2
    assert all(e.filer_slug == "saba" for e in evs)


def test_build_cohort_end_to_end_with_fake_getter():
    # A minimal full build: one filer, no terminations, deduped to one campaign.
    filer = ActivistFiler("saba", "Saba Capital", (SABA,))
    body = _body([_hit("SC 13D", "2024-01-18", [NPFD, SABA_DN], ["0001865389", SABA])])
    getter = _FakeGetter([(200, body)])
    result = build_cef_event_cohort(
        date(2024, 1, 1), date(2024, 2, 1),
        identity="id", http_get=getter, filers=[filer],
        include_terminations=False, throttle=0, sleep=lambda _s: None,
    )
    assert len(result.campaigns) == 1
    assert result.campaigns_per_filer == {"saba": 1}
    assert len(result.cohort) == 1


def test_known_filers_registry_is_well_formed():
    slugs = {f.slug for f in ACTIVIST_FILERS}
    assert {"saba", "karpus", "bulldog", "city_of_london", "ancora", "relative_value"} <= slugs
    # Every CIK is a 10-digit-padding-safe numeric string.
    for f in ACTIVIST_FILERS:
        assert f.ciks
        for c in f.ciks:
            assert c.lstrip("0").isdigit()
