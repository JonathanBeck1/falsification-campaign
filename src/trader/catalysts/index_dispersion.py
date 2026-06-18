"""T22 — index dispersion / correlation risk premium (PURE core).

This is the **pure, unit-tested core** for test T22, the last and most
structurally-interesting single-name vol-surface test. It contains no I/O: every
function is a deterministic function of in-memory numbers / frames. The thin
runner (`scripts/run_index_dispersion_study.py`) is the only part that touches
the option lake; it feeds this module the per-(name, date) ATM-straddle marks and
this module turns them into the pre-registered, vega-neutral dispersion book and
its gate metrics.

See `research/index_dispersion_preregistration.md` for the fixed design.

### The mechanism being tested

Index implied variance embeds an **implied average correlation** among its
constituents. Decomposing the index variance into constituent variances plus
cross-covariances::

    sigma_index^2  =  sum_i w_i^2 sigma_i^2  +  rho * ( sum_i!=j w_i w_j sigma_i sigma_j )

so the *implied* average correlation backed out of option-implied vols is::

    rho_imp  =  ( sigma_index^2 - sum_i w_i^2 sigma_i^2 )
                / ( (sum_i w_i sigma_i)^2 - sum_i w_i^2 sigma_i^2 )

The well-documented "correlation risk premium" is that ``rho_imp`` is
*structurally higher* than the correlation that subsequently realizes — index
options are richer than a basket of single-name options. Harvesting it is the
**dispersion trade**: SHORT the index straddle, LONG a vega-matched basket of
single-name straddles. It earns when names move *apart* (low realized
correlation) more than the option market priced.

### Why it is a prime "compensated-risk / beta-in-disguise" suspect (class 7)

Dispersion is short correlation. Correlation spikes to ~1 in every crash (2022
selloffs, the Aug-2024 carry unwind), so the dispersion book takes a large loss
exactly when everything falls together. Any positive average return is therefore
a candidate for *compensation for correlation-crash risk*, not alpha. The gate's
KEY controls below regress the book against (a) a pure short-index-vol stance and
(b) the realized-move/crash magnitude, so a return that is only short-vol beta or
only crash compensation collapses to ~0 incremental alpha.

### Friction is the crux ("expensive to harvest")

The long leg is ~27 single-name straddles, whose quoted bid/ask is far wider than
the index's. Rather than assume a friction, the runner charges the **realized
half-spread from the actual ATM quotes** in the lake (call+put, per leg, crossed
at entry and exit). This is where the pre-registered note's "structurally
capacity-limited - expensive to harvest" is put to the test with real spreads.

### Provenance / data-quality guard

Straddle marks come from the shared `vol_surface_data` foundation (parity-anchored
spot, two-sided quotes only, IV quality band). One extra guard lives here: a
constituent that **splits** between entry and exit shows a spurious ~-66%..-95%
"return" in the unadjusted parity spot (NVDA/AVGO 10:1, AMZN/GOOGL 20:1, TSLA
3:1 all in-window), which would fabricate enormous straddle P&L. Any name-period
whose entry->exit underlying return exceeds :data:`SPLIT_RETURN_GUARD` in
magnitude is dropped from that period (counted, reported) — no real mega-cap moves
that far in a ~2-week hold, so the guard is split-specific.
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
ATM_TARGET_DAYS = 30.0  # tenor we trade the dispersion book at
REBALANCE_STEP = 21  # trading days between (non-overlapping) rebalances
HOLD_DAYS = 10  # trading-day holding horizon (~14 calendar days)
MIN_BASKET_NAMES = 5  # a period needs at least this many priceable constituents

# A name-period whose |entry->exit underlying return| exceeds this is treated as
# a corporate-action (split) artifact and dropped from that period. The smallest
# split in the universe is TSLA 3:1 (-66.7%); the largest real 2-week mega-cap
# move is far short of 50%, so 0.50 is split-specific and never trims a real move.
SPLIT_RETURN_GUARD = 0.50

IS_END = pd.Timestamp("2024-03-31")  # IS: .. 2024-03-31 ; OOS: 2024-04-01 ..
PERIODS_PER_YEAR = 252.0 / REBALANCE_STEP  # ~12


# --------------------------------------------------------------------------- #
# Straddle value / vega (ATM call+put), pure — mirror vol_term_structure
# --------------------------------------------------------------------------- #
def straddle_value(
    spot: float,
    tenor_days: float,
    iv: float,
    *,
    strike: float | None = None,
    r: float = DEFAULT_RISK_FREE_RATE,
    q: float = DEFAULT_DIVIDEND_YIELD,
) -> float:
    """Black-Scholes value of a (near-ATM) straddle = call + put at ``strike``.

    ``strike`` defaults to ``spot`` (true ATM). Passing the *entry* strike lets a
    caller reprice the SAME contracts at exit. NaN-safe: returns NaN if any input
    is non-finite or tenor/iv/spot <= 0.
    """

    k = spot if strike is None else strike
    if not all(np.isfinite([spot, tenor_days, iv, k])) or spot <= 0 or tenor_days <= 0 or iv <= 0:
        return float("nan")
    T = tenor_days / DAYS_PER_YEAR
    call = float(bs_price(spot, k, T, iv, True, r=r, q=q))
    put = float(bs_price(spot, k, T, iv, False, r=r, q=q))
    return call + put


def straddle_vega(
    spot: float,
    tenor_days: float,
    iv: float,
    *,
    strike: float | None = None,
    r: float = DEFAULT_RISK_FREE_RATE,
    q: float = DEFAULT_DIVIDEND_YIELD,
) -> float:
    """BS vega of a straddle = vega(call) + vega(put) (equal for matched K). NaN-safe."""

    k = spot if strike is None else strike
    if not all(np.isfinite([spot, tenor_days, iv, k])) or spot <= 0 or tenor_days <= 0 or iv <= 0:
        return float("nan")
    T = tenor_days / DAYS_PER_YEAR
    return 2.0 * float(bs_vega(spot, k, T, iv, r=r, q=q))


# --------------------------------------------------------------------------- #
# Implied / realized average correlation (the mechanism descriptors)
# --------------------------------------------------------------------------- #
def implied_correlation(
    index_iv: float,
    constituent_ivs: np.ndarray | pd.Series,
    weights: np.ndarray | pd.Series,
) -> float:
    """Average implied correlation backed out of index vs constituent IVs.

    Inverts the index-variance decomposition (module docstring)::

        rho_imp = ( sig_idx^2 - sum w_i^2 sig_i^2 )
                  / ( (sum w_i sig_i)^2 - sum w_i^2 sig_i^2 )

    All IVs are annualized decimals. ``weights`` need not be normalized; they are
    normalized to sum 1 here (the formula is scale-free in w only after
    normalization). Returns NaN if fewer than two finite constituents or the
    cross-term denominator is ~0. The result is the "dirty"/proxy implied
    correlation (CBOE COR-style): it is not clipped, so a value >1 or <0 is
    surfaced honestly (it flags a basket/index composition mismatch rather than
    being silently hidden).
    """

    sig = np.asarray(constituent_ivs, dtype=float)
    w = np.asarray(weights, dtype=float)
    if sig.shape != w.shape:
        return float("nan")
    ok = np.isfinite(sig) & np.isfinite(w) & (sig > 0) & (w > 0)
    sig, w = sig[ok], w[ok]
    if sig.size < 2 or not np.isfinite(index_iv) or index_iv <= 0:
        return float("nan")
    w = w / w.sum()
    sum_w2_var = float(np.sum(w * w * sig * sig))
    sum_wsig = float(np.sum(w * sig))
    cross = sum_wsig * sum_wsig - sum_w2_var
    if abs(cross) < 1e-12:
        return float("nan")
    return float((index_iv * index_iv - sum_w2_var) / cross)


def realized_correlation(
    index_ret: np.ndarray | pd.Series,
    constituent_rets: pd.DataFrame,
    weights: np.ndarray | pd.Series,
) -> float:
    """Average realized correlation over a return window, same decomposition.

    Uses realized vols/covariances from the daily-return path so it is the
    apples-to-apples realized counterpart of :func:`implied_correlation`::

        rho_real = ( var(index) - sum w_i^2 var_i )
                   / ( (sum w_i sd_i)^2 - sum w_i^2 var_i )

    ``constituent_rets`` is a (T x N) frame of daily returns; ``weights`` aligns
    to its columns. Returns NaN if < 2 names or < 3 return rows or a ~0
    denominator. PURE; a *diagnostic* only — the gate runs on realized straddle
    P&L, not on this number.
    """

    rets = constituent_rets.dropna(axis=1, how="all")
    if rets.shape[1] < 2 or rets.shape[0] < 3:
        return float("nan")
    w = pd.Series(weights, index=constituent_rets.columns).reindex(rets.columns).to_numpy(dtype=float)
    ok = np.isfinite(w) & (w > 0)
    if ok.sum() < 2:
        return float("nan")
    rets = rets.iloc[:, ok]
    w = w[ok]
    w = w / w.sum()
    sd = rets.std(ddof=1).to_numpy(dtype=float)
    var_index = float(np.asarray(pd.Series(index_ret).dropna(), dtype=float).var(ddof=1))
    sum_w2_var = float(np.sum(w * w * sd * sd))
    sum_wsd = float(np.sum(w * sd))
    cross = sum_wsd * sum_wsd - sum_w2_var
    if abs(cross) < 1e-12 or not np.isfinite(var_index):
        return float("nan")
    return float((var_index - sum_w2_var) / cross)


# --------------------------------------------------------------------------- #
# Per-name ATM straddle mark (value + vega + realized half-spread)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StraddleMark:
    """One name's ATM straddle at one date: mid value, vega, quoted half-spread.

    ``half_spread`` is the *dollar* cost to cross both legs once =
    0.5 * [(ask_c - bid_c) + (ask_p - bid_p)] at the chosen ATM strike — the
    realized friction, taken from the actual quotes, not an assumption.
    ``strike``/``expiration`` pin the exact contracts so the exit can reprice the
    SAME ones. NaN value marks an unpriceable name-date.
    """

    value: float
    vega: float
    half_spread: float
    spot: float
    strike: float
    tenor_days: float
    iv: float
    expiration: pd.Timestamp | None = None

    @property
    def ok(self) -> bool:
        return bool(np.isfinite(self.value) and np.isfinite(self.vega) and self.vega > 0)


# --------------------------------------------------------------------------- #
# The dispersion book over one rebalance period
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DispersionLeg:
    """A constituent's entry mark, its same-contract exit value, and its weight."""

    name: str
    entry: StraddleMark
    exit_value: float  # value of the SAME (strike, expiration) straddle at exit
    exit_half_spread: float
    weight: float


