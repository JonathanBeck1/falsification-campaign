"""Deflated Sharpe Ratio (Bailey & López de Prado 2014).

Reference
---------
Bailey, D. H. and López de Prado, M., 2014. "The Deflated Sharpe Ratio:
Correcting for Selection Bias, Backtest Overfitting and Non-Normality."
Journal of Portfolio Management, 40 (5), 94-107.

Mathematical summary
--------------------
Given N candidate strategies tested on T per-period return observations, the
observed maximum Sharpe ratio ``SR_hat`` is upward-biased by trial selection.
Under the null hypothesis of zero true SR for every variant, the expected
maximum of N i.i.d. SR estimators is well-approximated by the extreme-value
formula (Bailey & López de Prado, eq. 6)::

    SR_0 = sqrt(V[SR]) * ( (1 - γ) · Φ⁻¹(1 - 1/N)
                          + γ · Φ⁻¹(1 - 1/(N·e)) )

where γ ≈ 0.5772 is the Euler-Mascheroni constant, ``e`` is Euler's number,
``Φ⁻¹`` is the inverse standard normal CDF, and ``V[SR]`` is the cross-trial
variance of the per-period SR estimator. Under H₀ with Gaussian returns
``V[SR] ≈ 1/(T-1)``.

The Deflated Sharpe Ratio is the probability that the observed SR exceeds
this selection-adjusted benchmark, with a higher-moment correction for skew
``γ_3`` and kurtosis ``γ_4`` (``γ_4 = 3`` under normality)::

    DSR = Φ[ (SR_hat - SR_0) · √(T-1)
            / √(1 - γ_3·SR_hat + (γ_4 - 1)/4 · SR_hat²) ]

DSR ∈ [0, 1]; values near 1 indicate the result is unlikely to be a chance
artifact of the trial count. All SR quantities in the formula above are in
per-period (e.g. daily) units — this module accepts annualized SR in its
public API and converts internally.
"""

from __future__ import annotations

import math
from statistics import NormalDist

# Euler-Mascheroni constant.
_EULER_MASCHERONI = 0.5772156649015329

_NORMAL = NormalDist()


def _expected_max_sharpe_under_null(
    n_trials: int, n_observations: int
) -> float:
    """Expected per-period best-of-N Sharpe under H₀ (true SR = 0).

    Closed-form Bailey-LdP extreme-value approximation. Under H₀ with Gaussian
    returns, the per-period SR estimator variance is ``1/(T-1)``.
    """
    if n_trials <= 1 or n_observations < 2:
        return 0.0
    sqrt_var_sr = math.sqrt(1.0 / (n_observations - 1))
    n = float(n_trials)
    q1 = 1.0 - 1.0 / n
    q2 = 1.0 - 1.0 / (n * math.e)
    z1 = _NORMAL.inv_cdf(q1)
    z2 = _NORMAL.inv_cdf(q2)
    return sqrt_var_sr * (
        (1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2
    )


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    n_observations: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    *,
    trading_days_per_year: int = 252,
) -> float:
    """Return the probability that the observed SR exceeds the SR threshold
    expected under the null of zero true SR, accounting for trial selection.
    Returns a value in [0, 1]. Often used as 1 - p-value of selection-adjusted
    test.

    ``observed_sharpe`` is the annualized Sharpe ratio of the best variant;
    ``n_trials`` is the number of candidate variants compared; ``n_observations``
    is the number of per-period (e.g. daily) return observations underlying
    ``observed_sharpe``.
    """
    if n_observations < 2:
        return 0.0
    sr_hat = observed_sharpe / math.sqrt(trading_days_per_year)
    sr_zero = _expected_max_sharpe_under_null(n_trials, n_observations)

    variance_factor = (
        1.0 - skewness * sr_hat + (kurtosis - 1.0) / 4.0 * sr_hat * sr_hat
    )
    if variance_factor <= 0.0:
        # Degenerate higher moments; cannot deflate meaningfully.
        return 0.0
    z = (sr_hat - sr_zero) * math.sqrt(n_observations - 1) / math.sqrt(
        variance_factor
    )
    return _NORMAL.cdf(z)


def deflated_sharpe_value(
    observed_sharpe: float,
    n_trials: int,
    n_observations: int,
    skewness: float = 0.0,  # kept for API parity with DSR
    kurtosis: float = 3.0,  # kept for API parity with DSR
    *,
    trading_days_per_year: int = 252,
) -> float:
    """Return the deflated SR point estimate (the implicit SR after subtracting
    the expected best-of-N inflation under the null). Useful as a leaderboard
    column the user can read directly.

    Returned in the same annualized units as ``observed_sharpe``. With
    ``n_trials <= 1`` this equals ``observed_sharpe`` (no selection inflation
    to subtract). With ``n_observations < 2`` the input is returned unchanged
    because the deflation constant is undefined.
    """
    if n_observations < 2 or n_trials <= 1:
        return observed_sharpe
    sr_zero_per_period = _expected_max_sharpe_under_null(
        n_trials, n_observations
    )
    sr_zero_annualized = sr_zero_per_period * math.sqrt(trading_days_per_year)
    return observed_sharpe - sr_zero_annualized
