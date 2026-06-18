"""T32 — Crypto Volatility Risk Premium (Deribit DVOL) backtest (pure core + gate).

The PURE engine for the crypto-VRP test pre-registered in
``research/crypto_vrp_preregistration.md``. No network here — it takes an
already-fetched DVOL implied-vol series (Deribit's 30-day IV index, fetched by
``crypto_vrp_data`` / the runner) and a spot daily-close series (Binance
archive, via ``crypto_data.py``) and produces:

  * the realized-vol forward series and the **IV - RV spread** (the *existence*
    measurement of the premium),
  * the daily **short-vol proxy P&L** — a variance-swap-replication accrual that
    collects entry implied variance and pays realized daily variance, so a
    single huge daily move produces a large, honest loss (the crypto tail),
  * the **mechanism control**: Pearson corr(entry IV-RV spread, short-vol P&L)
    and the spread-quartile P&L gradient — the equity-VRP kill showed corr ≈ 0
    (short-gamma beta, not VRP), so this gate is non-sign-only,
  * IS/OOS split, a long-vol / random-entry placebo, the tail (worst day, max
    drawdown, drop-worst-month robustness), and the full gate verdict.

Construction (fixed by the pre-reg):
  * IV(t) = DVOL close on UTC day t, in annualized **vol points** (e.g. 75.0 =
    75% annualized vol). We work in fractional vol: ``iv = DVOL / 100``.
  * RV_fwd(t, N) = annualized stdev of the next N daily log spot returns
    (close-to-close), √365-scaled — used ONLY to score the premium ex post.
  * vrp(t) = iv(t) - RV_fwd(t, N).
  * Short-vol proxy daily P&L (variance-swap replication, vega-normalized):
    ``pnl(t) = (iv(t-1)^2 - rv1d(t)^2) / (2 * iv(t-1)) - cost`` where
    ``rv1d(t) = |logret(t)| * sqrt(365)`` is day t's annualized realized vol.
    Dividing by ``2*iv`` converts the variance miss into ~vega (vol-point) units
    so a 1-vol-point edge is comparable across the IV range. Entry IV is
    ``iv(t-1)`` (strictly before day t's move → no look-ahead).
  * cost = friction in vol-points, charged as the same vega-normalized variance
    penalty per rebalance.

Everything is pure and unit-tested; the runner is the only thing that opens a
socket.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Pre-registered constants (FIXED in advance — see preregistration §3, §6, §7).
RV_WINDOW = 30                 # forward realized-vol window (days), matches DVOL 30d
FRICTION_VOL_PTS = 2.0         # round-trip friction in vol points (Deribit fee+spread+hedge)
ANN = 365                      # crypto 24/7/365
OOS_START = "2024-01-01"       # IS = 2021-03..2023-12, OOS = 2024-01..run
MECH_MIN_CORR = 0.10           # mechanism gate: |corr(spread, pnl)| must clear this (NON-sign-only)
PLACEBO_SEED = 20260614

CURRENCIES = ("BTC", "ETH")    # the only two DVOL currencies (no post-hoc selection)


# --------------------------------------------------------------------------- #
# Index hygiene (pure)
# --------------------------------------------------------------------------- #
def _align_index(s: pd.Series) -> pd.Series:
    """PURE: tz-naive, sorted, de-duplicated (keep last) copy of a dated series."""

    if s is None or len(s) == 0:
        return pd.Series(dtype=float)
    out = s.copy()
    if isinstance(out.index, pd.DatetimeIndex) and out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.astype(float)


def _clean_close(close: pd.Series) -> pd.Series:
    """PURE: index-hygiene a close series and drop non-positive prices."""

    c = _align_index(close)
    return c[c > 0]


# --------------------------------------------------------------------------- #
# Vol construction (pure)
# --------------------------------------------------------------------------- #
def daily_log_returns(close: pd.Series) -> pd.Series:
    """PURE: close-to-close daily log returns of a (tz-naive, sorted) close series."""

    c = _clean_close(close)
    if c.empty:
        return pd.Series(dtype=float)
    return np.log(c / c.shift(1)).dropna()


def realized_vol_forward(close: pd.Series, window: int = RV_WINDOW) -> pd.Series:
    """PURE: forward N-day annualized realized vol indexed by the OBSERVATION day.

    ``rv[t]`` = annualized stdev of the log returns on days ``t+1 .. t+window``
    (a strictly FORWARD window — returns occur after t). √window-free because we
    annualize the per-day stdev by √ANN. Days without a full forward window are
    dropped. Used only to score the premium ex post (never to select entry).
    """

    r = daily_log_returns(close)
    if len(r) <= window:
        return pd.Series(dtype=float)
    # Forward window: shift the rolling std so day t holds returns t+1..t+window.
    fwd = r.rolling(window).std(ddof=1).shift(-window) * np.sqrt(ANN)
    return fwd.dropna().rename("rv_fwd")


def realized_vol_1d(close: pd.Series) -> pd.Series:
    """PURE: per-day annualized realized vol proxy = |daily log return| * √ANN.

    This is the single-day realized-vol used in the short-vol accrual: a large
    daily move makes this huge, which is exactly the tail that eats short-vol.
    """

    r = daily_log_returns(close)
    return (r.abs() * np.sqrt(ANN)).rename("rv_1d")


def iv_rv_spread(iv: pd.Series, close: pd.Series, window: int = RV_WINDOW) -> pd.DataFrame:
    """PURE: align IV (fractional, e.g. 0.75) with forward RV → the VRP spread.

    Returns a DataFrame with columns ``iv``, ``rv_fwd``, ``vrp`` (= iv - rv_fwd),
    indexed by the days where BOTH are available. ``iv`` is expected already in
    fractional vol units (DVOL/100); see :func:`dvol_to_fraction`.
    """

    iv = _align_index(iv).rename("iv")
    rv = realized_vol_forward(close, window).rename("rv_fwd")
    empty = pd.DataFrame(columns=["iv", "rv_fwd", "vrp"], dtype=float)
    if iv.empty or rv.empty:
        return empty
    df = pd.concat([iv, rv], axis=1, join="inner").dropna()
    if df.empty:
        return empty
    df["vrp"] = df["iv"] - df["rv_fwd"]
    return df


def dvol_to_fraction(dvol: pd.Series) -> pd.Series:
    """PURE: DVOL index level (vol points, e.g. 75.0) → fractional vol (0.75)."""

    return (_align_index(dvol) / 100.0).rename("iv")


# --------------------------------------------------------------------------- #
# Short-vol proxy book (pure)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class VrpResult:
    """One currency's (or pooled) short-vol study output.

    ``book_ret`` is the after-cost daily short-vol P&L in vega (vol-point) units.
    ``gross_ret`` is pre-cost. ``entry_spread`` is the entry-day IV-RV spread
    aligned to each P&L day (for the mechanism correlation). ``spread_panel`` is
    the full iv/rv_fwd/vrp frame (the *existence* measurement).
    """

    book_ret: pd.Series
    gross_ret: pd.Series
    entry_spread: pd.Series
    spread_panel: pd.DataFrame


def short_vol_book(
    iv_frac: pd.Series,
    close: pd.Series,
    *,
    friction_vol_pts: float = FRICTION_VOL_PTS,
    window: int = RV_WINDOW,
    sign: int = +1,
    random_entry_seed: int | None = None,
) -> VrpResult:
    """PURE: build the daily short-vol proxy book from IV (fractional) + spot.

    P&L(t) (vega units) = ``sign * (iv(t-1)^2 - rv1d(t)^2) / (2*iv(t-1)) - cost``.
    ``sign=+1`` is SHORT vol (collect implied, pay realized); ``sign=-1`` is the
    long-vol placebo. ``random_entry_seed`` set ⇒ the entry IV is shuffled across
    days (random-timing placebo: destroys any IV↔move alignment).

    ``cost`` = vega-normalized friction: ``friction_vol_pts/100 / 2`` per day
    (round-trip vol-point cost charged once; the /2 reflects we model a
    round-trip on the rebalance accrual, half each leg's expectation). It is a
    flat drag in vol-point units, deliberately conservative.

    Returns a :class:`VrpResult`; ``entry_spread`` aligns each P&L day's entry
    IV-RV spread for the mechanism gate.
    """

    iv = _align_index(iv_frac)
    rv1 = realized_vol_1d(close)
    panel = iv_rv_spread(iv, close, window)  # for entry_spread + existence stat

    # Entry IV is the prior day's IV (strictly before day t's realized move).
    iv_entry = iv.shift(1)
    if random_entry_seed is not None:
        rng = np.random.default_rng(random_entry_seed)
        vals = iv_entry.dropna()
        shuffled = pd.Series(
            rng.permutation(vals.to_numpy()), index=vals.index, name="iv"
        )
        iv_entry = shuffled.reindex(iv_entry.index)

    df = pd.concat([iv_entry.rename("iv_entry"), rv1], axis=1, join="inner").dropna()
    df = df[df["iv_entry"] > 0]
    if df.empty:
        empty = pd.Series(dtype=float)
        return VrpResult(empty, empty, empty, panel)

    gross = sign * (df["iv_entry"] ** 2 - df["rv_1d"] ** 2) / (2.0 * df["iv_entry"])
    cost = (friction_vol_pts / 100.0) / 2.0
    net = (gross - cost).rename("book")
    gross = gross.rename("gross")

    # Align the entry-day VRP spread (iv(t-1) - rv_fwd(t-1)) to each P&L day t.
    entry_spread = panel["vrp"].shift(1).reindex(net.index).rename("entry_spread")
    return VrpResult(book_ret=net, gross_ret=gross, entry_spread=entry_spread,
                     spread_panel=panel)


# --------------------------------------------------------------------------- #
# Stats + tail + mechanism (pure)
# --------------------------------------------------------------------------- #
def book_stats(book: pd.Series) -> dict[str, float]:
    """PURE: t-stat, annualized mean/Sharpe, win-rate, worst-day, max drawdown.

    ``maxdd`` is an additive (vol-point) drawdown on the cumulative P&L (the book
    is in vega units, not multiplicative returns), so the curve is a cumsum and
    the drawdown is peak-to-trough in vol-points. ``worst`` is the single worst
    daily P&L (the tail).
    """

    x = book.dropna()
    n = len(x)
    if n < 2:
        return {"n": n, "mean": float("nan"), "t": float("nan"),
                "ann_ret": float("nan"), "sharpe": float("nan"),
                "win": float("nan"), "maxdd": float("nan"), "worst": float("nan")}
    mean = float(x.mean())
    sd = float(x.std(ddof=1))
    t = mean / (sd / np.sqrt(n)) if sd > 0 else float("nan")
    sharpe = (mean / sd * np.sqrt(ANN)) if sd > 0 else float("nan")
    curve = x.cumsum()
    maxdd = float((curve - curve.cummax()).min())
    return {
        "n": n, "mean": mean, "t": t,
        "ann_ret": mean * ANN, "sharpe": sharpe,
        "win": float((x > 0).mean()), "maxdd": maxdd, "worst": float(x.min()),
    }


def split_is_oos(book: pd.Series, oos_start: str = OOS_START) -> tuple[pd.Series, pd.Series]:
    """PURE: split a daily series into IS (< oos_start) and OOS (>= oos_start).

    tz-robust: the cut adopts the series' tz so tz-aware inputs do not raise.
    """

    cut = pd.Timestamp(oos_start)
    if isinstance(book.index, pd.DatetimeIndex) and book.index.tz is not None:
        cut = cut.tz_localize(book.index.tz)
    return book[book.index < cut], book[book.index >= cut]


def mechanism_corr(entry_spread: pd.Series, book: pd.Series) -> float:
    """PURE: Pearson corr between entry-day IV-RV spread and short-vol P&L.

    THE KEY VRP test. If the book harvests the *premium*, a bigger ex-post-
    overpriced entry IV should pay more → positive correlation. corr ≈ 0 means
    the P&L is short-gamma beta, NOT VRP (the equity-kill failure mode). NaN if
    < 3 paired points or zero variance.
    """

    df = pd.concat([entry_spread.rename("s"), book.rename("p")], axis=1).dropna()
    if len(df) < 3 or df["s"].std(ddof=1) == 0 or df["p"].std(ddof=1) == 0:
        return float("nan")
    return float(df["s"].corr(df["p"]))


def spread_quartile_gradient(entry_spread: pd.Series, book: pd.Series) -> list[float]:
    """PURE: mean short-vol P&L within each entry-spread quartile (Q1..Q4).

    A monotone increasing gradient (Q1 < … < Q4) is required by the mechanism
    gate alongside the correlation — overpriced-vol days should pay more.
    Returns [Q1, Q2, Q3, Q4] means (NaN-padded if too few points).
    """

    df = pd.concat([entry_spread.rename("s"), book.rename("p")], axis=1).dropna()
    if len(df) < 8:
        return [float("nan")] * 4
    try:
        df["q"] = pd.qcut(df["s"], 4, labels=False, duplicates="drop")
    except ValueError:
        return [float("nan")] * 4
    out: list[float] = []
    for q in range(4):
        sub = df.loc[df["q"] == q, "p"]
        out.append(float(sub.mean()) if len(sub) else float("nan"))
    return out


def is_monotone_increasing(values: list[float]) -> bool:
    """PURE: True iff the non-NaN sequence is strictly non-decreasing (≥4 pts)."""

    v = [x for x in values if x == x]  # drop NaN
    if len(v) < 4:
        return False
    return all(v[i] <= v[i + 1] for i in range(len(v) - 1))


def drop_worst_month(book: pd.Series) -> tuple[pd.Series, str]:
    """PURE: remove the single worst calendar month (by summed P&L) — tail test.

    Returns ``(book_without_worst_month, 'YYYY-MM')``. The gate requires the
    verdict NOT to hinge on this exclusion (if removing it is what makes the
    strategy work, the premium does not survive its tail).
    """

    x = book.dropna()
    if x.empty:
        return x, ""
    idx = x.index
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        idx = idx.tz_localize(None)
    periods = idx.to_period("M")
    by_month = x.groupby(periods).sum()
    worst = by_month.idxmin()
    keep = x[periods != worst]
    return keep, str(worst)


# --------------------------------------------------------------------------- #
# Gate (pure)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Gate:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    short: VrpResult,
    placebo_long: VrpResult,
    placebo_random: VrpResult,
    *,
    oos_start: str = OOS_START,
    min_corr: float = MECH_MIN_CORR,
) -> Gate:
    """PURE: apply the pre-registered crypto-VRP gate. PASS only if ALL hold.

    Gates (preregistration §7): N≥30; after-cost |t|≥2 & mean>0 (TAIL-INCLUSIVE,
    full sample); OOS sign stable; MECHANISM corr≥min_corr AND monotone quartile
    gradient (non-sign-only); TAIL — verdict must NOT hinge on dropping the worst
    month (sign preserved with full tail) and worst-month-removed must not be the
    only positive; placebo (long-vol) must mirror (not reproduce the edge).
    """

    reasons: list[str] = []
    ok = True

    full = book_stats(short.book_ret)
    n_ok = full["n"] >= 30
    reasons.append(f"{'PASS' if n_ok else 'FAIL'}: N={full['n']} (need ≥ 30)")
    ok &= n_ok

    # After-cost, TAIL-INCLUSIVE, full sample.
    sig_ok = (full["mean"] > 0) and (abs(full["t"]) >= 2.0)
    reasons.append(
        f"{'PASS' if sig_ok else 'FAIL'}: after-cost mean={full['mean']:+.5f} "
        f"t={full['t']:+.2f} (need >0 & |t|≥2, TAIL-INCLUSIVE)"
    )
    ok &= sig_ok

    # OOS sign stability.
    is_, oos = split_is_oos(short.book_ret, oos_start)
    s_is, s_oos = book_stats(is_), book_stats(oos)
    oos_ok = (s_is["n"] >= 10 and s_oos["n"] >= 10
              and np.sign(s_is["mean"]) == np.sign(s_oos["mean"])
              and s_is["mean"] > 0)
    reasons.append(
        f"{'PASS' if oos_ok else 'FAIL'}: OOS sign stable "
        f"IS mean={s_is['mean']:+.5f} (n={s_is['n']}) "
        f"OOS mean={s_oos['mean']:+.5f} (n={s_oos['n']})"
    )
    ok &= oos_ok

    # MECHANISM (non-sign-only): corr ≥ min_corr AND monotone quartile gradient.
    corr = mechanism_corr(short.entry_spread, short.book_ret)
    grad = spread_quartile_gradient(short.entry_spread, short.book_ret)
    mono = is_monotone_increasing(grad)
    mech_ok = (corr == corr) and (corr >= min_corr) and mono
    reasons.append(
        f"{'PASS' if mech_ok else 'FAIL'}: MECHANISM corr(spread,pnl)={corr:+.3f} "
        f"(need ≥ {min_corr:+.2f}) quartiles={[round(g, 5) for g in grad]} "
        f"monotone={mono} (sign-only is INSUFFICIENT — equity-kill lesson)"
    )
    ok &= mech_ok

    # TAIL survival: verdict must not hinge on dropping the worst month.
    kept, worst_m = drop_worst_month(short.book_ret)
    k_st = book_stats(kept)
    # Healthy: full-sample already positive (sig_ok). Tail-hinge: full negative
    # but worst-removed positive ⇒ verdict depends on excluding the tail ⇒ FAIL.
    tail_hinges = (full["mean"] <= 0) and (k_st["mean"] > 0)
    tail_ok = not tail_hinges
    reasons.append(
        f"{'PASS' if tail_ok else 'FAIL'}: TAIL — worst month {worst_m} removed "
        f"mean={k_st['mean']:+.5f} t={k_st['t']:+.2f}; full worst-day={full['worst']:+.4f} "
        f"maxdd={full['maxdd']:+.4f} (verdict must NOT hinge on dropping the tail)"
    )
    ok &= tail_ok

    # Placebo: the long-vol mirror should NOT also be a positive edge (it is the
    # negative of the short book minus a double cost). We require the short edge
    # not be reproduced by the random-entry placebo with |t|≥2 positive.
    rand_st = book_stats(placebo_random.book_ret)
    placebo_ok = not (rand_st["mean"] > 0 and abs(rand_st["t"]) >= 2.0)
    reasons.append(
        f"{'PASS' if placebo_ok else 'FAIL'}: PLACEBO random-entry "
        f"mean={rand_st['mean']:+.5f} t={rand_st['t']:+.2f} (must NOT reproduce edge)"
    )
    ok &= placebo_ok

    return Gate(passed=ok, reasons=reasons)
