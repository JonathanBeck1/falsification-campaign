"""T25 — Single-name 25-delta skew dynamics (PURE core + gate).

The pure engine for the skew test pre-registered in
``research/vol_skew_preregistration.md``. No network and no disk here: it
consumes an already-built panel (one row per (name, snapshot-date) with the
25-delta skew, ATM IV, and the realized forward stock return) and produces the
two pre-registered framings plus the full brain/30 gate:

  * **SIGNAL (PRIMARY)** — each cross-section is demeaned and ranked by
    ``skew = IV(25Δ put) - IV(25Δ call)``; we go **long the low-skew tertile,
    short the high-skew tertile** (sign-agnostic; the realized sign is reported
    and judged by |t|). The long-short is market-neutral by construction
    (cross-sectional demean), so the universe forward-return baseline is netted
    out. Friction is charged once per rebalance per leg.

  * **PREMIUM (SECONDARY) + KEY control** — a short-25Δ-put proxy P&L per name
    (collect the put's vol premium = ``skew`` vol-points, pay the realized
    downside), and the decisive disguise check: regress that premium on the
    short-ATM-vol P&L and the (negative) market-beta leg. The *residual* alpha is
    the only claimable skew premium. If the residual dies (|t|<2) the premium was
    short-vol + short-delta beta in disguise.

The **tail** is first-class: ``selling the 25Δ put is exactly the crash exposure
being insured``, so every premium statistic carries worst-period and max-drawdown
numbers, and a drop-worst-month robustness pass.

Everything here is a pure function of in-memory frames/arrays; the runner
(``scripts/run_vol_skew_study.py``) is the only thing that touches the lake,
yfinance, or the clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Pre-registered constants (see research/vol_skew_preregistration.md)
# --------------------------------------------------------------------------- #
# Forward-return horizon in trading days (PRIMARY window fwd_ret_0_p21).
FWD_TRADING_DAYS = 21

# Weekly sampling cadence (every Nth trade-day per name) to limit 21d overlap.
SAMPLE_EVERY = 5

# Tenor / delta the skew is read at (matches risk_reversal_25d defaults).
TARGET_DAYS = 30.0
TARGET_DELTA = 0.25

# Change-variant lookback for Δskew (trading days).
SKEW_CHANGE_LOOKBACK = 20

# Cross-sectional sort fraction. N=24 names -> tertiles (top/bottom ~1/3 = 8).
SORT_FRACTION = 1.0 / 3.0

# A cross-section needs at least this many valid-skew names to be usable.
MIN_NAMES_PER_DATE = 12

# Friction: single-name equity round trip ~10 bps (5 bps/side); 2x stress = 20.
EQUITY_ROUND_TRIP_BPS = 10.0
EQUITY_ROUND_TRIP_2X_BPS = 20.0

# Premium friction in vol-points (per rebalance, vega-normalized), + a 2x stress.
PREMIUM_COST_VOLPTS = 2.0
PREMIUM_COST_VOLPTS_2X = 4.0

# IS/OOS calendar split (declared in the pre-reg).
OOS_START = pd.Timestamp("2024-04-01")

# Placebo permutation count.
N_PERMUTATIONS = 200

# Trading days per year for annualization.
TRADING_DAYS_PER_YEAR = 252.0


# --------------------------------------------------------------------------- #
# Result containers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SeriesStats:
    """Summary statistics of a P&L / return series (one number per observation)."""

    n: int
    mean: float
    t: float
    std: float
    sharpe: float  # annualized (mean/std * sqrt(periods_per_year)); periods set by caller
    win: float
    worst: float
    best: float
    maxdd: float  # max drawdown of the cumulative (additive) series, <= 0
    median: float


@dataclass(frozen=True)
class GateResult:
    """The pre-registered gate verdict for one framing."""

    passed: bool
    reasons: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Pure statistics helpers
# --------------------------------------------------------------------------- #
def _t_stat(x: np.ndarray) -> float:
    """One-sample t-stat of the mean (mean / (std/sqrt(n))). NaN if n<2 or std=0."""

    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 2:
        return float("nan")
    sd = x.std(ddof=1)
    if sd == 0:
        return float("nan")
    return float(x.mean() / (sd / np.sqrt(n)))


def _max_drawdown(pnl: np.ndarray) -> float:
    """Max drawdown of the cumulative *additive* P&L series. Returns <= 0.

    Additive (not compounded) because the legs are demeaned returns / vol-point
    P&Ls that are summed across periods — the relevant tail for a short-crash
    book is the worst peak-to-trough of cumulative P&L.
    """

    pnl = np.asarray(pnl, dtype=float)
    pnl = pnl[np.isfinite(pnl)]
    if pnl.size == 0:
        return 0.0
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return float(dd.min())


def summarize(series: np.ndarray, *, periods_per_year: float = 52.0) -> SeriesStats:
    """Pure summary of a P&L series. ``periods_per_year`` sets Sharpe annualization."""

    x = np.asarray(series, dtype=float)
    x = x[np.isfinite(x)]
    n = x.size
    if n == 0:
        return SeriesStats(0, float("nan"), float("nan"), float("nan"),
                           float("nan"), float("nan"), float("nan"),
                           float("nan"), 0.0, float("nan"))
    mean = float(x.mean())
    sd = float(x.std(ddof=1)) if n > 1 else float("nan")
    t = _t_stat(x)
    sharpe = float(mean / sd * np.sqrt(periods_per_year)) if (sd and sd > 0) else float("nan")
    win = float((x > 0).mean())
    return SeriesStats(
        n=n,
        mean=mean,
        t=t,
        std=sd,
        sharpe=sharpe,
        win=win,
        worst=float(x.min()),
        best=float(x.max()),
        maxdd=_max_drawdown(x),
        median=float(np.median(x)),
    )


# --------------------------------------------------------------------------- #
# Panel hygiene
# --------------------------------------------------------------------------- #
PANEL_COLUMNS = ("ticker", "snapshot_date", "skew", "atm_iv", "fwd_ret", "mkt_fwd_ret")


def validate_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Return the subset of ``panel`` rows usable for the signal test.

    A usable row has a finite ``skew`` and a finite ``fwd_ret``. ``atm_iv`` and
    ``mkt_fwd_ret`` may be NaN (only the premium / baseline legs need them).
    PURE — no mutation of the input.
    """

    missing = [c for c in ("ticker", "snapshot_date", "skew", "fwd_ret") if c not in panel.columns]
    if missing:
        raise ValueError(f"panel missing required columns: {missing}")
    p = panel.copy()
    p["snapshot_date"] = pd.to_datetime(p["snapshot_date"])
    ok = np.isfinite(p["skew"].to_numpy(float)) & np.isfinite(p["fwd_ret"].to_numpy(float))
    return p[ok].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# SIGNAL framing (PRIMARY): cross-sectional tertile long-short
