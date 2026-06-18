"""Survivorship-aware Binance USDⓈ-M perp data foundation (free, no API key).

The whole reason this module exists the way it does: **survivorship is the killer**
for crypto-carry backtests (brain/33). The live ``/fapi/v1/exchangeInfo`` universe
only lists *currently-traded* perps — testing those alone is the small/illiquid-
equity kill transplanted to crypto: the dead tokens that went to zero are exactly
the ones that paid fat funding right before dying, so a survivor-only carry study
manufactures a gorgeous edge out of nothing.

### Where the data comes from (and why this source is survivorship-honest)

Binance's live REST host (``fapi.binance.com``) is geoblocked from many regions
(HTTP 451) and, more importantly, its ``exchangeInfo`` only shows live symbols.
Instead we read **``data.binance.vision``** — Binance's public, no-auth historical
data archive (an S3 bucket). Its key property: it is **append-only and never
purges delisted symbols**. A perp that was delisted years ago still has its full
funding-rate and kline history sitting in the archive, and *the last available
month is itself the delisting signal*. Verified live:

    SRMUSDT (Serum, dead)   funding 2020-09 .. 2024-07   -> delisted
    BTSUSDT (BitShares,dead) funding 2021-02 .. 2024-08  -> delisted
    BTCUSDT (alive)          funding 2020-01 .. current   -> live

So unlike yfinance-for-equities (which purges dead names), this archive lets us
build a universe that *includes the corpses*. The delisting flag is derived from
"last funding month is well before the archive's leading edge", not from any
paid delisting feed.

### Layout (mirrors ``catalysts/tiingo.py`` / ``catalysts/cef_universe.py``)

Pure, unit-testable parse/assembly core (``parse_funding_csv``,
``parse_kline_csv``, ``assemble_universe``, ``derive_delisted``) + a thin fetch
wrapper behind an injectable ``HttpGetter`` seam so every test opens no socket.
Network failures log and return ``None``/empty — never raise.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

import pandas as pd
import structlog

log = structlog.get_logger()

# Public archive bucket. The S3 *listing* API lives on the s3 host; the file
# *download* path is served by the data.binance.vision CDN. Both are no-auth and
# reachable from regions where fapi.binance.com returns 451.
S3_LIST_BASE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DL_BASE = "https://data.binance.vision"

# USDⓈ-M futures monthly dumps. "um" = USDT/USDC-margined.
FUNDING_PREFIX = "data/futures/um/monthly/fundingRate/"
KLINES_PREFIX = "data/futures/um/monthly/klines/"

# SPOT monthly kline dumps. Stablecoins (USDC/USTUSDT/...) trade on the SPOT
# market, not USDⓈ-M futures, so the depeg study (T34) reads this prefix. Same
# append-only, never-purged archive — it still holds UST's corpse
# (USTUSDT 2021-12..2022-05, the collapse window).
SPOT_KLINES_PREFIX = "data/spot/monthly/klines/"

# Funding CSV header (present on every month, all eras — verified 2020-01..2026).
_FUNDING_HEADER = ("calc_time", "funding_interval_hours", "last_funding_rate")
# Kline columns (the headerless legacy form; recent months prepend this header).
_KLINE_COLS = (
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
)


# --------------------------------------------------------------------------- #
# Injectable HTTP seam (identical contract to tiingo.HttpGetter, content-bytes)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HttpResponse:
    """Minimal response shape the client depends on (test-friendly).

    ``content`` carries raw bytes (zip payloads); ``text`` carries decoded body
    (the S3 XML listings). A getter populates whichever it can.
    """

    status_code: int
    content: bytes = b""
    text: str = ""


class HttpGetter(Protocol):
    """Injectable seam: ``GET url`` with query params -> response.

    Real impl wraps ``httpx``; tests pass a stub so no socket opens. Stubs should
    not raise — translate failures into a non-200 response (the client also
    tolerates raises, treating them as a fetch failure).
    """

    def __call__(self, url: str, *, params: dict[str, str] | None = None) -> HttpResponse: ...


def _httpx_getter(url: str, *, params: dict[str, str] | None = None) -> HttpResponse:
    """Default getter backed by ``httpx`` (imported lazily, only when called)."""

    import httpx

    resp = httpx.get(url, params=params or {}, timeout=60.0, follow_redirects=True)
    return HttpResponse(status_code=resp.status_code, content=resp.content, text=resp.text)


# --------------------------------------------------------------------------- #
# PURE parse core
# --------------------------------------------------------------------------- #
def _unzip_single_csv(content: bytes) -> str | None:
    """PURE: extract the single CSV member from a Binance dump zip, or ``None``."""

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError):
        return None
    names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    if not names:
        return None
    try:
        return zf.read(names[0]).decode("utf-8", errors="replace")
    except (KeyError, OSError):
        return None


def _epoch_to_utc(raw: int) -> pd.Timestamp:
    """PURE: epoch integer (s / ms / us) -> UTC Timestamp, unit auto-detected.

    Binance's archive is NOT unit-stable: legacy spot/futures dumps use
    millisecond ``open_time`` (13 digits) but dumps from ~2025-01 onward switched
    to **microseconds** (16 digits). Hardcoding ``unit="ms"`` silently mapped
    those microsecond values to the year ~52,000 (which pandas wraps into 1970),
    corrupting every 2025-2026 bar. We pick the unit by magnitude:

        >= 1e15  -> microseconds (16+ digit)
        >= 1e12  -> milliseconds (13 digit)
        else     -> seconds

    Bounds chosen so any plausible 2015-2100 timestamp lands in the right band.
    """

    if raw >= 1_000_000_000_000_000:  # 1e15 -> microseconds
        unit = "us"
    elif raw >= 1_000_000_000_000:  # 1e12 -> milliseconds
        unit = "ms"
    else:  # seconds
        unit = "s"
    return pd.Timestamp(raw, unit=unit, tz="UTC")


def parse_funding_csv(text: str, symbol: str) -> pd.Series | None:
    """PURE: a funding-rate CSV body -> Series of per-interval funding, or ``None``.

    Columns: ``calc_time`` (ms epoch), ``funding_interval_hours``,
    ``last_funding_rate`` (the realized funding for that interval, e.g.
    ``0.00035`` = +3.5 bps). Output is indexed by UTC timestamp (interval close),
    ascending, named ``symbol``; the value is the per-interval rate (NOT
    annualized). A leading header row is required and skipped; malformed/empty
    bodies yield ``None``.
    """

    if not text:
        return None
    times: list[pd.Timestamp] = []
    rates: list[float] = []
    reader = csv.reader(io.StringIO(text))
    for i, row in enumerate(reader):
        if len(row) < 3:
            continue
        if i == 0 and row[0].strip().lower() == _FUNDING_HEADER[0]:
            continue  # header
        try:
            ms = int(float(row[0]))
            rate = float(row[2])
        except (ValueError, IndexError):
            continue
        if rate != rate:  # NaN guard
            continue
        times.append(_epoch_to_utc(ms))
        rates.append(rate)
    if not rates:
        return None
    s = pd.Series(rates, index=pd.DatetimeIndex(times), name=symbol)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s if not s.empty else None


def parse_kline_csv(text: str, symbol: str) -> pd.DataFrame | None:
    """PURE: a daily-kline CSV body -> DataFrame indexed by UTC date, or ``None``.

    Handles both dump eras: legacy files are headerless 12-col rows; recent
    months prepend an ``open_time,open,...`` header (auto-detected and skipped).
    Returns columns ``[open, high, low, close, volume]`` floats, indexed by the
    bar's UTC date (from ``open_time``, unit auto-detected s/ms/us via
    :func:`_epoch_to_utc` — 2025+ dumps use microseconds). Empty/malformed
    bodies yield ``None``.
    """

    if not text:
        return None
    dates: list[pd.Timestamp] = []
    rows: list[tuple[float, float, float, float, float]] = []
    reader = csv.reader(io.StringIO(text))
    for i, row in enumerate(reader):
        if len(row) < 6:
            continue
        if i == 0 and not row[0].strip().lstrip("-").isdigit():
            continue  # header row (open_time is non-numeric)
        try:
            ms = int(float(row[0]))
            o, h, low_, c, v = (float(row[1]), float(row[2]), float(row[3]),
                                float(row[4]), float(row[5]))
        except (ValueError, IndexError):
            continue
        if c != c:  # NaN guard
            continue
        dates.append(_epoch_to_utc(ms).normalize())
        rows.append((o, h, low_, c, v))
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"],
                      index=pd.DatetimeIndex(dates))
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df if not df.empty else None


_MONTH_RE = re.compile(r"-(\d{4})-(\d{2})\.zip$")


def parse_month_list(xml: str) -> list[date]:
    """PURE: an S3 XML listing of a symbol's monthly zips -> sorted month dates.

    Each ``<Key>...SYMBOL-fundingRate-2021-03.zip</Key>`` yields the first-of-
    month date. Used both to discover a symbol's listing span and (via the last
    month) to detect delisting. Returns ascending, de-duplicated.
    """

    months: set[date] = set()
    for key in re.findall(r"<Key>([^<]+)</Key>", xml):
        m = _MONTH_RE.search(key)
        if m:
            months.add(date(int(m.group(1)), int(m.group(2)), 1))
    return sorted(months)


def parse_symbol_list(xml: str) -> list[str]:
    """PURE: an S3 XML *prefix* listing -> the list of symbol names under it.

    Prefixes look like ``.../fundingRate/SRMUSDT/``; we take the last path
    segment. Returns ascending, de-duplicated.
    """

    syms: set[str] = set()
    for pre in re.findall(r"<Prefix>([^<]+)</Prefix>", xml):
        seg = pre.rstrip("/").rsplit("/", 1)[-1]
        if seg:
            syms.add(seg)
    return sorted(syms)


# --------------------------------------------------------------------------- #
# Universe assembly + survivorship
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SymbolSpan:
    """One perp's listing span and survivorship verdict.

    ``first_month`` / ``last_month`` are first-of-month dates of the earliest /
    latest funding dump available. ``delisted`` is True when the symbol's archive
    stops well before the archive frontier (i.e. it stopped trading); a live
    symbol's ``last_month`` tracks the frontier.
    """

    symbol: str
    first_month: date
    last_month: date
    delisted: bool
    is_alt: bool


# Majors excluded from the "alt tail": the alt-crowding mechanism (retail crowds
# directional longs in small caps) is hypothesized strongest OUTSIDE the majors.
_MAJORS = frozenset({"BTCUSDT", "ETHUSDT", "BNBUSDT"})


def derive_delisted(last_month: date, frontier: date, *, gap_months: int = 2) -> bool:
    """PURE: is a symbol delisted, given its last funding month vs the frontier?

    ``frontier`` is the latest month present *anywhere* in the archive (the live
    leading edge). A symbol whose own ``last_month`` lags the frontier by more
    than ``gap_months`` stopped trading -> delisted. The 2-month slack absorbs
    normal archive-publish lag for live names.
    """

    delta = (frontier.year - last_month.year) * 12 + (frontier.month - last_month.month)
    return delta > gap_months


def assemble_universe(
    spans: Iterable[tuple[str, list[date]]],
    *,
    frontier: date | None = None,
    gap_months: int = 2,
) -> list[SymbolSpan]:
    """PURE: turn ``(symbol, [month dates])`` pairs into a survivorship universe.

    The ``frontier`` (latest month anywhere) defaults to the max last-month across
    all inputs. Each symbol gets first/last month, a ``delisted`` flag (via
    :func:`derive_delisted`), and an ``is_alt`` flag (everything but BTC/ETH/BNB).
    Symbols with no months are dropped. The output deliberately RETAINS delisted
    symbols — that retention is the whole survivorship correction.
    """

    rows: list[tuple[str, list[date]]] = [
        (sym, sorted(months)) for sym, months in spans if months
    ]
    if not rows:
        return []
    if frontier is None:
        frontier = max(months[-1] for _, months in rows)
    out: list[SymbolSpan] = []
    for sym, months in rows:
        out.append(
            SymbolSpan(
                symbol=sym,
                first_month=months[0],
                last_month=months[-1],
                delisted=derive_delisted(months[-1], frontier, gap_months=gap_months),
                is_alt=sym not in _MAJORS,
            )
        )
    return sorted(out, key=lambda r: r.symbol)


def survivorship_summary(universe: list[SymbolSpan]) -> dict[str, int]:
    """PURE: counts that prove (or disprove) the universe includes the corpses."""

    return {
        "total": len(universe),
        "delisted": sum(1 for s in universe if s.delisted),
        "live": sum(1 for s in universe if not s.delisted),
        "alt": sum(1 for s in universe if s.is_alt),
        "alt_delisted": sum(1 for s in universe if s.is_alt and s.delisted),
    }


# --------------------------------------------------------------------------- #
# Thin fetch wrappers (best-effort, never raise)
# --------------------------------------------------------------------------- #
def _list_xml(prefix: str, http_get: HttpGetter | None) -> str | None:
    getter = http_get or _httpx_getter
    try:
        resp = getter(S3_LIST_BASE, params={"delimiter": "/", "prefix": prefix})
    except Exception as exc:
        log.warning("crypto_list_failed", prefix=prefix, error=str(exc))
        return None
    if resp.status_code != 200:
        log.warning("crypto_list_bad_status", prefix=prefix, status=resp.status_code)
        return None
    return resp.text


def list_perp_symbols(*, http_get: HttpGetter | None = None) -> list[str]:
    """Fetch every perp symbol that has a funding dump (LIVE + DELISTED).

    This is the survivorship-honest universe spine: the funding archive lists
    ~800 symbols including long-dead perps, vs the ~300 live ones in
    ``exchangeInfo``. Returns ``[]`` on any failure.
    """

    xml = _list_xml(FUNDING_PREFIX, http_get)
    return parse_symbol_list(xml) if xml else []


def list_symbol_months(symbol: str, *, http_get: HttpGetter | None = None) -> list[date]:
    """Fetch the available funding-dump months for ``symbol`` (its listing span)."""

    xml = _list_xml(f"{FUNDING_PREFIX}{symbol}/", http_get)
    return parse_month_list(xml) if xml else []


def _fetch_zip_text(url: str, http_get: HttpGetter | None) -> str | None:
    getter = http_get or _httpx_getter
    try:
        resp = getter(url, params=None)
    except Exception as exc:
        log.warning("crypto_fetch_failed", url=url, error=str(exc))
        return None
    if resp.status_code != 200:
        # 404 is normal (a month with no data); log at debug-ish level.
        return None
    return _unzip_single_csv(resp.content)


def fetch_funding_month(
    symbol: str, year: int, month: int, *, http_get: HttpGetter | None = None
) -> pd.Series | None:
    """Fetch one month of funding for ``symbol``; ``None`` if absent/malformed."""

    url = f"{DL_BASE}/{FUNDING_PREFIX}{symbol}/{symbol}-fundingRate-{year:04d}-{month:02d}.zip"
    text = _fetch_zip_text(url, http_get)
    return parse_funding_csv(text, symbol) if text else None


def fetch_kline_month(
    symbol: str, year: int, month: int, *, interval: str = "1d", http_get: HttpGetter | None = None
) -> pd.DataFrame | None:
    """Fetch one month of ``interval`` klines for ``symbol``; ``None`` if absent."""

    url = (f"{DL_BASE}/{KLINES_PREFIX}{symbol}/{interval}/"
           f"{symbol}-{interval}-{year:04d}-{month:02d}.zip")
    text = _fetch_zip_text(url, http_get)
    return parse_kline_csv(text, symbol) if text else None


def fetch_spot_kline_month(
    symbol: str, year: int, month: int, *, interval: str = "1d", http_get: HttpGetter | None = None
) -> pd.DataFrame | None:
    """Fetch one month of SPOT ``interval`` klines for ``symbol``; ``None`` if absent.

    Spot counterpart of :func:`fetch_kline_month`. Stablecoin pairs (USDC, UST,
    DAI, ...) live on the spot market, so the depeg study reads this path. Reuses
    the same pure :func:`parse_kline_csv` core. UST's collapse months really are
    here (``USTUSDT-1d-2022-05.zip``), which is the entire point of T34.
    """

    url = (f"{DL_BASE}/{SPOT_KLINES_PREFIX}{symbol}/{interval}/"
           f"{symbol}-{interval}-{year:04d}-{month:02d}.zip")
    text = _fetch_zip_text(url, http_get)
    return parse_kline_csv(text, symbol) if text else None


def fetch_spot_kline_history(
    symbol: str, start: date, end: date, *, interval: str = "1d", http_get: HttpGetter | None = None
) -> pd.DataFrame | None:
    """Concatenate monthly SPOT daily-kline dumps for ``symbol`` over ``[start, end]``.

    Missing months are skipped silently — a dead stablecoin (UST) simply stops,
    and the final available close is its realized terminal price. Best-effort.
    """

    parts = [
        df for (y, m) in _months_between(start, end)
        if (df := fetch_spot_kline_month(symbol, y, m, interval=interval, http_get=http_get))
        is not None
    ]
    if not parts:
        return None
    out = pd.concat(parts)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def list_spot_symbol_months(
    symbol: str, *, interval: str = "1d", http_get: HttpGetter | None = None
) -> list[date]:
    """Fetch the available SPOT kline months for ``symbol`` (its listing span)."""

    xml = _list_xml(f"{SPOT_KLINES_PREFIX}{symbol}/{interval}/", http_get)
    return parse_month_list(xml) if xml else []


def _months_between(start: date, end: date) -> list[tuple[int, int]]:
    """PURE: inclusive list of (year, month) from ``start`` to ``end``."""

    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def fetch_funding_history(
    symbol: str, start: date, end: date, *, http_get: HttpGetter | None = None
) -> pd.Series | None:
    """Concatenate monthly funding dumps for ``symbol`` over ``[start, end]``.

    Returns the per-interval funding Series (UTC index) or ``None`` if no month
    served data. Missing months are skipped silently (delisted symbols simply
    stop). Best-effort throughout.
    """

    parts = [
        s for (y, m) in _months_between(start, end)
        if (s := fetch_funding_month(symbol, y, m, http_get=http_get)) is not None
    ]
    if not parts:
        return None
    out = pd.concat(parts)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.name = symbol
    return out


def fetch_kline_history(
    symbol: str, start: date, end: date, *, interval: str = "1d", http_get: HttpGetter | None = None
) -> pd.DataFrame | None:
    """Concatenate monthly daily-kline dumps for ``symbol`` over ``[start, end]``."""

    parts = [
        df for (y, m) in _months_between(start, end)
        if (df := fetch_kline_month(symbol, y, m, interval=interval, http_get=http_get)) is not None
    ]
    if not parts:
        return None
    out = pd.concat(parts)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def utc_today() -> date:
    """The current UTC date (frontier anchor for delisting detection)."""

    return datetime.now(UTC).date()
