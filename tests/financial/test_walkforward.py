"""Walk-forward orchestration tests: fold boundaries, ordering, no look-ahead.

The sweep evaluator is mocked so these tests are pure and deterministic — they
verify the anti-overfitting machinery (fold math, best-param selection, train/
test isolation), not any backtest numbers.
"""

from __future__ import annotations

from datetime import date
from itertools import pairwise

import pytest

from trader.options.walkforward import (
    make_walk_forward_folds,
    run_walk_forward,
)


def test_folds_have_no_look_ahead_and_no_train_test_overlap():
    folds = make_walk_forward_folds(date(2026, 1, 1), date(2026, 4, 30), train_days=30, test_days=15)
    assert folds, "expected at least one fold"
    for fold in folds:
        # test starts the day after train ends -> strictly no look-ahead
        assert (fold.test_start - fold.train_end).days == 1
        assert fold.train_start <= fold.train_end < fold.test_start <= fold.test_end
        assert (fold.train_end - fold.train_start).days == 29
        assert (fold.test_end - fold.test_start).days == 14


def test_default_step_makes_non_overlapping_test_windows():
    folds = make_walk_forward_folds(date(2026, 1, 1), date(2026, 12, 31), train_days=60, test_days=20)
    for earlier, later in pairwise(folds):
        # next train advances by test_days (default step) -> test windows don't overlap
        assert (later.train_start - earlier.train_start).days == 20
        assert later.test_start > earlier.test_start
        assert earlier.test_end < later.test_end


def test_folds_indexed_sequentially_and_within_range():
    folds = make_walk_forward_folds(date(2026, 1, 1), date(2026, 6, 30), train_days=45, test_days=15)
    assert [f.index for f in folds] == list(range(len(folds)))
    for fold in folds:
        assert fold.train_start >= date(2026, 1, 1)
        assert fold.test_end <= date(2026, 6, 30)


def test_invalid_fold_sizes_raise():
    with pytest.raises(ValueError):
        make_walk_forward_folds(date(2026, 1, 1), date(2026, 2, 1), train_days=0, test_days=10)
    with pytest.raises(ValueError):
        make_walk_forward_folds(date(2026, 1, 1), date(2026, 2, 1), train_days=10, test_days=0)


def test_run_walk_forward_picks_best_in_sample_and_scores_out_of_sample():
    folds = make_walk_forward_folds(date(2026, 1, 1), date(2026, 3, 31), train_days=30, test_days=15)
    sweep_calls: list[tuple[date, date]] = []
    eval_calls: list[tuple[dict, date, date]] = []

    def sweep_fn(train_start, train_end):
        sweep_calls.append((train_start, train_end))
        # Two candidates; the second has the higher total_pnl and should be chosen.
        return [
            {"params": {"wing_width": 5.0}, "metrics": {"total_pnl": 100.0, "win_rate": 0.6}},
            {"params": {"wing_width": 10.0}, "metrics": {"total_pnl": 250.0, "win_rate": 0.7}},
        ]

    def evaluate_fn(params, test_start, test_end):
        eval_calls.append((dict(params), test_start, test_end))
        # Out-of-sample is worse than in-sample (typical degradation).
        return {"total_pnl": 80.0, "win_rate": 0.55}

    results = run_walk_forward(folds, sweep_fn=sweep_fn, evaluate_fn=evaluate_fn, score_key="total_pnl")

    assert len(results) == len(folds)
    for result in results:
        # best in-sample candidate selected
        assert result.best_params == {"wing_width": 10.0}
        assert result.in_sample["total_pnl"] == 250.0
        assert result.out_of_sample["total_pnl"] == 80.0
        # degradation = in-sample - out-of-sample
        assert result.degradation["total_pnl"] == pytest.approx(170.0)
        assert result.degradation["win_rate"] == pytest.approx(0.15)

    # No look-ahead: sweep only ever saw train windows; evaluate only saw the
    # matching test window, which begins after that fold's train ends.
    assert sweep_calls == [(f.train_start, f.train_end) for f in folds]
    for (_params, test_start, test_end), fold in zip(eval_calls, folds, strict=True):
        assert test_start == fold.test_start
        assert test_end == fold.test_end
        assert test_start > fold.train_end


def test_run_walk_forward_skips_folds_with_no_candidates():
    folds = make_walk_forward_folds(date(2026, 1, 1), date(2026, 3, 31), train_days=30, test_days=15)

    def sweep_fn(train_start, train_end):
        return []

    def evaluate_fn(params, test_start, test_end):  # pragma: no cover - never called
        raise AssertionError("evaluate_fn should not be called when there are no candidates")

    results = run_walk_forward(folds, sweep_fn=sweep_fn, evaluate_fn=evaluate_fn)
    assert results == []


def test_report_renders_fold_rows_and_average_degradation():
    from trader.options.walkforward import format_walk_forward_report

    folds = make_walk_forward_folds(date(2026, 1, 1), date(2026, 3, 31), train_days=30, test_days=15)

    def sweep_fn(train_start, train_end):
        return [{"params": {"wing_width": 5.0}, "metrics": {"total_pnl": 100.0, "win_rate": 0.6}}]

    def evaluate_fn(params, test_start, test_end):
        return {"total_pnl": 40.0, "win_rate": 0.5}

    results = run_walk_forward(folds, sweep_fn=sweep_fn, evaluate_fn=evaluate_fn)
    report = format_walk_forward_report(results, ticker="SPY", score_key="total_pnl")
    assert "# SPY Walk-Forward Analysis" in report
    assert "avg_degradation_total_pnl: 60.0" in report
    assert f"- folds: {len(results)}" in report
