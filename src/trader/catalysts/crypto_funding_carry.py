"""T29 — perp funding-rate carry backtest (pure core + gate).

The PURE engine for the cross-sectional funding-carry test pre-registered in
``research/crypto_funding_carry_preregistration.md``. No network here — it takes
already-fetched per-symbol funding Series + daily-close DataFrames (built by
``crypto_data.py``) and produces the daily after-cost book return, the
funding-vs-price decomposition, IS/OOS split, placebo, and the gate verdict.

Construction (fixed by the pre-reg):
  * Each UTC day *t*, rank symbols by trailing-7d mean per-interval funding,
    **lagged one day** (selection uses only data through t-1 — no look-ahead).
  * Short the top-decile (≥ ``min_basket``) — a short into positive funding
    COLLECTS it. Equal weight.
  * Daily book return = funding_collected(t) - perp_price_return_short_leg(t)
    - turnoverxround_trip_cost. The short leg's price return enters with a MINUS
    (short profits when price falls). Under the delta-neutral idealization the
    long-spot leg cancels the price delta, so we ALSO report the funding-only and
    price-only components to prove which one drives the result.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# 8h funding → 3 intervals/day; daily funding yield = sum of the day's intervals.
ROUND_TRIP_COST = 0.0012  # 12 bps = ~6 bps/side taker x 2, applied to TURNOVER.
TRAILING_DAYS = 7
TOP_QUANTILE = 0.10  # top funding decile
MIN_BASKET = 5  # minimum names for a day to count


# --------------------------------------------------------------------------- #
# Panel assembly (pure)
# --------------------------------------------------------------------------- #
def daily_funding_panel(funding: dict[str, pd.Series]) -> pd.DataFrame:
    """PURE: per-symbol interval funding Series -> daily funding-yield panel.

    Each symbol's intraday (8h) funding is summed within a UTC day to a daily
    funding yield (the cash a short collects that day if funding stays positive).
    Output: DataFrame indexed by UTC date, columns = symbols, NaN where a symbol
    had no funding that day (not yet listed / already delisted).
    """

    cols: dict[str, pd.Series] = {}
    for sym, s in funding.items():
        if s is None or s.empty:
            continue
        daily = s.groupby(s.index.tz_convert("UTC").normalize()).sum()
        daily.index = daily.index.tz_localize(None)
        cols[sym] = daily
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


def daily_return_panel(klines: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """PURE: per-symbol daily-close DataFrames -> daily close-to-close return panel.

    NaN where a symbol is unlisted/delisted on a date. A delisted token's last
    real bar is its last return; no forward-fill past it (its collapse is realized
    by its actual closes, which the archive retains).
    """

    cols: dict[str, pd.Series] = {}
    for sym, df in klines.items():
        if df is None or df.empty or "close" not in df:
            continue
        close = df["close"].copy()
        if close.index.tz is not None:
            close.index = close.index.tz_localize(None)
        cols[sym] = close.sort_index().pct_change()
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


# --------------------------------------------------------------------------- #
# Backtest (pure)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CarryResult:
    """Daily book series + decomposition for one run (cohort / survivor / placebo)."""

    book_ret: pd.Series          # after-cost daily book return
    funding_component: pd.Series  # funding collected that day (pre-cost)
    price_component: pd.Series    # short-leg price PnL that day (pre-cost)
    cost_component: pd.Series     # turnover cost that day
    n_names: pd.Series            # basket size each day

    @property
    def n_days(self) -> int:
        return int((self.n_names >= MIN_BASKET).sum())


def _select_top(funding_signal_row: pd.Series, quantile: float) -> list[str]:
    """PURE: names in the top-``quantile`` of (positive) trailing funding."""

    valid = funding_signal_row.dropna()
    valid = valid[valid > 0]  # only short names that actually PAY funding
    if valid.empty:
        return []
    k = max(1, int(np.ceil(len(valid) * quantile)))
    return list(valid.sort_values(ascending=False).head(k).index)


def run_carry(
    funding_daily: pd.DataFrame,
    ret_daily: pd.DataFrame,
    *,
    symbols: list[str] | None = None,
    quantile: float = TOP_QUANTILE,
    cost: float = ROUND_TRIP_COST,
    trailing: int = TRAILING_DAYS,
    seed: int | None = None,
) -> CarryResult:
    """PURE: run the daily top-decile short-perp funding-carry book.

    ``symbols`` restricts the universe (e.g. survivor-only). ``seed`` (if set)
    switches to the RANDOM-DECILE placebo: same basket size, random names.
    Selection on day *t* uses trailing-mean funding through *t-1* (lagged → no
    look-ahead). Returns a :class:`CarryResult`.
    """

    if symbols is not None:
        keep = [s for s in symbols if s in funding_daily.columns]
        funding_daily = funding_daily[keep]
        ret_daily = ret_daily.reindex(columns=keep)

    # Align both panels on the union of dates.
    idx = funding_daily.index.union(ret_daily.index).sort_values()
    funding_daily = funding_daily.reindex(idx)
    ret_daily = ret_daily.reindex(index=idx, columns=funding_daily.columns)

    # Trailing-mean funding signal, then LAG one day (selection uses t-1 info).
    signal = funding_daily.rolling(trailing, min_periods=trailing).mean().shift(1)

    rng = np.random.default_rng(seed) if seed is not None else None

    book, f_comp, p_comp, c_comp, counts = [], [], [], [], []
    prev: set[str] = set()
    for t in idx:
        sig_row = signal.loc[t]
        if seed is None:
            names = _select_top(sig_row, quantile)
        else:
            # Placebo: same size as the real basket would be, random names from
            # those that have a (positive) signal that day.
            pool = sig_row.dropna()
            pool = pool[pool > 0]
            k = len(_select_top(sig_row, quantile))
            names = (list(rng.choice(pool.index, size=min(k, len(pool)), replace=False))
                     if k and len(pool) else [])

        if not names:
            book.append(np.nan)
            f_comp.append(np.nan)
            p_comp.append(np.nan)
            c_comp.append(np.nan)
            counts.append(0)
            prev = set()
            continue

        w = 1.0 / len(names)
        day_funding = funding_daily.loc[t, names]
        # Short collects funding when it's positive on the held day.
        funding_pnl = float(np.nansum(day_funding.values) * w)
        # Short leg: profit = -price_return. NaN returns (just-listed) → 0 contrib.
        day_ret = ret_daily.loc[t, names].fillna(0.0)
        price_pnl = float(-np.nansum(day_ret.values) * w)
        # Turnover = fraction of book that changed names this rebalance.
        cur = set(names)
        turnover = 1.0 if not prev else len(cur ^ prev) / (2 * max(len(cur), len(prev)))
        cost_pnl = turnover * cost
        prev = cur

        f_comp.append(funding_pnl)
        p_comp.append(price_pnl)
        c_comp.append(cost_pnl)
        book.append(funding_pnl + price_pnl - cost_pnl)
        counts.append(len(names))

    return CarryResult(
        book_ret=pd.Series(book, index=idx, name="book"),
        funding_component=pd.Series(f_comp, index=idx, name="funding"),
        price_component=pd.Series(p_comp, index=idx, name="price"),
        cost_component=pd.Series(c_comp, index=idx, name="cost"),
        n_names=pd.Series(counts, index=idx, name="n"),
    )


# --------------------------------------------------------------------------- #
# Stats + gate (pure)
# --------------------------------------------------------------------------- #
def daily_stats(book: pd.Series) -> dict[str, float]:
    """PURE: t-stat, annualized mean/Sharpe, win-rate on a daily return series."""

    x = book.dropna()
    n = len(x)
    if n < 2:
        return {"n": n, "mean": float("nan"), "t": float("nan"),
                "ann_ret": float("nan"), "sharpe": float("nan"), "win": float("nan")}
    mean = float(x.mean())
    sd = float(x.std(ddof=1))
    t = mean / (sd / np.sqrt(n)) if sd > 0 else float("nan")
    sharpe = (mean / sd * np.sqrt(365)) if sd > 0 else float("nan")
    return {
        "n": n, "mean": mean, "t": t,
        "ann_ret": mean * 365, "sharpe": sharpe,
        "win": float((x > 0).mean()),
    }


def split_is_oos(book: pd.Series, oos_start: str = "2023-01-01") -> tuple[pd.Series, pd.Series]:
    """PURE: split the daily book into IS (< oos_start) and OOS (>= oos_start)."""

    cut = pd.Timestamp(oos_start)
    return book[book.index < cut], book[book.index >= cut]


@dataclass(frozen=True)
class Gate:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    cohort: CarryResult,
    survivor: CarryResult,
    placebo: CarryResult,
    *,
    oos_start: str = "2023-01-01",
) -> Gate:
    """PURE: apply the pre-registered gate. Returns PASS only if ALL hold."""

    reasons: list[str] = []
    ok = True

    full = daily_stats(cohort.book_ret)
    n = cohort.n_days
    c1 = n >= 30
    ok &= c1
    reasons.append(f"[{'PASS' if c1 else 'FAIL'}] N={n} days with >= {MIN_BASKET} names (need >= 30)")

    c2 = (full["mean"] > 0) and (abs(full["t"]) >= 2.0)
    ok &= c2
    reasons.append(f"[{'PASS' if c2 else 'FAIL'}] after-cost mean={full['mean']:.6f}/day "
                   f"t={full['t']:+.2f} (need >0 & |t|>=2)")

    is_, oos = split_is_oos(cohort.book_ret, oos_start)
    s_is, s_oos = daily_stats(is_), daily_stats(oos)
    same_sign = (np.sign(s_is["mean"]) == np.sign(s_oos["mean"])) and s_is["mean"] > 0
    c3 = same_sign and s_is["n"] >= 30 and s_oos["n"] >= 30
    ok &= c3
    reasons.append(f"[{'PASS' if c3 else 'FAIL'}] OOS sign stable: IS mean={s_is['mean']:+.6f} "
                   f"(n={s_is['n']}) OOS={s_oos['mean']:+.6f} (n={s_oos['n']})")

    # Funding must dominate price (it's carry, not beta).
    f_mean = float(cohort.funding_component.dropna().mean())
    p_mean = float(cohort.price_component.dropna().mean())
    c4 = (f_mean > 0) and (f_mean > abs(p_mean))
    ok &= c4
    reasons.append(f"[{'PASS' if c4 else 'FAIL'}] funding dominates: funding={f_mean:+.6f} "
                   f"price={p_mean:+.6f} /day (funding must be + and > |price|)")

    # Survivorship: claim rests on the delisted-included cohort, not survivor-only.
    # Reported as INFO (the gap magnitude); the cohort's own c2 already enforces
    # that the claim cannot rest on survivor-only being the positive one.
    surv = daily_stats(survivor.book_ret)
    reasons.append(f"[INFO] survivorship gap: cohort mean={full['mean']:+.6f} (t={full['t']:+.2f}) "
                   f"vs survivor-only={surv['mean']:+.6f} (t={surv['t']:+.2f})")

    pl = daily_stats(placebo.book_ret)
    c6 = abs(pl["t"]) < 2.0
    ok &= c6
    reasons.append(f"[{'PASS' if c6 else 'FAIL'}] placebo ~0: mean={pl['mean']:+.6f} t={pl['t']:+.2f} "
                   f"(need |t|<2)")

    sharpe = full["sharpe"]
    tripwire = (sharpe > 3) or (full["win"] > 0.85)
    reasons.append(f"[{'TRIPPED' if tripwire else 'ok'}] too-good tripwire: Sharpe={sharpe:.2f} "
                   f"win={full['win']:.2%}")

    return Gate(passed=ok, reasons=reasons)