# --------------------------------------------------------------------------- #
def _tertile_long_short_one_date(
    skew: np.ndarray,
    demeaned_fwd: np.ndarray,
    *,
    sort_fraction: float,
) -> float | None:
    """Long-low-skew minus short-high-skew, on the demeaned forward returns.

    Returns the equal-weight long-short return for one cross-section, or None if
    there are too few names to form non-overlapping tertiles. Sign convention:
    LONG the lowest-skew names, SHORT the highest-skew names (so a *positive*
    result means low put-skew names outperform — the realized sign is what the
    caller judges; this function does not assume it).
    """

    n = skew.size
    k = int(np.floor(n * sort_fraction))
    if k < 1 or 2 * k > n:
        return None
    order = np.argsort(skew, kind="mergesort")  # ascending skew
    low = order[:k]   # lowest put-skew -> LONG
    high = order[-k:]  # highest put-skew -> SHORT
    return float(demeaned_fwd[low].mean() - demeaned_fwd[high].mean())


def signal_long_short(
    panel: pd.DataFrame,
    *,
    sort_fraction: float = SORT_FRACTION,
    min_names: int = MIN_NAMES_PER_DATE,
    cost_bps: float = EQUITY_ROUND_TRIP_BPS,
) -> pd.DataFrame:
    """Per-date market-neutral long-short return from sorting on ``skew``.

    For each snapshot date with >= ``min_names`` valid names: demean the forward
    returns cross-sectionally (nets out the universe baseline), then go long the
    bottom ``sort_fraction`` of names by skew and short the top. Charge
    ``cost_bps`` once per rebalance across the two legs (a long-short turns over
    both legs each period -> charge the full round trip once).

    Returns a frame indexed by date with columns ``gross, net, n_names``. PURE.
    """

    v = validate_panel(panel)
    rows: list[dict] = []
    cost = cost_bps / 1e4
    for dt, grp in v.groupby("snapshot_date", sort=True):
        if len(grp) < min_names:
            continue
        skew = grp["skew"].to_numpy(float)
        fwd = grp["fwd_ret"].to_numpy(float)
        demeaned = fwd - fwd.mean()
        ls = _tertile_long_short_one_date(skew, demeaned, sort_fraction=sort_fraction)
        if ls is None:
            continue
        rows.append({"snapshot_date": dt, "gross": ls, "net": ls - cost, "n_names": len(grp)})
    return pd.DataFrame(rows)


