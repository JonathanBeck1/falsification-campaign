"""Campaign test T23 — single-name earnings IV crush (short straddle).

Pre-registered in ``research/earnings_iv_crush_preregistration.md``. Falsify-first.

Hypothesis: selling a name's ~ATM straddle at the close **before** scheduled
earnings and buying it back at the close **after** earns a positive after-cost
P&L, because pre-earnings ATM implied vol systematically *overstates* the
realized overnight move (the priced straddle exceeds the realized |gap| on
average). Mechanism: event-vol risk premium. The honest controls (lessons from
T43/T19): (a) is the premium just compensation for jump variance — does it
survive once the fat left tail lands in-sample? and (b) does it exceed the
ordinary non-earnings one-day short-straddle carry (placebo)?

**Spot provenance (decided at pre-reg).** The lake's ``underlying_close`` is NULL
and the foundation's yfinance fallback returns *split-adjusted* closes that do
not match the lake's *as-of-trade-date* (unadjusted) strikes for names that split
after the trade date — putting "ATM" on a deep-ITM strike and producing absurd
IVs. We therefore anchor spot from the option chain itself via **put-call
parity** on the front expiration (``parity_spot``): self-consistent with the
strikes, no external series. The straddle P&L is computed from the actual option
**bid/ask** (sell at bid on entry, buy at ask on exit), so a few-cents spot error
only affects which strike is "ATM", not the P&L.

Everything here is **pure**: it operates on in-memory chain frames and does no
I/O. Only the runner (``scripts/run_earnings_iv_crush_study.py``) touches the
lake and yfinance earnings dates. Unit-tested on synthetic chains.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

# Minimum calendar days to expiry on the entry close for the front straddle:
# avoids 0-DTE pin artifacts while staying short-tenor enough to be earnings-
# dominated. Pre-registered (sec.4).
MIN_FRONT_DAYS = 5

# Per-straddle commission: $0.65/leg x 2 legs x 2 (open+close) = $2.60, charged
# as a fraction of (spot * 100) per event. Pre-registered (sec.6).
COMMISSION_PER_STRADDLE = 2.60
CONTRACT_MULTIPLIER = 100.0

# A single-event short-straddle return beyond this magnitude (in spot units) is
# treated as a data glitch (a chain mispricing) and the event is dropped, counted.
MAX_ABS_EVENT_RETURN = 2.0

# Hour-of-day (US/Eastern) at/after which earnings is treated as after-close
# (AMC -> priced next session). Mirrors earnings_premium.is_amc.
AMC_HOUR_ET = 13


# --------------------------------------------------------------------------- #
# small pure stats (mirrors earnings_premium; kept local so this module stands
# alone and is independently unit-tested)
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


def t_stat_one_sample(values: list[float]) -> float:
    """One-sample t against 0 (mean / SE). 0.0 if < 2 usable obs."""

    vals = _clean(values)
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    sd = std(vals)
    # Treat std that is NaN, exactly zero, or negligible relative to the level as
    # "no dispersion" so a numerically-tiny residual (e.g. a constant series whose
    # float sum leaves ~1e-17 variance) does not explode the t-stat.
    if sd != sd or sd <= 1e-12 * (abs(m) + 1.0):
        return 0.0
    return m / (sd / math.sqrt(n))


def welch_t(a: list[float], b: list[float]) -> float:
    """Welch (unequal-variance) two-sample t for ``mean(a) - mean(b)``.

    Positive => a's mean exceeds b's. 0.0 if either side has < 2 usable obs.
    """

    va, vb = _clean(a), _clean(b)
    na, nb = len(va), len(vb)
    if na < 2 or nb < 2:
        return 0.0
    ma, mb = sum(va) / na, sum(vb) / nb
    sa2 = sum((x - ma) ** 2 for x in va) / (na - 1)
    sb2 = sum((x - mb) ** 2 for x in vb) / (nb - 1)
    denom = math.sqrt(sa2 / na + sb2 / nb)
    if denom == 0.0:
        return 0.0
    return (ma - mb) / denom


def pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation of paired (xs, ys); NaN if < 2 pairs or zero variance."""

    pairs = [(float(x), float(y)) for x, y in zip(xs, ys, strict=True) if x == x and y == y]
    if len(pairs) < 2:
        return float("nan")
    px = [p[0] for p in pairs]
    py = [p[1] for p in pairs]
    mx, my = mean(px), mean(py)
    sx, sy = std(px), std(py)
    if sx == 0 or sy == 0 or sx != sx or sy != sy:
        return float("nan")
    cov = sum((x - mx) * (y - my) for x, y in pairs) / (len(pairs) - 1)
    return cov / (sx * sy)


