"""Cross-exchange perp funding dispersion (T31) — pure core + OKX fetcher.

The T31 hypothesis: the SAME perpetual carries DIFFERENT realized funding on two
venues at the same 8h timestamp, and a market-neutral book (long the perp on the
LOW-funding venue, short on the HIGH-funding venue) harvests that DIFFERENCE with
no net crypto price exposure. This module supplies:

  * a survivorship-honest OKX public-funding fetcher (no auth, injectable HTTP
    seam mirroring ``crypto_data.HttpGetter`` so tests open no socket), and
  * a PURE, unit-testable measurement core: align two venues' funding on the 8h
    grid, compute the per-interval signed difference and harvestable ``|d|``,
    subtract the (fee-heavy, two-venue) round-trip cost, and run the gate.

### The load-bearing alignment detail

Binance's ``data.binance.vision`` archive stamps funding with sub-second jitter
(``00:00:00.005Z``); OKX stamps the exact 8h boundary. Both fund on the
00:00/08:00/16:00 UTC grid. :func:`floor_to_funding_hour` snaps both to the hour
so the inner join matches — without it ~60% of rows drop silently and the sample
is quietly halved.

### The decisive control

Cross-venue arb is fee-heavy: you pay taker fees on BOTH venues, each leg opened
AND closed = 4 taker fills per round trip. The honest question is not "is
dispersion nonzero?" (it always is) but "is ``mean(|d|)`` per interval larger
than the two-venue round-trip cost?" :func:`break_even_intervals` answers it.

OKX's public funding-rate-history endpoint only serves ~3 months (~283 rows),
which bounds the venue-pair overlap window — a documented depth wall, not a
modeling choice.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
import structlog

from trader.catalysts.crypto_data import HttpGetter, HttpResponse, _httpx_getter

log = structlog.get_logger()

OKX_FUNDING_URL = "https://www.okx.com/api/v5/public/funding-rate-history"

# Symbols fixed ex-ante in the pre-reg: liquid perps listed on BOTH venues whose
# ticker maps cleanly Binance ``SYMBOLUSDT`` <-> OKX ``SYMBOL-USDT-SWAP``.
CANDIDATE_BASES: tuple[str, ...] = (
    "BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "ADA", "AVAX", "LINK", "LTC",
    "DOT", "TRX", "BCH", "NEAR", "APT", "ARB", "OP", "MATIC", "ATOM", "FIL",
)


def binance_symbol(base: str) -> str:
    """PURE: base ticker -> Binance USDⓈ-M perp symbol (``BTC`` -> ``BTCUSDT``)."""

    return f"{base}USDT"


def okx_inst_id(base: str) -> str:
    """PURE: base ticker -> OKX USDT-SWAP instId (``BTC`` -> ``BTC-USDT-SWAP``)."""

    return f"{base}-USDT-SWAP"


# --------------------------------------------------------------------------- #
# PURE parse core
# --------------------------------------------------------------------------- #
def parse_okx_funding(body: str, base: str) -> pd.Series | None:
    """PURE: an OKX funding-rate-history JSON body -> per-interval funding Series.

    OKX returns ``{"code":"0","data":[{"fundingTime":ms,"realizedRate":...,
    "fundingRate":...}, ...]}``. We use ``realizedRate`` (the rate actually
    paid at that interval); if absent we fall back to ``fundingRate``. Output is
    indexed by UTC interval-close timestamp, ascending, named ``base+"USDT"`` to
    match the Binance symbol convention. Per-interval (NOT annualized). Malformed
    / empty / non-zero-code bodies yield ``None``.
    """

    if not body:
        return None
    try:
        obj = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, Mapping) or obj.get("code") not in ("0", 0):
        return None
    rows = obj.get("data")
    if not isinstance(rows, list) or not rows:
        return None
    times: list[pd.Timestamp] = []
    rates: list[float] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        raw_t = r.get("fundingTime")
        raw_r = r.get("realizedRate")
        if raw_r in (None, ""):
            raw_r = r.get("fundingRate")
        try:
            ms = int(float(raw_t))
            rate = float(raw_r)
        except (TypeError, ValueError):
            continue
        if rate != rate:  # NaN guard
            continue
        times.append(pd.Timestamp(ms, unit="ms", tz="UTC"))
        rates.append(rate)
    if not rates:
        return None
    s = pd.Series(rates, index=pd.DatetimeIndex(times), name=binance_symbol(base))
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s if not s.empty else None


def floor_to_funding_hour(s: pd.Series) -> pd.Series:
    """PURE: snap a funding Series' index to the hour (kills sub-second jitter).

    Binance archive stamps carry ms jitter (``00:00:00.005``); flooring to the
    hour makes the two venues' 8h-grid timestamps join. Duplicates after flooring
    keep the last (defensive; the grid is 8h so collisions are not expected).
    """

    idx = s.index.floor("h")
    out = pd.Series(s.to_numpy(), index=idx, name=s.name)
    return out[~out.index.duplicated(keep="last")].sort_index()


# --------------------------------------------------------------------------- #
# Dispersion measurement
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DispersionPanel:
    """Per-(symbol, timestamp) aligned funding from two venues + the difference.

    ``long_format`` is a tidy DataFrame with columns ``[symbol, ts, venue_a,
    venue_b, diff, abs_diff]`` where ``diff = venue_a - venue_b`` and the
    market-neutral book harvests ``abs_diff`` (always receive the high venue, pay
    the low venue). ``n_obs`` is the row count; ``n_symbols`` / ``n_timestamps``
    the distinct counts. All per-interval (8h), NOT annualized.
    """

    long_format: pd.DataFrame
    venue_a: str
    venue_b: str

    @property
    def n_obs(self) -> int:
        return len(self.long_format)

    @property
    def n_symbols(self) -> int:
        return int(self.long_format["symbol"].nunique()) if self.n_obs else 0

    @property
    def n_timestamps(self) -> int:
        return int(self.long_format["ts"].nunique()) if self.n_obs else 0


def build_dispersion_panel(
    venue_a_funding: Mapping[str, pd.Series],
    venue_b_funding: Mapping[str, pd.Series],
    *,
    venue_a: str = "binance",
    venue_b: str = "okx",
) -> DispersionPanel:
    """PURE: align two venues' funding maps on (symbol, 8h timestamp).

    Inputs are ``{symbol -> per-interval funding Series}`` for each venue. For
    every symbol present in BOTH maps, both Series are floored to the funding
    hour (:func:`floor_to_funding_hour`) and inner-joined on timestamp. The
    result is a tidy long-format panel; symbols absent from either venue, or with
    no overlapping timestamps, contribute nothing (this is the both-venues-alive
    survivorship intersection).
    """

    frames: list[pd.DataFrame] = []
    common = sorted(set(venue_a_funding) & set(venue_b_funding))
    for sym in common:
        a = floor_to_funding_hour(venue_a_funding[sym])
        b = floor_to_funding_hour(venue_b_funding[sym])
        joined = pd.concat({"venue_a": a, "venue_b": b}, axis=1).dropna()
        if joined.empty:
            continue
        joined = joined.reset_index().rename(columns={"index": "ts"})
        if "ts" not in joined.columns:
            joined = joined.rename(columns={joined.columns[0]: "ts"})
        joined.insert(0, "symbol", sym)
        frames.append(joined)
    if not frames:
        empty = pd.DataFrame(
            columns=["symbol", "ts", "venue_a", "venue_b", "diff", "abs_diff"]
        )
        return DispersionPanel(empty, venue_a, venue_b)
    panel = pd.concat(frames, ignore_index=True)
    panel["diff"] = panel["venue_a"] - panel["venue_b"]
    panel["abs_diff"] = panel["diff"].abs()
    panel = panel.sort_values(["ts", "symbol"]).reset_index(drop=True)
    return DispersionPanel(panel, venue_a, venue_b)


# --------------------------------------------------------------------------- #
# Cost model + harvest
# --------------------------------------------------------------------------- #
def round_trip_cost(leg_fee_bps: float, *, n_legs: int = 2) -> float:
    """PURE: two-venue round-trip taker cost as a fraction.

    A matched cross-venue position has ``n_legs`` legs (Binance + OKX = 2), each
    opened AND closed -> ``2 * n_legs`` taker fills. Returns the cost as a decimal
    fraction (e.g. ``leg_fee_bps=5, n_legs=2`` -> ``4 * 0.0005 = 0.0020`` = 20 bps).
    """

    return 2.0 * n_legs * (leg_fee_bps / 1e4)


def break_even_intervals(mean_abs_diff: float, rt_cost: float) -> float:
    """PURE: how many 8h intervals of harvest pay for one round trip.

    ``rt_cost / mean(|d|)``. If you must hold for many intervals (days/weeks) to
    cover a single round trip, basis drift and two-venue margin risk over that
    hold dominate -> dead on arrival. ``inf`` if there is no positive dispersion.
    """

    if mean_abs_diff <= 0:
        return float("inf")
    return rt_cost / mean_abs_diff


@dataclass(frozen=True)
class HarvestStats:
    """Aggregate per-interval harvest stats for the cross-venue book.

    ``mean_abs_diff`` is the gross per-interval dispersion harvested (always
    receive the high venue). ``after_cost_*`` amortize the round-trip cost over an
    assumed holding period of ``hold_intervals`` 8h intervals. ``t`` is on the
    portfolio's per-timestamp mean ``|d|`` series (cross-sectional mean per
    timestamp), so the N is the number of timestamps, not raw obs.
    """

    n_obs: int
    n_timestamps: int
    mean_abs_diff: float
    mean_signed_diff: float
    t_gross: float
    rt_cost: float
    hold_intervals: int
    after_cost_mean: float
    t_after_cost: float
    break_even_intervals: float
    win_rate: float


def _portfolio_series(panel: pd.DataFrame, col: str) -> pd.Series:
    """PURE: cross-sectional mean of ``col`` per timestamp (the book's per-step ret)."""

    if panel.empty:
        return pd.Series(dtype=float)
    return panel.groupby("ts")[col].mean().sort_index()


def harvest_stats(
    panel: DispersionPanel,
    *,
    leg_fee_bps: float = 5.0,
    hold_intervals: int = 21,
) -> HarvestStats:
    """PURE: aggregate the cross-venue funding harvest, gross and after-cost.

    The portfolio per interval is the cross-sectional mean ``|d|`` over symbols
    available at that timestamp. The round-trip cost (two venues, 4 taker fills)
    is amortized over ``hold_intervals`` 8h intervals (default 21 ~= 1 week) and
    subtracted per interval. The PRIMARY metric is ``after_cost_mean`` and its
    t-stat. ``break_even_intervals`` is the window-independent kill control.
    """

    df = panel.long_format
    rt = round_trip_cost(leg_fee_bps)
    if df.empty:
        return HarvestStats(0, 0, 0.0, 0.0, 0.0, rt, hold_intervals, 0.0, 0.0,
                            float("inf"), 0.0)
    abs_port = _portfolio_series(df, "abs_diff")
    signed_port = _portfolio_series(df, "diff")
    mean_abs = float(abs_port.mean())
    per_interval_cost = rt / max(hold_intervals, 1)
    after = abs_port - per_interval_cost
    return HarvestStats(
        n_obs=len(df),
        n_timestamps=len(abs_port),
        mean_abs_diff=mean_abs,
        mean_signed_diff=float(signed_port.mean()),
        t_gross=_tstat(abs_port),
        rt_cost=rt,
        hold_intervals=hold_intervals,
        after_cost_mean=float(after.mean()),
        t_after_cost=_tstat(after),
        break_even_intervals=break_even_intervals(mean_abs, rt),
        win_rate=float((after > 0).mean()),
    )


def _tstat(s: pd.Series) -> float:
    """PURE: one-sample t-stat of a series mean vs 0 (0.0 if degenerate)."""

    x = s.dropna().to_numpy()
    if x.size < 2:
        return 0.0
    sd = x.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(x.mean() / (sd / np.sqrt(x.size)))


# --------------------------------------------------------------------------- #
# Placebo (venue-label shuffle) + IS/OOS
# --------------------------------------------------------------------------- #
def venue_shuffle_signed_mean(panel: DispersionPanel, *, seed: int) -> float:
    """PURE: mean SIGNED diff after randomly flipping which venue is A vs B.

    Randomly negates each row's ``diff`` (== swapping venue labels) under a fixed
    seed. A real, sign-stable directional dispersion would survive a signed read;
    a placebo that destroys the venue pairing collapses the signed mean toward 0.
    (``|d|`` is sign-invariant, so the placebo targets the SIGNED variant.)
    """

    df = panel.long_format
    if df.empty:
        return 0.0
    rng = np.random.default_rng(seed)
    flips = rng.choice([-1.0, 1.0], size=len(df))
    shuffled = df["diff"].to_numpy() * flips
    return float(np.mean(shuffled))


def split_is_oos(panel: DispersionPanel, oos_start: str) -> tuple[DispersionPanel, DispersionPanel]:
    """PURE: split the panel into IS (< oos_start) and OOS (>= oos_start) by ts."""

    df = panel.long_format
    if df.empty:
        return panel, panel
    cut = pd.Timestamp(oos_start, tz="UTC")
    is_df = df[df["ts"] < cut].reset_index(drop=True)
    oos_df = df[df["ts"] >= cut].reset_index(drop=True)
    return (
        DispersionPanel(is_df, panel.venue_a, panel.venue_b),
        DispersionPanel(oos_df, panel.venue_a, panel.venue_b),
    )


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    full: HarvestStats,
    is_stats: HarvestStats,
    oos_stats: HarvestStats,
    placebo_signed_mean: float,
    *,
    min_n: int = 30,
    min_t: float = 2.0,
    max_breakeven_intervals: float = 21.0,
) -> GateResult:
    """PURE: apply the pre-registered T31 gate. ALL checks must pass.

    Checks (from the pre-reg / brain/30): N>=30 matched timestamps; after-cost
    |t|>=2 AND after-cost mean>0; the DECISIVE dispersion>cost control
    (break-even hold <= ~1 week of intervals); OOS sign stability with both
    halves N>=10; placebo (venue-shuffle) collapses the signed mean. Returns a
    verdict and a human-readable reason per check.
    """

    reasons: list[str] = []
    ok = True

    if full.n_timestamps >= min_n:
        reasons.append(f"PASS N: {full.n_timestamps} timestamps >= {min_n}")
    else:
        ok = False
        reasons.append(f"FAIL N: {full.n_timestamps} timestamps < {min_n}")

    if full.after_cost_mean > 0 and abs(full.t_after_cost) >= min_t:
        reasons.append(
            f"PASS after-cost: mean={full.after_cost_mean:+.2e} t={full.t_after_cost:+.2f}"
        )
    else:
        ok = False
        reasons.append(
            f"FAIL after-cost: mean={full.after_cost_mean:+.2e} t={full.t_after_cost:+.2f} "
            f"(need mean>0 and |t|>={min_t})"
        )

    if full.break_even_intervals <= max_breakeven_intervals:
        reasons.append(
            f"PASS dispersion>cost: break-even {full.break_even_intervals:.1f} intervals "
            f"<= {max_breakeven_intervals:.0f}"
        )
    else:
        ok = False
        reasons.append(
            f"FAIL dispersion>cost: break-even {full.break_even_intervals:.1f} intervals "
            f"> {max_breakeven_intervals:.0f} (mean|d|={full.mean_abs_diff:.2e} vs "
            f"round-trip {full.rt_cost:.4f}) -> DEAD ON ARRIVAL after two-venue fees"
        )

    is_sign = np.sign(is_stats.mean_signed_diff)
    oos_sign = np.sign(oos_stats.mean_signed_diff)
    if (
        is_stats.n_timestamps >= 10
        and oos_stats.n_timestamps >= 10
        and is_sign == oos_sign
        and is_sign != 0
    ):
        reasons.append(
            f"PASS OOS sign: IS={is_stats.mean_signed_diff:+.2e}(n={is_stats.n_timestamps}) "
            f"OOS={oos_stats.mean_signed_diff:+.2e}(n={oos_stats.n_timestamps})"
        )
    else:
        ok = False
        reasons.append(
            f"FAIL OOS sign: IS={is_stats.mean_signed_diff:+.2e}(n={is_stats.n_timestamps}) "
            f"OOS={oos_stats.mean_signed_diff:+.2e}(n={oos_stats.n_timestamps})"
        )

    # Placebo: the venue-shuffle should collapse the SIGNED mean toward ~0 relative
    # to the real signed dispersion. If the real signed mean is itself ~0 there is
    # no directional edge for the placebo to break (it informs, not gates here).
    if abs(placebo_signed_mean) < abs(full.mean_signed_diff):
        reasons.append(
            f"PASS placebo: shuffle signed mean {placebo_signed_mean:+.2e} "
            f"< real {full.mean_signed_diff:+.2e}"
        )
    else:
        ok = False
        reasons.append(
            f"FAIL placebo: shuffle signed mean {placebo_signed_mean:+.2e} "
            f">= real {full.mean_signed_diff:+.2e} (no stable directional dispersion)"
        )

    return GateResult(passed=ok, reasons=reasons)