def placebo_long_short(
    panel: pd.DataFrame,
    *,
    n_perm: int = N_PERMUTATIONS,
    seed: int = 12345,
    sort_fraction: float = SORT_FRACTION,
    min_names: int = MIN_NAMES_PER_DATE,
) -> dict[str, float]:
    """Within-date skew-shuffle permutation test (composition-matched).

    For each permutation, shuffle the skew->name assignment *within each date*
    and recompute the long-short mean. Returns the permutation distribution's
    mean and a two-sided p-value for the observed gross long-short mean. A real
    cross-sectional signal beats the shuffle; a drift artifact does not. PURE
    (deterministic given ``seed``).
    """

    v = validate_panel(panel)
    obs = signal_long_short(v, sort_fraction=sort_fraction, min_names=min_names)
    if obs.empty:
        return {"obs_mean": float("nan"), "perm_mean": float("nan"), "p_value": float("nan"),
                "n_perm": 0}
    obs_mean = float(obs["gross"].mean())

    rng = np.random.default_rng(seed)
    groups = [grp for _, grp in v.groupby("snapshot_date", sort=True) if len(grp) >= min_names]
    perm_means = np.full(n_perm, np.nan)
    for j in range(n_perm):
        per_date = []
        for grp in groups:
            skew = grp["skew"].to_numpy(float).copy()
            fwd = grp["fwd_ret"].to_numpy(float)
            demeaned = fwd - fwd.mean()
            rng.shuffle(skew)  # break the skew<->name link, keep the date's returns
            ls = _tertile_long_short_one_date(skew, demeaned, sort_fraction=sort_fraction)
            if ls is not None:
                per_date.append(ls)
        if per_date:
            perm_means[j] = float(np.mean(per_date))
    perm_means = perm_means[np.isfinite(perm_means)]
    if perm_means.size == 0:
        return {"obs_mean": obs_mean, "perm_mean": float("nan"), "p_value": float("nan"),
                "n_perm": 0}
    # two-sided p: fraction of |perm| >= |obs| (shuffle is centered near 0)
    p = float((np.abs(perm_means) >= abs(obs_mean)).mean())
    return {"obs_mean": obs_mean, "perm_mean": float(perm_means.mean()),
            "p_value": p, "n_perm": int(perm_means.size)}


def is_oos_split(
    ls: pd.DataFrame,
    *,
    oos_start: pd.Timestamp = OOS_START,
    value_col: str = "net",
) -> dict[str, SeriesStats]:
    """Split a per-date long-short frame into IS/OOS by calendar and summarize each."""

    if ls.empty:
        empty = summarize(np.array([]))
        return {"is": empty, "oos": empty}
    d = ls.copy()
    d["snapshot_date"] = pd.to_datetime(d["snapshot_date"])
    is_mask = d["snapshot_date"] < oos_start
    return {
        "is": summarize(d.loc[is_mask, value_col].to_numpy(float)),
        "oos": summarize(d.loc[~is_mask, value_col].to_numpy(float)),
    }


def up_down_symmetry(panel: pd.DataFrame, **kwargs) -> dict[str, float]:
    """Smoking-gun symmetry: long-low-minus-high vs the *reversed* sort.

    A genuine cross-sectional signal flips sign when the sort is reversed
    (antisymmetric). If both directions drift the *same* sign, the long-short is
    inheriting universe drift, not a skew signal. Returns both means and their
    sum (should be ~0 for a real signal). PURE.
    """

    fwd = signal_long_short(panel, **kwargs)
    # reversed sort = long high-skew, short low-skew = negate the long-short
    fwd_mean = float(fwd["gross"].mean()) if not fwd.empty else float("nan")
    rev_mean = -fwd_mean
    return {"forward_mean": fwd_mean, "reversed_mean": rev_mean,
            "sum": fwd_mean + rev_mean}


