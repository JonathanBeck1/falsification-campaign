"""Shared single-name option vol-surface foundation (T22-T26 infrastructure).

This is **infrastructure, not a test**. The single-name option vol-surface
tests — dispersion (T22), earnings IV crush (T23), skew (T24), term structure
(T25), hard-to-borrow (T26) — all reuse the loader, the Black-Scholes implied
-vol solver, and the surface builders defined here. Keeping one audited
foundation means every downstream test sees the *same* IVs from the *same*
quotes under the *same* quality guards, so a kill in one test cannot be blamed
on a private, undocumented vol pipeline.

### Data provenance (brain/30 gate, taxonomy class 4 — "derived/fake data")

The option quotes are a **free, owned** parquet lake of single-name EOD option
chains collected from ThetaData:

    $TRADER_EOD_LAKE_ROOT/   (default <repo>/lake/option_eod_quotes)
        root=TICKER/trade_year=YYYY/TICKER_YYYY-MM-DD.parquet

Columns: ``trade_date, root, expiration, strike, right (C/P), bid, ask, close,
volume, open_interest, underlying_close, source``. ~28 roots, 2022-2026.

**Underlying caveat (verified 2026-06-17):** ``underlying_close`` is NULL across
the *entire* lake as collected — not merely before the documented ~2023-06
ThetaData stock-EOD floor. The naive fallback (yfinance daily close) is
**wrong** and was a real bug: yfinance returns *split-adjusted* closes, but the
lake stores **unadjusted** strikes as-of-trade-date. For any name that split
*after* a given trade date (e.g. AVGO 10:1 Jul-2024, the NFLX series), the
yfinance close is ~10x off the lake's strike scale, so "ATM" lands on a deep-ITM
contract and the recovered IV blows up to ~290% (verified before this fix:
AVGO 2023-06-01 ATM30 = 2.85, NFLX 2023-01-18 / 2024-10-15 ATM30 = 2.99). The
mismatch also shows up subtly on non-splitters because the yfinance series is
adjusted for *all later* corporate actions / its own reference epoch.

**Fix — put-call-parity spot (the source of truth for moneyness).** The
underlying is now derived *from the option chain itself* so it is, by
construction, on the same unadjusted scale as the strikes. On the shortest
liquid expiration for each ``(ticker, trade_date)`` we take the near-the-money
matched (strike) call+put mid pairs and invert European put-call parity::

    S ≈ K·e^{-rT} + (C_mid - P_mid)              (no-dividend form)

and use a robust central estimate (the median over the few strikes nearest the
crude ATM where both legs carry a genuine two-sided quote). The discount uses
the module's flat ``DEFAULT_RISK_FREE_RATE``; **dividend yield is assumed 0**
(documented simplification — a borrow/dividend basis shifts the parity spot by
≈ (q·T)·S, i.e. tens of bps for these 30-90d tenors, negligible for ATM
selection). This recovers, e.g., NFLX = $327 on 2023-01-18 (consistent with the
$325 strike scale; the T23 decision doc anchored $326.44) and AVGO = $787 on
2023-06-01 (vs the broken yfinance $79).

Precedence is **lake-first → parity → yfinance(last-resort cross-check only)**:
the lake's ``underlying_close`` is used wherever non-null (a future backfill may
populate it); otherwise the parity spot is the effective source. The yfinance
split-adjusted close is **no longer used for moneyness** — it is kept only as an
optional, clearly-marked sanity cross-check and as a final fallback for the
(rare) date whose chain is too thin to invert parity.

The option *price* used everywhere is the **mid** = (bid + ask) / 2. Rows
without a genuine two-sided quote (bid <= 0 or ask <= 0) or with mid <= 0 are
dropped before any IV is computed — a stale/one-sided quote is not a price.

### Risk-free rate

We use a single documented constant, ``DEFAULT_RISK_FREE_RATE = 0.04`` (4%
annualized, continuously compounded), matching the rate already wired through
the rest of the options tooling (``cli.py``/``short_put.py`` default 0.04). The
vol-surface quantities we care about — ATM level, 25-delta skew, term-structure
slope — are *differences and ratios* of IVs at the same date, so a modest
mis-specification of the flat rate is differenced out and does not bias the
downstream tests. Dividend yield is taken as 0 (documented simplification; for
30-90d tenors on these names the effect on IV is second-order).

### Purity

The IV solver and every surface builder are **pure** functions of in-memory
frames — no I/O. Only :func:`load_option_quotes` touches the filesystem and (via
an injectable ``underlying_fetcher`` seam) yfinance, so all unit tests run
network-free and disk-free by injecting synthetic frames and a stub underlying.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd
import structlog

from trader.config import eod_lake_root

log = structlog.get_logger()

# --------------------------------------------------------------------------- #
# Constants (all documented; see module docstring)
# --------------------------------------------------------------------------- #
# Resolved from TRADER_EOD_LAKE_ROOT (repo-relative default); the lake itself is
# licensed (ThetaData-derived) and not shipped. See trader.config.eod_lake_root.
LAKE_ROOT = eod_lake_root()

# Flat continuously-compounded risk-free proxy; matches the rest of the options
# tooling. Surface quantities are IV differences/ratios, so this is non-binding.
DEFAULT_RISK_FREE_RATE = 0.04
DEFAULT_DIVIDEND_YIELD = 0.0

# Calendar days per year for time-to-expiry (trade_date -> expiration).
DAYS_PER_YEAR = 365.0

# Quality guards on implied vol. An IV outside this band is a bad quote / failed
# solve, not a real vol, and is excluded from every surface.
MIN_VALID_IV = 0.01  # 1%
MAX_VALID_IV = 3.00  # 300%

# A surface point must clear at least this open interest OR carry a two-sided
# quote. (Two-sided is already enforced by the loader; OI is the extra guard for
# surface points specifically.)
DEFAULT_MIN_OPEN_INTEREST = 0

# Risk-reversal delta tolerance: the nearest-available wing on each side must be
# within this of the target delta, else the skew is mislabeled (a 10Δ skew
# returned as a "25Δ" number). See :func:`risk_reversal_25d`.
DELTA_TOL = 0.10

# Identifiability floor for implied_vol: a solved IV is only trusted if the BS
# vega at the solution exceeds this. A deep-ITM contract at intrinsic value has
# a price flat across a wide vol range (near-zero vega), so any vol the solver
# lands on there is meaningless — return NaN instead. The floor is far below any
# genuinely-OTM option's vega, so it never NaNs a real surface point; it only
# rejects the non-identifiable intrinsic-valued rows iv_grid would otherwise
# expose. (price units per 1.0 of absolute vol.)
_IDENTIFY_VEGA_FLOOR = 1e-4

# Newton/bisection solver controls.
_IV_LO = 1e-4
_IV_HI = 5.0
_NEWTON_ITERS = 60
_BISECT_ITERS = 80
_PRICE_TOL = 1e-6
_VEGA_FLOOR = 1e-8

# Standard normal helpers (vectorized, no scipy dependency).
_SQRT_2PI = float(np.sqrt(2.0 * np.pi))


# --------------------------------------------------------------------------- #
# Injectable underlying-fetch seam (keeps tests network-free)
# --------------------------------------------------------------------------- #
# NOTE: yfinance is the *last-resort* spot source only. Because it returns
# split-adjusted closes that do not match the lake's unadjusted strikes, it must
# never be the value used for moneyness when a chain is invertible — see
# ``_parity_spot_per_date`` and the module docstring. The seam is retained so the
# rare too-thin-to-invert date can still be filled (and as a sanity cross-check),
# and so tests can inject a stub.
class UnderlyingFetcher(Protocol):
    """``(ticker, start, end) -> {date: close}`` daily-close map for the underlying.

    The default implementation hits yfinance; tests inject a stub. Implementations
    must never raise — a failed fetch returns an empty mapping. **Caveat:** the
    yfinance closes are split-adjusted and are used only as a last-resort fallback
    (see module docstring); parity-derived spot is the primary moneyness source.
    """

    def __call__(self, ticker: str, start: date, end: date) -> Mapping[date, float]: ...


def yfinance_daily_close(ticker: str, start: date, end: date) -> dict[date, float]:
    """Best-effort daily-close map from yfinance for ``ticker`` over [start, end].

    Returns ``{trade_date: close}`` (tz-naive python ``date`` keys). Never raises:
    any failure logs and returns ``{}`` so the loader can decide how to proceed.
    yfinance is imported lazily so importing this module opens no socket.

    **Demoted to last-resort.** These closes are *split-adjusted* and therefore
    do not match the lake's unadjusted strike scale for any name that split after
    the trade date; they are NOT used for moneyness when the option chain can be
    inverted via put-call parity. See the module docstring.
    """

    try:
        import yfinance as yf

        # end is inclusive for the caller; yfinance 'end' is exclusive, pad by 1d.
        frame = yf.download(
            ticker,
            start=start.isoformat(),
            end=(pd.Timestamp(end) + pd.Timedelta(days=1)).date().isoformat(),
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception as exc:  # never raise out of the fetch layer
        log.warning("yfinance_fetch_failed", ticker=ticker, error=str(exc))
        return {}
    if frame is None or frame.empty:
        log.warning("yfinance_empty", ticker=ticker, start=str(start), end=str(end))
        return {}
    # yfinance may return a single- or multi-indexed column frame; pick Close.
    close = frame["Close"]
    if isinstance(close, pd.DataFrame):
        # MultiIndex columns (e.g. one ticker) -> squeeze to a Series.
        close = close.iloc[:, 0]
    out: dict[date, float] = {}
    for idx, value in close.items():
        ts = pd.Timestamp(idx)
        val = float(value)
        if np.isfinite(val) and val > 0:
            out[ts.date()] = val
    return out


# --------------------------------------------------------------------------- #
# Loader (the only I/O in this module)
# --------------------------------------------------------------------------- #
def _lake_files_for(ticker: str, start: date, end: date, lake_root: Path) -> list[Path]:
    """Per-day parquet paths under ``root=TICKER`` whose date is in [start, end]."""

    root_dir = lake_root / f"root={ticker}"
    if not root_dir.is_dir():
        return []
    files: list[Path] = []
    for year in range(start.year, end.year + 1):
        ydir = root_dir / f"trade_year={year}"
        if not ydir.is_dir():
            continue
        for path in sorted(ydir.glob(f"{ticker}_*.parquet")):
            d = _date_from_filename(path, ticker)
            if d is not None and start <= d <= end:
                files.append(path)
    return files


def _date_from_filename(path: Path, ticker: str) -> date | None:
    """Parse ``TICKER_YYYY-MM-DD.parquet`` -> date, or None if it doesn't match."""

    stem = path.stem  # TICKER_YYYY-MM-DD
    prefix = f"{ticker}_"
    if not stem.startswith(prefix):
        return None
    try:
        return datetime.strptime(stem[len(prefix) :], "%Y-%m-%d").date()
    except ValueError:
        return None


