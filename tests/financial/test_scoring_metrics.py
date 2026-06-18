"""Pure-function metric tests for the horse-race leaderboard.

Every metric is small + numeric. Tests use hand-built equity curves so
expected values are verifiable by hand.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from trader.scoring.metrics import (
    annualized_return,
    daily_returns,
    hit_rate,
    max_drawdown,
    sharpe_ratio,
    total_return,
)


def _curve(values: list[float], *, start: date | None = None) -> list[tuple[date, float]]:
    start = start or date(2026, 1, 1)
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


# ── total_return ────────────────────────────────────────────────────────────


def test_total_return_empty_curve_zero():
    assert total_return([]) == 0.0


def test_total_return_single_point_zero():
    assert total_return(_curve([100.0])) == 0.0


def test_total_return_flat_curve_zero():
    assert total_return(_curve([100.0, 100.0, 100.0])) == 0.0


def test_total_return_doubling_one():
    assert total_return(_curve([100.0, 200.0])) == 1.0


def test_total_return_halving_minus_half():
    assert total_return(_curve([100.0, 50.0])) == -0.5


def test_total_return_non_positive_first_returns_zero():
    assert total_return(_curve([0.0, 100.0])) == 0.0


# ── daily_returns ───────────────────────────────────────────────────────────


def test_daily_returns_empty_or_single():
    assert daily_returns([]) == []
    assert daily_returns(_curve([100.0])) == []


def test_daily_returns_two_points():
    assert daily_returns(_curve([100.0, 110.0])) == [0.1]


def test_daily_returns_skip_non_positive_prior():
    """If a prior equity is 0, that interval is dropped — avoids div-by-zero."""
    out = daily_returns([(date(2026, 1, 1), 100.0), (date(2026, 1, 2), 0.0), (date(2026, 1, 3), 50.0)])
    # First interval: (0-100)/100 = -1.0
    # Second interval: prior is 0, skipped.
    assert out == [-1.0]


# ── annualized_return ───────────────────────────────────────────────────────


def test_annualized_return_empty_zero():
    assert annualized_return([]) == 0.0


def test_annualized_return_single_zero():
    assert annualized_return(_curve([100.0])) == 0.0


def test_annualized_return_flat_zero():
    assert annualized_return(_curve([100.0, 100.0])) == 0.0


def test_annualized_return_one_year_doubling_approx_one():
    """252-interval (one trading year) doubling → ~1.0 annualized return."""
    values = [100.0]
    # 253 points → 252 intervals
    growth_per_step = 2.0 ** (1 / 252)
    for _ in range(252):
        values.append(values[-1] * growth_per_step)
    result = annualized_return(_curve(values))
    assert math.isclose(result, 1.0, rel_tol=1e-9)


def test_annualized_return_one_day_one_pct_big():
    """1 interval, +1% → annualized = 1.01^252 - 1 ≈ 11.7"""
    result = annualized_return(_curve([100.0, 101.0]))
    assert math.isclose(result, 1.01**252 - 1, rel_tol=1e-9)


# ── sharpe_ratio ────────────────────────────────────────────────────────────


def test_sharpe_empty_or_single_zero():
    assert sharpe_ratio([]) == 0.0
    assert sharpe_ratio([0.01]) == 0.0


def test_sharpe_zero_variance_zero():
    assert sharpe_ratio([0.01, 0.01, 0.01, 0.01]) == 0.0


def test_sharpe_known_input():
    """Annualized Sharpe = mean/stdev * sqrt(252). Compare to direct formula."""
    from statistics import mean as _mean
    from statistics import stdev as _stdev

    rets = [0.02, -0.01, 0.015, -0.005]
    expected = _mean(rets) / _stdev(rets) * math.sqrt(252)
    result = sharpe_ratio(rets)
    assert math.isclose(result, expected, rel_tol=1e-9)


# ── max_drawdown ────────────────────────────────────────────────────────────


def test_max_drawdown_empty_or_single_zero():
    assert max_drawdown([]) == 0.0
    assert max_drawdown(_curve([100.0])) == 0.0


def test_max_drawdown_monotone_up_zero():
    assert max_drawdown(_curve([100.0, 110.0, 120.0, 130.0])) == 0.0


def test_max_drawdown_v_shape_minus_twenty_pct():
    """100 → 80 → 100: max drawdown is -0.20."""
    assert math.isclose(max_drawdown(_curve([100.0, 80.0, 100.0])), -0.20, rel_tol=1e-9)


def test_max_drawdown_two_peaks_uses_deepest():
    """100 → 90 → 95 → 70 → 80: deepest trough is from peak 100 to 70 = -0.30."""
    result = max_drawdown(_curve([100.0, 90.0, 95.0, 70.0, 80.0]))
    assert math.isclose(result, -0.30, rel_tol=1e-9)


def test_max_drawdown_resets_on_new_peak():
    """Peak resets: 100 → 120 → 96 = drawdown from new peak 120 → 96 = -0.20."""
    result = max_drawdown(_curve([100.0, 120.0, 96.0]))
    assert math.isclose(result, -0.20, rel_tol=1e-9)


# ── hit_rate ────────────────────────────────────────────────────────────────


def test_hit_rate_empty_returns_half():
    assert hit_rate([]) == 0.5


def test_hit_rate_all_positive():
    assert hit_rate([0.01, 0.02, 0.005]) == 1.0


def test_hit_rate_all_negative():
    assert hit_rate([-0.01, -0.02, -0.005]) == 0.0


def test_hit_rate_mixed():
    assert hit_rate([0.01, -0.01, 0.005, 0.0]) == 2 / 4  # zero is NOT a hit


def test_hit_rate_zero_not_counted_as_hit():
    assert hit_rate([0.0, 0.0, 0.01]) == 1 / 3