def dispersion_period_pnl(
    index_entry: StraddleMark,
    index_exit_value: float,
    index_exit_half_spread: float,
    basket: list[DispersionLeg],
    *,
    charge_friction: bool = True,
) -> dict[str, float]:
    """After-cost dispersion P&L for one rebalance period, normalized.

    Book: SHORT 1 index straddle; LONG a basket of single-name straddles sized
    **vega-neutral** to the index, with intra-basket vega split by ``weight``::

        n_i  =  w_i * vega_index / vega_i        (so sum_i n_i vega_i = vega_index)

    Gross P&L (per 1 short index straddle)::

        long basket   :  sum_i n_i * (V_i_exit - V_i_entry)
        short index   :  -(V_idx_exit - V_idx_entry)

    Friction: every straddle crossed at entry AND exit, charged at the actual
    quoted half-spread (entry spread for the entry cross, exit spread for the exit
    cross). Normalized by the index straddle entry premium so periods are
    comparable and the t-stat is on a return-like series::

        dispersion_return = (gross - cost) / V_idx_entry

    Returns a dict with the decomposed pieces so the runner can run the KEY
    controls (short-index-vol-only, long-basket-only). NaN-return if the index leg
    or < MIN_BASKET_NAMES constituent legs are unpriceable.
    """

    if not index_entry.ok or not np.isfinite(index_exit_value) or index_entry.value <= 0:
        return _nan_pnl()
    legs = [lg for lg in basket if lg.entry.ok and np.isfinite(lg.exit_value)]
    if len(legs) < MIN_BASKET_NAMES:
        return _nan_pnl()

    w = np.array([lg.weight for lg in legs], dtype=float)
    if not np.all(np.isfinite(w)) or w.sum() <= 0:
        return _nan_pnl()
    w = w / w.sum()

    vega_idx = index_entry.vega
    # n_i = w_i * vega_idx / vega_i  -> each name supplies w_i * vega_idx of vega.
    n_i = np.array([w[k] * vega_idx / lg.entry.vega for k, lg in enumerate(legs)], dtype=float)

    dV_basket = np.array([lg.exit_value - lg.entry.value for lg in legs], dtype=float)
    long_gross = float(np.sum(n_i * dV_basket))
    short_gross = -(index_exit_value - index_entry.value)  # short index straddle
    gross = long_gross + short_gross

    # Friction: cross each straddle at entry and exit (actual quoted half-spreads).
    cost = 0.0
    if charge_friction:
        idx_cost = index_entry.half_spread + (
            index_exit_half_spread if np.isfinite(index_exit_half_spread) else index_entry.half_spread
        )
        basket_cost = float(
            np.sum(
                [
                    n_i[k]
                    * (
                        lg.entry.half_spread
                        + (lg.exit_half_spread if np.isfinite(lg.exit_half_spread) else lg.entry.half_spread)
                    )
                    for k, lg in enumerate(legs)
                ]
            )
        )
        cost = idx_cost + basket_cost

    norm = index_entry.value
    return {
        "ret": (gross - cost) / norm,
        "gross": gross / norm,
        "cost": cost / norm,
        "long_only": long_gross / norm,  # long-basket-vol stance (control B)
        "short_index_only": short_gross / norm,  # short-index-vol stance (control A)
        "n_names": float(len(legs)),
    }


