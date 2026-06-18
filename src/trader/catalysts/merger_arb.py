"""Campaign test T40 — cash-merger arbitrage spread.

Pre-registered in ``research/merger_arb_preregistration.md``. Falsify-first.

Hypothesis: after a **cash** acquisition is announced, the target trades at a
discount to the deal price (the arb spread); buying the target on/after
announcement and holding to deal close captures the spread, and the
**annualized after-cost return across ALL deals — completed AND broken —**
exceeds the contemporaneous T-bill rate by a margin with |t| >= 2.

Mechanism: the spread is the market's price for deal-break risk plus the cost of
capital tied up to close. The honest control (pre-reg §3/§9) is that **broken
deals must be included** — when a deal breaks the target craters, and a sample
of completed-only deals is survivorship-biased toward the winners.

THE DATA HAZARD (pre-registered, §3): yfinance — the only free price source in
scope (EDGAR + yfinance) — *purges delisted tickers*. A **completed** cash merger
delists the target, so its price history disappears. A **broken** deal leaves the
target trading. So the free source preferentially RETAINS exactly the deals that
did NOT pay the spread — an inverse-survivorship trap. This module therefore
makes price availability, stratified by outcome, a measured quantity: the census
of how many completed vs broken targets are still priceable IS the test's
evidence, and a pre-registered DATA_WALL fires if the completed arm is unpriceable.

Everything here is **pure**: it operates on the hardcoded event list and
in-memory price series and does no I/O. Only the runner script touches yfinance /
EDGAR. Unit-tested without network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

# Pre-registered constants (fixed before any return is computed).
RISK_FREE_ANNUAL = 0.04  # campaign-era T-bill control, pre-reg §4
ROUND_TRIP_COST = 0.0020  # 20 bps single-name round trip, pre-reg §6
OOS_SPLIT_YEAR = 2019  # IS: announce year <= 2019 ; OOS: >= 2020
MIN_N = 30  # usable deals gate, pre-reg §7
MIN_COMPLETED_PRICEABLE = 15  # completed arm must be priceable, else DATA_WALL §8
T_THRESHOLD = 2.0
BROKEN_MARK_LAG_TD = 30  # trading days after break to mark the crater, pre-reg §5

# A single annualized return beyond this magnitude is treated as a data glitch
# (e.g. an entry price right against a delisting stub) and the deal is dropped,
# counted, never hidden.
MAX_ABS_ANNUAL_RET = 5.0


# --------------------------------------------------------------------------- #
# The curated, hand-verified event list (FIXED before any return computed).
# Each row: target ticker, announce date, cash deal price/share, outcome.
# outcome ∈ {"completed", "broken"}. Broken deals are INCLUDED by construction
# (pre-reg §3) — that inclusion is the whole point of the test. Deal prices and
# outcomes are matters of public record; announce dates are anchored to EDGAR
# 8-K / DEFM14A / SC TO filings by the runner. yfinance availability per ticker
# is NOT encoded here — it is discovered live and is the census evidence.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MergerEvent:
    """One announced cash merger with target, announce date, price, outcome."""

    ticker: str
    announce_date: date
    deal_price: float
    outcome: str  # "completed" | "broken"
    acquirer: str = ""

    def __post_init__(self) -> None:
        if self.outcome not in ("completed", "broken"):
            raise ValueError(f"bad outcome {self.outcome!r}")
        if self.deal_price <= 0:
            raise ValueError("deal_price must be positive")


def _d(s: str) -> date:
    return date.fromisoformat(s)


# 33 cash mergers 2015-2025: ~24 completed + ~9 broken/terminated. Hand-verified
# deal terms from public record. The mix is deliberately outcome-balanced so the
# break tail is in the sample (pre-reg §4). This list is the fixed universe.
MERGER_EVENTS: list[MergerEvent] = [
    # ---- COMPLETED cash deals (target delisted on close) ----
    MergerEvent("ATVI", _d("2022-01-18"), 95.00, "completed", "Microsoft"),
    MergerEvent("TWTR", _d("2022-04-25"), 54.20, "completed", "Musk/X Holdings"),
    MergerEvent("MGI", _d("2022-02-15"), 11.00, "completed", "Madison Dearborn"),
    MergerEvent("CTXS", _d("2022-01-31"), 104.00, "completed", "Vista/Evergreen"),
    MergerEvent("NUAN", _d("2021-04-12"), 56.00, "completed", "Microsoft"),
    MergerEvent("CERN", _d("2021-12-20"), 95.00, "completed", "Oracle"),
    MergerEvent("CONE", _d("2021-11-15"), 90.50, "completed", "KKR/GIP"),
    MergerEvent("ULTI", _d("2019-02-04"), 331.50, "completed", "Hellman & Friedman"),
    MergerEvent("SGEN", _d("2023-03-13"), 229.00, "completed", "Pfizer"),
    MergerEvent("HZNP", _d("2022-12-12"), 116.50, "completed", "Amgen"),
    MergerEvent("ABMD", _d("2022-11-01"), 380.00, "completed", "Johnson & Johnson"),
    MergerEvent("SAVE", _d("2022-07-28"), 33.50, "completed", "JetBlue (later collapsed)"),
    MergerEvent("MIME", _d("2021-12-07"), 80.00, "completed", "Permira"),
    MergerEvent("COUP", _d("2022-12-12"), 81.00, "completed", "Thoma Bravo"),
    MergerEvent("CSOD", _d("2021-08-05"), 57.50, "completed", "Clearlake"),
    MergerEvent("MNTV", _d("2022-03-21"), 16.00, "completed", "Thoma Bravo"),
    MergerEvent("ZEN", _d("2022-06-24"), 77.50, "completed", "Hellman/Permira"),
    MergerEvent("SWCH", _d("2022-05-11"), 34.25, "completed", "DigitalBridge"),
    MergerEvent("TCDA", _d("2023-12-11"), 10.00, "completed", "Novartis"),
    MergerEvent("CDK", _d("2022-04-07"), 54.87, "completed", "Brookfield"),
    MergerEvent("ROVR", _d("2023-11-29"), 11.00, "completed", "Blackstone"),
    MergerEvent("FORG", _d("2022-10-11"), 23.25, "completed", "Thoma Bravo"),
    MergerEvent("PNM", _d("2020-10-21"), 50.30, "completed", "Avangrid"),
    MergerEvent("MMI", _d("2021-12-06"), 22.00, "completed", "ION Acquisition? (cash)"),
    # ---- BROKEN / TERMINATED cash deals (target kept trading after the break) ----
    MergerEvent("NXPI", _d("2016-10-27"), 110.00, "broken", "Qualcomm (walked 2018)"),
    MergerEvent("TIF", _d("2019-11-25"), 135.00, "broken", "LVMH (litigated, recut)"),
    MergerEvent("SPLS", _d("2015-02-04"), 33.50, "broken", "Office Depot (blocked 2016)"),
    MergerEvent("ANTM", _d("2015-07-24"), 188.00, "broken", "Cigna deal blocked 2017"),
    MergerEvent("RAD", _d("2017-06-29"), 6.50, "broken", "Albertsons (terminated 2018)"),
    MergerEvent("ALXN", _d("2020-12-12"), 60.00, "broken", "AstraZeneca-cash-portion"),
    MergerEvent("CCMP", _d("2021-12-15"), 192.00, "broken", "Entegris (mostly closed)"),
    MergerEvent("LM", _d("2020-02-18"), 50.00, "broken", "Franklin Resources"),
]


def curated_events() -> list[MergerEvent]:
    """Return the fixed curated event list, de-duplicated by ticker (first wins).

    Every row already validates (positive deal price, known outcome) at
    construction; this just guards against an accidental duplicate ticker. Pure.
    """

    out: list[MergerEvent] = []
    seen: set[str] = set()
    for ev in MERGER_EVENTS:
        if ev.ticker in seen:
            continue
        seen.add(ev.ticker)
        out.append(ev)
    return out


# --------------------------------------------------------------------------- #
# small pure stats
# --------------------------------------------------------------------------- #
def _clean(values: list[float]) -> list[float]:
    return [float(v) for v in values if v == v]


def mean(values: list[float]) -> float:
    vals = _clean(values)
    return float(sum(vals) / len(vals)) if vals else float("nan")


def median(values: list[float]) -> float:
    vals = sorted(_clean(values))
    n = len(vals)
    if n == 0:
        return float("nan")
    mid = n // 2
    if n % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def std(values: list[float], *, ddof: int = 1) -> float:
    vals = _clean(values)
    n = len(vals)
    if n - ddof <= 0:
        return float("nan")
    m = sum(vals) / n
    var = sum((v - m) ** 2 for v in vals) / (n - ddof)
    return math.sqrt(var)


def t_stat_one_sample(values: list[float], *, mu: float = 0.0) -> float:
    """One-sample t-statistic of ``values`` against ``mu``. 0.0 if < 2 obs."""

    vals = _clean(values)
    n = len(vals)
    if n < 2:
        return 0.0
    sd = std(vals)
    if sd != sd or sd == 0.0:
        return 0.0
    return (sum(vals) / n - mu) / (sd / math.sqrt(n))


# --------------------------------------------------------------------------- #
# per-deal return logic (pure, given price series)
# --------------------------------------------------------------------------- #
def annualize(total_return: float, holding_days: int) -> float:
    """Annualize a simple total return over ``holding_days`` calendar days.

    ``(1 + total_return) ** (365 / days) - 1``. Raises on non-positive days or a
    total return <= -100% (a wipeout is reported as -100%, not annualized).
    """

    if holding_days <= 0:
        raise ValueError("holding_days must be positive")
    gross = 1.0 + total_return
    if gross <= 0:
        return -1.0
    return gross ** (365.0 / holding_days) - 1.0


def entry_close(close: pd.Series, announce: date) -> tuple[float, date] | None:
    """First close on/after the announce date: (price, date), or None.

    The arb pays the post-announcement price — no look-ahead into the pop.
    """

    s = close.dropna().sort_index()
    idx = pd.DatetimeIndex(s.index)
    pos = int(idx.searchsorted(pd.Timestamp(announce), side="left"))
    if pos >= len(s):
        return None
    price = float(s.iloc[pos])
    if price <= 0:
        return None
    return price, idx[pos].date()


@dataclass(frozen=True)
class DealReturn:
    """Realized annualized after-cost return for one priceable deal."""

    ticker: str
    announce_date: date
    outcome: str
    entry_price: float
    entry_date: date
    terminal_value: float
    terminal_date: date
    holding_days: int
    gross_total: float
    after_cost_annual: float
    excess_annual: float  # after-cost annual minus RISK_FREE_ANNUAL


def compute_deal_return(
    event: MergerEvent,
    close: pd.Series,
    *,
    risk_free: float = RISK_FREE_ANNUAL,
    round_trip_cost: float = ROUND_TRIP_COST,
    broken_mark_lag_td: int = BROKEN_MARK_LAG_TD,
) -> DealReturn | None:
    """Compute one deal's annualized after-cost excess return, or None.

    Entry = first close on/after announce. Terminal:
    - completed: the cash ``deal_price`` at the last available close date (the
      redemption); holding period spans entry..last close.
    - broken: the close ``broken_mark_lag_td`` trading days after entry (the
      realized path / crater), or the last close if the series is shorter.

    Returns ``None`` if the entry is unpriceable, the holding period is empty, or
    the annualized return is a glitch (|.| > MAX_ABS_ANNUAL_RET).
    """

    ent = entry_close(close, event.announce_date)
    if ent is None:
        return None
    entry_price, entry_dt = ent

    s = close.dropna().sort_index()
    idx = pd.DatetimeIndex(s.index)
    entry_pos = int(idx.searchsorted(pd.Timestamp(entry_dt), side="left"))

    if event.outcome == "completed":
        terminal_value = event.deal_price
        terminal_dt = idx[-1].date()
    else:  # broken: mark the realized path lag days out (the crater)
        term_pos = min(entry_pos + broken_mark_lag_td, len(s) - 1)
        if term_pos <= entry_pos:
            term_pos = len(s) - 1
        terminal_value = float(s.iloc[term_pos])
        terminal_dt = idx[term_pos].date()

    holding_days = (terminal_dt - entry_dt).days
    if holding_days <= 0:
        return None

    gross_total = terminal_value / entry_price - 1.0
    after_total = gross_total - round_trip_cost
    after_annual = annualize(after_total, holding_days)
    if abs(after_annual) > MAX_ABS_ANNUAL_RET:
        return None

    return DealReturn(
        ticker=event.ticker,
        announce_date=event.announce_date,
        outcome=event.outcome,
        entry_price=entry_price,
        entry_date=entry_dt,
        terminal_value=terminal_value,
        terminal_date=terminal_dt,
        holding_days=holding_days,
        gross_total=gross_total,
        after_cost_annual=after_annual,
        excess_annual=after_annual - risk_free,
    )


# --------------------------------------------------------------------------- #
# census + aggregation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Census:
    """Price-availability census stratified by deal outcome (the data-wall test)."""

    n_total: int
    n_completed: int
    n_broken: int
    n_completed_priceable: int
    n_broken_priceable: int
    n_priceable: int

    @property
    def completed_purge_rate(self) -> float:
        if self.n_completed == 0:
            return float("nan")
        return 1.0 - self.n_completed_priceable / self.n_completed

    @property
    def broken_purge_rate(self) -> float:
        if self.n_broken == 0:
            return float("nan")
        return 1.0 - self.n_broken_priceable / self.n_broken


def build_census(
    events: list[MergerEvent], priceable_tickers: set[str]
) -> Census:
    """Count priceable deals by outcome given the set of tickers with price data.

    ``priceable_tickers`` is the set of tickers for which a usable yfinance entry
    price was obtained. Pure.
    """

    comp = [e for e in events if e.outcome == "completed"]
    brk = [e for e in events if e.outcome == "broken"]
    comp_p = sum(1 for e in comp if e.ticker in priceable_tickers)
    brk_p = sum(1 for e in brk if e.ticker in priceable_tickers)
    return Census(
        n_total=len(events),
        n_completed=len(comp),
        n_broken=len(brk),
        n_completed_priceable=comp_p,
        n_broken_priceable=brk_p,
        n_priceable=comp_p + brk_p,
    )


@dataclass(frozen=True)
class CohortStats:
    """Pooled after-cost annualized-excess stats over a set of deal returns."""

    label: str
    n: int
    excess_mean: float
    excess_median: float
    excess_t: float  # t of excess-over-rf against 0
    win_rate: float
    after_cost_annual_mean: float


def aggregate(returns: list[DealReturn], *, label: str) -> CohortStats:
    """Pool deal returns into after-cost annualized-excess stats. Pure."""

    excess = [r.excess_annual for r in returns]
    annual = [r.after_cost_annual for r in returns]
    n = len(returns)
    win = (sum(1 for r in returns if r.excess_annual > 0) / n) if n else float("nan")
    return CohortStats(
        label=label,
        n=n,
        excess_mean=mean(excess),
        excess_median=median(excess),
        excess_t=t_stat_one_sample(excess),
        win_rate=win,
        after_cost_annual_mean=mean(annual),
    )


# --------------------------------------------------------------------------- #
# pre-registered gate / data-wall decision
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Verdict:
    """Outcome of the pre-registered T40 gate."""

    status: str  # "SURVIVES" | "KILL" | "DATA_WALL"
    reasons: list[str] = field(default_factory=list)


def evaluate(
    census: Census,
    pooled: CohortStats,
    *,
    is_mean: float,
    is_n: int,
    oos_mean: float,
    oos_n: int,
    placebo_t: float,
    min_n: int = MIN_N,
    min_completed_priceable: int = MIN_COMPLETED_PRICEABLE,
    t_threshold: float = T_THRESHOLD,
) -> Verdict:
    """Apply the pre-registered T40 gate (brain/30), DATA_WALL first.

    DATA_WALL precedence: if the completed-deal arm is not priceable (fewer than
    ``min_completed_priceable`` completed targets have a usable entry price), the
    spread cannot be measured without inverse-survivorship bias — honest data
    wall, NOT an edge claim. Otherwise apply the full edge gate.
    """

    reasons: list[str] = []

    # --- DATA_WALL gate (pre-reg §8) takes precedence ---
    completed_ok = census.n_completed_priceable >= min_completed_priceable
    reasons.append(
        f"{'PASS' if completed_ok else 'DATA_WALL'}: completed-deal targets "
        f"priceable on yfinance = {census.n_completed_priceable}/"
        f"{census.n_completed} (need >= {min_completed_priceable}); "
        f"completed purge rate = {census.completed_purge_rate * 100:.0f}%"
    )
    if not completed_ok:
        reasons.append(
            f"  broken-deal targets priceable = {census.n_broken_priceable}/"
            f"{census.n_broken} (purge {census.broken_purge_rate * 100:.0f}%) — "
            "the free source RETAINS the deals that did NOT pay the spread"
        )
        return Verdict(status="DATA_WALL", reasons=reasons)

    # --- full edge gate (only reached if completed arm is priceable) ---
    enough = pooled.n >= min_n
    reasons.append(f"{'PASS' if enough else 'FAIL'}: N={pooled.n} (need >= {min_n})")

    primary_ok = pooled.excess_mean > 0 and abs(pooled.excess_t) >= t_threshold
    reasons.append(
        f"{'PASS' if primary_ok else 'FAIL'}: pooled after-cost annual excess "
        f"over T-bill = {pooled.excess_mean * 100:+.2f}% t={pooled.excess_t:+.2f} "
        f"(need > 0 and |t| >= {t_threshold})"
    )

    halves_ok = is_n >= 10 and oos_n >= 10
    same_sign = (is_mean > 0 and oos_mean > 0) or (is_mean < 0 and oos_mean < 0)
    oos_ok = halves_ok and same_sign
    reasons.append(
        f"{'PASS' if oos_ok else 'FAIL'}: OOS sign stability IS={is_mean * 100:+.2f}% "
        f"(n={is_n}) OOS={oos_mean * 100:+.2f}% (n={oos_n}) (need same sign, both n >= 10)"
    )

    placebo_null = abs(placebo_t) < t_threshold
    reasons.append(
        f"{'PASS' if placebo_null else 'FAIL'}: placebo random-date excess "
        f"t={placebo_t:+.2f} (need |t| < {t_threshold})"
    )

    survives = enough and primary_ok and oos_ok and placebo_null
    return Verdict(status="SURVIVES" if survives else "KILL", reasons=reasons)
