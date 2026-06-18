"""Unit tests for the universal gate checklist (src/trader/research/gate.py).

Every gate branch is exercised in both its pass and fail direction on synthetic
data. No network, no files — pure math, so these pin the campaign's gate logic
against silent drift.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from trader.research import gate


# --------------------------------------------------------------------------- #
# core stats
# --------------------------------------------------------------------------- #
def test_t_stat_matches_manual_formula():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    arr = np.asarray(vals)
    expected = arr.mean() / (arr.std(ddof=1) / math.sqrt(len(vals)))
    assert gate.t_stat(vals) == pytest.approx(expected)


def test_t_stat_degenerate_cases_return_zero():
    assert gate.t_stat([]) == 0.0
    assert gate.t_stat([3.0]) == 0.0           # N<2
    assert gate.t_stat([2.0, 2.0, 2.0]) == 0.0  # zero variance


def test_t_stat_drops_nans():
    assert gate.t_stat([1.0, float("nan"), 2.0, 3.0]) == pytest.approx(
        gate.t_stat([1.0, 2.0, 3.0])
    )


def test_t_stat_honours_null():
    vals = [5.0, 5.0, 5.0, 6.0, 4.0]
    # centred on its own mean (5.0) -> t == 0
    assert gate.t_stat(vals, null=5.0) == pytest.approx(0.0, abs=1e-9)


def test_after_cost_expectancy_subtracts_cost():
    assert gate.after_cost_expectancy([10.0, 20.0, 30.0], 5.0) == pytest.approx(15.0)


def test_after_cost_expectancy_empty_is_nan():
    assert math.isnan(gate.after_cost_expectancy([], 5.0))


def test_sharpe_annualization():
    vals = [0.01, -0.005, 0.02, 0.0, 0.015]
    base = gate.sharpe(vals)
    ann = gate.sharpe(vals, periods_per_year=252)
    assert ann == pytest.approx(base * math.sqrt(252))


def test_win_rate():
    assert gate.win_rate([1.0, -1.0, 2.0, 0.0]) == pytest.approx(0.5)  # 0 is not a win
    assert gate.win_rate([]) == 0.0


# --------------------------------------------------------------------------- #
# permutation p-value (seeded, composition-matched)
# --------------------------------------------------------------------------- #
def test_permutation_pvalue_is_seed_deterministic():
    cells = [[0.0, 0.01, -0.01, 0.02] for _ in range(20)]
    p1 = gate.permutation_pvalue(0.005, cells, seed=7, n_permutations=500)
    p2 = gate.permutation_pvalue(0.005, cells, seed=7, n_permutations=500)
    assert p1 == p2  # identical seed -> identical result


def test_permutation_pvalue_does_not_touch_global_rng():
    import random

    random.seed(123)
    state_before = random.getstate()
    np_before = np.random.get_state()[1][0]
    gate.permutation_pvalue(0.0, [[0.1, -0.1]] * 5, seed=99, n_permutations=100)
    assert random.getstate() == state_before
    assert np.random.get_state()[1][0] == np_before


def test_permutation_pvalue_large_observed_is_significant():
    # observed mean far in the right tail of a ~0-centred placebo -> small p
    cells = [list(np.linspace(-0.02, 0.02, 50)) for _ in range(30)]
    p = gate.permutation_pvalue(0.05, cells, seed=1, n_permutations=1000)
    assert p < 0.05


def test_permutation_pvalue_inside_band_is_not_significant():
    # observed == centre of the placebo distribution -> ~0.5
    cells = [list(np.linspace(-0.02, 0.02, 50)) for _ in range(30)]
    p = gate.permutation_pvalue(0.0, cells, seed=1, n_permutations=1000)
    assert p > 0.05


def test_permutation_pvalue_empty_cell_returns_one():
    assert gate.permutation_pvalue(0.1, [[0.1, 0.2], []], seed=1) == 1.0
    assert gate.permutation_pvalue(0.1, [], seed=1) == 1.0


def test_permutation_pvalue_never_returns_exactly_zero():
    # Finite-sample correction (1+count)/(1+n): even when NO placebo cohort
    # reaches the observed mean, the minimum reportable p is 1/(1+n), never 0.0 —
    # a finite resample cannot license a hard probability-zero significance claim.
    cells = [[0.0, 0.0, 0.0] for _ in range(10)]  # constant placebo
    p = gate.permutation_pvalue(0.05, cells, seed=1, n_permutations=999)
    assert p == pytest.approx(1.0 / 1000)
    assert p > 0.0


def test_permutation_pvalue_lower_tail_for_negative_edge():
    # A genuine NEGATIVE edge must be tested in the LOWER tail. With a symmetric
    # placebo, a strong negative observed should be significant when
    # require_positive=False, and (the old bug) ~1.0 when forced upper-tail.
    cells = [list(np.linspace(-0.02, 0.02, 50)) for _ in range(30)]
    p_lower = gate.permutation_pvalue(-0.05, cells, seed=1, n_permutations=1000, require_positive=False)
    p_upper = gate.permutation_pvalue(-0.05, cells, seed=1, n_permutations=1000, require_positive=True)
    assert p_lower < 0.05  # correctly significant in the right tail
    assert p_upper > 0.95  # the hardwired-upper-tail bug would have failed this edge


def test_clean_drops_inf():
    # _clean must drop +/-inf (not just NaN) so depeg/delisting inf-returns don't
    # overstate N or trip a tripwire RuntimeWarning.
    assert gate._clean([1.0, float("inf"), 2.0, float("-inf"), float("nan")]) == [1.0, 2.0]


# --------------------------------------------------------------------------- #
# individual gate steps — pass and fail
# --------------------------------------------------------------------------- #
def test_gate_sample_size_pass_and_fail():
    assert gate.gate_sample_size(30).passed
    assert gate.gate_sample_size(31).passed
    assert not gate.gate_sample_size(29).passed


def test_gate_after_cost_pass():
    # strong positive signal, low variance, cost small -> net>0 and |t|>=2
    pnls = [0.02] * 40
    pnls[0] = 0.018  # introduce variance so t is finite & large
    step = gate.gate_after_cost(pnls, cost_per_trade=0.001)
    assert step.passed


def test_gate_after_cost_fails_on_friction():
    # raw mean positive but cost wipes it out -> net<=0 even if t large
    pnls = [0.001 + 0.0001 * (i % 2) for i in range(40)]  # mean ~0.00105
    step = gate.gate_after_cost(pnls, cost_per_trade=0.01)
    assert not step.passed
    assert "net mean" in step.detail


def test_gate_after_cost_fails_on_weak_t():
    rng = np.random.default_rng(0)
    pnls = (rng.normal(0.0005, 0.05, 60)).tolist()  # tiny mean, big noise -> |t|<2
    step = gate.gate_after_cost(pnls, cost_per_trade=0.0)
    assert not step.passed


def test_gate_oos_sign_stability_pass():
    step = gate.gate_oos_sign_stability([0.01] * 12, [0.008] * 12)
    assert step.passed


def test_gate_oos_sign_stability_fails_on_sign_flip():
    step = gate.gate_oos_sign_stability([0.01] * 12, [-0.01] * 12)
    assert not step.passed


def test_gate_oos_sign_stability_fails_on_thin_half():
    step = gate.gate_oos_sign_stability([0.01] * 12, [0.01] * 5)  # late N<10
    assert not step.passed


def test_gate_baseline_net_pass_and_fail():
    assert gate.gate_baseline_net(0.05, 0.02).passed       # cohort beats baseline
    assert not gate.gate_baseline_net(0.02, 0.05).passed   # baseline absorbs it


def test_gate_placebo_band_pass_and_fail():
    assert gate.gate_placebo(observed_t=3.0, placebo_t=1.9).passed
    assert not gate.gate_placebo(observed_t=1.3, placebo_t=1.9).passed  # inside band


def test_gate_permutation_pass_and_fail():
    assert gate.gate_permutation(0.01).passed
    assert not gate.gate_permutation(0.47).passed  # the product_news number


# --------------------------------------------------------------------------- #
# too-good tripwire
# --------------------------------------------------------------------------- #
def test_tripwire_fires_on_high_win_rate():
    flagged, detail = gate.too_good_tripwire([0.01] * 19 + [-0.01])  # 95% win
    assert flagged
    assert "win=" in detail


def test_tripwire_fires_on_high_sharpe():
    flagged, _ = gate.too_good_tripwire([0.02] * 30, periods_per_year=None)
    # 30 identical -> std 0 -> sharpe 0; add a wiggle to get a huge finite sharpe
    flagged, detail = gate.too_good_tripwire([0.02, 0.0201] * 15)
    assert flagged
    assert "Sharpe=" in detail


def test_tripwire_fires_on_outlier_driven_mean():
    # 49 ~zero values + one 224%-style monster row drives the whole mean.
    # MAD collapses (constant core) but the top-row concentration check catches
    # it — exactly the Tiingo 224% CEF glitch pattern.
    vals = [0.0] * 49 + [2.24]
    flagged, detail = gate.too_good_tripwire(vals)
    assert flagged
    assert "top-row share" in detail


def test_tripwire_fires_on_mad_gap_when_core_has_spread():
    # a core with real dispersion + a fat right tail spread across several rows
    # (so no single row dominates) -> mean >> median in MAD units fires the gap.
    rng = np.random.default_rng(11)
    tail = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    vals = [*rng.normal(0.0, 0.01, 60).tolist(), *tail]
    flagged, detail = gate.too_good_tripwire(vals)
    assert flagged
    assert "median-mean" in detail  # MAD-gap branch, not the concentration one


def test_tripwire_quiet_on_normal_series():
    rng = np.random.default_rng(3)
    vals = rng.normal(0.001, 0.02, 200).tolist()  # modest mean, symmetric
    flagged, detail = gate.too_good_tripwire(vals)
    assert not flagged
    assert "none exceeded" in detail


# --------------------------------------------------------------------------- #
# end-to-end: evaluate_gate
# --------------------------------------------------------------------------- #
def _good_pnls(n=40, mean=0.02, sd=0.005, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.normal(mean, sd, n)).tolist()


def test_evaluate_gate_full_pass():
    pnls = _good_pnls()
    early, late = pnls[:20], pnls[20:]
    res = gate.evaluate_gate(
        "synthetic__edge",
        pnls,
        cost_per_trade=0.001,
        oos_split=(early, late),
        baseline_mean=0.0,
        placebo_cells=[list(np.linspace(-0.02, 0.02, 40))] * len(pnls),
        seed=7,
        n_permutations=500,
        preregistered=True,
        provenance_documented=True,
    )
    assert res.passed, res.reasons
    assert res.n == 40
    assert res.verdict() == "PASS"
    # every step line is rendered
    assert any("after-cost signal" in r for r in res.reasons)
    assert any("matched-control permutation" in r for r in res.reasons)


def test_evaluate_gate_fails_when_prereg_not_acknowledged():
    pnls = _good_pnls()
    res = gate.evaluate_gate(
        "synthetic__no_prereg",
        pnls,
        cost_per_trade=0.001,
        oos_split=(pnls[:20], pnls[20:]),
        baseline_mean=0.0,
        placebo_t=1.0,
        preregistered=False,         # forgot the pre-reg
        provenance_documented=True,
    )
    assert not res.passed
    assert gate.gate_summary(res).startswith("synthetic__no_prereg: FAIL")


def test_evaluate_gate_fails_when_no_placebo_supplied():
    pnls = _good_pnls()
    res = gate.evaluate_gate(
        "synthetic__no_placebo",
        pnls,
        cost_per_trade=0.001,
        oos_split=(pnls[:20], pnls[20:]),
        baseline_mean=0.0,
        preregistered=True,
        provenance_documented=True,
    )
    assert not res.passed
    perm = next(s for s in res.steps if s.name == "matched-control permutation")
    assert not perm.passed
    assert "no placebo" in perm.detail


def test_evaluate_gate_fails_on_baseline_absorption():
    # product_news pattern: cohort mean fully explained by the baseline
    pnls = _good_pnls(mean=0.02)
    res = gate.evaluate_gate(
        "synthetic__absorbed",
        pnls,
        cost_per_trade=0.0,
        oos_split=(pnls[:20], pnls[20:]),
        baseline_mean=0.02,          # baseline == cohort mean -> net ~0
        placebo_t=1.0,
        preregistered=True,
        provenance_documented=True,
    )
    assert not res.passed
    base = next(s for s in res.steps if s.name == "baseline net")
    assert not base.passed


def test_evaluate_gate_surfaces_tripwire_flag_without_blocking():
    # a too-good but otherwise clean cohort: passes blocking gates, flag fires
    pnls = [0.02] * 38 + [0.019, 0.021]  # ~100% win, tiny variance -> huge sharpe
    res = gate.evaluate_gate(
        "synthetic__too_good",
        pnls,
        cost_per_trade=0.0,
        oos_split=(pnls[:20], pnls[20:]),
        baseline_mean=0.0,
        placebo_cells=[list(np.linspace(-0.02, 0.02, 40))] * len(pnls),
        seed=7,
        n_permutations=300,
        preregistered=True,
        provenance_documented=True,
    )
    assert res.tripwire_flag
    assert "tripwire" in res.reasons[-1].lower()


def test_evaluate_gate_fails_on_n_below_30():
    pnls = _good_pnls(n=20)
    res = gate.evaluate_gate(
        "synthetic__thin",
        pnls,
        cost_per_trade=0.001,
        oos_split=(pnls[:10], pnls[10:]),
        baseline_mean=0.0,
        placebo_t=1.0,
        preregistered=True,
        provenance_documented=True,
    )
    assert not res.passed
    n_step = next(s for s in res.steps if s.name == "sample size")
    assert not n_step.passed


def test_report_lines_render_markdown():
    pnls = _good_pnls()
    res = gate.evaluate_gate(
        "synthetic__md",
        pnls,
        cost_per_trade=0.001,
        oos_split=(pnls[:20], pnls[20:]),
        baseline_mean=0.0,
        placebo_t=1.0,
        preregistered=True,
        provenance_documented=True,
    )
    lines = res.report_lines()
    assert all(line.startswith("- **") for line in lines)
    assert len(lines) == len(res.steps) + 1  # steps + tripwire line