def is_amc(hour_et: int | None) -> bool:
    """True if earnings at ``hour_et`` (US/Eastern, or None) is after-close.

    AMC means the market prices it the NEXT session. Missing time -> AMC.
    """

    if hour_et is None:
        return True
    return int(hour_et) >= AMC_HOUR_ET


# --------------------------------------------------------------------------- #
# Spot anchoring via put-call parity (the provenance-clean ATM detector)
# --------------------------------------------------------------------------- #
def _two_sided(chain: pd.DataFrame) -> pd.DataFrame:
    """Rows with a genuine two-sided quote and a mid; adds ``mid`` column. Pure."""

    c = chain.copy()
    c["bid"] = pd.to_numeric(c["bid"], errors="coerce")
    c["ask"] = pd.to_numeric(c["ask"], errors="coerce")
    c["strike"] = pd.to_numeric(c["strike"], errors="coerce")
    c["right"] = c["right"].astype(str).str.upper().str[0]
    c = c[(c["bid"] > 0) & (c["ask"] > 0)]
    c = c.assign(mid=(c["bid"] + c["ask"]) / 2.0)
    c = c[c["mid"] > 0]
    return c[c["right"].isin(("C", "P"))]


def parity_spot(chain_for_expiry: pd.DataFrame) -> float:
    """Put-call-parity-implied spot from one expiration's two-sided quotes.

    For each strike with both a call and put mid, S ≈ K + (C - P) (small-rT,
    no-dividend approximation). The estimate is taken at the strike where |C - P|
    is smallest (deepest ATM, least parity noise), which is the most reliable
    anchor. Returns NaN if no call/put strike pair exists. PURE.
    """

    c = _two_sided(chain_for_expiry)
    if c.empty:
        return float("nan")
    calls = c[c["right"] == "C"][["strike", "mid"]].rename(columns={"mid": "cmid"})
    puts = c[c["right"] == "P"][["strike", "mid"]].rename(columns={"mid": "pmid"})
    merged = calls.merge(puts, on="strike", how="inner")
    if merged.empty:
        return float("nan")
    diff = (merged["cmid"] - merged["pmid"]).abs()
    k_idx = diff.to_numpy().argmin()
    row = merged.iloc[k_idx]
    return float(row["strike"] + (row["cmid"] - row["pmid"]))


def select_front_expiration(
    chain: pd.DataFrame,
    trade_date: date | pd.Timestamp,
    *,
    min_days: int = MIN_FRONT_DAYS,
) -> pd.Timestamp | None:
    """Nearest expiration with >= ``min_days`` calendar days to expiry on ``trade_date``.

    Returns the chosen ``expiration`` Timestamp, or None if none qualifies. PURE.
    """

    td = pd.Timestamp(trade_date).normalize()
    exps = pd.to_datetime(chain["expiration"]).dt.normalize().unique()
    qualifying = sorted(e for e in exps if (e - td).days >= min_days)
    return pd.Timestamp(qualifying[0]) if qualifying else None


def atm_strike(chain_for_expiry: pd.DataFrame, spot: float) -> float | None:
    """Strike nearest ``spot`` that carries BOTH a two-sided call and put. PURE."""

    c = _two_sided(chain_for_expiry)
    if c.empty or math.isnan(spot) or spot <= 0:
        return None
    both = c.groupby("strike")["right"].nunique()
    strikes = both[both >= 2].index.to_numpy(dtype=float)
    if strikes.size == 0:
        return None
    return float(strikes[(abs(strikes - spot)).argmin()])


