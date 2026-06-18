"""Walk-forward / out-of-sample evaluation — the anti-overfitting guard.

A parameter sweep that you then trade is overfit by construction: you picked the
settings that looked best on the very data you measured. Walk-forward analysis
fixes that by splitting the date range into sequential folds, optimizing on each
*train* fold, and scoring those chosen parameters on the *following, unseen*
*test* fold. Persistent edge survives out-of-sample; overfit edge collapses.

This module is split in two:

- Pure orchestration (``make_walk_forward_folds`` + ``run_walk_forward``) that
  takes injected ``sweep_fn``/``evaluate_fn`` callables. This is fully testable
  with mocks and is where the no-look-ahead guarantee lives: a fold's test window
  always starts strictly after its train window ends.
- Concrete builders that wire the real intraday sweep + backtest to a
  ``QuoteSource``, loading only one fold window at a time (folds are bounded, so
  this preserves the day-by-day streaming / memory-safety property).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trader.options.sources import QuoteSource

# A candidate is one sweep row: its parameters plus the in-sample metrics it earned.
SweepCandidate = Mapping[str, object]
SweepFn = Callable[[date, date], Sequence[SweepCandidate]]
EvaluateFn = Callable[[Mapping[str, object], date, date], Mapping[str, object]]

_DEGRADATION_KEYS = ("total_pnl", "total_return", "win_rate", "profit_factor", "sharpe")


@dataclass(frozen=True)
class WalkForwardFold:
    index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date


@dataclass(frozen=True)
class WalkForwardFoldResult:
    fold: WalkForwardFold
    best_params: Mapping[str, object]
    in_sample: Mapping[str, object]
    out_of_sample: Mapping[str, object]
    degradation: Mapping[str, float]


def make_walk_forward_folds(
    start: date,
    end: date,
    *,
    train_days: int,
    test_days: int,
    step_days: int | None = None,
) -> list[WalkForwardFold]:
    """Split ``[start, end]`` into sequential train/test folds (calendar days).

    Each fold's test window begins the day after its train window ends (no
    look-ahead, no overlap between a fold's own train and test). ``step_days``
    controls how far the train window advances between folds (default
    ``test_days`` => non-overlapping test windows / classic walk-forward).
    """
    if train_days < 1 or test_days < 1:
        raise ValueError("train_days and test_days must be >= 1")
    step = step_days if step_days is not None else test_days
    if step < 1:
        raise ValueError("step_days must be >= 1")

    folds: list[WalkForwardFold] = []
    train_start = start
    index = 0
    while True:
        train_end = train_start + timedelta(days=train_days - 1)
        test_start = train_end + timedelta(days=1)
        test_end = test_start + timedelta(days=test_days - 1)
        if test_end > end:
            break
        folds.append(
            WalkForwardFold(
                index=index,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        index += 1
        train_start = train_start + timedelta(days=step)
    return folds


def run_walk_forward(
    folds: Sequence[WalkForwardFold],
    *,
    sweep_fn: SweepFn,
    evaluate_fn: EvaluateFn,
    score_key: str = "total_pnl",
) -> list[WalkForwardFoldResult]:
    """Optimize on each train fold, then score the winner on the unseen test fold.

    ``sweep_fn(train_start, train_end)`` returns sweep candidates, each a mapping
    with ``params`` and ``metrics`` keys. The best candidate by
    ``metrics[score_key]`` is selected, then ``evaluate_fn(params, test_start,
    test_end)`` produces out-of-sample metrics. Degradation is in-sample minus
    out-of-sample for a fixed set of comparable metrics.
    """
    results: list[WalkForwardFoldResult] = []
    for fold in folds:
        candidates = list(sweep_fn(fold.train_start, fold.train_end))
        if not candidates:
            continue
        best = max(candidates, key=lambda candidate: _score(candidate, score_key))
        params = _require_mapping(best, "params")
        in_sample = _require_mapping(best, "metrics")
        out_of_sample = evaluate_fn(params, fold.test_start, fold.test_end)
        results.append(
            WalkForwardFoldResult(
                fold=fold,
                best_params=params,
                in_sample=in_sample,
                out_of_sample=out_of_sample,
                degradation=_degradation(in_sample, out_of_sample),
            )
        )
    return results


def format_walk_forward_report(
    results: Sequence[WalkForwardFoldResult],
    *,
    ticker: str,
    score_key: str = "total_pnl",
) -> str:
    lines = [
        f"# {ticker} Walk-Forward Analysis",
        "",
        "Out-of-sample evaluation. In-sample is the best sweep result on each train "
        "fold; out-of-sample applies those same parameters to the following unseen "
        "test fold. Large positive degradation = likely overfitting.",
        "",
        "| fold | train | test | "
        f"is_{score_key} | oos_{score_key} | is_win_rate | oos_win_rate | degradation_{score_key} |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        fold = result.fold
        lines.append(
            f"| {fold.index} | {fold.train_start}..{fold.train_end} | "
            f"{fold.test_start}..{fold.test_end} | "
            f"{_fmt(result.in_sample.get(score_key))} | {_fmt(result.out_of_sample.get(score_key))} | "
            f"{_fmt(result.in_sample.get('win_rate'))} | {_fmt(result.out_of_sample.get('win_rate'))} | "
            f"{_fmt(result.degradation.get(score_key))} |"
        )
    if results:
        avg_deg = sum(r.degradation.get(score_key, 0.0) for r in results) / len(results)
        lines += ["", f"- folds: {len(results)}", f"- avg_degradation_{score_key}: {round(avg_deg, 4)}"]
    else:
        lines += ["", "- folds: 0"]
    return "\n".join(lines) + "\n"


# --- concrete intraday-iron-condor builders (used by the CLI) ----------------


def build_intraday_sweep_fn(
    source: QuoteSource,
    *,
    ticker: str,
    grids: Mapping[str, object],
) -> SweepFn:
    """A ``sweep_fn`` that runs the real intraday sweep over a fold's train window.

    Loads only the fold window (bounded) via the QuoteSource, so memory stays
    proportional to a single fold, not the whole range.
    """
    from trader.options.intraday_sweep import run_intraday_iron_condor_sweep

    def _sweep(train_start: date, train_end: date) -> list[dict[str, object]]:
        bars = _load_window(source, ticker, train_start, train_end)
        rows = run_intraday_iron_condor_sweep(
            bars,
            ticker=ticker,
            start=train_start,
            end=train_end,
            entry_times=list(grids["entry_times"]),  # type: ignore[arg-type]
            selection_mode=str(grids["selection_mode"]),
            wing_widths=list(grids["wing_widths"]),  # type: ignore[arg-type]
            target_deltas=list(grids.get("target_deltas") or []) or None,
            target_short_bids=list(grids.get("target_short_bids") or []) or None,
            profit_targets=list(grids["profit_targets"]),  # type: ignore[arg-type]
            stop_loss_multiples=list(grids["stop_loss_multiples"]),  # type: ignore[arg-type]
            min_dte=int(grids["min_dte"]),  # type: ignore[arg-type]
            max_dte=int(grids["max_dte"]),  # type: ignore[arg-type]
        )
        return [
            {
                "params": {
                    "entry_time": row.entry_time,
                    "selection_mode": row.selection_mode,
                    "wing_width": row.wing_width,
                    "target_delta": row.target_delta,
                    "target_short_bid": row.target_short_bid,
                    "profit_target_pct": row.profit_target_pct,
                    "stop_loss_credit_multiple": row.stop_loss_credit_multiple,
                },
                "metrics": {
                    "total_pnl": row.total_pnl,
                    "win_rate": row.win_rate,
                    "profit_factor": row.profit_factor,
                    "trade_count": row.trade_count,
                    "max_drawdown": row.max_drawdown,
                },
            }
            for row in rows
        ]

    return _sweep


def build_intraday_evaluate_fn(
    source: QuoteSource,
    *,
    ticker: str,
    min_dte: int,
    max_dte: int,
) -> EvaluateFn:
    """An ``evaluate_fn`` that backtests chosen params on a fold's test window."""
    from trader.options.intraday import (
        IntradayIronCondorBacktestConfig,
        IntradayIronCondorSelectorConfig,
        run_intraday_iron_condor_backtest,
    )

    def _evaluate(params: Mapping[str, object], test_start: date, test_end: date) -> dict[str, object]:
        config = IntradayIronCondorBacktestConfig(
            ticker=ticker,
            start=test_start,
            end=test_end,
            selector=IntradayIronCondorSelectorConfig(
                min_dte=min_dte,
                max_dte=max_dte,
                wing_width=float(params["wing_width"]),  # type: ignore[arg-type]
                selection_mode=str(params["selection_mode"]),
                target_delta=float(params.get("target_delta") or 0.16),  # type: ignore[arg-type]
                target_short_bid=float(params.get("target_short_bid") or 1.0),  # type: ignore[arg-type]
            ),
            entry_time=str(params["entry_time"]),
            profit_target_pct=float(params["profit_target_pct"]),  # type: ignore[arg-type]
            stop_loss_credit_multiple=float(params["stop_loss_credit_multiple"]),  # type: ignore[arg-type]
        )
        # Stream the test window day-by-day through the engine.
        result = run_intraday_iron_condor_backtest(source, config)
        summary = result.summary
        return {
            "total_pnl": summary.total_pnl,
            "win_rate": summary.win_rate,
            "profit_factor": summary.profit_factor,
            "trade_count": summary.trade_count,
            "max_drawdown": summary.max_drawdown,
        }

    return _evaluate


def _load_window(source: QuoteSource, ticker: str, start: date, end: date) -> list:
    return [bar for _trade_date, day_bars in source.iter_days(ticker, start, end) for bar in day_bars]


def _score(candidate: SweepCandidate, score_key: str) -> float:
    metrics = candidate.get("metrics", {})
    if not isinstance(metrics, Mapping):
        return float("-inf")
    value = metrics.get(score_key)
    return float(value) if isinstance(value, (int, float)) else float("-inf")


def _require_mapping(candidate: SweepCandidate, key: str) -> Mapping[str, object]:
    value = candidate.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"sweep candidate missing '{key}' mapping")
    return value


def _degradation(in_sample: Mapping[str, object], out_of_sample: Mapping[str, object]) -> dict[str, float]:
    degradation: dict[str, float] = {}
    for key in _DEGRADATION_KEYS:
        is_value = in_sample.get(key)
        oos_value = out_of_sample.get(key)
        if isinstance(is_value, (int, float)) and isinstance(oos_value, (int, float)):
            degradation[key] = round(float(is_value) - float(oos_value), 6)
    return degradation


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