def _nan_pnl() -> dict[str, float]:
    return {
        "ret": float("nan"),
        "gross": float("nan"),
        "cost": float("nan"),
        "long_only": float("nan"),
        "short_index_only": float("nan"),
        "n_names": 0.0,
    }


# --------------------------------------------------------------------------- #
# Statistics (local copies so T22 depends only on the foundation)
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


def annualize_mean(per_period_mean: float, periods_per_year: float = PERIODS_PER_YEAR) -> float:
    """Scale a per-period mean to annual (simple, additive)."""

    return per_period_mean * periods_per_year


def summarize(series: pd.Series) -> dict[str, float]:
    """Headline stats for a per-period return series: mean, t, win, tail, drawdown."""

    a = pd.Series(series).dropna()
    if a.empty:
        return {}
    mean = float(a.mean())
    sd = float(a.std(ddof=1)) if len(a) > 1 else float("nan")
    cum = a.cumsum()
    return {
        "n": len(a),
        "mean": mean,
        "t": tstat(a),
        "win_rate": float((a > 0).mean()),
        "sd": sd,
        "sharpe_per_period": (mean / sd) if sd and sd > 0 else float("nan"),
        "worst_period": float(a.min()),
        "max_drawdown": float((cum - cum.cummax()).min()),
        "median": float(a.median()),
    }