# --------------------------------------------------------------------------- #
# Straddle pricing (honest bid/ask crossing)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StraddleQuote:
    """One ATM straddle's two-sided legs at a single close."""

    expiration: pd.Timestamp
    strike: float
    spot: float
    call_bid: float
    call_ask: float
    put_bid: float
    put_ask: float

    @property
    def mid(self) -> float:
        return (self.call_bid + self.call_ask + self.put_bid + self.put_ask) / 2.0

    @property
    def sell_proceeds(self) -> float:
        """Cash received selling the straddle to the bid (liquidity taker)."""

        return self.call_bid + self.put_bid

    @property
    def buy_cost(self) -> float:
        """Cash paid buying the straddle back at the ask (liquidity taker)."""

        return self.call_ask + self.put_ask

    @property
    def priced_move(self) -> float:
        """Straddle mid / spot — the breakeven |move| the seller is paid for."""

        return self.mid / self.spot if self.spot > 0 else float("nan")


def straddle_quote(
    chain_for_expiry: pd.DataFrame,
    strike: float,
    spot: float,
    expiration: pd.Timestamp,
) -> StraddleQuote | None:
    """Build the ATM :class:`StraddleQuote` at ``strike`` from two-sided quotes.

    Returns None if either the call or put leg lacks a two-sided quote. PURE.
    """

    c = _two_sided(chain_for_expiry)
    leg_c = c[(c["strike"] == strike) & (c["right"] == "C")]
    leg_p = c[(c["strike"] == strike) & (c["right"] == "P")]
    if leg_c.empty or leg_p.empty:
        return None
    cc = leg_c.iloc[0]
    pp = leg_p.iloc[0]
    return StraddleQuote(
        expiration=pd.Timestamp(expiration),
        strike=float(strike),
        spot=float(spot),
        call_bid=float(cc["bid"]),
        call_ask=float(cc["ask"]),
        put_bid=float(pp["bid"]),
        put_ask=float(pp["ask"]),
    )


# --------------------------------------------------------------------------- #
# One earnings event's short-straddle P&L
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CrushEvent:
    """One earnings event's short-straddle round trip (enter pre-, exit post-)."""

    ticker: str
    earnings_date: date
    entry_date: date
    exit_date: date
    expiration: pd.Timestamp
    strike: float
    pre_spot: float
    post_spot: float
    priced_move: float  # entry straddle mid / pre_spot
    realized_move: float  # |post_spot/pre_spot - 1|
    entry_proceeds: float  # cash received selling straddle (bid)
    exit_cost: float  # cash paid buying it back (ask)
    after_cost_return: float  # short-straddle P&L / pre_spot (commission-charged)
    mid_to_mid_return: float  # context-only: (entry_mid - exit_mid)/pre_spot

    @property
    def crush_gap(self) -> float:
        """priced_move - realized_move (positive => IV overstated the move)."""

        return self.priced_move - self.realized_move


