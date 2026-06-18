"""Survivorship-bias-free CEF universe spine from free SEC EDGAR data.

Phase 5 (CEF resolution-selection study) requires a *point-in-time* membership
table of every US closed-end fund 2015-2026 — the ground-truth identity layer
that matched-control selection is built on. The whole reason this exists: live
vendor universes (CEFConnect, CEFA) **purge** dead funds, which are exactly the
"resolved" observations a survivorship-corrected study must keep. SEC's annual
"investment company series and class" datasets retain every registered fund per
year, so a fund that is present early and absent later is a delisting/
deregistration signal we can read straight off the membership table.

Data source (free, no key, no paid API): SEC publishes one CSV per year under
``https://www.sec.gov/files/investment/data/other/...``. Each row is a
series/class registration carrying an *Entity Org Type* field where **32 =
closed-end fund**. (Caveat, verified: org-type 32 also captures insurance
separate accounts / variable-annuity funds, which are not exchange-listed CEFs —
the ticker-resolution step and downstream NAV join filter those out; the raw
org-32 CIK count is therefore an upper bound on tradeable CEFs.)

Format quirks handled (all observed live):
  * column headers vary by year — 2015 uses ``CIK``/``Org Type``, 2017-2018 use
    lowercase ``entity_org_type``, 2019+ use ``CIK Number``/``Entity Org Type``;
  * some files carry a banner/blank line before the header;
  * 2025/2026 files carry a UTF-8 BOM;
  * 2016 is simply **absent** from SEC's listing (a real gap, not an error);
  * embedded commas inside quoted entity names — a real CSV parser is mandatory.

Tickers are **NULL for CEFs** in these CSVs (confirmed: 0/2449 org-32 rows in
2019 carry a class ticker), and ``data.sec.gov/submissions`` strips tickers from
*dead* funds. We resolve tickers best-effort from EDGAR full-text search
``display_names`` — which preserve the ``FUND NAME (TICKER) (CIK …)`` form — and
leave them null (recording the miss) where not resolvable. We never guess.

Pattern mirrors ``catalysts/tiingo.py`` / ``catalysts/cef_events.py``: a pure,
unit-testable parse/assembly core, plus a thin fetch wrapper behind an injectable
``HttpGetter`` seam so tests open no socket. Network failures log and continue.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd
import structlog

log = structlog.get_logger()

CEF_ORG_TYPE = "32"
YEAR_START = 2015
YEAR_END = 2026

# SEC moved/renamed the dataset directory over the years; the file-name spelling
# also drifted. These are the verified-live URLs per year (probed 2026-06).
# ``None`` years (2016) have no published file and are skipped.
_BASE_OLD = (
    "https://www.sec.gov/files/investment/data/other/"
    "investment-company-series-and-class-information"
)
_BASE_NEW = (
    "https://www.sec.gov/files/investment/data/other/"
    "investment-company-series-class-information"
)
SEC_YEAR_URLS: dict[int, str] = {
    2015: f"{_BASE_OLD}/investment_company_series_class_2015.csv",
    # 2016: absent from SEC's published listing (verified 404 under both names).
    2017: f"{_BASE_OLD}/investment_company_series_class_2017.csv",
    2018: f"{_BASE_OLD}/investment_company_series_class_2018.csv",
    2019: f"{_BASE_OLD}/investment_company_series_class_2019.csv",
    2020: f"{_BASE_OLD}/investment_company_series_class_2020.csv",
    2021: f"{_BASE_OLD}/investment_company_series_class_2021.csv",
    2022: f"{_BASE_OLD}/investment_company_series_class_2022.csv",
    # 2023 moved to the NEW dir; 2024 is back under the OLD dir (verified live).
    2023: f"{_BASE_NEW}/investment_company_series_class_2023.csv",
    2024: f"{_BASE_OLD}/investment-company-series-class-2024.csv",
    2025: f"{_BASE_NEW}/investment-company-series-class-2025.csv",
    2026: f"{_BASE_NEW}/investment-company-series-class-2026.csv",
}

_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"

# Tiingo's public, free, no-key catalogue of every symbol it carries — including
# the Nasdaq MFQS NAV symbols (``X<ticker>X``, exchange ``NMFQS``) for closed-end
# funds, which it RETAINS after delisting (verified: dead funds keep their span).
# This is the corrected survivorship-free identity anchor: the SEC org-type-32
# series/class file is ~99% insurance separate accounts and omits real CEFs
# entirely (see module docstring / brain/32 amendment 2026-06-13).
TIINGO_SUPPORTED_TICKERS_URL = (
    "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
)
# SEC's free ticker<->CIK map for LIVE filers (dead funds' tickers are stripped).
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# A Tiingo NMFQS NAV symbol is a CEF candidate when it both starts and ends with
# ``X`` (the NMFQS NAV-symbol convention) and has an inner ticker (len > 2).
NMFQS_EXCHANGE = "NMFQS"
# An ``X…X`` symbol is flagged delisted when its last history date sits this many
# days or more before the file's max date (the file is rebuilt daily, so a live
# fund's end date tracks "today").
_DELISTED_GAP_DAYS = 30

# Exchanges that mark a genuinely exchange-LISTED closed-end fund (vs an
# insurance separate account / variable-annuity entity, which also carry
# org-type 32 but have no exchange listing). Used only to flag, never to drop.
_LISTED_EXCHANGES = frozenset(
    {"NYSE", "NYSE AMERICAN", "NYSEAMERICAN", "NYSE ARCA", "NASDAQ", "AMEX", "BATS", "CBOE"}
)

# ``NAME (TICKER) (CIK 0000000000)`` — ticker group is optional in the wild, so
# we require the ``(CIK …)`` anchor and only capture a ticker when one precedes
# it. Tickers are 1-7 chars of upper-alnum plus ``.`` / ``-`` (e.g. BRK.A).
_DISPLAY_RE = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,7})\)\s*\(CIK\s*0*(\d+)\)")


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CefYearRecord:
    """One (CIK, year) presence of a closed-end fund in the SEC universe file."""

    cik: str  # zero-stripped numeric CIK (e.g. "40417")
    name: str
    year: int


@dataclass(frozen=True)
class CefMembership:
    """Point-in-time membership row for one fund across the whole window.

    ``years`` is the sorted set of years the CIK appeared as org-type 32.
    ``first_year`` / ``last_year`` bracket the listing span. ``delisted`` is the
    survivorship signal: the fund was present at some point but is absent in the
    final year of the window — i.e. it left the registered universe.

    ``exchange`` / ``listed`` come from ``data.sec.gov/submissions`` and separate
    a genuinely exchange-listed CEF from the insurance separate accounts that also
    carry org-type 32. ``listed`` is the gate the downstream NAV/price study uses.
    """

    cik: str
    name: str
    first_year: int
    last_year: int
    years: tuple[int, ...]
    ticker: str | None
    delisted: bool
    exchange: str | None = None
    listed: bool = False


@dataclass(frozen=True)
class TiingoCefSymbol:
    """One CEF candidate parsed from Tiingo's ``supported_tickers`` catalogue.

    ``nmfqs_symbol`` is the ``X<ticker>X`` NMFQS NAV symbol; ``price_ticker`` is
    the X-stripped inner ticker (the exchange-traded symbol). ``start_date`` /
    ``end_date`` are the retained history span (ISO ``YYYY-MM-DD`` or ``None``).
    ``cik`` is attached later from ``company_tickers.json`` (``None`` until then —
    dead funds whose tickers SEC has stripped stay ``None``, recorded not guessed).
    ``delisted`` = the last history date sits well before the file's max date.
    ``price_ticker_traded`` = the inner ticker also appears on a real exchange in
    the same file (not only as the NMFQS NAV symbol) — a tradeable-price gate.
    """

    nmfqs_symbol: str
    price_ticker: str
    start_date: str | None
    end_date: str | None
    delisted: bool
    price_ticker_traded: bool
    cik: str | None = None


@dataclass(frozen=True)
class TickerInfo:
    """Resolved identity for one CIK: ticker + primary exchange (either may be
    ``None`` when unresolved). ``listed`` is ``True`` only when the exchange is a
    recognized US listing venue — the tradeable-CEF gate."""

    ticker: str | None
    exchange: str | None
    listed: bool


# --------------------------------------------------------------------------- #
# HTTP seam (injectable, test-friendly)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HttpResponse:
    """Minimal HTTP response shape the fetchers depend on (test-friendly).

    ``content`` carries raw bytes for binary payloads (the Tiingo
    ``supported_tickers.zip``); the text/json fetchers ignore it."""

    status_code: int
    text: str = ""
    json_body: object = None
    content: bytes | None = None


class HttpGetter(Protocol):
    """Injectable ``GET url`` seam. Implementations must not raise on HTTP errors;
    they translate failures into a non-200 ``HttpResponse`` (a raise is also
    tolerated by callers as a fetch failure)."""

    def __call__(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse: ...


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
    return HttpResponse(
        status_code=resp.status_code,
        text=resp.text,
        json_body=body,
        content=resp.content,
    )


# --------------------------------------------------------------------------- #
# Pure parse core
# --------------------------------------------------------------------------- #


def _normalize_cik(raw: str) -> str:
    """Strip leading zeros from a CIK so the same fund matches across sources."""

    return raw.strip().lstrip("0") or "0"


def _find_header_and_columns(
    rows: list[list[str]],
) -> tuple[int, int, int, int] | None:
    """Locate the header row and the (cik, org-type, name) column indices.

    Tolerant to the year-to-year header drift: matches case-insensitively on the
    substrings that are stable across every observed schema. Returns
    ``(header_idx, cik_col, org_col, name_col)`` or ``None`` if no header found.
    """

    for idx, row in enumerate(rows):
        low = [c.strip().lower() for c in row]
        has_cik = any("cik" in c for c in low)
        has_org = any("org" in c for c in low)
        if not (has_cik and has_org):
            continue
        cik_col = next((i for i, c in enumerate(low) if "cik" in c), None)
        org_col = next((i for i, c in enumerate(low) if "org" in c), None)
        # Prefer "name of registrant" / "entity name" / "entity_name" but never
        # the CIK column itself.
        name_col = next(
            (i for i, c in enumerate(low) if "name" in c and i != cik_col),
            None,
        )
        if cik_col is None or org_col is None or name_col is None:
            continue
        return idx, cik_col, org_col, name_col
    return None


def parse_cef_rows(raw_csv: str, year: int) -> list[CefYearRecord]:
    """PURE: from one year's raw SEC series/class CSV text, return CEF records.

    Filters to Entity-Org-Type == 32, dedups to one record per CIK (the file has
    one row per share class — many per fund), strips leading zeros off the CIK,
    and stamps the year. Malformed / short rows are skipped, not fatal. Returns
    ``[]`` for empty or header-less input.
    """

    if not raw_csv or not raw_csv.strip():
        return []

    # ``utf-8-sig`` upstream strips the BOM; here we just defensively drop a
    # leading BOM char if the caller passed bytes-decoded text.
    if raw_csv and raw_csv[0] == "﻿":
        raw_csv = raw_csv[1:]

    rows = list(csv.reader(io.StringIO(raw_csv)))
    found = _find_header_and_columns(rows)
    if found is None:
        log.warning("cef_universe_no_header", year=year)
        return []
    header_idx, cik_col, org_col, name_col = found

    by_cik: dict[str, CefYearRecord] = {}
    needed = max(cik_col, org_col, name_col)
    for row in rows[header_idx + 1:]:
        if len(row) <= needed:
            continue
        if row[org_col].strip() != CEF_ORG_TYPE:
            continue
        cik = _normalize_cik(row[cik_col])
        if not cik or cik == "0":
            continue
        name = row[name_col].strip()
        # Keep the first non-empty name we see for this CIK (class rows repeat it).
        if cik in by_cik and not name:
            continue
        if cik not in by_cik:
            by_cik[cik] = CefYearRecord(cik=cik, name=name, year=year)

    return sorted(by_cik.values(), key=lambda r: r.cik)


# --------------------------------------------------------------------------- #
# Ticker resolution (pure extraction + thin fetch)
# --------------------------------------------------------------------------- #


def extract_ticker_from_display_names(
    cik: str, display_names: Iterable[str]
) -> str | None:
    """PURE: pull this CIK's ticker from EDGAR EFTS ``display_names``.

    EFTS preserves ``FUND NAME (TICKER) (CIK 0000…)``. We only accept a ticker
    when the trailing ``(CIK …)`` matches *this* fund (zero-insensitive) — so a
    co-filer's ticker on the same filing is never mis-attributed. Returns the
    ticker or ``None`` (the miss is the caller's to record; we never guess).
    """

    target = _normalize_cik(cik)
    for name in display_names:
        for tkr, dn_cik in _DISPLAY_RE.findall(name or ""):
            if _normalize_cik(dn_cik) == target:
                return tkr
    return None


def _collect_display_names(json_body: object) -> list[str]:
    """PURE: flatten ``display_names`` from an EFTS search JSON body."""

    if not isinstance(json_body, dict):
        return []
    hits = json_body.get("hits", {})
    if not isinstance(hits, dict):
        return []
    out: list[str] = []
    for h in hits.get("hits", []) or []:
        if not isinstance(h, dict):
            continue
        src = h.get("_source", {})
        if not isinstance(src, dict):
            continue
        for n in src.get("display_names", []) or []:
            if isinstance(n, str):
                out.append(n)
    return out


def resolve_ticker(
    cik: str,
    *,
    identity: str,
    http_get: HttpGetter | None = None,
) -> str | None:
    """Best-effort: query EFTS for ``cik`` and extract its ticker, else ``None``.

    Network failures log and return ``None`` (recorded as an unresolved miss
    upstream — never a crash, never a guess)."""

    getter = http_get or _httpx_getter
    padded = cik.zfill(10)
    headers = {"User-Agent": identity}
    params = {"q": "", "ciks": padded}
    try:
        resp = getter(_EFTS_URL, params=params, headers=headers)
    except Exception as exc:  # best-effort
        log.warning("cef_universe_ticker_fetch_failed", cik=cik, error=str(exc))
        return None
    if resp.status_code != 200:
        log.warning("cef_universe_ticker_bad_status", cik=cik, status=resp.status_code)
        return None
    names = _collect_display_names(resp.json_body)
    return extract_ticker_from_display_names(cik, names)


def parse_submissions_identity(json_body: object) -> TickerInfo:
    """PURE: pull (ticker, primary exchange, listed) from a submissions JSON body.

    ``data.sec.gov/submissions/CIK{cik10}.json`` carries parallel ``tickers`` and
    ``exchanges`` arrays. We take the first ticker whose paired exchange is a
    recognized US listing venue (the tradeable-CEF gate); if no ticker is paired
    with a listed exchange we still surface the first ticker/exchange so the caller
    can see a partial resolution. Empty arrays (separate accounts, dead funds whose
    tickers are stripped) yield an all-``None`` / not-listed ``TickerInfo``.
    """

    if not isinstance(json_body, dict):
        return TickerInfo(None, None, False)
    tickers = json_body.get("tickers") or []
    exchanges = json_body.get("exchanges") or []
    if not isinstance(tickers, list):
        tickers = []
    if not isinstance(exchanges, list):
        exchanges = []

    best: tuple[str, str | None] | None = None
    fallback: tuple[str, str | None] | None = None
    for i, tkr in enumerate(tickers):
        if not isinstance(tkr, str) or not tkr.strip():
            continue
        exch = exchanges[i] if i < len(exchanges) else None
        exch_norm = exch.strip().upper() if isinstance(exch, str) and exch.strip() else None
        if fallback is None:
            fallback = (tkr.strip(), exch_norm)
        if exch_norm in _LISTED_EXCHANGES and best is None:
            best = (tkr.strip(), exch_norm)

    if best is not None:
        return TickerInfo(best[0], best[1], True)
    if fallback is not None:
        return TickerInfo(fallback[0], fallback[1], False)
    return TickerInfo(None, None, False)


def resolve_identity(
    cik: str,
    *,
    identity: str,
    http_get: HttpGetter | None = None,
    efts_fallback: bool = True,
) -> TickerInfo:
    """Best-effort identity for ``cik``: primary = ``data.sec.gov/submissions``
    (clean ticker + exchange for LIVE funds), optional fallback = EFTS
    ``display_names`` (recovers tickers for DEAD funds, whose tickers submissions
    strips).

    ``efts_fallback`` is ``True`` for correctness when called per-CIK, but the
    batch builder turns it OFF by default: org-type-32 is dominated by tickerless
    insurance separate accounts, so an EFTS lookup for *every* unresolved CIK is
    hundreds of slow rate-limited calls that almost never pay off. Submissions
    alone resolves every LIVE listed fund; the EFTS pass is a targeted slow option
    for dead-listed-fund ticker recovery.

    Returns a ``TickerInfo`` — ``listed`` is set only when submissions reports a
    recognized exchange. Network failures log and degrade (never crash, never
    guess); a fund resolvable by neither source comes back all-``None``."""

    getter = http_get or _httpx_getter
    headers = {"User-Agent": identity}
    url = _SUBMISSIONS_URL.format(cik10=cik.zfill(10))
    info = TickerInfo(None, None, False)
    try:
        resp = getter(url, headers=headers)
        if resp.status_code == 200:
            info = parse_submissions_identity(resp.json_body)
        else:
            log.warning("cef_universe_submissions_bad_status", cik=cik, status=resp.status_code)
    except Exception as exc:  # best-effort
        log.warning("cef_universe_submissions_fetch_failed", cik=cik, error=str(exc))

    if info.ticker is not None or not efts_fallback:
        return info

    # Fallback: EFTS display_names (dead funds). Keep submissions' exchange/listed.
    efts_ticker = resolve_ticker(cik, identity=identity, http_get=http_get)
    if efts_ticker is not None:
        return TickerInfo(efts_ticker, info.exchange, info.listed)
    return info


# --------------------------------------------------------------------------- #
# Membership assembly (pure)
# --------------------------------------------------------------------------- #


def build_membership(
    records: Iterable[CefYearRecord],
    *,
    window_end: int = YEAR_END,
    tickers: dict[str, str | None] | None = None,
    identities: dict[str, TickerInfo] | None = None,
) -> list[CefMembership]:
    """PURE: fold per-year presence into one point-in-time membership row per CIK.

    For each CIK: the sorted set of years seen, first/last year (listing span),
    and a ``delisted`` flag = present at some point but **absent in
    ``window_end``** (left the registered universe = survivorship signal). The
    most recent non-empty name wins (funds rename).

    Identity attachment: pass ``identities`` (CIK -> ``TickerInfo``) to attach
    ticker + exchange + listed; or the simpler ``tickers`` (CIK -> ticker-or-None)
    when exchange data is not in hand. ``identities`` wins where both are given.
    """

    tickers = tickers or {}
    identities = identities or {}
    years_by_cik: dict[str, set[int]] = {}
    # Track latest name per CIK by the year it was observed.
    name_by_cik: dict[str, tuple[int, str]] = {}
    for r in records:
        years_by_cik.setdefault(r.cik, set()).add(r.year)
        prev = name_by_cik.get(r.cik)
        if r.name and (prev is None or r.year >= prev[0]):
            name_by_cik[r.cik] = (r.year, r.name)

    out: list[CefMembership] = []
    for cik, years in years_by_cik.items():
        ys = tuple(sorted(years))
        info = identities.get(cik)
        if info is not None:
            ticker, exchange, listed = info.ticker, info.exchange, info.listed
        else:
            ticker, exchange, listed = tickers.get(cik), None, False
        out.append(
            CefMembership(
                cik=cik,
                name=name_by_cik.get(cik, (0, ""))[1],
                first_year=ys[0],
                last_year=ys[-1],
                years=ys,
                ticker=ticker,
                delisted=window_end not in years,
                exchange=exchange,
                listed=listed,
            )
        )
    return sorted(out, key=lambda m: m.cik)


def membership_to_dataframe(memberships: Iterable[CefMembership]) -> pd.DataFrame:
    """PURE: render membership rows to a stable-schema DataFrame for parquet."""

    rows = [
        {
            "cik": m.cik,
            "name": m.name,
            "ticker": m.ticker,
            "exchange": m.exchange,
            "listed": m.listed,
            "first_year": m.first_year,
            "last_year": m.last_year,
            "n_years": len(m.years),
            "years": ",".join(str(y) for y in m.years),
            "delisted": m.delisted,
        }
        for m in memberships
    ]
    cols = [
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
    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values("cik").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Tiingo NMFQS identity path (pure parse + join), the corrected CEF anchor
# --------------------------------------------------------------------------- #


def _parse_iso_date(value: str | None) -> _dt.date | None:
    """PURE: parse an ISO ``YYYY-MM-DD`` date, or ``None`` on empty/garbage."""

    if not value:
        return None
    try:
        return _dt.date.fromisoformat(value.strip())
    except ValueError:
        return None


def _tiingo_max_date(rows: Iterable[dict[str, str]]) -> _dt.date | None:
    """PURE: the maximum ``endDate`` across every catalogue row (the file's
    "as-of"). A live symbol's end date tracks this; a delisted one sits before it.
    """

    mx: _dt.date | None = None
    for r in rows:
        d = _parse_iso_date(r.get("endDate"))
        if d is not None and (mx is None or d > mx):
            mx = d
    return mx


def parse_tiingo_cef_symbols(
    raw_csv: str,
    *,
    delisted_gap_days: int = _DELISTED_GAP_DAYS,
) -> list[TiingoCefSymbol]:
    """PURE: from Tiingo's ``supported_tickers.csv`` text, return CEF candidates.

    A candidate is an ``NMFQS``-exchange row whose ticker matches ``X…X`` with a
    non-empty inner ticker. Duplicate rows for the same symbol (Tiingo emits a
    bare placeholder row plus a dated one) are merged into the WIDEST history span.
    Each candidate carries: the X-stripped ``price_ticker``; the merged start/end
    dates; a ``delisted`` flag (end date >= ``delisted_gap_days`` before the file's
    max end date); and ``price_ticker_traded`` (the inner ticker also appears on a
    non-NMFQS exchange in the same file). CIK is left ``None`` here — attached by
    ``attach_ciks``. Returns ``[]`` for empty/header-less input.
    """

    if not raw_csv or not raw_csv.strip():
        return []
    if raw_csv[0] == "﻿":  # defensive BOM strip
        raw_csv = raw_csv[1:]

    reader = csv.DictReader(io.StringIO(raw_csv))
    rows = list(reader)
    if not rows:
        return []

    file_max = _tiingo_max_date(rows)

    # Inner tickers that trade on a *real* (non-NMFQS) exchange somewhere in file.
    traded_tickers: set[str] = set()
    for r in rows:
        exch = (r.get("exchange") or "").strip().upper()
        tkr = (r.get("ticker") or "").strip().upper()
        if tkr and exch and exch != NMFQS_EXCHANGE:
            traded_tickers.add(tkr)

    # Merge X…X NMFQS rows to the widest span.
    merged: dict[str, list[_dt.date | None]] = {}
    for r in rows:
        if (r.get("exchange") or "").strip().upper() != NMFQS_EXCHANGE:
            continue
        sym = (r.get("ticker") or "").strip().upper()
        if not (sym.startswith("X") and sym.endswith("X") and len(sym) > 2):
            continue
        sd = _parse_iso_date(r.get("startDate"))
        ed = _parse_iso_date(r.get("endDate"))
        cur = merged.get(sym)
        if cur is None:
            merged[sym] = [sd, ed]
        else:
            if sd is not None and (cur[0] is None or sd < cur[0]):
                cur[0] = sd
            if ed is not None and (cur[1] is None or ed > cur[1]):
                cur[1] = ed

    out: list[TiingoCefSymbol] = []
    for sym, (sd, ed) in merged.items():
        inner = sym[1:-1].upper()
        delisted = bool(
            ed is not None
            and file_max is not None
            and (file_max - ed).days >= delisted_gap_days
        )
        out.append(
            TiingoCefSymbol(
                nmfqs_symbol=sym,
                price_ticker=inner,
                start_date=sd.isoformat() if sd else None,
                end_date=ed.isoformat() if ed else None,
                delisted=delisted,
                price_ticker_traded=inner in traded_tickers,
                cik=None,
            )
        )
    return sorted(out, key=lambda s: s.nmfqs_symbol)


def parse_company_tickers(json_body: object) -> dict[str, str]:
    """PURE: build an upper-cased ``ticker -> CIK`` map from SEC
    ``company_tickers.json`` (``{"0": {"cik_str", "ticker", "title"}, ...}``).

    CIK is returned zero-stripped to match the rest of this module. Malformed
    entries are skipped. Returns ``{}`` for a non-dict body.
    """

    if isinstance(json_body, str):
        try:
            json_body = json.loads(json_body)
        except (ValueError, TypeError):
            return {}
    if not isinstance(json_body, dict):
        return {}
    out: dict[str, str] = {}
    for v in json_body.values():
        if not isinstance(v, dict):
            continue
        tkr = v.get("ticker")
        cik = v.get("cik_str")
        if not isinstance(tkr, str) or not tkr.strip() or cik is None:
            continue
        out[tkr.strip().upper()] = _normalize_cik(str(cik))
    return out


def attach_ciks(
    symbols: Iterable[TiingoCefSymbol],
    ticker_to_cik: dict[str, str],
) -> list[TiingoCefSymbol]:
    """PURE: join each candidate's X-stripped ``price_ticker`` to a CIK.

    Unresolved tickers (mostly dead funds, whose tickers SEC strips from
    ``company_tickers.json``) keep ``cik=None`` — recorded, never guessed.
    """

    out: list[TiingoCefSymbol] = []
    for s in symbols:
        cik = ticker_to_cik.get(s.price_ticker.upper())
        out.append(
            s if s.cik == cik else TiingoCefSymbol(
                nmfqs_symbol=s.nmfqs_symbol,
                price_ticker=s.price_ticker,
                start_date=s.start_date,
                end_date=s.end_date,
                delisted=s.delisted,
                price_ticker_traded=s.price_ticker_traded,
                cik=cik,
            )
        )
    return out


def tiingo_symbols_to_year_records(
    symbols: Iterable[TiingoCefSymbol],
    *,
    year_start: int = YEAR_START,
    year_end: int = YEAR_END,
) -> tuple[list[CefYearRecord], dict[str, TickerInfo]]:
    """PURE: bridge Tiingo candidates into the EXISTING membership machinery.

    Synthesizes a per-year presence record for every year of overlap between the
    symbol's [start_date, end_date] span and the window — so ``build_membership``
    computes the same first/last year, listing span, and (absent-in-final-year)
    delisted flag it does for the SEC path, but anchored on the Tiingo set. The
    membership ``key`` is the CIK when resolved, else the NMFQS symbol (so dead
    funds without a CIK still get a spine row). Also returns a CIK/symbol ->
    ``TickerInfo`` map carrying the derived price ticker as the identity, with
    ``listed`` = the price ticker actually trades on an exchange.
    """

    records: list[CefYearRecord] = []
    identities: dict[str, TickerInfo] = {}
    for s in symbols:
        key = s.cik if s.cik else s.nmfqs_symbol
        sd = _parse_iso_date(s.start_date)
        ed = _parse_iso_date(s.end_date)
        # Default to the full window when a bound is missing (rare; conservative).
        lo = max(year_start, sd.year) if sd else year_start
        hi = min(year_end, ed.year) if ed else year_end
        if hi < lo:
            # History ends before the window starts -> still record one presence at
            # its end year if that lands in-window; otherwise skip (out of scope).
            if ed and year_start <= ed.year <= year_end:
                lo = hi = ed.year
            else:
                continue
        name = s.price_ticker  # no fund name in Tiingo; price ticker is the label
        for y in range(lo, hi + 1):
            records.append(CefYearRecord(cik=key, name=name, year=y))
        identities[key] = TickerInfo(
            ticker=s.price_ticker,
            exchange=NMFQS_EXCHANGE if not s.price_ticker_traded else "EXCHANGE",
            listed=s.price_ticker_traded,
        )
    return records, identities


def tiingo_symbols_to_dataframe(
    symbols: Iterable[TiingoCefSymbol],
) -> pd.DataFrame:
    """PURE: render Tiingo CEF candidates to a stable-schema DataFrame for parquet.

    This is the identity/anchor table (one row per NMFQS NAV symbol); pair it with
    ``membership_to_dataframe`` output for the point-in-time span/delisted view.
    """

    rows = [
        {
            "nmfqs_symbol": s.nmfqs_symbol,
            "price_ticker": s.price_ticker,
            "cik": s.cik,
            "start_date": s.start_date,
            "end_date": s.end_date,
            "delisted": s.delisted,
            "price_ticker_traded": s.price_ticker_traded,
            "cik_resolved": s.cik is not None,
        }
        for s in symbols
    ]
    cols = [
        "nmfqs_symbol",
        "price_ticker",
        "cik",
        "start_date",
        "end_date",
        "delisted",
        "price_ticker_traded",
        "cik_resolved",
    ]
    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values("nmfqs_symbol").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Tiingo / company_tickers thin fetch wrappers (injectable seam)
# --------------------------------------------------------------------------- #


def fetch_tiingo_supported_csv(
    *,
    http_get: HttpGetter | None = None,
    url: str = TIINGO_SUPPORTED_TICKERS_URL,
) -> str | None:
    """Fetch + unzip Tiingo's ``supported_tickers.zip`` to its CSV text (best-
    effort; free, no key). Network/zip failures log and return ``None``."""

    getter = http_get or _httpx_getter
    try:
        resp = getter(url, headers={"User-Agent": "trader-research"})
    except Exception as exc:  # best-effort
        log.warning("cef_universe_tiingo_fetch_failed", error=str(exc))
        return None
    if resp.status_code != 200:
        log.warning("cef_universe_tiingo_bad_status", status=resp.status_code)
        return None
    data = resp.content if resp.content is not None else (
        resp.text.encode("latin-1", "ignore") if resp.text else None
    )
    if not data:
        log.warning("cef_universe_tiingo_empty")
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            name = next(
                (n for n in zf.namelist() if n.lower().endswith(".csv")),
                None,
            )
            if name is None:
                log.warning("cef_universe_tiingo_no_csv", names=zf.namelist())
                return None
            return zf.read(name).decode("utf-8", "replace")
    except (zipfile.BadZipFile, OSError) as exc:
        log.warning("cef_universe_tiingo_unzip_failed", error=str(exc))
        return None


def fetch_company_tickers(
    *,
    identity: str,
    http_get: HttpGetter | None = None,
    url: str = COMPANY_TICKERS_URL,
) -> dict[str, str]:
    """Fetch SEC ``company_tickers.json`` -> ``ticker -> CIK`` map (best-effort;
    free, needs a descriptive User-Agent). Failures log and return ``{}``."""

    getter = http_get or _httpx_getter
    try:
        resp = getter(url, headers={"User-Agent": identity})
    except Exception as exc:  # best-effort
        log.warning("cef_universe_company_tickers_fetch_failed", error=str(exc))
        return {}
    if resp.status_code != 200:
        log.warning("cef_universe_company_tickers_bad_status", status=resp.status_code)
        return {}
    body = resp.json_body if resp.json_body is not None else resp.text
    mapping = parse_company_tickers(body)
    log.info("cef_universe_company_tickers_parsed", tickers=len(mapping))
    return mapping


def build_tiingo_cef_universe(
    *,
    identity: str,
    http_get: HttpGetter | None = None,
) -> tuple[list[TiingoCefSymbol], dict[str, str]]:
    """Orchestrate the corrected (Tiingo-anchored) identity build, best-effort.

    Fetches the Tiingo catalogue + ``company_tickers.json``, parses the ``X…X``
    NMFQS CEF candidates, and attaches CIKs. Returns ``(symbols, ticker_to_cik)``;
    ``symbols`` is empty only if the Tiingo fetch itself failed.
    """

    raw = fetch_tiingo_supported_csv(http_get=http_get)
    if raw is None:
        log.warning("cef_universe_tiingo_unavailable")
        return [], {}
    symbols = parse_tiingo_cef_symbols(raw)
    ticker_to_cik = fetch_company_tickers(identity=identity, http_get=http_get)
    symbols = attach_ciks(symbols, ticker_to_cik)
    n_cik = sum(1 for s in symbols if s.cik)
    n_delisted = sum(1 for s in symbols if s.delisted)
    log.info(
        "cef_universe_tiingo_built",
        symbols=len(symbols),
        cik_resolved=n_cik,
        delisted=n_delisted,
    )
    return symbols, ticker_to_cik


# --------------------------------------------------------------------------- #
# Thin year-fetch wrapper
# --------------------------------------------------------------------------- #


@dataclass
class UniverseFetchResult:
    """What ``fetch_universe_records`` gathered, plus per-year diagnostics."""

    records: list[CefYearRecord] = field(default_factory=list)
    per_year_ciks: dict[int, int] = field(default_factory=dict)
    failed_years: list[int] = field(default_factory=list)


def fetch_year_csv(
    year: int,
    *,
    identity: str,
    http_get: HttpGetter | None = None,
) -> str | None:
    """Fetch one year's raw SEC CSV text, or ``None`` (best-effort).

    Years with no published file (e.g. 2016) and any network/HTTP failure return
    ``None`` after logging — the caller continues with the rest of the window."""

    url = SEC_YEAR_URLS.get(year)
    if url is None:
        log.info("cef_universe_year_unavailable", year=year)
        return None
    getter = http_get or _httpx_getter
    headers = {"User-Agent": identity}
    try:
        resp = getter(url, headers=headers)
    except Exception as exc:  # best-effort
        log.warning("cef_universe_year_fetch_failed", year=year, error=str(exc))
        return None
    if resp.status_code != 200:
        log.warning("cef_universe_year_bad_status", year=year, status=resp.status_code)
        return None
    return resp.text


def fetch_universe_records(
    *,
    identity: str,
    years: Iterable[int] | None = None,
    http_get: HttpGetter | None = None,
) -> UniverseFetchResult:
    """Pull every year 2015-2026 and parse CEF records, best-effort.

    Each year is fetched + parsed independently; a failed or absent year logs and
    is skipped (recorded in ``failed_years``) rather than aborting the build."""

    yrs = list(years) if years is not None else list(range(YEAR_START, YEAR_END + 1))
    result = UniverseFetchResult()
    for year in yrs:
        raw = fetch_year_csv(year, identity=identity, http_get=http_get)
        if raw is None:
            result.failed_years.append(year)
            continue
        recs = parse_cef_rows(raw, year)
        if not recs:
            result.failed_years.append(year)
            continue
        result.records.extend(recs)
        result.per_year_ciks[year] = len(recs)
        log.info("cef_universe_year_parsed", year=year, ciks=len(recs))
    return result


def resolve_tickers(
    ciks: Iterable[str],
    *,
    identity: str,
    http_get: HttpGetter | None = None,
) -> dict[str, str | None]:
    """Best-effort ticker per CIK via EFTS; ``None`` where unresolved (recorded)."""

    out: dict[str, str | None] = {}
    for cik in ciks:
        out[cik] = resolve_ticker(cik, identity=identity, http_get=http_get)
    n_hit = sum(1 for v in out.values() if v)
    log.info("cef_universe_tickers_resolved", resolved=n_hit, total=len(out))
    return out


def resolve_identities(
    ciks: Iterable[str],
    *,
    identity: str,
    http_get: HttpGetter | None = None,
    efts_fallback: bool = False,
) -> dict[str, TickerInfo]:
    """Best-effort identity (ticker + exchange + listed) per CIK, recording misses.

    Submissions-first; EFTS-fallback is OFF by default here (see
    ``resolve_identity`` for why — separate accounts make a blanket EFTS pass slow
    and unproductive). All-``None`` for CIKs neither source resolves."""

    out: dict[str, TickerInfo] = {}
    for cik in ciks:
        out[cik] = resolve_identity(
            cik, identity=identity, http_get=http_get, efts_fallback=efts_fallback
        )
    n_tkr = sum(1 for v in out.values() if v.ticker)
    n_listed = sum(1 for v in out.values() if v.listed)
    log.info(
        "cef_universe_identities_resolved",
        tickers=n_tkr,
        listed=n_listed,
        total=len(out),
    )
    return out