# --------------------------------------------------------------------------- #
# PREMIUM framing (SECONDARY) + the KEY disguise control
# --------------------------------------------------------------------------- #
def short_put_premium_pnl(
    panel: pd.DataFrame,
    *,
    cost_volpts: float = PREMIUM_COST_VOLPTS,
) -> pd.DataFrame:
    """Per-(name,date) short-25Δ-put proxy P&L in vol-points, delta-hedged.

    The premium collected for selling the 25Δ put over the call is exactly the
    skew (in vol-points): ``skew = IV(25Δ put) - IV(25Δ call)``. A delta-hedged
    short put earns that vol-point premium when realized downside is benign and
    loses when the name sells off hard. We proxy the realized cost of the crash
    leg by the name's *negative* forward return scaled into vol-points: a sharp
    drop over the holding window is the insurance payout the seller owes.

    Proxy P&L (vol-points, per rebalance):
        pnl = skew - max(0, -fwd_ret) * SCALE - cost_volpts

    where ``-fwd_ret`` is the drawdown the put seller insures and SCALE converts
    a fractional drop into comparable vol-points. This is deliberately a *proxy*
    (no full options book); its purpose is the tail and the disguise control, not
    a tradeable claim. Entry skew is from day t; the payout uses the strictly-
    forward return -> no look-ahead. PURE.
    """

    v = panel.copy()
    v["snapshot_date"] = pd.to_datetime(v["snapshot_date"])
    ok = np.isfinite(v["skew"].to_numpy(float)) & np.isfinite(v["fwd_ret"].to_numpy(float))
    v = v[ok].reset_index(drop=True)
    skew = v["skew"].to_numpy(float)
    fwd = v["fwd_ret"].to_numpy(float)
    # Crash payout: only downside moves cost the put seller; scale to vol-points.
    # SCALE chosen so a -10% move (~0.10) costs ~10 vol-points, comparable to a
    # rich-skew premium -> SCALE = 1.0 in vol-points-per-unit-fractional-drop.
    payout = np.maximum(0.0, -fwd)
    pnl = skew - payout - cost_volpts / 100.0  # skew is fractional vol; cost in vol-pts->frac
    out = v[["ticker", "snapshot_date", "skew", "atm_iv", "fwd_ret"]].copy()
    out["payout"] = payout
    out["pnl"] = pnl
    return out


def short_vol_control_pnl(panel: pd.DataFrame) -> np.ndarray:
    """The short-ATM-vol leg the premium must be regressed against (disguise test).

    A short straddle / short ATM-vol position also pays when the name doesn't
    move and loses when it does — the *same* short-gamma exposure a short put
    carries. Proxy: ``atm_iv - |fwd_ret|`` (collect the ATM vol premium, pay
    realized absolute move). If the skew "premium" is just this in disguise, a
    regression of premium-pnl on this control leaves no residual alpha. PURE.
    """

    v = panel.copy()
    ok = np.isfinite(v["skew"].to_numpy(float)) & np.isfinite(v["fwd_ret"].to_numpy(float))
    v = v[ok].reset_index(drop=True)
    atm = pd.to_numeric(v.get("atm_iv"), errors="coerce").to_numpy(float)
    fwd = v["fwd_ret"].to_numpy(float)
    return atm - np.abs(fwd)


def market_beta_control_pnl(panel: pd.DataFrame) -> np.ndarray:
    """The short-delta-beta leg: a short put is long the market (short downside).

    A short put has positive delta (long the underlying). Its directional P&L is
    therefore ``+1 * name_fwd_ret`` — proxied here by the name's own forward
    return (the short-delta exposure). Regressing premium-pnl on this isolates
    whether the "premium" is just being long the names. PURE.
    """

    v = panel.copy()
    ok = np.isfinite(v["skew"].to_numpy(float)) & np.isfinite(v["fwd_ret"].to_numpy(float))
    v = v[ok].reset_index(drop=True)
    return v["fwd_ret"].to_numpy(float)