# --------------------------------------------------------------------------- #
# Thin OKX fetcher (best-effort, never raises; injectable seam)
# --------------------------------------------------------------------------- #
def fetch_okx_funding_history(
    base: str,
    *,
    max_pages: int = 8,
    http_get: HttpGetter | None = None,
) -> pd.Series | None:
    """Fetch OKX public funding history for ``base`` (paginated, best-effort).

    OKX's ``funding-rate-history`` returns newest-first pages of up to 100 rows;
    the ``after`` cursor (a fundingTime ms) fetches records OLDER than it. We page
    until an empty page or ``max_pages``. The public endpoint serves only ~3
    months total (a documented depth wall). Returns the per-interval funding
    Series (named ``base+"USDT"``) or ``None`` on any failure. Never raises.
    """

    getter = http_get or _httpx_getter
    inst = okx_inst_id(base)
    parts: list[pd.Series] = []
    after: str | None = None
    for _ in range(max_pages):
        params = {"instId": inst, "limit": "100"}
        if after is not None:
            params["after"] = after
        try:
            resp = getter(OKX_FUNDING_URL, params=params)
        except Exception as exc:
            log.warning("okx_funding_failed", base=base, error=str(exc))
            break
        if not isinstance(resp, HttpResponse) or resp.status_code != 200:
            status = getattr(resp, "status_code", "n/a")
            log.warning("okx_funding_bad_status", base=base, status=status)
            break
        s = parse_okx_funding(resp.text, base)
        if s is None or s.empty:
            break
        parts.append(s)
        # Oldest fundingTime on this page becomes the next `after` cursor.
        oldest_ms = int(s.index.min().timestamp() * 1000)
        next_after = str(oldest_ms)
        if next_after == after:  # no progress -> stop
            break
        after = next_after
        if len(s) < 100:  # last (short) page
            break
    if not parts:
        return None
    out = pd.concat(parts)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.name = binance_symbol(base)
    return out
