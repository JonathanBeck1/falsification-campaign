"""Detect closed-end-fund (CEF) activist + termination events from free EDGAR.

This is the **point-in-time event-detection foundation** for Phase 5 / test T21
(CEF resolution-selection). It builds the pre-registration *cohort* — every
activist-entry and every fund-termination event 2015-2026 — against which the
eventual matched-control NAV study (which needs Tiingo NAV, a later purchase)
will be run. By construction every event carries an EDGAR *filing date*, so the
cohort is point-in-time with no look-ahead.

Two event families, both read off EDGAR full-text search (``efts.sec.gov``),
which is free and no-key:

1. **Activist entry** — an SC 13D (or 13D/A) filed by a known CEF activist
   against a closed-end-fund target. We track several filers, not just Saba:
   Saba Capital, Karpus, Bulldog/Goldstein/Special Opportunities, City of London
   Investment Group, Ancora, Relative Value Partners. Each ``(filer, target)``
   pair is deduped to its **earliest 13D** = the campaign start. A 13D/A with no
   prior 13D in-window still anchors the campaign at its own date (a pre-window
   13D we cannot see; the amendment is the earliest we observe).

2. **Termination / resolution** — the fund ceased to exist or is being wound up:
   N-8F (deregistration = completed liquidation/merger), 25/25-NSE (delisting),
   N-14/N-14 8C/425/DEFM14A (merger), and DEF 14A carrying "plan of liquidation"
   (announcement-time, tradeable). Form taxonomy is reused verbatim from
   ``cef_resolution.py`` so the two modules cannot drift.

EFTS quirks handled (all observed live, 2026-06):
  * ``forms="SC 13D"`` is a **root-form** query — it returns BOTH ``SC 13D`` and
    ``SC 13D/A``. We split on the exact per-hit ``form`` field.
  * the ``from=`` deep-pagination parameter **500s** past the first 100-hit page,
    so we never paginate; instead we **chunk the date range** small enough that
    each window's total stays <=100 and one page captures it whole.
  * EFTS **500s intermittently under load** even on valid queries — every fetch
    retries with exponential backoff, and the chunk is dropped (logged) only
    after the retries are exhausted, so the build degrades, never crashes.

Pattern mirrors ``cef_universe.py``: a pure, unit-testable parse/dedup/classify
core, plus thin fetch wrappers behind an injectable ``HttpGetter`` seam so tests
open no socket.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol

import structlog

from trader.catalysts.cef_resolution import (
    DELISTING_FORMS,
    DEREGISTRATION_FORMS,
    MERGER_FORMS,
    TENDER_FORMS,
)

log = structlog.get_logger()

# --------------------------------------------------------------------------- #
# Known CEF activist filers (EDGAR CIKs)
# --------------------------------------------------------------------------- #

# Each filer is keyed by a stable slug; ``cik`` drives the EFTS ``ciks`` filter
# (which returns every filing on which that CIK is a party). Where a single
# activist files under several related entities (Bulldog / Phillip Goldstein /
# Special Opportunities Fund), we list each CIK and fold them under one slug so a
# campaign is deduped across the family, not split.


@dataclass(frozen=True)
class ActivistFiler:
    """A known CEF activist and the EDGAR CIK(s) it files 13Ds under."""

    slug: str
    name: str
    ciks: tuple[str, ...]


# CIKs are zero-padded to 10 digits for the EFTS ``ciks`` param. Every CIK below
# was VERIFIED LIVE (2026-06) by querying the EFTS ``ciks`` filter for SC 13D and
# confirming a non-trivial 2015-2026 13D count under that exact CIK — the initial
# guesses for several filers were WRONG and are corrected here:
#   * Karpus is CIK 1048703 (Karpus Management, Inc.), not 1017918.
#   * Bulldog files under 1504304 (Bulldog Investors, LLP/LLC); Phillip Goldstein
#     also files personally under 1067621. (The bare "Special Opportunities Fund"
#     name collides with the unrelated "Drawbridge Special Opportunities Fund", so
#     we anchor Bulldog on the verified filer CIKs, not that name.)
#   * City of London's filer is 1018138 (City of London Investment Group PLC) — the
#     dominant 13D filer (73 in-window) — not the management-company CIKs.
#   * Ancora files under 1446114 (Advisors) + 1836192 (Alternatives), not 1253327.
#   * Relative Value Partners is 1649910, not 1509022.
ACTIVIST_FILERS: tuple[ActivistFiler, ...] = (
    ActivistFiler("saba", "Saba Capital Management, L.P.", ("0001510281",)),
    ActivistFiler("karpus", "Karpus Management, Inc.", ("0001048703",)),
    ActivistFiler(
        "bulldog",
        "Bulldog Investors, LLP / Phillip Goldstein",
        ("0001504304", "0001067621"),
    ),
    ActivistFiler(
        "city_of_london",
        "City of London Investment Group PLC",
        ("0001018138",),
    ),
    ActivistFiler(
        "ancora",
        "Ancora Advisors LLC / Ancora Alternatives LLC",
        ("0001446114", "0001836192"),
    ),
    ActivistFiler(
        "relative_value",
        "Relative Value Partners Group, LLC",
        ("0001649910",),
    ),
)

# Name phrases for the EFTS ``q=`` fallback (used when a filer's CIK list is
# incomplete — a name-phrase query catches filings the CIK filter misses because
# the activist filed under a sibling entity we did not enumerate).
ACTIVIST_NAME_QUERIES: dict[str, tuple[str, ...]] = {
    "saba": ('"Saba Capital"',),
    "karpus": ('"Karpus"',),
    # NOTE: "Special Opportunities Fund" is deliberately omitted — it collides with
    # the unrelated "Drawbridge Special Opportunities Fund". Anchor on filer CIKs.
    "bulldog": ('"Bulldog Investors"', '"Phillip Goldstein"'),
    "city_of_london": ('"City of London Investment Group"',),
    "ancora": ('"Ancora Advisors"', '"Ancora Alternatives"'),
    "relative_value": ('"Relative Value Partners"',),
}

# --------------------------------------------------------------------------- #
# Event-type taxonomy
# --------------------------------------------------------------------------- #

EVENT_ACTIVIST_ENTRY = "activist_entry"
EVENT_LIQUIDATION = "liquidation"
EVENT_MERGER = "merger"
EVENT_TENDER = "tender"
EVENT_DEREGISTRATION = "deregistration"
EVENT_DELISTING = "delisting"

TERMINATION_EVENT_TYPES = frozenset(
    {
        EVENT_LIQUIDATION,
        EVENT_MERGER,
        EVENT_TENDER,
        EVENT_DEREGISTRATION,
        EVENT_DELISTING,
    }
)

# Map an EDGAR form (already upper-cased + stripped) to a termination event type.
# Forms are pulled straight from ``cef_resolution.py`` so the two modules share a
# single source of truth. ``liquidation`` is detected separately from a DEF 14A
# whose body carries "plan of liquidation" (form alone is not enough there).
_FORM_TO_EVENT: dict[str, str] = {
    **{f: EVENT_DEREGISTRATION for f in DEREGISTRATION_FORMS},
    **{f: EVENT_DELISTING for f in DELISTING_FORMS},
    **{f: EVENT_MERGER for f in MERGER_FORMS},
    **{f: EVENT_TENDER for f in TENDER_FORMS},
}

# The EFTS root-form queries that surface termination events, each paired with the
# date-chunk size (days) that keeps a window's total under the 100-hit page — sized
# from VERIFIED 2022 full-year volumes (probed live 2026-06):
#   N-8F 157/yr, 25 117/yr, 25-NSE 994/yr, N-14 8C 36/yr, DEFM14A 246/yr.
# Bare ``N-14`` (172/yr) is dropped: ``N-14 8C`` is the closed-end-fund-specific
# merger-registration variant and DEFM14A covers the proxy, so bare N-14 is
# redundant noise. Bare ``425`` (4,441/yr — business-combination *communications*,
# overwhelmingly operating companies) is dropped for the same reason: it would
# dominate runtime (~7-day chunks → hundreds of extra calls) while adding near-zero
# incremental CEF mergers over N-14 8C + DEFM14A. Both are documented data choices,
# not oversights.
TERMINATION_FORM_STEPS: dict[str, int] = {
    "N-8F": 120,
    "25": 120,
    "25-NSE": 25,
    "N-14 8C": 365,
    "DEFM14A": 90,
}
TERMINATION_ROOT_FORMS: tuple[str, ...] = tuple(TERMINATION_FORM_STEPS)

# DEF 14A liquidation announcement — needs the phrase, not just the form.
LIQUIDATION_PROXY_FORM = "DEF 14A"
LIQUIDATION_PHRASE = '"plan of liquidation"'

# 25/25-NSE delisting notices list TWO parties: the issuer (first) and the listing
# exchange (e.g. "Nasdaq Stock Market LLC", CIK 1354457). The subject is the
# issuer; these exchange CIKs are co-parties we must never mistake for the target.
_EXCHANGE_CIKS = frozenset(
    {
        "1354457",  # Nasdaq Stock Market LLC
        "1368308",  # NYSE Arca
        "1101680",  # New York Stock Exchange LLC
        "1108524",  # NYSE American (formerly American Stock Exchange)
        "1568177",  # NYSE National / others
        "1411502",  # Cboe / BATS
    }
)

# A subject (target) display-name string looks like ``FUND NAME (TICKER) (CIK …)``.
# CEF targets are funds, so we also use a loose name filter to avoid sweeping in
# operating-company 13D targets. ``None`` ticker is tolerated (capture the CIK).
_DISPLAY_RE = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,7})\)\s*\(CIK\s*0*(\d+)\)")
_CIK_ONLY_RE = re.compile(r"\(CIK\s*0*(\d+)\)")

# Heuristic keywords that mark a 13D target as a closed-end FUND (vs an operating
# company). Used only to label/flag, never silently dropped — the runner reports
# the fund-vs-other split so the heuristic is auditable.
_FUND_KEYWORDS = (
    "fund",
    "trust",
    "income",
    "municipal",
    "muni",
    "term",
    "closed-end",
    "closed end",
    "investors",
    "portfolio",
    "strategic",
    "dividend",
    "yield",
    "opportunities",
)


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CefCampaign:
    """An activist's earliest observed 13D against one CEF target (campaign start).

    Back-compat shape (the original Saba-only record carried exactly these four
    fields); ``filer_slug`` is added for the multi-filer build and defaults so old
    call-sites keep working.
    """

    ticker: str
    cik: str
    name: str
    filing_date: date
    filer_slug: str = "saba"
    filer_cik: str | None = None


@dataclass(frozen=True)
class CefEvent:
    """One row of the combined CEF event cohort table.

    ``event_type`` is one of the EVENT_* constants. ``filer_cik`` is set only for
    activist entries (the activist's CIK); ``target_cik`` / ``target_ticker`` are
    the subject fund (ticker is ``None`` when EDGAR does not surface one — common
    for dead funds). ``filing_date`` is the point-in-time stamp. ``form`` records
    the EDGAR form that triggered the event for auditing.
    """

    event_type: str
    target_cik: str
    target_ticker: str | None
    target_name: str
    filing_date: date
    form: str
    filer_slug: str | None = None
    filer_cik: str | None = None
    is_fund_name: bool = True


# --------------------------------------------------------------------------- #
# HTTP seam (injectable, test-friendly) — mirrors cef_universe.py
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HttpResponse:
    """Minimal HTTP response shape the fetchers depend on (test-friendly)."""

    status_code: int
    json_body: object = None
    text: str = ""


class HttpGetter(Protocol):
    """Injectable ``GET url`` seam. Implementations translate failures into a
    non-200 ``HttpResponse`` (a raise is also tolerated as a fetch failure)."""

    def __call__(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse: ...


_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"


def _httpx_getter(
    url: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> HttpResponse:
    """Default getter backed by ``httpx`` (imported only when actually called)."""

    import httpx

    resp = httpx.get(url, params=params, headers=headers, timeout=60.0, follow_redirects=True)
    body: object = None
    try:
        body = resp.json()
    except Exception:
        body = None
    return HttpResponse(status_code=resp.status_code, json_body=body, text=resp.text)


# --------------------------------------------------------------------------- #
# Pure parse core
# --------------------------------------------------------------------------- #


def _normalize_cik(raw: str) -> str:
    """Strip leading zeros so the same fund matches across sources / queries."""

    return raw.strip().lstrip("0") or "0"


def looks_like_fund_name(name: str) -> bool:
    """PURE: True if ``name`` reads like a closed-end fund (vs an operating co)."""

    n = (name or "").lower()
    return any(k in n for k in _FUND_KEYWORDS)


def parse_target_from_display(display: str) -> tuple[str | None, str | None, str]:
    """PURE: from one EFTS ``display_names`` entry, return (ticker, cik, name).

    Accepts both ``NAME (TICKER) (CIK …)`` and the ticker-less ``NAME (CIK …)``.
    Returns ``(None, None, raw)`` if no CIK anchor is present.
    """

    m = _DISPLAY_RE.search(display or "")
    if m:
        ticker, cik = m.group(1), _normalize_cik(m.group(2))
        name = display.split("(")[0].strip()
        return ticker, cik, name
    m2 = _CIK_ONLY_RE.search(display or "")
    if m2:
        name = display.split("(")[0].strip()
        return None, _normalize_cik(m2.group(1)), name
    return None, None, (display or "").strip()


def _iter_hit_sources(json_body: object) -> Iterator[dict]:
    """PURE: yield each hit's ``_source`` dict from an EFTS search body."""

    if not isinstance(json_body, dict):
        return
    hits = json_body.get("hits", {})
    if not isinstance(hits, dict):
        return
    for h in hits.get("hits", []) or []:
        if isinstance(h, dict):
            src = h.get("_source", {})
            if isinstance(src, dict):
                yield src


def parse_activist_hits(
    json_body: object,
    filer_ciks: Iterable[str],
) -> list[CefEvent]:
    """PURE: extract activist-entry events from one EFTS page.

    ``filer_ciks`` are this activist's CIK(s) (zero-stripped). For each hit we
    confirm the activist is actually a *party* (its CIK is in the hit's ``ciks``
    list — a text match alone is not enough), then take the OTHER party as the
    target fund. Only exact ``SC 13D`` / ``SC 13D/A`` forms are kept (the root-form
    query also returns the amendments). One ``CefEvent`` per (target, filing) hit;
    dedup-to-earliest is a separate fold (``dedup_campaigns``).
    """

    filer_set = {_normalize_cik(c) for c in filer_ciks}
    out: list[CefEvent] = []
    for s in _iter_hit_sources(json_body):
        form = str(s.get("form", "")).upper().strip()
        if form not in {"SC 13D", "SC 13D/A"}:
            continue
        hit_ciks = {_normalize_cik(str(c)) for c in (s.get("ciks") or [])}
        filer_cik = next((c for c in filer_set if c in hit_ciks), None)
        if filer_cik is None:
            continue
        fdate_raw = s.get("file_date")
        if not fdate_raw:
            continue
        try:
            fdate = date.fromisoformat(str(fdate_raw))
        except ValueError:
            continue
        # The target is the non-filer party. Prefer the display_name whose CIK is
        # NOT the activist; fall back to any non-activist CIK in ``ciks``.
        names = s.get("display_names") or []
        target: tuple[str | None, str, str] | None = None
        for dn in names:
            tkr, cik, nm = parse_target_from_display(str(dn))
            if cik and cik not in filer_set:
                target = (tkr, cik, nm)
                break
        if target is None:
            continue
        tkr, cik, nm = target
        out.append(
            CefEvent(
                event_type=EVENT_ACTIVIST_ENTRY,
                target_cik=cik,
                target_ticker=tkr,
                target_name=nm,
                filing_date=fdate,
                form=form,
                filer_cik=filer_cik,
                is_fund_name=looks_like_fund_name(nm),
            )
        )
    return out


def parse_termination_hits(json_body: object) -> list[CefEvent]:
    """PURE: extract termination events from one EFTS page.

    Maps the per-hit exact ``form`` to a termination event type via the shared
    ``cef_resolution`` taxonomy. The subject is the first non-exchange party with a
    CIK (25/25-NSE list the listing exchange as a co-party — see ``_EXCHANGE_CIKS``).
    Hits whose exact form maps to no termination type are skipped (the root-form
    query can pull adjacent forms). One ``CefEvent`` per hit.
    """

    out: list[CefEvent] = []
    for s in _iter_hit_sources(json_body):
        form = str(s.get("form", "")).upper().strip()
        event_type = _FORM_TO_EVENT.get(form)
        if event_type is None:
            continue
        fdate_raw = s.get("file_date")
        if not fdate_raw:
            continue
        try:
            fdate = date.fromisoformat(str(fdate_raw))
        except ValueError:
            continue
        names = s.get("display_names") or []
        target = None
        for dn in names:
            tkr, cik, nm = parse_target_from_display(str(dn))
            if cik and cik not in _EXCHANGE_CIKS:
                target = (tkr, cik, nm)
                break
        if target is None:
            continue
        tkr, cik, nm = target
        out.append(
            CefEvent(
                event_type=event_type,
                target_cik=cik,
                target_ticker=tkr,
                target_name=nm,
                filing_date=fdate,
                form=form,
                is_fund_name=looks_like_fund_name(nm),
            )
        )
    return out


def parse_liquidation_proxy_hits(json_body: object) -> list[CefEvent]:
    """PURE: extract liquidation-announcement events from a DEF 14A page.

    The query is a phrase search (``"plan of liquidation"``) restricted to
    ``DEF 14A`` / ``DEFA14A``; any matching proxy is a liquidation announcement at
    its filing date (announcement-time, tradeable). Subject = first CIK party.
    """

    out: list[CefEvent] = []
    for s in _iter_hit_sources(json_body):
        form = str(s.get("form", "")).upper().strip()
        if not form.startswith("DEF"):
            continue
        fdate_raw = s.get("file_date")
        if not fdate_raw:
            continue
        try:
            fdate = date.fromisoformat(str(fdate_raw))
        except ValueError:
            continue
        names = s.get("display_names") or []
        target = None
        for dn in names:
            tkr, cik, nm = parse_target_from_display(str(dn))
            if cik:
                target = (tkr, cik, nm)
                break
        if target is None:
            continue
        tkr, cik, nm = target
        out.append(
            CefEvent(
                event_type=EVENT_LIQUIDATION,
                target_cik=cik,
                target_ticker=tkr,
                target_name=nm,
                filing_date=fdate,
                form=form,
                is_fund_name=looks_like_fund_name(nm),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Dedup / cohort assembly (pure)
# --------------------------------------------------------------------------- #


def dedup_campaigns(events: Iterable[CefEvent]) -> list[CefCampaign]:
    """PURE: fold activist-entry events to one earliest 13D per (filer, target).

    The campaign START is the earliest filing we observe for a given activist
    against a given target fund — across both SC 13D and SC 13D/A (a 13D/A whose
    initial 13D predates the window still anchors the campaign at the amendment we
    can see). Dedup key is ``(filer_cik or filer_slug, target_cik)``. Ticker/name
    are taken from the earliest hit. Sorted by (filing_date, target_ticker).
    """

    earliest: dict[tuple[str, str], CefEvent] = {}
    for e in events:
        if e.event_type != EVENT_ACTIVIST_ENTRY:
            continue
        key = (e.filer_cik or e.filer_slug or "", e.target_cik)
        prev = earliest.get(key)
        if prev is None or e.filing_date < prev.filing_date:
            earliest[key] = e

    out = [
        CefCampaign(
            ticker=e.target_ticker or "",
            cik=e.target_cik,
            name=e.target_name,
            filing_date=e.filing_date,
            filer_slug=e.filer_slug or "",
            filer_cik=e.filer_cik,
        )
        for e in earliest.values()
    ]
    return sorted(out, key=lambda c: (c.filing_date, c.ticker, c.cik))


def dedup_termination_events(events: Iterable[CefEvent]) -> list[CefEvent]:
    """PURE: dedup termination events to one earliest per (target, event_type).

    A fund can file several N-8Fs / 25s; the *first* is the resolution date. We
    dedup per (target_cik, event_type) so a single fund contributes at most one
    row per termination kind (it may still appear under both, say, delisting and
    deregistration — those are distinct signals). Sorted by (filing_date, cik).
    """

    earliest: dict[tuple[str, str], CefEvent] = {}
    for e in events:
        if e.event_type not in TERMINATION_EVENT_TYPES and e.event_type != EVENT_LIQUIDATION:
            continue
        key = (e.target_cik, e.event_type)
        prev = earliest.get(key)
        if prev is None or e.filing_date < prev.filing_date:
            earliest[key] = e
    return sorted(earliest.values(), key=lambda e: (e.filing_date, e.target_cik, e.event_type))


def build_cohort(
    campaigns: Iterable[CefCampaign],
    terminations: Iterable[CefEvent],
) -> list[CefEvent]:
    """PURE: assemble the combined cohort table (activist entries + terminations).

    Activist campaigns are rendered as ``activist_entry`` ``CefEvent`` rows;
    termination events pass through as-is. Sorted by (filing_date, event_type,
    target_cik) for a stable, point-in-time-ordered cohort.
    """

    rows: list[CefEvent] = []
    for c in campaigns:
        rows.append(
            CefEvent(
                event_type=EVENT_ACTIVIST_ENTRY,
                target_cik=c.cik,
                target_ticker=c.ticker or None,
                target_name=c.name,
                filing_date=c.filing_date,
                form="SC 13D",
                filer_slug=c.filer_slug or None,
                filer_cik=c.filer_cik,
                is_fund_name=looks_like_fund_name(c.name),
            )
        )
    rows.extend(terminations)
    return sorted(rows, key=lambda e: (e.filing_date, e.event_type, e.target_cik))


def cohort_to_dataframe(events: Iterable[CefEvent]):
    """PURE: render cohort events to a stable-schema DataFrame for parquet."""

    import pandas as pd

    rows = [
        {
            "event_type": e.event_type,
            "filer_slug": e.filer_slug,
            "filer_cik": e.filer_cik,
            "target_cik": e.target_cik,
            "target_ticker": e.target_ticker,
            "target_name": e.target_name,
            "filing_date": e.filing_date.isoformat(),
            "form": e.form,
            "is_fund_name": e.is_fund_name,
        }
        for e in events
    ]
    cols = [
        "event_type",
        "filer_slug",
        "filer_cik",
        "target_cik",
        "target_ticker",
        "target_name",
        "filing_date",
        "form",
        "is_fund_name",
    ]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df = df.sort_values(["filing_date", "event_type", "target_cik"]).reset_index(drop=True)
    return df


# --------------------------------------------------------------------------- #
# Date chunking (pure) — the EFTS pagination work-around
# --------------------------------------------------------------------------- #


def date_chunks(
    since: date, until: date, *, step_days: int
) -> list[tuple[date, date]]:
    """PURE: split ``[since, until]`` into inclusive windows of <= ``step_days``.

    EFTS ``from=`` deep pagination 500s past page 1, so we never paginate; instead
    each window is small enough that its total stays under the 100-hit page. The
    caller picks ``step_days`` per filer (a prolific filer like Saba needs ~90d
    quarters; a quiet one fits a full year)."""

    if step_days < 1:
        step_days = 1
    out: list[tuple[date, date]] = []
    start = since
    while start <= until:
        end = min(start + timedelta(days=step_days - 1), until)
        out.append((start, end))
        start = end + timedelta(days=1)
    return out


# --------------------------------------------------------------------------- #
# Thin fetch wrappers (injectable seam, retry/backoff for EFTS 500s)
# --------------------------------------------------------------------------- #


@dataclass
class EftsFetchResult:
    """A page of EFTS hits plus the reported total (for overflow detection)."""

    json_body: object
    total: int
    overflowed: bool  # total > 100: a window too wide; results truncated


def _efts_total(json_body: object) -> int:
    if not isinstance(json_body, dict):
        return 0
    hits = json_body.get("hits", {})
    if not isinstance(hits, dict):
        return 0
    total = hits.get("total", {})
    if isinstance(total, dict):
        v = total.get("value")
        return int(v) if isinstance(v, int) else 0
    return int(total) if isinstance(total, int) else 0


def efts_search(
    params: dict[str, str],
    *,
    identity: str,
    http_get: HttpGetter | None = None,
    max_retries: int = 6,
    backoff: float = 1.0,
    sleep=time.sleep,
) -> EftsFetchResult | None:
    """One EFTS query with retry/backoff on the intermittent 500s.

    Returns ``None`` only after the retries are exhausted (logged), so a single
    flaky window degrades the build rather than crashing it. ``overflowed`` is
    set when the window's total exceeds the 100-hit page (the caller should
    shrink ``step_days``)."""

    getter = http_get or _httpx_getter
    headers = {"User-Agent": identity}
    for attempt in range(max_retries):
        try:
            resp = getter(_EFTS_URL, params=params, headers=headers)
        except Exception as exc:  # best-effort
            log.warning("cef_events_efts_exc", attempt=attempt, error=str(exc))
            sleep(backoff * (2**attempt))
            continue
        if resp.status_code == 200:
            total = _efts_total(resp.json_body)
            return EftsFetchResult(
                json_body=resp.json_body, total=total, overflowed=total > 100
            )
        log.warning("cef_events_efts_status", attempt=attempt, status=resp.status_code)
        sleep(backoff * (2**attempt))
    log.warning("cef_events_efts_exhausted", params=params)
    return None


def fetch_activist_events(
    filer: ActivistFiler,
    since: date,
    until: date,
    *,
    identity: str,
    http_get: HttpGetter | None = None,
    step_days: int = 60,
    throttle: float = 0.3,
    sleep=time.sleep,
) -> list[CefEvent]:
    """Fetch every SC 13D/13D/A this filer filed in-window, as activist events.

    Date-chunked (no ``from=`` pagination); each chunk is fetched once per filer
    CIK with retry. Throttled between calls (EFTS fair-access). Best-effort: a
    chunk that exhausts retries is dropped (logged), not fatal. Returns the raw
    (un-deduped) event list — dedup to campaign starts via ``dedup_campaigns``."""

    out: list[CefEvent] = []
    for lo, hi in date_chunks(since, until, step_days=step_days):
        for cik in filer.ciks:
            params = {
                "ciks": cik.zfill(10),
                "forms": "SC 13D",
                "startdt": lo.isoformat(),
                "enddt": hi.isoformat(),
            }
            res = efts_search(params, identity=identity, http_get=http_get, sleep=sleep)
            if res is None:
                continue
            if res.overflowed:
                log.warning(
                    "cef_events_window_overflow",
                    filer=filer.slug,
                    cik=cik,
                    lo=lo.isoformat(),
                    hi=hi.isoformat(),
                    total=res.total,
                )
            hits = parse_activist_hits(res.json_body, filer.ciks)
            for h in hits:
                out.append(
                    CefEvent(
                        event_type=h.event_type,
                        target_cik=h.target_cik,
                        target_ticker=h.target_ticker,
                        target_name=h.target_name,
                        filing_date=h.filing_date,
                        form=h.form,
                        filer_slug=filer.slug,
                        filer_cik=h.filer_cik,
                        is_fund_name=h.is_fund_name,
                    )
                )
            if throttle:
                sleep(throttle)
    log.info("cef_events_activist_fetched", filer=filer.slug, events=len(out))
    return out


def fetch_termination_events(
    since: date,
    until: date,
    *,
    identity: str,
    http_get: HttpGetter | None = None,
    step_days: int | None = None,
    throttle: float = 0.3,
    sleep=time.sleep,
    root_forms: Iterable[str] = TERMINATION_ROOT_FORMS,
) -> list[CefEvent]:
    """Fetch termination filings (N-8F/25/25-NSE/N-14 8C/DEFM14A) market-wide.

    Each root form is date-chunked at its own ``TERMINATION_FORM_STEPS`` size,
    sized from verified per-year volumes so a window stays under the 100-hit page
    (25-NSE is >900/yr → 25-day chunks; N-14 8C is 36/yr → a full year). Pass
    ``step_days`` to override every form with a single value (a global cap for
    safety). These forms are filed by ALL funds, not just CEFs; the runner narrows
    to fund-name targets + the CEF universe downstream. Best-effort. Returns raw
    events — dedup via ``dedup_termination_events``."""

    out: list[CefEvent] = []
    for form in root_forms:
        form_step = step_days if step_days is not None else TERMINATION_FORM_STEPS.get(form, 30)
        for lo, hi in date_chunks(since, until, step_days=form_step):
            params = {
                "forms": form,
                "startdt": lo.isoformat(),
                "enddt": hi.isoformat(),
            }
            res = efts_search(params, identity=identity, http_get=http_get, sleep=sleep)
            if res is None:
                continue
            if res.overflowed:
                log.warning(
                    "cef_events_term_overflow",
                    form=form,
                    lo=lo.isoformat(),
                    hi=hi.isoformat(),
                    total=res.total,
                )
            out.extend(parse_termination_hits(res.json_body))
            if throttle:
                sleep(throttle)
    log.info("cef_events_termination_fetched", events=len(out))
    return out


def fetch_liquidation_proxies(
    since: date,
    until: date,
    *,
    identity: str,
    http_get: HttpGetter | None = None,
    step_days: int | None = None,
    throttle: float = 0.3,
    sleep=time.sleep,
) -> list[CefEvent]:
    """Fetch DEF 14A proxies carrying "plan of liquidation" (announcement-time).

    Phrase + form restricted; date-chunked at 90 days by default (the phrase query
    is ~86 DEF 14A/yr, comfortably under the 100-hit page). Best-effort. Returns
    raw liquidation events (announcement at filing date)."""

    step = step_days if step_days is not None else 90
    out: list[CefEvent] = []
    for lo, hi in date_chunks(since, until, step_days=step):
        params = {
            "q": LIQUIDATION_PHRASE,
            "forms": LIQUIDATION_PROXY_FORM,
            "startdt": lo.isoformat(),
            "enddt": hi.isoformat(),
        }
        res = efts_search(params, identity=identity, http_get=http_get, sleep=sleep)
        if res is None:
            continue
        if res.overflowed:
            log.warning(
                "cef_events_liq_overflow", lo=lo.isoformat(), hi=hi.isoformat(), total=res.total
            )
        out.extend(parse_liquidation_proxy_hits(res.json_body))
        if throttle:
            sleep(throttle)
    log.info("cef_events_liquidation_fetched", events=len(out))
    return out


# --------------------------------------------------------------------------- #
# Top-level orchestration
# --------------------------------------------------------------------------- #


@dataclass
class CohortBuildResult:
    """Everything the cohort build gathered, with per-filer / per-type diagnostics."""

    campaigns: list[CefCampaign] = field(default_factory=list)
    terminations: list[CefEvent] = field(default_factory=list)
    cohort: list[CefEvent] = field(default_factory=list)
    campaigns_per_filer: dict[str, int] = field(default_factory=dict)
    terminations_per_type: dict[str, int] = field(default_factory=dict)


def build_cef_event_cohort(
    since: date,
    until: date,
    *,
    identity: str,
    http_get: HttpGetter | None = None,
    filers: Iterable[ActivistFiler] = ACTIVIST_FILERS,
    activist_step_days: int = 60,
    termination_step_days: int | None = None,
    throttle: float = 0.3,
    include_terminations: bool = True,
    sleep=time.sleep,
) -> CohortBuildResult:
    """Live: build the full CEF event cohort (activist + termination) 2015-2026.

    Best-effort and network-bound. Activist campaigns are deduped to each
    (filer, target) earliest 13D; termination events to each (target, type)
    earliest filing. The combined cohort is point-in-time by construction."""

    result = CohortBuildResult()

    all_activist: list[CefEvent] = []
    for filer in filers:
        evs = fetch_activist_events(
            filer,
            since,
            until,
            identity=identity,
            http_get=http_get,
            step_days=activist_step_days,
            throttle=throttle,
            sleep=sleep,
        )
        all_activist.extend(evs)
    campaigns = dedup_campaigns(all_activist)
    result.campaigns = campaigns
    for c in campaigns:
        result.campaigns_per_filer[c.filer_slug] = (
            result.campaigns_per_filer.get(c.filer_slug, 0) + 1
        )

    terminations: list[CefEvent] = []
    if include_terminations:
        raw_term = fetch_termination_events(
            since,
            until,
            identity=identity,
            http_get=http_get,
            step_days=termination_step_days,
            throttle=throttle,
            sleep=sleep,
        )
        raw_liq = fetch_liquidation_proxies(
            since,
            until,
            identity=identity,
            http_get=http_get,
            step_days=termination_step_days,
            throttle=throttle,
            sleep=sleep,
        )
        terminations = dedup_termination_events([*raw_term, *raw_liq])
    result.terminations = terminations
    for e in terminations:
        result.terminations_per_type[e.event_type] = (
            result.terminations_per_type.get(e.event_type, 0) + 1
        )

    result.cohort = build_cohort(campaigns, terminations)
    log.info(
        "cef_events_cohort_built",
        campaigns=len(campaigns),
        terminations=len(terminations),
        cohort=len(result.cohort),
    )
    return result


# --------------------------------------------------------------------------- #
# Back-compat: the original Saba-only entry point
# --------------------------------------------------------------------------- #


def fetch_saba_cef_campaigns(
    since: date,
    until: date,
    *,
    identity: str,
    http_get: HttpGetter | None = None,
    step_days: int = 90,
    throttle: float = 0.3,
    sleep=time.sleep,
) -> list[CefCampaign]:
    """Return Saba's initial SC 13D CEF campaigns (earliest filing per subject).

    Preserved for back-compat. Now uses the date-chunked, retrying multi-filer
    machinery under the hood (Saba is one ``ActivistFiler``); same return shape."""

    saba = next(f for f in ACTIVIST_FILERS if f.slug == "saba")
    events = fetch_activist_events(
        saba,
        since,
        until,
        identity=identity,
        http_get=http_get,
        step_days=step_days,
        throttle=throttle,
        sleep=sleep,
    )
    campaigns = dedup_campaigns(events)
    log.info("cef_events_built", campaigns=len(campaigns))
    return campaigns