def compute_crush_event(
    *,
    ticker: str,
    earnings_date: date,
    entry_chain: pd.DataFrame,
    exit_chain: pd.DataFrame,
    entry_date: date,
    exit_date: date,
    min_front_days: int = MIN_FRONT_DAYS,
    commission_per_straddle: float = COMMISSION_PER_STRADDLE,
) -> CrushEvent | None:
    """Compute one earnings short-straddle round trip from entry/exit chains.

    Selection (all pre-registered):
    - front expiration on ``entry_date`` with >= ``min_front_days`` days, that
      also exists in ``exit_chain`` (so we can mark the exit);
    - parity-implied spot on each close;
    - ATM strike nearest the entry parity spot carrying both legs.

    P&L (short straddle, honest fills): sell at bid on entry, buy back at ask on
    exit, minus commission; expressed as a fraction of entry spot. Returns None
    if any required quote is missing or the event return is a glitch. PURE.
    """

    if entry_chain.empty or exit_chain.empty:
        return None

    expiration = select_front_expiration(entry_chain, entry_date, min_days=min_front_days)
    if expiration is None:
        return None

    entry_exp = entry_chain[pd.to_datetime(entry_chain["expiration"]).dt.normalize() == expiration]
    exit_exp = exit_chain[pd.to_datetime(exit_chain["expiration"]).dt.normalize() == expiration]
    if entry_exp.empty or exit_exp.empty:
        return None

    pre_spot = parity_spot(entry_exp)
    post_spot = parity_spot(exit_exp)
    if math.isnan(pre_spot) or math.isnan(post_spot) or pre_spot <= 0 or post_spot <= 0:
        return None

    strike = atm_strike(entry_exp, pre_spot)
    if strike is None:
        return None

    entry_q = straddle_quote(entry_exp, strike, pre_spot, expiration)
    exit_q = straddle_quote(exit_exp, strike, post_spot, expiration)
    if entry_q is None or exit_q is None:
        return None

    commission_frac = commission_per_straddle / (pre_spot * CONTRACT_MULTIPLIER)

    # Short straddle: + proceeds at entry (sold to bid), - cost at exit (bought
    # at ask). Per-share P&L = sell_proceeds - buy_cost. Normalise by spot.
    gross_pnl_per_share = entry_q.sell_proceeds - exit_q.buy_cost
    after_cost_return = gross_pnl_per_share / pre_spot - commission_frac

    mid_to_mid_return = (entry_q.mid - exit_q.mid) / pre_spot

    realized_move = abs(post_spot / pre_spot - 1.0)

    if abs(after_cost_return) > MAX_ABS_EVENT_RETURN:
        return None

    return CrushEvent(
        ticker=ticker,
        earnings_date=earnings_date,
        entry_date=entry_date,
        exit_date=exit_date,
        expiration=expiration,
        strike=strike,
        pre_spot=pre_spot,
        post_spot=post_spot,
        priced_move=entry_q.priced_move,
        realized_move=realized_move,
        entry_proceeds=entry_q.sell_proceeds,
        exit_cost=exit_q.buy_cost,
        after_cost_return=after_cost_return,
        mid_to_mid_return=mid_to_mid_return,
    )


# --------------------------------------------------------------------------- #
# Cohort aggregation + tail report
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CohortStats:
    """Pooled after-cost short-straddle stats for a set of events."""

    label: str
    n: int
    mean: float
    median: float
    t_stat: float
    win_rate: float
    sharpe: float  # mean/std of the after-cost returns


def aggregate(returns: list[float], *, label: str) -> CohortStats:
    """Pool a list of after-cost short-straddle returns. Pure."""

    vals = _clean(returns)
    n = len(vals)
    m = mean(vals)
    sd = std(vals)
    sharpe = (m / sd) if (sd == sd and sd > 0) else float("nan")
    win = (sum(1 for v in vals if v > 0) / n) if n else float("nan")
    return CohortStats(
        label=label,
        n=n,
        mean=m,
        median=median(vals),
        t_stat=t_stat_one_sample(vals),
        win_rate=win,
        sharpe=sharpe,
    )


@dataclass(frozen=True)
class TailReport:
    """The loss-distribution view — the decision-binding part of T23."""

    worst_return: float
    worst_label: str
    n_losses: int
    loss_share_of_n: float
    top5_loss_sum: float  # sum of the 5 most negative after-cost returns
    gross_sum: float  # sum of all after-cost returns
    mean_ex_worst5: float  # mean after removing the 5 worst events
    deaths_dominate: bool  # full mean <= 0 AND mean_ex_worst5 > 0


