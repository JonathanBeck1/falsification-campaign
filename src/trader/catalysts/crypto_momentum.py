"""T33 — crypto time-series momentum / trend-following backtest (pure core + gate).

The PURE engine for the per-asset trend-following test pre-registered in
``research/crypto_momentum_preregistration.md``. No network here — it takes
already-fetched per-symbol daily-close DataFrames (built by ``crypto_data.py``)
and produces the daily after-cost momentum book, the buy-and-hold benchmarks,
IS/OOS split, the random-timing placebo, and the gate verdict.

Construction (fixed by the pre-reg):
  * Per asset *i*, signal on day *t* = trailing-N-day return through **t-1**:
    ``r_trail = close(t-1)/close(t-1-N) - 1`` (lagged → no look-ahead).
  * Position (long-flat PRIMARY): ``1 if r_trail > 0 else 0``. Equal-weight
    across all names with a position; daily rebalance.
  * Daily book = ``mean_i[ pos_i(t)*ret_i(t) ] - turnover*round_trip_cost``.
  * THE KEY CONTROL: the same code computes buy-and-hold Sharpe for BTC and for
    the equal-weight universe. A momentum book whose Sharpe does NOT exceed BOTH
    is beta-timing / exposure management, not alpha — a KILL (same lesson as the
    sell-in-May exposure trap).

Pre-registered lookbacks (fixed, NOT mined): N ∈ {30, 90}; PRIMARY = 90.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trader.research.gate import too_good_tripwire

# ~6 bps/side crypto taker x 2, applied to the fraction of book that FLIPS.
ROUND_TRIP_COST = 0.0012  # 12 bps
LOOKBACKS = (30, 90)      # pre-registered, fixed in advance
PRIMARY_LOOKBACK = 90     # the gate's binding lookback (slower, less fee-sensitive)
MIN_NAMES = 5             # minimum live names for a day to count
ANN = 365                 # crypto trades 24/7/365


# --------------------------------------------------------------------------- #
# Panel assembly (pure)
# --------------------------------------------------------------------------- #
def daily_close_panel(klines: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """PURE: per-symbol daily-close DataFrames -> aligned close-price panel.

    Columns = symbols, index = UTC date (tz-naive). NaN where a symbol is
    unlisted/delisted on a date — no forward-fill past a delisted token's last
    real close (its collapse is realized by its actual closes, which the archive
    retains; this is the survivorship correction).
    """

    cols: dict[str, pd.Series] = {}
    for sym, df in klines.items():
        if df is None or df.empty or "close" not in df:
            continue
        close = df["close"].copy()
        if close.index.tz is not None:
            close.index = close.index.tz_localize(None)
        cols[sym] = close.sort_index()
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


def daily_return_panel(close: pd.DataFrame) -> pd.DataFrame:
    """PURE: close-price panel -> daily close-to-close simple-return panel.

    NaN on a symbol's first observed day and wherever it is unlisted.
    """

    if close.empty:
        return close
    return close.pct_change()


# --------------------------------------------------------------------------- #
# Backtest (pure)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MomentumResult:
    """Daily after-cost momentum book + decomposition for one run."""

    book_ret: pd.Series       # after-cost daily book return
    gross_ret: pd.Series      # pre-cost daily book return
    cost_component: pd.Series  # turnover cost that day
    turnover: pd.Series       # fraction of book that flipped position
    n_names: pd.Series        # live names with a position each day

    @property
    def n_days(self) -> int:
        return int((self.n_names >= MIN_NAMES).sum())


def momentum_positions(
    close: pd.DataFrame,
    *,
    lookback: int,
    long_short: bool = False,
) -> pd.DataFrame:
    """PURE: trailing-N-day-return sign positions, LAGGED one day (no look-ahead).

    ``r_trail(t)`` uses closes through ``t-1`` only; the resulting position is
    held on day ``t`` and earns the t-1->t return. Long-flat (default):
    ``1 if r_trail>0 else 0``. ``long_short``: ``sign(r_trail)``. NaN where the
    trailing window is incomplete (treated as no position downstream).
    """

    # Trailing N-day return computed on closes, then SHIFTED one day so the
    # position on day t uses only information available at t-1's close.
    r_trail = (close / close.shift(lookback) - 1.0).shift(1)
    if long_short:
        pos = np.sign(r_trail)
    else:
        pos = (r_trail > 0).astype(float)
        pos = pos.where(r_trail.notna())  # keep NaN where signal undefined
    return pos


def run_momentum(
    close: pd.DataFrame,
    ret: pd.DataFrame,
    *,
    lookback: int = PRIMARY_LOOKBACK,
    cost: float = ROUND_TRIP_COST,
    long_short: bool = False,
    placebo_seed: int | None = None,
) -> MomentumResult:
    """PURE: run the daily equal-weight time-series-momentum book.

    Each day, hold the lagged trailing-return position in every name that has a
    live return; equal-weight across names with a non-zero position. After-cost
    book = gross - turnover*cost, where turnover is the fraction of (equal-
    weighted) book whose position changed since yesterday.

    ``placebo_seed`` (if set) RANDOMISES the entry/exit timing: each name's
    position column is independently permuted in time (preserving its long
    fraction / exposure) so the basket has the same average exposure but no real
    trend timing. A real edge must beat this placebo.
    """

    idx = close.index
    ret = ret.reindex(index=idx, columns=close.columns)
    pos = momentum_positions(close, lookback=lookback, long_short=long_short)

    if placebo_seed is not None:
        rng = np.random.default_rng(placebo_seed)
        shuffled = {}
        for c in pos.columns:
            col = pos[c]
            vals = col.to_numpy(copy=True)
            mask = ~np.isnan(vals)
            sub = vals[mask]
            rng.shuffle(sub)  # permute only the defined entries (keeps exposure)
            vals[mask] = sub
            shuffled[c] = vals
        pos = pd.DataFrame(shuffled, index=pos.index, columns=pos.columns)

    book, gross, cost_c, turn, counts = [], [], [], [], []
    prev = pd.Series(0.0, index=close.columns)
    for t in idx:
        pos_row = pos.loc[t].fillna(0.0)
        ret_row = ret.loc[t]
        # A name contributes only if it has BOTH a position and a live return.
        live = ret_row.notna() & (pos_row != 0.0)
        names = pos_row.index[live]
        k = len(names)
        if k < 1:
            book.append(np.nan)
            gross.append(np.nan)
            cost_c.append(np.nan)
            turn.append(0.0)
            counts.append(0)
            prev = pd.Series(0.0, index=close.columns)
            continue

        w = 1.0 / k
        gross_pnl = float((pos_row[names] * ret_row[names]).sum() * w)
        # Turnover = equal-weighted L1 change in position vs yesterday, /2 (a full
        # flip on every name = 1.0). Names not held today/yesterday weight 0.
        cur = pd.Series(0.0, index=close.columns)
        cur[names] = pos_row[names] * w
        turnover = float(np.abs(cur - prev).sum() / 2.0)
        cost_pnl = turnover * cost
        prev = cur

        gross.append(gross_pnl)
        cost_c.append(cost_pnl)
        book.append(gross_pnl - cost_pnl)
        turn.append(turnover)
        counts.append(k)

    return MomentumResult(
        book_ret=pd.Series(book, index=idx, name="book"),
        gross_ret=pd.Series(gross, index=idx, name="gross"),
        cost_component=pd.Series(cost_c, index=idx, name="cost"),
        turnover=pd.Series(turn, index=idx, name="turnover"),
        n_names=pd.Series(counts, index=idx, name="n"),
    )


def buy_and_hold(ret: pd.Series | pd.DataFrame) -> pd.Series:
    """PURE: a long-only buy-and-hold daily return series.

    A Series passes through (single asset, e.g. BTC). A DataFrame becomes the
    equal-weight-across-live-names daily return (the universe benchmark): each
    day, mean of the live (non-NaN) per-name returns.
    """

    if isinstance(ret, pd.Series):
        return ret.rename("bh")
    return ret.mean(axis=1, skipna=True).rename("bh")


# --------------------------------------------------------------------------- #
# Stats + gate (pure)
# --------------------------------------------------------------------------- #
def daily_stats(book: pd.Series) -> dict[str, float]:
    """PURE: t-stat, annualized mean/Sharpe, win-rate, max-drawdown on dailies."""

    x = book.dropna()
    n = len(x)
    if n < 2:
        return {"n": n, "mean": float("nan"), "t": float("nan"),
                "ann_ret": float("nan"), "sharpe": float("nan"),
                "win": float("nan"), "maxdd": float("nan")}
    mean = float(x.mean())
    sd = float(x.std(ddof=1))
    t = mean / (sd / np.sqrt(n)) if sd > 0 else float("nan")
    sharpe = (mean / sd * np.sqrt(ANN)) if sd > 0 else float("nan")
    curve = (1.0 + x).cumprod()
    maxdd = float((curve / curve.cummax() - 1.0).min())
    return {
        "n": n, "mean": mean, "t": t,
        "ann_ret": mean * ANN, "sharpe": sharpe,
        "win": float((x > 0).mean()), "maxdd": maxdd,
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
    momentum: MomentumResult,
    bh_btc: pd.Series,
    bh_universe: pd.Series,
    placebo: MomentumResult,
    *,
    oos_start: str = "2023-01-01",
) -> Gate:
    """PURE: apply the pre-registered gate. Returns PASS only if ALL hold.

    The binding control is the exposure / beta-timing test: the momentum book's
    after-cost Sharpe MUST exceed BOTH buy-and-hold Sharpes (BTC and EW universe)
    over the same span. A higher return at a LOWER Sharpe than buy-and-hold is
    beta-timing, not alpha → FAIL.
    """

    reasons: list[str] = []
    ok = True

    full = daily_stats(momentum.book_ret)
    n = momentum.n_days
    c1 = n >= 30
    ok &= c1
    reasons.append(f"[{'PASS' if c1 else 'FAIL'}] N={n} days with >= {MIN_NAMES} names (need >= 30)")

    c2 = (full["mean"] > 0) and (abs(full["t"]) >= 2.0)
    ok &= c2
    reasons.append(f"[{'PASS' if c2 else 'FAIL'}] after-cost mean={full['mean']:+.6f}/day "
                   f"t={full['t']:+.2f} (need >0 & |t|>=2)")

    is_, oos = split_is_oos(momentum.book_ret, oos_start)
    s_is, s_oos = daily_stats(is_), daily_stats(oos)
    same_sign = (np.sign(s_is["mean"]) == np.sign(s_oos["mean"])) and s_is["mean"] > 0
    c3 = same_sign and s_is["n"] >= 30 and s_oos["n"] >= 30
    ok &= c3
    reasons.append(f"[{'PASS' if c3 else 'FAIL'}] OOS sign stable: IS mean={s_is['mean']:+.6f} "
                   f"(n={s_is['n']}) OOS={s_oos['mean']:+.6f} (n={s_oos['n']})")

    # THE KEY CONTROL: momentum Sharpe must beat BOTH buy-and-hold Sharpes.
    mom_sh = full["sharpe"]
    btc_sh = daily_stats(bh_btc)["sharpe"]
    uni_sh = daily_stats(bh_universe)["sharpe"]
    c4 = (mom_sh > btc_sh) and (mom_sh > uni_sh)
    ok &= c4
    reasons.append(f"[{'PASS' if c4 else 'FAIL'}] EXPOSURE CONTROL: momentum Sharpe={mom_sh:+.3f} "
                   f"vs B&H BTC={btc_sh:+.3f} vs B&H universe={uni_sh:+.3f} "
                   f"(momentum must beat BOTH, else it's beta-timing not alpha)")

    pl = daily_stats(placebo.book_ret)
    c5 = abs(pl["t"]) < 2.0
    ok &= c5
    reasons.append(f"[{'PASS' if c5 else 'FAIL'}] placebo (random timing) ~0: mean={pl['mean']:+.6f} "
                   f"t={pl['t']:+.2f} (need |t|<2)")

    # Full brain/30 tripwire (shared): Sharpe>3 / win>85% PLUS the |median-mean|/MAD
    # and single-row-concentration checks the hand-rolled subset omitted — the ones
    # that catch an outlier-driven mean (the Tiingo-224% / stablecoin-tail pattern).
    tripwire, tw_detail = too_good_tripwire(momentum.book_ret, periods_per_year=ANN)
    reasons.append(f"[{'TRIPPED' if tripwire else 'ok'}] too-good tripwire: {tw_detail}")

    return Gate(passed=ok, reasons=reasons)
