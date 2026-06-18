"""REAL discount-capture survival backtest for Saba CEF activist campaigns.

This replaces the *bounded estimate* in ``research/cef_survival_estimate.md`` with
an actual realized backtest. The estimate multiplied a resolution RATE by an
ASSUMED entry discount; here we buy the fund the trading day after the 13D and
hold to the **resolution date** (for resolved funds) or to a cap (for ongoing
funds), then measure realized excess return vs the broad-CEF benchmark (PCEF).

Why this needs Tiingo: the resolved "winners" delisted (liquidation / merger /
open-ending) and yfinance purges delisted symbols. The price provider tries
yfinance first and falls back to Tiingo, which retains delisted EOD — without it
the backtest is **survivorship-truncated upward** in the wrong direction (it
*drops* exactly the resolution payoffs the thesis is about). The runner says so
loudly when no Tiingo key is present.

NAV-free by construction: return is target-minus-PCEF, which nets out CEF-market
beta and broad discount moves without per-fund NAV. So this measures
**discount-capture excess over the CEF market**, not absolute return.

Holding-period semantics:

* ENTRY = first available trading day strictly after ``filing_date`` (t0+1).
* EXIT  = the resolution date for resolved campaigns; else ``min(today,
          t0 + max_hold_days)`` for ongoing ones (a censored, still-running hold).
* Excess = (exit/entry - 1) for the target MINUS the same for PCEF over the
  matched [entry, exit] window. Annualized by the realized holding-days.

The aggregation / t-stat machinery mirrors ``cef_study.py`` (WindowStat pattern)
so the two studies report comparably. Everything that touches *numbers* is a pure
function over price Series and is unit-tested on synthetic data; the only I/O is
the price-provider seam, which is injected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd
import structlog

log = structlog.get_logger()

DEFAULT_BENCHMARK = "PCEF"
DEFAULT_MAX_HOLD_DAYS = 730  # ~2.0yr cap for ongoing campaigns (median-to-resolution)
TRADING_DAYS_PER_YEAR = 252.0

# Fast-resolving sponsors (from cef_resolution_report.md §2): clean upside.
FAST_SPONSORS = frozenset({"Tortoise", "ClearBridge", "MFS", "Pioneer", "BlackRock"})
# Persistent foot-draggers — explicitly excluded from the tilt.
SLOW_SPONSORS = frozenset({"Invesco", "abrdn", "BNY Mellon"})


# --- Inputs ------------------------------------------------------------------


@dataclass(frozen=True)
class Campaign:
    """One Saba CEF campaign joined with its resolution outcome label.

    ``resolution_date`` is ``None`` for ongoing campaigns (we then cap the hold).
    ``resolved`` distinguishes a true terminal event from a censored hold.
    ``is_municipal`` and ``sponsor`` drive the basket tilt.
    """

    ticker: str
    name: str
    filing_date: date
    sponsor: str
    is_municipal: bool
    resolved: bool
    resolution_date: date | None


@dataclass(frozen=True)
class CampaignReturn:
    """Realized outcome for one campaign (or the reason it could not be priced)."""

    ticker: str
    entry_date: date
    exit_date: date
    holding_days: int
    target_return: float
    bench_return: float
    excess_return: float
    excess_annualized: float
    resolved: bool
    priced: bool
    note: str


@dataclass(frozen=True)
class BasketStat:
    """Aggregate excess-return stats for one basket (untilted / tilted)."""

    label: str
    n: int
    mean_excess: float
    median_excess: float
    mean_excess_annualized: float
    median_holding_years: float
    pct_positive: float
    t_stat: float


# --- Price provider seam -----------------------------------------------------


class PriceProvider(Protocol):
    """``ticker, start, end -> adj_close Series | None``.

    The production provider tries yfinance then Tiingo (see ``make_provider``);
    tests pass a dict-backed stub so the pure pipeline runs offline.
    """

    def __call__(self, ticker: str, start: date, end: date) -> pd.Series | None: ...


def make_provider() -> PriceProvider:
    """Build the real provider: yfinance first, Tiingo fallback for delisted.

    Best-effort and lazy — imports happen inside the closure so importing this
    module never requires network libraries. Returns adjusted closes.
    """

    def provider(ticker: str, start: date, end: date) -> pd.Series | None:
        from trader.catalysts import prices, tiingo

        yf = prices.fetch_daily(ticker, start, end)
        if yf is not None:
            close = yf[0]
            if close is not None and not close.empty:
                return close

        tg = tiingo.fetch_daily(ticker, start, end)
        if tg is not None:
            close = tg[0]
            if close is not None and not close.empty:
                log.info("survival_used_tiingo_fallback", ticker=ticker)
                return close

        log.warning("survival_no_price_data", ticker=ticker)
        return None

    return provider


# --- Pure return math --------------------------------------------------------


def _sorted(series: pd.Series) -> pd.Series:
    s = series.dropna().sort_index()
    s.index = pd.DatetimeIndex(s.index)
    return s


def _price_at_or_after(series: pd.Series, when: pd.Timestamp) -> tuple[pd.Timestamp, float] | None:
    """First (date, price) on or after ``when`` — the realistic fill for an entry."""

    idx = series.index
    pos = int(idx.searchsorted(when, side="left"))
    if pos >= len(idx):
        return None
    return idx[pos], float(series.iloc[pos])


def _price_at_or_before(series: pd.Series, when: pd.Timestamp) -> tuple[pd.Timestamp, float] | None:
    """Last (date, price) on or before ``when`` — the realistic fill for an exit.

    For a delisted fund the resolution date may fall after the last quote; we then
    take the final available price (the last mark before the fund left the tape).
    """

    idx = series.index
    pos = int(idx.searchsorted(when, side="right")) - 1
    if pos < 0:
        return None
    return idx[pos], float(series.iloc[pos])


def compute_campaign_return(
    target_close: pd.Series,
    bench_close: pd.Series,
    *,
    ticker: str,
    filing_date: date,
    resolved: bool,
    resolution_date: date | None,
    today: date,
    max_hold_days: int = DEFAULT_MAX_HOLD_DAYS,
) -> CampaignReturn | None:
    """PURE: realized excess discount-capture return for one campaign, or ``None``.

    ENTRY = first target trading day strictly after ``filing_date``. EXIT target
    date = ``resolution_date`` if resolved else ``min(today, filing + max_hold)``;
    the actual exit price is the last target quote on/before that date (handles
    delisting gaps). Benchmark return is measured over the **same realized
    [entry, exit] dates** so beta nets out. Returns ``None`` if prices are missing
    or the window is degenerate.
    """

    tgt = _sorted(target_close)
    if tgt.empty:
        return None
    bench = _sorted(bench_close)
    if bench.empty:
        return None

    entry_after = pd.Timestamp(filing_date) + pd.Timedelta(days=1)
    entry = _price_at_or_after(tgt, entry_after)
    if entry is None:
        return None
    entry_date, entry_px = entry
    if entry_px <= 0:
        return None

    if resolved and resolution_date is not None:
        target_exit = pd.Timestamp(resolution_date)
    else:
        capped = min(today, filing_date + pd.Timedelta(days=max_hold_days).to_pytimedelta())
        target_exit = pd.Timestamp(capped)

    exit_hit = _price_at_or_before(tgt, target_exit)
    if exit_hit is None:
        return None
    exit_date, exit_px = exit_hit
    if exit_date <= entry_date or exit_px <= 0:
        return None

    # Benchmark fills aligned to the SAME realized entry/exit dates.
    b_entry = _price_at_or_after(bench, entry_date)
    b_exit = _price_at_or_before(bench, exit_date)
    if b_entry is None or b_exit is None or b_entry[1] <= 0 or b_exit[1] <= 0:
        return None

    tgt_ret = exit_px / entry_px - 1.0
    bench_ret = b_exit[1] / b_entry[1] - 1.0
    excess = tgt_ret - bench_ret

    holding_days = int((exit_date - entry_date).days)
    years = max(holding_days / 365.25, 1e-9)
    # Annualize the EXCESS multiplicatively (geometric), guarding the base.
    base = 1.0 + excess
    excess_ann = (base ** (1.0 / years) - 1.0) if base > 0 else float("nan")

    return CampaignReturn(
        ticker=ticker,
        entry_date=entry_date.date(),
        exit_date=exit_date.date(),
        holding_days=holding_days,
        target_return=tgt_ret,
        bench_return=bench_ret,
        excess_return=excess,
        excess_annualized=excess_ann,
        resolved=resolved,
        priced=True,
        note="resolved" if resolved else "censored-cap",
    )


# --- Tilt / basket selection (pure) -----------------------------------------


def is_tilted(campaign: Campaign) -> bool:
    """Tilt rule from the resolution study: keep muni OR fast-sponsor names, and
    drop the persistent foot-draggers (Invesco / abrdn / BNY Mellon).

    A muni at a slow sponsor is still kept (muni is the strongest separator);
    only an equity name at a slow sponsor with no other reason is excluded.
    """

    if campaign.sponsor in SLOW_SPONSORS and not campaign.is_municipal:
        return False
    return campaign.is_municipal or campaign.sponsor in FAST_SPONSORS


# --- Aggregation (mirrors cef_study.WindowStat / t-stat) ---------------------


def _t_stat(values: list[float]) -> float:
    vals = [v for v in values if v == v]
    n = len(vals)
    if n < 2:
        return 0.0
    s = pd.Series(vals)
    sd = float(s.std(ddof=1))
    if sd == 0:
        return 0.0
    return float(s.mean() / (sd / math.sqrt(n)))


def aggregate_basket(returns: list[CampaignReturn], *, label: str) -> BasketStat:
    """Aggregate realized excess returns into one basket stat block."""

    excess = [r.excess_return for r in returns if r.priced and r.excess_return == r.excess_return]
    ann = [r.excess_annualized for r in returns if r.priced and r.excess_annualized == r.excess_annualized]
    hold_years = [r.holding_days / 365.25 for r in returns if r.priced]
    n = len(excess)
    if n == 0:
        return BasketStat(label, 0, float("nan"), float("nan"), float("nan"), float("nan"), float("nan"), 0.0)
    s = pd.Series(excess)
    return BasketStat(
        label=label,
        n=n,
        mean_excess=float(s.mean()),
        median_excess=float(s.median()),
        mean_excess_annualized=float(pd.Series(ann).mean()) if ann else float("nan"),
        median_holding_years=float(pd.Series(hold_years).median()) if hold_years else float("nan"),
        pct_positive=float((s > 0).mean()),
        t_stat=_t_stat(excess),
    )


# --- Backtest driver (uses the injected provider) ----------------------------


@dataclass(frozen=True)
class BacktestResult:
    untilted: BasketStat
    tilted: BasketStat
    per_campaign: list[CampaignReturn]
    n_campaigns: int
    n_priced: int
    n_resolved_priced: int


def run_backtest(
    campaigns: list[Campaign],
    provider: PriceProvider,
    *,
    benchmark: str = DEFAULT_BENCHMARK,
    today: date | None = None,
    max_hold_days: int = DEFAULT_MAX_HOLD_DAYS,
) -> BacktestResult:
    """Price every campaign + the benchmark, compute realized excess, aggregate.

    The benchmark series is fetched once over the full campaign span and reused.
    Campaigns that cannot be priced (no yfinance AND no Tiingo) are recorded with
    ``priced=False`` and excluded from the stats — the runner reports how many
    dropped, since dropping resolved names biases the result downward.
    """

    today = today or date.today()
    if not campaigns:
        empty = aggregate_basket([], label="empty")
        return BacktestResult(empty, empty, [], 0, 0, 0)

    span_start = min(c.filing_date for c in campaigns)
    span_end = today
    bench = provider(benchmark, span_start, span_end)
    if bench is None or bench.empty:
        log.warning("survival_no_benchmark", benchmark=benchmark)
        empty = aggregate_basket([], label="no-benchmark")
        return BacktestResult(empty, empty, [], len(campaigns), 0, 0)

    per_campaign: list[CampaignReturn] = []
    for c in campaigns:
        end_for_fetch = c.resolution_date or today
        # Pad the fetch window so entry/exit edges are covered.
        target = provider(c.ticker, c.filing_date, min(today, end_for_fetch + pd.Timedelta(days=10).to_pytimedelta()))
        if target is None or target.empty:
            per_campaign.append(
                CampaignReturn(
                    ticker=c.ticker,
                    entry_date=c.filing_date,
                    exit_date=c.filing_date,
                    holding_days=0,
                    target_return=float("nan"),
                    bench_return=float("nan"),
                    excess_return=float("nan"),
                    excess_annualized=float("nan"),
                    resolved=c.resolved,
                    priced=False,
                    note="no-price-data",
                )
            )
            continue

        r = compute_campaign_return(
            target,
            bench,
            ticker=c.ticker,
            filing_date=c.filing_date,
            resolved=c.resolved,
            resolution_date=c.resolution_date,
            today=today,
            max_hold_days=max_hold_days,
        )
        if r is None:
            per_campaign.append(
                CampaignReturn(
                    ticker=c.ticker,
                    entry_date=c.filing_date,
                    exit_date=c.filing_date,
                    holding_days=0,
                    target_return=float("nan"),
                    bench_return=float("nan"),
                    excess_return=float("nan"),
                    excess_annualized=float("nan"),
                    resolved=c.resolved,
                    priced=False,
                    note="window-degenerate",
                )
            )
            continue
        per_campaign.append(r)

    by_ticker = {c.ticker: c for c in campaigns}
    untilted_rets = [r for r in per_campaign if r.priced]
    tilted_rets = [r for r in per_campaign if r.priced and is_tilted(by_ticker[r.ticker])]

    n_priced = len(untilted_rets)
    n_resolved_priced = sum(1 for r in untilted_rets if r.resolved)

    return BacktestResult(
        untilted=aggregate_basket(untilted_rets, label="untilted"),
        tilted=aggregate_basket(tilted_rets, label="tilted (muni + fast-sponsor)"),
        per_campaign=per_campaign,
        n_campaigns=len(campaigns),
        n_priced=n_priced,
        n_resolved_priced=n_resolved_priced,
    )


# --- Pre-registered gate -----------------------------------------------------


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    result: BacktestResult,
    *,
    t_threshold: float = 2.0,
    min_priced: int = 20,
) -> GateVerdict:
    """Gate: realized TILTED excess > 0 with |t| >= 2, exceeding the untilted basket.

    This is the pre-registered success condition for the *tilt*: not just "is
    discount capture positive" but "does the muni+fast-sponsor selection beat the
    naive follow-everything basket, with a defensible t-stat." Requires enough
    priced names that the tilt isn't a 3-fund accident.
    """

    reasons: list[str] = []
    tilt = result.tilted
    base = result.untilted

    enough = result.n_priced >= min_priced
    reasons.append(f"{'PASS' if enough else 'FAIL'}: priced N={result.n_priced} (need >= {min_priced})")

    positive_sig = (tilt.mean_excess > 0) and (abs(tilt.t_stat) >= t_threshold)
    reasons.append(
        f"{'PASS' if positive_sig else 'FAIL'}: tilted excess mean={tilt.mean_excess:+.4f} "
        f"t={tilt.t_stat:+.2f} (need >0 & |t|>={t_threshold})"
    )

    beats_base = tilt.mean_excess > base.mean_excess
    reasons.append(
        f"{'PASS' if beats_base else 'FAIL'}: tilt beats untilted — tilted mean={tilt.mean_excess:+.4f} "
        f"vs untilted mean={base.mean_excess:+.4f}"
    )

    return GateVerdict(passed=enough and positive_sig and beats_base, reasons=reasons)