_QUOTE_COLUMNS = [
    "trade_date",
    "root",
    "expiration",
    "strike",
    "right",
    "bid",
    "ask",
    "close",
    "volume",
    "open_interest",
    "underlying_close",
]


def load_option_quotes(
    ticker: str,
    start: date,
    end: date,
    *,
    lake_root: Path = LAKE_ROOT,
    underlying_fetcher: UnderlyingFetcher = yfinance_daily_close,
    frames: Iterable[pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Load a tidy frame of two-sided option quotes with a guaranteed underlying.

    Reads the lake for ``ticker`` over the inclusive ``[start, end]`` trade-date
    range and returns one row per (trade_date, expiration, strike, right) with:

    - ``mid`` = (bid + ask) / 2  (rows with bid<=0, ask<=0, or mid<=0 are dropped)
    - ``underlying`` — guaranteed non-null: the lake's ``underlying_close`` where
      present, otherwise the yfinance daily close joined by ``trade_date`` (rows
      whose date has no underlying from either source are dropped, counted in the
      log).
    - ``tau`` — time to expiry in years ((expiration - trade_date) / 365), with
      same-day/expired rows (tau <= 0) dropped.
    - typed columns: ``trade_date``/``expiration`` as ``datetime64``, ``strike``/
      ``bid``/``ask``/``mid``/``underlying`` float, ``open_interest``/``volume``
      int, ``right`` in {"C","P"}.

    The ``frames`` argument is a test seam: when provided, those in-memory frames
    are used *instead of* reading the lake (the underlying fallback still runs),
    so unit tests need neither disk nor network.

    Returns an empty (typed) frame if nothing loads.
    """

    raw = _read_raw_quotes(ticker, start, end, lake_root, frames)
    if raw.empty:
        return _empty_quote_frame()

    raw = raw.copy()
    raw["trade_date"] = pd.to_datetime(raw["trade_date"])
    raw["expiration"] = pd.to_datetime(raw["expiration"])
    raw["right"] = raw["right"].astype(str).str.upper().str[0]
    for col in ("strike", "bid", "ask", "close"):
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    for col in ("volume", "open_interest"):
        raw[col] = pd.to_numeric(raw.get(col), errors="coerce").fillna(0).astype("int64")

    # Two-sided quote requirement -> mid as the option price.
    raw = raw[(raw["bid"] > 0) & (raw["ask"] > 0)]
    raw = raw.assign(mid=(raw["bid"] + raw["ask"]) / 2.0)
    raw = raw[raw["mid"] > 0]
    raw = raw[raw["right"].isin(("C", "P"))]
    if raw.empty:
        return _empty_quote_frame()

    # tau is computed BEFORE attaching the underlying because the parity-spot
    # derivation discounts strikes by e^{-rT} and so needs the per-row tenor.
    # Expired/same-day rows (tau <= 0) are dropped here so they neither anchor the
    # parity spot nor survive into the surface.
    raw["tau"] = (raw["expiration"] - raw["trade_date"]).dt.days / DAYS_PER_YEAR
    before = len(raw)
    raw = raw[raw["tau"] > 0]
    if len(raw) < before:
        log.debug("dropped_expired_rows", ticker=ticker, dropped=before - len(raw))
    if raw.empty:
        return _empty_quote_frame()

    raw = _attach_underlying(raw, ticker, start, end, underlying_fetcher)
    if raw.empty:
        return _empty_quote_frame()

    cols = [
        "trade_date",
        "expiration",
        "tau",
        "root",
        "strike",
        "right",
        "bid",
        "ask",
        "mid",
        "close",
        "volume",
        "open_interest",
        "underlying",
    ]
    out = raw[cols].reset_index(drop=True)
    return out


def _read_raw_quotes(
    ticker: str,
    start: date,
    end: date,
    lake_root: Path,
    frames: Iterable[pd.DataFrame] | None,
) -> pd.DataFrame:
    """Gather raw rows either from injected ``frames`` or the parquet lake."""

    if frames is not None:
        parts = [f for f in frames if f is not None and not f.empty]
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    files = _lake_files_for(ticker, start, end, lake_root)
    if not files:
        log.warning("no_lake_files", ticker=ticker, start=str(start), end=str(end))
        return pd.DataFrame()
    parts = []
    for path in files:
        try:
            parts.append(pd.read_parquet(path))
        except Exception as exc:  # one bad shard must not kill the load
            log.warning("parquet_read_failed", path=str(path), error=str(exc))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# --------------------------------------------------------------------------- #
# Put-call-parity spot (the provenance-clean underlying — same scale as strikes)
# --------------------------------------------------------------------------- #
# How many of the strikes nearest the crude ATM to median over for a robust
# parity-spot estimate. A handful of strikes washes out per-strike quote noise
# without reaching into the illiquid wings where C-P parity is unreliable.
PARITY_NEAREST_STRIKES = 5


def parity_spot_from_expiry(
    expiry_quotes: pd.DataFrame,
    *,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    n_strikes: int = PARITY_NEAREST_STRIKES,
) -> float:
    """Put-call-parity-implied spot from ONE expiration's two-sided quotes.

    Inverts European put-call parity (no-dividend form)::

        S ≈ K·e^{-rT} + (C_mid - P_mid)

    For each strike that has BOTH a two-sided call and put, this yields one spot
    estimate. We take a *robust central* estimate: the median over the
    ``n_strikes`` strikes whose ``|C_mid - P_mid|`` is smallest — i.e. the strikes
    closest to at-the-money, where parity is least contaminated by the wide
    deep-ITM/OTM spreads. This is, by construction, on the lake's *unadjusted*
    strike scale, so it matches the strikes even for post-split names.

    The frame must carry ``strike``, ``right`` (C/P), ``mid`` and ``tau`` (years).
    Returns NaN if no matched call/put strike pair exists. PURE (no I/O).

    Dividend assumption: q = 0 (documented). A nonzero borrow/dividend basis
    shifts S by ≈ (q·T)·S, negligible for the ATM selection this feeds.
    """

    if expiry_quotes.empty:
        return float("nan")
    c = expiry_quotes
    calls = c[c["right"] == "C"][["strike", "mid", "tau"]].rename(columns={"mid": "cmid"})
    puts = c[c["right"] == "P"][["strike", "mid"]].rename(columns={"mid": "pmid"})
    merged = calls.merge(puts, on="strike", how="inner")
    if merged.empty:
        return float("nan")

    # One parity-spot estimate per strike: S = K·e^{-rT} + (C - P).
    tau = merged["tau"].to_numpy(dtype=float)
    disc_k = merged["strike"].to_numpy(dtype=float) * np.exp(-risk_free_rate * tau)
    est = disc_k + (merged["cmid"].to_numpy(dtype=float) - merged["pmid"].to_numpy(dtype=float))

    # Rank strikes by parity-noise proxy |C - P| (smallest = nearest ATM) and take
    # a robust median over the nearest few. |C - P| ≈ |S - K·e^{-rT}|, so this is
    # equivalent to "strikes nearest the (discounted) money".
    noise = np.abs(merged["cmid"].to_numpy(dtype=float) - merged["pmid"].to_numpy(dtype=float))
    order = np.argsort(noise, kind="stable")
    keep = order[: max(1, n_strikes)]
    spot = float(np.median(est[keep]))
    return spot if np.isfinite(spot) and spot > 0 else float("nan")


def _parity_spot_per_date(
    raw: pd.DataFrame,
    *,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict[pd.Timestamp, float]:
    """Map ``{normalized trade_date -> parity spot}`` using each date's shortest
    liquid expiration. PURE.

    ``raw`` already carries two-sided ``mid`` rows (the loader filtered to those)
    and a per-row ``tau`` (years). For each trade_date we pick the shortest tenor
    that has at least one matched call/put strike pair, then invert parity there
    (the shortest liquid expiration is the most ATM-dense and least affected by
    the dividend/borrow basis we drop).
    """

    out: dict[pd.Timestamp, float] = {}
    if raw.empty or "tau" not in raw or "mid" not in raw:
        return out
    for td, day in raw.groupby(raw["trade_date"].dt.normalize()):
        # Shortest tenor first; use the first expiration that actually inverts.
        spot = float("nan")
        for _, expiry in sorted(day.groupby("expiration"), key=lambda kv: kv[1]["tau"].iloc[0]):
            spot = parity_spot_from_expiry(expiry, risk_free_rate=risk_free_rate)
            if np.isfinite(spot) and spot > 0:
                break
        if np.isfinite(spot) and spot > 0:
            out[pd.Timestamp(td)] = spot
    return out


def _attach_underlying(
    raw: pd.DataFrame,
    ticker: str,
    start: date,
    end: date,
    underlying_fetcher: UnderlyingFetcher,
    *,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> pd.DataFrame:
    """Guarantee a non-null float ``underlying`` column, on the lake's strike scale.

    Precedence (see module docstring): **lake-first → put-call parity →
    yfinance(last-resort)**.

    1. Lake ``underlying_close`` wherever non-null (a future backfill may add it).
    2. Otherwise the put-call-parity spot for that ``trade_date`` (the effective
       source today, since the lake column is universally null). This is on the
       same unadjusted scale as the strikes, fixing the split-adjusted-spot bug.
    3. Only for a ``trade_date`` whose chain is too thin to invert parity do we
       fall back to the (split-adjusted) yfinance close — and we log it loudly,
       because that value is on the wrong scale for post-split names.

    Rows whose ``trade_date`` still has no underlying after all three are dropped
    (and counted) — an IV is meaningless without a spot.
    """

    lake_uc = pd.to_numeric(raw.get("underlying_close"), errors="coerce")
    raw = raw.assign(underlying=lake_uc)
    norm_td = raw["trade_date"].dt.normalize()

    # (2) Parity fill — the primary source today.
    missing_mask = raw["underlying"].isna() | (raw["underlying"] <= 0)
    if missing_mask.any():
        parity_map = _parity_spot_per_date(raw, risk_free_rate=risk_free_rate)
        if parity_map:
            fill = norm_td.map(parity_map)
            raw["underlying"] = raw["underlying"].where(~missing_mask, fill)

    # (3) yfinance last-resort — only for dates parity could not recover. These are
    # split-adjusted and may be on the wrong scale; logged so callers can see it.
    missing_mask = raw["underlying"].isna() | (raw["underlying"] <= 0)
    if missing_mask.any():
        need_dates = sorted({d.date() for d in raw.loc[missing_mask, "trade_date"]})
        if need_dates:
            fetched = underlying_fetcher(ticker, min(need_dates), max(need_dates))
            fetched_map = {pd.Timestamp(k).normalize(): float(v) for k, v in fetched.items()}
            fill = norm_td.map(fetched_map)
            raw["underlying"] = raw["underlying"].where(~missing_mask, fill)
            filled = int((missing_mask & raw["underlying"].notna() & (raw["underlying"] > 0)).sum())
            if filled:
                log.warning(
                    "underlying_from_yfinance_last_resort",
                    ticker=ticker,
                    rows=filled,
                    note="split-adjusted close; parity could not invert these dates",
                )

    before = len(raw)
    raw = raw[raw["underlying"].notna() & (raw["underlying"] > 0)]
    dropped = before - len(raw)
    if dropped:
        log.warning("dropped_rows_no_underlying", ticker=ticker, dropped=dropped, kept=len(raw))
    return raw


def _empty_quote_frame() -> pd.DataFrame:
    dtypes = {
        "trade_date": "datetime64[ns]",
        "expiration": "datetime64[ns]",
        "tau": "float64",
        "root": "object",
        "strike": "float64",
        "right": "object",
        "bid": "float64",
        "ask": "float64",
        "mid": "float64",
        "close": "float64",
        "volume": "int64",
        "open_interest": "int64",
        "underlying": "float64",
    }
    return pd.DataFrame({c: pd.Series(dtype=dt) for c, dt in dtypes.items()})


# --------------------------------------------------------------------------- #
# PURE Black-Scholes core (vectorized; no scipy)
# --------------------------------------------------------------------------- #
# Pure-numpy erf, used when scipy is unavailable so the module never
# hard-depends on scipy. Abramowitz & Stegun 7.1.26 (max abs err ~1.5e-7).
def _erf_np(x: np.ndarray) -> np.ndarray:
    a1, a2, a3, a4, a5 = (
        0.254829592,
        -0.284496736,
        1.421413741,
        -1.453152027,
        1.061405429,
    )
    p = 0.3275911
    sign = np.sign(x)
    ax = np.abs(x)
    t = 1.0 / (1.0 + p * ax)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * np.exp(-ax * ax)
    return sign * y


try:  # prefer scipy's erf; degrade gracefully to the polynomial approximation.
    from scipy.special import erf as _scipy_erf

    def _norm_cdf(x: np.ndarray) -> np.ndarray:
        return 0.5 * (1.0 + _scipy_erf(x / np.sqrt(2.0)))

except Exception:  # pragma: no cover - exercised only when scipy is absent

    def _norm_cdf(x: np.ndarray) -> np.ndarray:
        return 0.5 * (1.0 + _erf_np(x / np.sqrt(2.0)))


def _norm_pdf(x: np.ndarray) -> np.ndarray:
    return np.exp(-0.5 * x * x) / _SQRT_2PI


def bs_price(
    S: np.ndarray,
    K: np.ndarray,
    T: np.ndarray,
    vol: np.ndarray,
    is_call: np.ndarray,
    *,
    r: float = DEFAULT_RISK_FREE_RATE,
    q: float = DEFAULT_DIVIDEND_YIELD,
) -> np.ndarray:
    """Vectorized European Black-Scholes price. Inputs broadcast; arrays in/out."""

    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.asarray(T, dtype=float)
    vol = np.asarray(vol, dtype=float)
    is_call = np.asarray(is_call, dtype=bool)

    sqrtT = np.sqrt(np.maximum(T, 0.0))
    denom = np.where(vol * sqrtT > 0, vol * sqrtT, np.nan)
    d1 = (np.log(S / K) + (r - q + 0.5 * vol * vol) * T) / denom
    d2 = d1 - vol * sqrtT
    disc_S = S * np.exp(-q * T)
    disc_K = K * np.exp(-r * T)
    call = disc_S * _norm_cdf(d1) - disc_K * _norm_cdf(d2)
    put = disc_K * _norm_cdf(-d2) - disc_S * _norm_cdf(-d1)
    return np.where(is_call, call, put)


def bs_vega(
    S: np.ndarray,
    K: np.ndarray,
    T: np.ndarray,
    vol: np.ndarray,
    *,
    r: float = DEFAULT_RISK_FREE_RATE,
    q: float = DEFAULT_DIVIDEND_YIELD,
) -> np.ndarray:
    """Vectorized BS vega (∂price/∂vol). Same for calls and puts."""

    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.asarray(T, dtype=float)
    vol = np.asarray(vol, dtype=float)
    sqrtT = np.sqrt(np.maximum(T, 0.0))
    denom = np.where(vol * sqrtT > 0, vol * sqrtT, np.nan)
    d1 = (np.log(S / K) + (r - q + 0.5 * vol * vol) * T) / denom
    return S * np.exp(-q * T) * _norm_pdf(d1) * sqrtT


def implied_vol(
    price: np.ndarray,
    S: np.ndarray,
    K: np.ndarray,
    T: np.ndarray,
    is_call: np.ndarray,
    *,
    r: float = DEFAULT_RISK_FREE_RATE,
    q: float = DEFAULT_DIVIDEND_YIELD,
) -> np.ndarray:
    """Solve BS implied vol per contract; NaN where it can't converge.

    Vectorized Newton's method (vega step) with a bisection fallback for the rows
    Newton fails to bracket — robust for the deep-ITM/OTM and stale-quote rows a
    surface inevitably contains. Returns NaN where:

    - any input is non-finite or non-positive (S, K, T, price <= 0), or
    - ``price`` is below intrinsic / above the no-arb max (no real IV exists), or
    - neither Newton nor bisection lands within tolerance.

    Inputs broadcast to a common shape; the result has that shape (float).
    """

    price = np.asarray(price, dtype=float)
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.asarray(T, dtype=float)
    is_call = np.asarray(is_call, dtype=bool)
    price, S, K, T, is_call = np.broadcast_arrays(price, S, K, T, is_call)
    shape = price.shape
    price, S, K, T, is_call = (np.ravel(a).astype(float if a.dtype != bool else bool)
                               for a in (price, S, K, T, is_call))

    out = np.full(price.shape, np.nan, dtype=float)

    finite = np.isfinite(price) & np.isfinite(S) & np.isfinite(K) & np.isfinite(T)
    valid = finite & (price > 0) & (S > 0) & (K > 0) & (T > 0)

    # No-arbitrage bounds: an undiscounted-friendly check using discounted spot.
    disc_S = np.where(valid, S * np.exp(-q * T), np.nan)
    disc_K = np.where(valid, K * np.exp(-r * T), np.nan)
    intrinsic = np.where(is_call, np.maximum(disc_S - disc_K, 0.0), np.maximum(disc_K - disc_S, 0.0))
    upper = np.where(is_call, disc_S, disc_K)
    in_bounds = valid & (price >= intrinsic - _PRICE_TOL) & (price <= upper + _PRICE_TOL)

    idx = np.where(in_bounds)[0]
    if idx.size == 0:
        return out.reshape(shape)

    p = price[idx]
    s = S[idx]
    k = K[idx]
    t = T[idx]
    c = is_call[idx]

    # Newton from a sensible seed (Brenner-Subrahmanyam-ish, clamped).
    vol = np.clip(np.sqrt(2.0 * np.pi / t) * (p / s), 0.05, 2.0)
    vol = np.where(np.isfinite(vol), vol, 0.5)
    for _ in range(_NEWTON_ITERS):
        model = bs_price(s, k, t, vol, c, r=r, q=q)
        vega = bs_vega(s, k, t, vol, r=r, q=q)
        diff = model - p
        safe_vega = np.where(np.abs(vega) > _VEGA_FLOOR, vega, np.nan)
        step = np.nan_to_num(diff / safe_vega, nan=0.0, posinf=0.0, neginf=0.0)
        vol_new = np.clip(vol - step, _IV_LO, _IV_HI)
        converged = np.abs(diff) <= _PRICE_TOL
        vol = np.where(converged, vol, vol_new)
        if np.all(converged):
            break

    model = bs_price(s, k, t, vol, c, r=r, q=q)
    ok = np.abs(model - p) <= 1e-4 * np.maximum(p, 1.0)

    # Bisection fallback for the rows Newton didn't resolve.
    bad = ~ok
    if np.any(bad):
        vol[bad] = _bisect_iv(p[bad], s[bad], k[bad], t[bad], c[bad], r=r, q=q)
        model = bs_price(s, k, t, vol, c, r=r, q=q)
        ok = np.abs(model - p) <= 1e-3 * np.maximum(p, 1.0)

    # Identifiability guard: reject solutions where the price barely responds to
    # vol (vega below the floor) — a deep-ITM contract at intrinsic value is flat
    # in vol, so the "solved" IV there is an arbitrary point in a wide flat band,
    # not a real implied vol. NaN it instead of returning the bisection midpoint.
    vega_at_sol = bs_vega(s, k, t, vol, r=r, q=q)
    ok = ok & (np.abs(vega_at_sol) >= _IDENTIFY_VEGA_FLOOR)

    resolved = np.full(idx.shape, np.nan)
    resolved[ok] = vol[ok]
    out[idx] = resolved
    return out.reshape(shape)


def _bisect_iv(
    price: np.ndarray,
    S: np.ndarray,
    K: np.ndarray,
    T: np.ndarray,
    is_call: np.ndarray,
    *,
    r: float,
    q: float,
) -> np.ndarray:
    """Vectorized bisection on [_IV_LO, _IV_HI]; price is monotone in vol."""

    lo = np.full(price.shape, _IV_LO)
    hi = np.full(price.shape, _IV_HI)
    for _ in range(_BISECT_ITERS):
        mid = 0.5 * (lo + hi)
        model = bs_price(S, K, T, mid, is_call, r=r, q=q)
        too_low = model < price  # price increases with vol -> raise the floor
        lo = np.where(too_low, mid, lo)
        hi = np.where(too_low, hi, mid)
    return 0.5 * (lo + hi)


# --------------------------------------------------------------------------- #
# Surface enrichment: add IV + delta + moneyness to a quote frame
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SurfaceConfig:
    """Knobs for surface construction (all documented in the module docstring)."""

    risk_free_rate: float = DEFAULT_RISK_FREE_RATE
    dividend_yield: float = DEFAULT_DIVIDEND_YIELD
    min_iv: float = MIN_VALID_IV
    max_iv: float = MAX_VALID_IV
    min_open_interest: int = DEFAULT_MIN_OPEN_INTEREST


# Module-level default config (avoids a call in argument defaults; B008).
DEFAULT_SURFACE_CONFIG = SurfaceConfig()


def compute_implied_vols(
    quotes: pd.DataFrame,
    *,
    config: SurfaceConfig = DEFAULT_SURFACE_CONFIG,
) -> pd.DataFrame:
    """Add ``iv``, ``delta``, ``moneyness``, ``log_moneyness`` to a quote frame.

    Operates on the output of :func:`load_option_quotes` (or any frame with
    ``mid, underlying, strike, tau, right``). IVs outside [min_iv, max_iv] and
    rows below ``min_open_interest`` are set to NaN (the row is kept so callers
    can still see the quote, but it is excluded from surface points). PURE.
    """

    if quotes.empty:
        out = quotes.copy()
        for col in ("iv", "delta", "moneyness", "log_moneyness"):
            out[col] = pd.Series(dtype="float64")
        return out

    q = quotes.copy()
    is_call = (q["right"].astype(str).str.upper().str[0] == "C").to_numpy()
    S = q["underlying"].to_numpy(dtype=float)
    K = q["strike"].to_numpy(dtype=float)
    T = q["tau"].to_numpy(dtype=float)
    price = q["mid"].to_numpy(dtype=float)

    iv = implied_vol(price, S, K, T, is_call, r=config.risk_free_rate, q=config.dividend_yield)

    # Quality guards: drop implausible IVs and below-OI points (to NaN).
    bad = ~np.isfinite(iv) | (iv < config.min_iv) | (iv > config.max_iv)
    if config.min_open_interest > 0 and "open_interest" in q:
        bad = bad | (q["open_interest"].to_numpy() < config.min_open_interest)
    iv = np.where(bad, np.nan, iv)

    delta = _bs_delta(S, K, T, iv, is_call, r=config.risk_free_rate, q=config.dividend_yield)
    moneyness = K / S
    log_moneyness = np.log(np.where((K > 0) & (S > 0), K / S, np.nan))

    q["iv"] = iv
    q["delta"] = delta
    q["moneyness"] = moneyness
    q["log_moneyness"] = log_moneyness
    return q


def _bs_delta(
    S: np.ndarray,
    K: np.ndarray,
    T: np.ndarray,
    vol: np.ndarray,
    is_call: np.ndarray,
    *,
    r: float,
    q: float,
) -> np.ndarray:
    """Vectorized BS delta (NaN where vol is NaN)."""

    S = np.asarray(S, float)
    K = np.asarray(K, float)
    T = np.asarray(T, float)
    vol = np.asarray(vol, float)
    sqrtT = np.sqrt(np.maximum(T, 0.0))
    denom = np.where(vol * sqrtT > 0, vol * sqrtT, np.nan)
    d1 = (np.log(S / K) + (r - q + 0.5 * vol * vol) * T) / denom
    disc = np.exp(-q * T)
    call_delta = disc * _norm_cdf(d1)
    put_delta = disc * (_norm_cdf(d1) - 1.0)
    return np.where(np.asarray(is_call, bool), call_delta, put_delta)


# --------------------------------------------------------------------------- #
# Convenience surfaces per (ticker, trade_date)
# --------------------------------------------------------------------------- #
def _single_date(enriched: pd.DataFrame, trade_date: date | pd.Timestamp) -> pd.DataFrame:
    ts = pd.Timestamp(trade_date).normalize()
    return enriched[enriched["trade_date"].dt.normalize() == ts]


def _atm_iv_impl(
    enriched: pd.DataFrame,
    trade_date: date | pd.Timestamp,
    *,
    target_days: float,
    moneyness_window: float,
) -> tuple[float, pd.Timestamp | None]:
    """``(atm_iv, chosen_expiration)`` — the engine behind :func:`atm_iv`.

    Returns the chosen expiration too so :func:`term_structure` can require its
    near/far legs to come from *distinct* expirations (else the "slope" is a
    spurious 0). ``(nan, None)`` when no qualifying point exists.
    """

    day = _single_date(enriched, trade_date)
    day = day[np.isfinite(day["iv"])]
    if day.empty:
        return float("nan"), None

    near = day[np.abs(day["moneyness"] - 1.0) <= moneyness_window]
    pool = near if not near.empty else day
    # Expiry whose tenor (in days) is closest to target, among expiries with data.
    tenors = pool.assign(days=pool["tau"] * DAYS_PER_YEAR)
    grp = tenors.groupby("expiration")["days"].first()
    if grp.empty:
        return float("nan"), None
    chosen_exp = (grp - target_days).abs().idxmin()
    leg = tenors[tenors["expiration"] == chosen_exp]
    if leg.empty:
        return float("nan"), None

    # ANTI-WING-AVERAGE GUARD: if NO strike on the date landed inside the moneyness
    # window (near.empty -> pool is the whole chain), do NOT average the whole
    # smile of the chosen expiry — that returns a wing-average, not an ATM IV.
    # Restrict to the SINGLE strike nearest the money (its matched call+put).
    if near.empty:
        kbest = leg.iloc[int((leg["moneyness"] - 1.0).abs().to_numpy().argmin())]["strike"]
        leg = leg[leg["strike"] == kbest]
    return float(leg["iv"].mean()), pd.Timestamp(chosen_exp)


def atm_iv(
    enriched: pd.DataFrame,
    trade_date: date | pd.Timestamp,
    *,
    target_days: float = 30.0,
    moneyness_window: float = 0.05,
) -> float:
    """ATM implied vol at the tenor nearest ``target_days`` for one trade_date.

    Selection: among expirations on that date with valid (non-NaN) IV, pick the
    expiration whose day-count is closest to ``target_days``; within it, average
    the call and put IVs of the strikes inside ``moneyness_window`` of spot
    (|K/S - 1| <= window). If NO strike on the date is inside that window, fall
    back to the **single nearest-the-money strike** (never a smile-wide average).
    Returns NaN if no qualifying point exists. Reused by T23 (earnings IV crush)
    and as the level anchor for the term-structure and skew helpers.
    """

    iv, _ = _atm_iv_impl(
        enriched, trade_date, target_days=target_days, moneyness_window=moneyness_window
    )
    return iv


def iv_grid(
    enriched: pd.DataFrame,
    trade_date: date | pd.Timestamp,
) -> pd.DataFrame:
    """Full IV-by-(moneyness, tenor) grid for one trade_date (long/tidy form).

    Returns the valid-IV rows for that date with columns ``expiration, tau,
    tenor_days, strike, right, moneyness, log_moneyness, delta, iv`` — the raw
    material every downstream surface stat is computed from. Sorted by
    (expiration, strike, right).
    """

    day = _single_date(enriched, trade_date)
    day = day[np.isfinite(day["iv"])].copy()
    if day.empty:
        return pd.DataFrame(
            columns=[
                "expiration", "tau", "tenor_days", "strike", "right",
                "moneyness", "log_moneyness", "delta", "iv",
            ]
        )
    day["tenor_days"] = day["tau"] * DAYS_PER_YEAR
    cols = [
        "expiration", "tau", "tenor_days", "strike", "right",
        "moneyness", "log_moneyness", "delta", "iv",
    ]
    return day[cols].sort_values(["expiration", "strike", "right"]).reset_index(drop=True)


def risk_reversal_25d(
    enriched: pd.DataFrame,
    trade_date: date | pd.Timestamp,
    *,
    target_days: float = 30.0,
    target_delta: float = 0.25,
) -> float:
    """25-delta skew = IV(25-delta put) - IV(25-delta call) at the tenor near target_days.

    Positive means downside (put) vol richer than upside (call) vol — the normal
    equity skew. For each side we pick, within the chosen expiry, the contract
    whose |delta| is closest to ``target_delta`` (calls have +delta, puts -delta).
    Returns NaN if either 25Δ leg is missing. The decisive number for T24 (skew).
    """

    day = _single_date(enriched, trade_date)
    day = day[np.isfinite(day["iv"]) & np.isfinite(day["delta"])]
    if day.empty:
        return float("nan")

    tenors = day.assign(days=day["tau"] * DAYS_PER_YEAR)
    grp = tenors.groupby("expiration")["days"].first()
    if grp.empty:
        return float("nan")
    chosen_exp = (grp - target_days).abs().idxmin()
    leg = tenors[tenors["expiration"] == chosen_exp]

    calls = leg[leg["right"] == "C"]
    puts = leg[leg["right"] == "P"]
    if calls.empty or puts.empty:
        return float("nan")

    call_row = calls.iloc[(calls["delta"] - target_delta).abs().to_numpy().argmin()]
    put_row = puts.iloc[(puts["delta"] + target_delta).abs().to_numpy().argmin()]
    # Delta tolerance band: if the nearest available wing is not actually near the
    # target delta (e.g. only ~10Δ wings survived the IV filter on a thin chain),
    # returning its skew would mislabel a different-moneyness number as the 25Δ
    # risk reversal — and skew magnitude scales with how far out the wing is.
    # Require BOTH wings within DELTA_TOL of the target; else NaN (drop the date).
    if (
        abs(abs(float(call_row["delta"])) - target_delta) > DELTA_TOL
        or abs(abs(float(put_row["delta"])) - target_delta) > DELTA_TOL
    ):
        return float("nan")
    return float(put_row["iv"] - call_row["iv"])


def term_structure(
    enriched: pd.DataFrame,
    trade_date: date | pd.Timestamp,
    *,
    near_days: float = 30.0,
    far_days: float = 90.0,
    moneyness_window: float = 0.05,
) -> dict[str, float]:
    """ATM term structure: ATM IV near vs far, plus their difference (slope).

    Returns ``{"near_iv", "far_iv", "slope"}`` where ``slope = far_iv - near_iv``
    (positive = upward-sloping / contango of vol). Each leg reuses
    :func:`atm_iv`. NaNs propagate when a leg is unavailable. The T25 primitive.
    """

    near, near_exp = _atm_iv_impl(
        enriched, trade_date, target_days=near_days, moneyness_window=moneyness_window
    )
    far, far_exp = _atm_iv_impl(
        enriched, trade_date, target_days=far_days, moneyness_window=moneyness_window
    )
    # Distinct-expiration requirement: if both legs resolve to the SAME expiration
    # (e.g. only one expiry quoted on the date), near_iv == far_iv and the "slope"
    # is a spurious 0 — a fake "flat term structure" point. Return slope=NaN so the
    # date drops from the cohort instead of entering as a populated null.
    if near_exp is None or far_exp is None or near_exp == far_exp:
        return {"near_iv": near, "far_iv": far, "slope": float("nan")}
    return {"near_iv": near, "far_iv": far, "slope": far - near}


def surface_summary(
    enriched: pd.DataFrame,
    trade_date: date | pd.Timestamp,
    *,
    atm_target_days: float = 30.0,
    near_days: float = 30.0,
    far_days: float = 90.0,
) -> dict[str, float]:
    """One-call summary for a (ticker, trade_date): ATM30, 25Δ skew, term slope.

    Convenience aggregator the downstream tests call to get the headline numbers
    in a single dict: ``atm_iv_30d, skew_25d, ts_near_iv, ts_far_iv, ts_slope,
    n_valid_points``.
    """

    ts = term_structure(enriched, trade_date, near_days=near_days, far_days=far_days)
    day = _single_date(enriched, trade_date)
    n_valid = int(np.isfinite(day["iv"]).sum()) if not day.empty else 0
    return {
        "atm_iv_30d": atm_iv(enriched, trade_date, target_days=atm_target_days),
        "skew_25d": risk_reversal_25d(enriched, trade_date, target_days=atm_target_days),
        "ts_near_iv": ts["near_iv"],
        "ts_far_iv": ts["far_iv"],
        "ts_slope": ts["slope"],
        "n_valid_points": float(n_valid),
    }