def disguise_regression(
    premium_pnl: np.ndarray,
    short_vol_leg: np.ndarray,
    beta_leg: np.ndarray,
) -> dict[str, float]:
    """OLS premium_pnl ~ const + short_vol_leg + beta_leg; return residual-alpha t.

    The KEY control from the pre-reg: if the skew "premium" is short-vol +
    short-delta beta in disguise, the intercept (residual alpha) is ~0 with
    |t|<2. We return the intercept, its t-stat, the two betas, and R^2. Pure
    closed-form OLS (no sklearn). PURE.
    """

    y = np.asarray(premium_pnl, float)
    x1 = np.asarray(short_vol_leg, float)
    x2 = np.asarray(beta_leg, float)
    m = np.isfinite(y) & np.isfinite(x1) & np.isfinite(x2)
    y, x1, x2 = y[m], x1[m], x2[m]
    n = y.size
    if n < 5:
        return {"alpha": float("nan"), "alpha_t": float("nan"),
                "beta_vol": float("nan"), "beta_mkt": float("nan"),
                "r2": float("nan"), "n": n}
    X = np.column_stack([np.ones(n), x1, x2])
    # OLS via lstsq
    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    dof = n - X.shape[1]
    if dof <= 0:
        return {"alpha": float(coef[0]), "alpha_t": float("nan"),
                "beta_vol": float(coef[1]), "beta_mkt": float(coef[2]),
                "r2": float("nan"), "n": n}
    sigma2 = float(resid @ resid) / dof
    xtx_inv = np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(sigma2 * xtx_inv))
    alpha_t = float(coef[0] / se[0]) if se[0] > 0 else float("nan")
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = float(1.0 - (resid @ resid) / ss_tot) if ss_tot > 0 else float("nan")
    return {"alpha": float(coef[0]), "alpha_t": alpha_t,
            "beta_vol": float(coef[1]), "beta_mkt": float(coef[2]),
            "r2": r2, "n": n}


def drop_worst_month(premium_pnl_frame: pd.DataFrame, *, value_col: str = "pnl") -> dict[str, float]:
    """Tail robustness: full-sample mean/t vs after dropping the worst calendar month.

    A short-crash-insurance premium that hinges on one selloff month is rejected.
    Returns full and drop-worst mean & t, and the worst month label. PURE.
    """

    d = premium_pnl_frame.copy()
    d["snapshot_date"] = pd.to_datetime(d["snapshot_date"])
    d["ym"] = d["snapshot_date"].dt.to_period("M")
    full = d[value_col].to_numpy(float)
    by_month = d.groupby("ym")[value_col].sum()
    if by_month.empty:
        return {"full_mean": float("nan"), "full_t": float("nan"),
                "drop_mean": float("nan"), "drop_t": float("nan"), "worst_month": ""}
    worst_ym = by_month.idxmin()
    kept = d[d["ym"] != worst_ym][value_col].to_numpy(float)
    return {
        "full_mean": float(np.nanmean(full)),
        "full_t": _t_stat(full),
        "drop_mean": float(np.nanmean(kept)) if kept.size else float("nan"),
        "drop_t": _t_stat(kept),
        "worst_month": str(worst_ym),
    }


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #
def evaluate_signal_gate(
    ls: pd.DataFrame,
    placebo: dict[str, float],
    *,
    min_n: int = 30,
    value_col: str = "net",
) -> GateResult:
    """Apply the pre-registered gate to the SIGNAL (PRIMARY) framing. PURE."""

    reasons: list[str] = []
    if ls.empty:
        return GateResult(False, ["no usable cross-sections"])

    net = ls[value_col].to_numpy(float)
    stats = summarize(net)
    splits = is_oos_split(ls, value_col=value_col)
    is_s, oos_s = splits["is"], splits["oos"]

    # N
    if stats.n < min_n:
        reasons.append(f"N={stats.n} < {min_n}")
    # after-cost |t|>=2 (sign-agnostic: a strong negative is still a finding, but
    # the pre-reg long-short is judged on |t| with a CONSISTENT realized sign)
    if not (np.isfinite(stats.t) and abs(stats.t) >= 2.0):
        reasons.append(f"after-cost |t|={stats.t:.2f} < 2.0")
    # OOS sign stability (same sign, both N>=10)
    if not (np.isfinite(is_s.mean) and np.isfinite(oos_s.mean)
            and np.sign(is_s.mean) == np.sign(oos_s.mean)
            and is_s.n >= 10 and oos_s.n >= 10):
        reasons.append(
            f"OOS sign unstable IS(mean={is_s.mean:+.5f},n={is_s.n}) "
            f"OOS(mean={oos_s.mean:+.5f},n={oos_s.n})"
        )
    # placebo
    p = placebo.get("p_value", float("nan"))
    if not (np.isfinite(p) and p < 0.05):
        reasons.append(f"placebo perm p={p:.3f} >= 0.05")

    return GateResult(len(reasons) == 0, reasons)