def tail_report(events: list[CrushEvent]) -> TailReport:
    """Loss distribution + 'do the deaths dominate?' (pre-registered). Pure."""

    rows = [(e.after_cost_return, f"{e.ticker} {e.earnings_date}") for e in events]
    rets = [r for r, _ in rows]
    n = len(rets)
    if n == 0:
        return TailReport(
            worst_return=float("nan"),
            worst_label="",
            n_losses=0,
            loss_share_of_n=float("nan"),
            top5_loss_sum=float("nan"),
            gross_sum=float("nan"),
            mean_ex_worst5=float("nan"),
            deaths_dominate=False,
        )
    ranked = sorted(rows, key=lambda r: r[0])  # most negative first
    worst_ret, worst_label = ranked[0]
    n_losses = sum(1 for r in rets if r < 0)
    top5 = ranked[:5]
    top5_loss_sum = sum(r for r, _ in top5)
    gross_sum = sum(rets)
    ex_worst5 = [r for r, _ in ranked[5:]]
    mean_ex5 = mean(ex_worst5) if ex_worst5 else float("nan")
    full_mean = mean(rets)
    deaths_dominate = (full_mean <= 0) and (mean_ex5 == mean_ex5) and (mean_ex5 > 0)
    return TailReport(
        worst_return=worst_ret,
        worst_label=worst_label,
        n_losses=n_losses,
        loss_share_of_n=n_losses / n,
        top5_loss_sum=top5_loss_sum,
        gross_sum=gross_sum,
        mean_ex_worst5=mean_ex5,
        deaths_dominate=deaths_dominate,
    )


# --------------------------------------------------------------------------- #
# Pre-registered gate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_gate(
    *,
    n_events: int,
    after_cost_mean: float,
    after_cost_t: float,
    is_mean: float,
    is_n: int,
    oos_mean: float,
    oos_n: int,
    placebo_mean: float,
    earnings_minus_placebo_t: float,
    min_n: int = 30,
    t_threshold: float = 2.0,
) -> GateVerdict:
    """Pre-registered T23 gate (ALL must hold), from brain/30.

    1. N >= ``min_n`` usable events.
    2. After-cost short-straddle mean > 0 AND |t| >= ``t_threshold``.
    3. OOS sign stability: IS and OOS means same sign, both halves N >= 10.
    4. Placebo: earnings premium exceeds the non-earnings one-day short-straddle
       carry at Welch |t| >= ``t_threshold`` (else the 'edge' is just being short
       vol generally).
    Each line is reported PASS/FAIL. (The tail report is decision-binding but is
    surfaced separately by the runner, not gated here.)
    """

    reasons: list[str] = []

    enough = n_events >= min_n
    reasons.append(f"{'PASS' if enough else 'FAIL'}: N={n_events} (need >= {min_n})")

    primary_ok = after_cost_mean > 0 and abs(after_cost_t) >= t_threshold
    reasons.append(
        f"{'PASS' if primary_ok else 'FAIL'}: after-cost short-straddle mean="
        f"{after_cost_mean:+.5f} t={after_cost_t:+.2f} "
        f"(need > 0 and |t| >= {t_threshold})"
    )

    halves_n_ok = is_n >= 10 and oos_n >= 10
    same_sign = (is_mean > 0 and oos_mean > 0) or (is_mean < 0 and oos_mean < 0)
    oos_ok = halves_n_ok and same_sign
    reasons.append(
        f"{'PASS' if oos_ok else 'FAIL'}: OOS sign stability IS={is_mean:+.5f} "
        f"(n={is_n}) OOS={oos_mean:+.5f} (n={oos_n}) (need same sign, both n >= 10)"
    )

    placebo_ok = earnings_minus_placebo_t >= t_threshold
    reasons.append(
        f"{'PASS' if placebo_ok else 'FAIL'}: earnings minus non-earnings placebo "
        f"(placebo mean={placebo_mean:+.5f}) Welch t={earnings_minus_placebo_t:+.2f} "
        f"(need >= {t_threshold})"
    )

    return GateVerdict(
        passed=enough and primary_ok and oos_ok and placebo_ok,
        reasons=reasons,
    )
