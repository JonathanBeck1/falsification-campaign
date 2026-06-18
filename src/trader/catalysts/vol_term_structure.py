"""T24 — single-name IV term-structure carry (PURE core).

This is the **pure, unit-tested core** for test T24. It contains no I/O: every
function is a deterministic function of in-memory numbers / frames. The thin
runner (`scripts/run_vol_term_structure_study.py`) is the only part that touches
the option lake and yfinance; it feeds this module the per-(name, date) ATM-IV
term-structure samples and the BS marks, and this module turns them into the
pre-registered cross-sectional long-short calendar book and its gate metrics.

See `research/vol_term_structure_preregistration.md` for the fixed design.

### What the carry position is

On each monthly rebalance date the slope `s = far_iv - near_iv` is computed per
name from `vol_surface_data.term_structure`. Names are ranked cross-sectionally:

- **long tercile** (steepest contango): SHORT the near-ATM straddle, LONG the
  far-ATM straddle, sized **vega-neutral** at entry (so net vol-level exposure
  ≈ 0). This is the classic short-near / long-far calendar that earns roll-down
  if the far leg rolls down an upward curve.
- **short tercile** (flattest / backwardated): the mirror.

The book is dollar-neutral and vega-neutral, so its unconditional short-vol beta
cancels by construction — the discipline that separates *slope carry* from a
plain short-vol stance. We ALSO compute, separately, an unconditional short-vol
book and regress the slope book on it (the harder control; see
`incremental_alpha`).

### Marking (the roll-down mechanic)

A straddle's value and vega come from the module's own Black-Scholes (reused
from `vol_surface_data`). At entry the near/far straddles are priced at the
entry curve. At exit (h trading days later) the SAME contracts are repriced with
(a) the tenor reduced by h calendar-days and (b) the ATM IV the curve now shows
at that reduced tenor — i.e. the originally-90d leg is marked at the curve's
(90-h)d IV. That re-query along the (typically lower) near part of the curve IS
the roll-down. All of that interpolation is done in the runner via
`vol_surface_data.atm_iv`; this module receives the entry/exit (spot, tenor, iv)
tuples and computes the P&L.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trader.catalysts.vol_surface_data import (
    DAYS_PER_YEAR,
    DEFAULT_DIVIDEND_YIELD,
    DEFAULT_RISK_FREE_RATE,
    bs_price,
    bs_vega,
)

# --------------------------------------------------------------------------- #
# Fixed design constants (pre-registered)
# --------------------------------------------------------------------------- #
NEAR_DAYS = 30.0
FAR_DAYS = 90.0
REBALANCE_STEP = 21  # trading days between (non-overlapping) rebalances
# Holding horizon in TRADING days. 10 trading days ≈ 14 calendar days, leaving
# ~16 calendar days on the ~30d near leg — meaningful roll-down WITHOUT consuming
# the near leg to expiry (a 21-trading-day hold ≈ 30 calendar days would expire
# the near leg, making its vega→0 and the vega-neutral sizing degenerate). This
# corrects a trading-vs-calendar-day unit mismatch; the rebalance step stays 21
# so holds remain non-overlapping. See the pre-reg §5 correction note.
HOLD_DAYS = 10  # trading-day holding horizon
TERCILE_FRAC = 1.0 / 3.0

# Friction: half bid/ask spread expressed as a vol-point haircut on each leg,
# charged on entry and exit. 1 vol point = 0.01 in IV units.
VOL_POINT = 0.01
FRICTION_VOL_POINTS = 1.0  # 1.0 vol-pt half-spread per straddle round trip (per leg)

IS_END = pd.Timestamp("2024-03-31")  # IS: .. 2024-03-31 ; OOS: 2024-04-01 ..


# --------------------------------------------------------------------------- #
# Straddle value / vega (ATM call+put), pure
# --------------------------------------------------------------------------- #
def straddle_value(
    spot: float,
    tenor_days: float,
    iv: float,
    *,
    r: float = DEFAULT_RISK_FREE_RATE,
    q: float = DEFAULT_DIVIDEND_YIELD,
) -> float:
    """Black-Scholes value of an ATM (K=spot) straddle = call + put.

    NaN-safe: returns NaN if any input is non-finite or tenor/iv/spot <= 0.
    """

    if not all(np.isfinite([spot, tenor_days, iv])) or spot <= 0 or tenor_days <= 0 or iv <= 0:
        return float("nan")
    T = tenor_days / DAYS_PER_YEAR
    call = float(bs_price(spot, spot, T, iv, True, r=r, q=q))
    put = float(bs_price(spot, spot, T, iv, False, r=r, q=q))
    return call + put


def straddle_vega(
    spot: float,
    tenor_days: float,
    iv: float,
    *,
    r: float = DEFAULT_RISK_FREE_RATE,
    q: float = DEFAULT_DIVIDEND_YIELD,
) -> float:
    """BS vega of an ATM straddle = 2 x single-option vega (call & put share vega).

    NaN-safe like :func:`straddle_value`.
    """

    if not all(np.isfinite([spot, tenor_days, iv])) or spot <= 0 or tenor_days <= 0 or iv <= 0:
        return float("nan")
    T = tenor_days / DAYS_PER_YEAR
    return 2.0 * float(bs_vega(spot, spot, T, iv, r=r, q=q))


# --------------------------------------------------------------------------- #
# Single-name calendar P&L over one holding period
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CalendarLeg:
    """The entry/exit marks needed to price one name's vega-neutral calendar.

    All IVs in decimals (0.30 = 30%). ``*_entry`` observed at rebalance close;
    ``*_exit`` observed h trading days later on the SAME originally-issued
    contracts (tenor reduced, IV re-read off the curve at the reduced tenor).
    """

    spot_entry: float
    spot_exit: float
    near_tenor_entry: float  # ~30
    far_tenor_entry: float  # ~90
    near_tenor_exit: float  # ~30 - h_calendar_days  (clamped >0)
    far_tenor_exit: float  # ~90 - h_calendar_days
    near_iv_entry: float
    far_iv_entry: float
    near_iv_exit: float  # curve's ATM IV at near_tenor_exit on the exit date
    far_iv_exit: float  # curve's ATM IV at far_tenor_exit on the exit date


def calendar_pnl(
    leg: CalendarLeg,
    *,
    direction: int,
    friction_vol_points: float = FRICTION_VOL_POINTS,
    r: float = DEFAULT_RISK_FREE_RATE,
    q: float = DEFAULT_DIVIDEND_YIELD,
) -> float:
    """After-cost P&L of one name's **vega-neutral** calendar over the holding period.

    ``direction = +1`` is the long-side calendar (short near / long far straddle),
    earned by steep-contango names; ``-1`` is the mirror. Sizing: 1.0 far straddle
    and ``n_near = vega_far_entry / vega_near_entry`` near straddles so entry vega
    nets to ~0. Returns a P&L in **per-unit-far-vega** dollars; the book then
    equal-weights names, so the absolute scale cancels in the long-short mean —
    what matters is sign and relative magnitude. NaN if either leg can't be
    priced.

    Friction: each straddle leg is crossed at entry and exit; a
    ``friction_vol_points`` vol-point half-spread on each of the (near, far)
    straddles, charged via vega at entry and exit (4 straddle-crossings total),
    subtracted from gross.
    """

    v_near0 = straddle_value(leg.spot_entry, leg.near_tenor_entry, leg.near_iv_entry, r=r, q=q)
    v_far0 = straddle_value(leg.spot_entry, leg.far_tenor_entry, leg.far_iv_entry, r=r, q=q)
    v_near1 = straddle_value(leg.spot_exit, leg.near_tenor_exit, leg.near_iv_exit, r=r, q=q)
    v_far1 = straddle_value(leg.spot_exit, leg.far_tenor_exit, leg.far_iv_exit, r=r, q=q)

    vega_near0 = straddle_vega(leg.spot_entry, leg.near_tenor_entry, leg.near_iv_entry, r=r, q=q)
    vega_far0 = straddle_vega(leg.spot_entry, leg.far_tenor_entry, leg.far_iv_entry, r=r, q=q)

    vals = [v_near0, v_far0, v_near1, v_far1, vega_near0, vega_far0]
    if not all(np.isfinite(vals)) or vega_near0 <= 0:
        return float("nan")

    n_far = 1.0
    n_near = vega_far0 / vega_near0  # vega-neutral at entry

    # Long-side calendar (+1): short near (+ when near falls), long far.
    gross = direction * (n_far * (v_far1 - v_far0) - n_near * (v_near1 - v_near0))

    # Friction: half-spread (vol points) x vega, per straddle, entry+exit.
    hs = friction_vol_points * VOL_POINT
    vega_near1 = straddle_vega(leg.spot_exit, leg.near_tenor_exit, leg.near_iv_exit, r=r, q=q)
    vega_far1 = straddle_vega(leg.spot_exit, leg.far_tenor_exit, leg.far_iv_exit, r=r, q=q)
    cost = hs * (
        n_near * (vega_near0 + (vega_near1 if np.isfinite(vega_near1) else vega_near0))
        + n_far * (vega_far0 + (vega_far1 if np.isfinite(vega_far1) else vega_far0))
    )
    return float(gross - cost)


def short_vol_pnl(
    spot_entry: float,
    near_tenor_entry: float,
    near_iv_entry: float,
    spot_exit: float,
    near_tenor_exit: float,
    near_iv_exit: float,
    *,
    friction_vol_points: float = FRICTION_VOL_POINTS,
    r: float = DEFAULT_RISK_FREE_RATE,
    q: float = DEFAULT_DIVIDEND_YIELD,
) -> float:
    """After-cost P&L of shorting ONE near-ATM straddle (the control book leg).

    The unconditional short-vol stance: short the near straddle on every name,
    no slope conditioning. Sized to 1.0 entry-vega-dollar so it is comparable in
    scale to the calendar leg. NaN if unpriceable.
    """

    v0 = straddle_value(spot_entry, near_tenor_entry, near_iv_entry, r=r, q=q)
    v1 = straddle_value(spot_exit, near_tenor_exit, near_iv_exit, r=r, q=q)
    vega0 = straddle_vega(spot_entry, near_tenor_entry, near_iv_entry, r=r, q=q)
    if not all(np.isfinite([v0, v1, vega0])) or vega0 <= 0:
        return float("nan")
    n = 1.0 / vega0  # 1 vega-dollar of short straddle
    gross = -n * (v1 - v0)  # short -> profit when value falls
    hs = friction_vol_points * VOL_POINT
    vega1 = straddle_vega(spot_exit, near_tenor_exit, near_iv_exit, r=r, q=q)
    cost = hs * n * (vega0 + (vega1 if np.isfinite(vega1) else vega0))
    return float(gross - cost)


# --------------------------------------------------------------------------- #
# Cross-sectional book assembly
# --------------------------------------------------------------------------- #
def assign_terciles(slopes: pd.Series) -> pd.Series:
    """Map each name's slope to {+1 (top), 0 (mid), -1 (bottom)} by rank.

    Ties broken by rank order; needs >= 3 non-NaN names. Names with NaN slope are
    dropped (not assigned). Returns an int Series aligned to the non-NaN inputs.
    """

    s = slopes.dropna()
    n = len(s)
    if n < 3:
        return pd.Series(dtype="int64")
    ranks = s.rank(method="first")
    k = int(np.floor(n * TERCILE_FRAC))
    k = max(k, 1)
    out = pd.Series(0, index=s.index, dtype="int64")
    out[ranks <= k] = -1  # lowest slope -> short tercile
    out[ranks > n - k] = +1  # highest slope -> long tercile
    return out


def period_long_short_return(
    legs: pd.DataFrame,
) -> dict[str, float]:
    """One rebalance period's long-short / tercile / short-vol returns.

    ``legs`` has one row per name with columns: ``tercile`` (+1/0/-1),
    ``cal_pnl`` (after-cost calendar P&L if this name were on the long-side
    calendar, direction handled here), ``sv_pnl`` (unconditional short-vol P&L).

    Returns equal-weighted means:
      - ``long_ret``  : mean cal_pnl over the top tercile (long-side calendar)
      - ``short_ret`` : mean of the MIRROR calendar over the bottom tercile
                        (= -cal_pnl, since the mirror flips the calendar)
      - ``ls_ret``    : long_ret + short_ret  (dollar-neutral long-short book)
      - ``sv_ret``    : mean short-vol P&L over ALL names (the control)
      - ``n_long`` / ``n_short`` / ``n_names``
    NaN returns are dropped within each leg.
    """

    df = legs
    top = df[df["tercile"] == 1]["cal_pnl"].dropna()
    bot = df[df["tercile"] == -1]["cal_pnl"].dropna()
    sv = df["sv_pnl"].dropna()

    long_ret = float(top.mean()) if len(top) else float("nan")
    # bottom tercile trades the MIRROR calendar -> P&L = -(long-side P&L)
    short_ret = float((-bot).mean()) if len(bot) else float("nan")
    parts = [r for r in (long_ret, short_ret) if np.isfinite(r)]
    ls_ret = float(np.sum(parts)) if parts else float("nan")
    sv_ret = float(sv.mean()) if len(sv) else float("nan")
    return {
        "long_ret": long_ret,
        "short_ret": short_ret,
        "ls_ret": ls_ret,
        "sv_ret": sv_ret,
        "n_long": len(top),
        "n_short": len(bot),
        "n_names": len(df),
    }


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
def tstat(x: np.ndarray | pd.Series) -> float:
    """One-sample t-stat of the mean vs 0 (NaN-dropped). NaN if < 2 obs or zero var."""

    a = np.asarray(pd.Series(x).dropna(), dtype=float)
    if a.size < 2:
        return float("nan")
    sd = a.std(ddof=1)
    if sd == 0:
        return float("nan")
    return float(a.mean() / (sd / np.sqrt(a.size)))


def annualize_mean(per_period_mean: float, periods_per_year: float) -> float:
    """Scale a per-period mean return to annual (simple, additive)."""

    return per_period_mean * periods_per_year


def incremental_alpha(ls: np.ndarray | pd.Series, sv: np.ndarray | pd.Series) -> dict[str, float]:
    """Regress the slope book return on the short-vol book return; report the alpha.

    The KEY control: ``ls = alpha + beta * sv + eps``. If the slope book's edge is
    just short-vol beta, alpha collapses to ~0 / |t| < 2. Returns
    ``{alpha, alpha_t, beta, n}`` (alpha is per-period). Pairs are aligned and
    NaN rows dropped. NaN alpha if < 3 paired obs or no variance in sv.
    """

    df = pd.DataFrame({"ls": pd.Series(ls).reset_index(drop=True),
                       "sv": pd.Series(sv).reset_index(drop=True)}).dropna()
    n = len(df)
    if n < 3:
        return {"alpha": float("nan"), "alpha_t": float("nan"), "beta": float("nan"), "n": n}
    x = df["sv"].to_numpy()
    y = df["ls"].to_numpy()
    if x.std() == 0:
        # no variance to regress on; alpha is just the mean of y
        return {"alpha": float(y.mean()), "alpha_t": tstat(y), "beta": 0.0, "n": n}
    X = np.column_stack([np.ones(n), x])
    beta_hat, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta_hat
    dof = n - 2
    if dof < 1:
        return {"alpha": float(beta_hat[0]), "alpha_t": float("nan"), "beta": float(beta_hat[1]), "n": n}
    sigma2 = (resid @ resid) / dof
    xtx_inv = np.linalg.inv(X.T @ X)
    se_alpha = float(np.sqrt(sigma2 * xtx_inv[0, 0]))
    alpha = float(beta_hat[0])
    alpha_t = alpha / se_alpha if se_alpha > 0 else float("nan")
    return {"alpha": alpha, "alpha_t": float(alpha_t), "beta": float(beta_hat[1]), "n": n}


def placebo_pvalue(
    per_period_legs: list[pd.DataFrame],
    observed_ls_mean: float,
    *,
    k: int = 500,
    seed: int = 12345,
) -> float:
    """Permutation p-value: shuffle tercile labels within each period, recompute LS.

    For each of ``k`` draws we randomly re-assign the +1/0/-1 tercile labels
    (preserving the per-period counts) and recompute the long-short mean across
    periods; the p-value is the fraction of shuffled means >= the observed mean
    (one-sided, since the hypothesis is a positive LS return). A real slope edge
    yields p small; pure noise yields p ~ 0.5.
    """

    rng = np.random.default_rng(seed)
    sign_count = 0
    valid = 0
    for _ in range(k):
        shuffled_means = []
        for legs in per_period_legs:
            if legs.empty:
                continue
            shuf = legs.copy()
            shuf["tercile"] = rng.permutation(shuf["tercile"].to_numpy())
            res = period_long_short_return(shuf)
            if np.isfinite(res["ls_ret"]):
                shuffled_means.append(res["ls_ret"])
        if shuffled_means:
            valid += 1
            if np.mean(shuffled_means) >= observed_ls_mean:
                sign_count += 1
    if valid == 0:
        return float("nan")
    return float(sign_count / valid)


def summarize(ls_series: pd.Series, sv_series: pd.Series) -> dict[str, float]:
    """Headline stats for a per-period return series: mean, t, win rate, tail."""

    a = pd.Series(ls_series).dropna()
    if a.empty:
        return {}
    mean = float(a.mean())
    t = tstat(a)
    win = float((a > 0).mean())
    sd = float(a.std(ddof=1)) if len(a) > 1 else float("nan")
    sharpe = mean / sd if sd and sd > 0 else float("nan")
    cum = a.cumsum()
    running_max = cum.cummax()
    max_dd = float((cum - running_max).min())  # most-negative drawdown in cum P&L
    worst = float(a.min())
    return {
        "n": len(a),
        "mean": mean,
        "t": float(t),
        "win_rate": win,
        "sd": sd,
        "sharpe_per_period": float(sharpe),
        "worst_period": worst,
        "max_drawdown": max_dd,
        "median": float(a.median()),
    }