def incremental_alpha(book: np.ndarray | pd.Series, control: np.ndarray | pd.Series) -> dict[str, float]:
    """Regress the dispersion book on a control book; report the alpha (per period).

    ``book = alpha + beta * control + eps``. If the dispersion return is just the
    control stance (short index vol, or crash compensation), alpha -> ~0 / |t|<2.
    Returns ``{alpha, alpha_t, beta, n}``; pairs aligned, NaN rows dropped.
    """

    df = pd.DataFrame(
        {"y": pd.Series(book).reset_index(drop=True), "x": pd.Series(control).reset_index(drop=True)}
    ).dropna()
    n = len(df)
    if n < 3:
        return {"alpha": float("nan"), "alpha_t": float("nan"), "beta": float("nan"), "n": n}
    x = df["x"].to_numpy()
    y = df["y"].to_numpy()
    if x.std() == 0:
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
    return {
        "alpha": alpha,
        "alpha_t": (alpha / se_alpha) if se_alpha > 0 else float("nan"),
        "beta": float(beta_hat[1]),
        "n": n,
    }


def sign_flip_placebo(
    per_period_returns: np.ndarray | pd.Series,
    *,
    k: int = 2000,
    seed: int = 22,
) -> float:
    """Permutation p-value: randomly flip the sign of each period's return.

    The dispersion book has a fixed sign (short index / long basket). Under the
    null of "no correlation premium", the per-period return is a zero-mean wobble
    whose sign is arbitrary, so flipping signs at random should reproduce the
    observed mean about as often as not. p = fraction of sign-flipped means >=
    observed (one-sided). A real premium sits in the right tail (small p).
    """

    a = np.asarray(pd.Series(per_period_returns).dropna(), dtype=float)
    if a.size < 2:
        return float("nan")
    obs = float(a.mean())
    rng = np.random.default_rng(seed)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(k, a.size))
    means = (signs * a).mean(axis=1)
    return float((means >= obs).mean())


__all__ = [
    "ATM_TARGET_DAYS",
    "HOLD_DAYS",
    "IS_END",
    "MIN_BASKET_NAMES",
    "PERIODS_PER_YEAR",
    "REBALANCE_STEP",
    "SPLIT_RETURN_GUARD",
    "DispersionLeg",
    "StraddleMark",
    "annualize_mean",
    "dispersion_period_pnl",
    "implied_correlation",
    "incremental_alpha",
    "realized_correlation",
    "sign_flip_placebo",
    "straddle_value",
    "straddle_vega",
    "summarize",
    "tstat",
]
