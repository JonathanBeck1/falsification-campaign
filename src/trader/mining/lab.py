"""Strategy-mining lab with multiple-testing control.

Runs many candidate variants, splits each into in-sample (IS) / out-of-sample
(OOS), and judges the *best* IS Sharpe with the **deflated Sharpe ratio** (DSR),
which accounts for how many variants were tried. A variant only counts as a real
find if it clears BOTH:
  1. DSR >= dsr_threshold (the best-of-N IS Sharpe is significant after the
     selection correction), AND
  2. it holds up OUT-OF-SAMPLE (OOS Sharpe positive, same sign as IS).

This is the difference between honest discovery and a mirage factory: mining 500
variants without (1) hands you ~25 "p<0.05 winners" that are pure noise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from trader.mining.strategies import Variant
from trader.scoring.deflated_sharpe import deflated_sharpe_ratio, deflated_sharpe_value


def annualized_sharpe(daily: pd.Series, ppy: int = 252) -> float:
    r = daily.dropna()
    if len(r) < 2:
        return 0.0
    sd = float(r.std(ddof=1))
    if sd < 1e-10:        # degenerate / constant series — not a real Sharpe
        return 0.0
    return float(r.mean() / sd * math.sqrt(ppy))


@dataclass(frozen=True)
class VariantScore:
    name: str
    family: str
    ticker: str
    is_sharpe: float
    oos_sharpe: float
    n_is: int
    n_oos: int


@dataclass(frozen=True)
class LabReport:
    n_trials: int
    split: str
    best: VariantScore | None
    best_dsr: float           # P(best IS Sharpe is real | N trials)
    best_deflated_sharpe: float
    expected_false_winners_p05: float   # how many noise winners at naive p<0.05
    oos_confirmed: list[VariantScore]   # cleared DSR and held up OOS
    leaderboard: list[VariantScore]     # top by OOS Sharpe


def _split(daily: pd.Series, split: pd.Timestamp) -> tuple[pd.Series, pd.Series]:
    return daily[daily.index < split], daily[daily.index >= split]


def run_lab(
    variants: list[Variant],
    *,
    split: str,
    dsr_threshold: float = 0.95,
    top_k: int = 15,
) -> LabReport:
    sp = pd.Timestamp(split)
    scores: list[VariantScore] = []
    for v in variants:
        is_r, oos_r = _split(v.daily_returns, sp)
        if len(is_r) < 60 or len(oos_r) < 30:
            continue
        scores.append(VariantScore(
            name=v.name, family=v.family, ticker=v.ticker,
            is_sharpe=annualized_sharpe(is_r), oos_sharpe=annualized_sharpe(oos_r),
            n_is=len(is_r), n_oos=len(oos_r),
        ))
    n = len(scores)
    if n == 0:
        return LabReport(0, split, None, 0.0, 0.0, 0.0, [], [])

    best = max(scores, key=lambda s: s.is_sharpe)
    is_returns_best = None  # skew/kurt of the best variant's IS returns
    for v in variants:
        if v.name == best.name:
            is_returns_best = _split(v.daily_returns, sp)[0]
            break
    skew = float(is_returns_best.skew()) if is_returns_best is not None else 0.0
    kurt = float(is_returns_best.kurt() + 3.0) if is_returns_best is not None else 3.0

    dsr = deflated_sharpe_ratio(best.is_sharpe, n_trials=n, n_observations=best.n_is,
                                skewness=skew, kurtosis=kurt)
    defl = deflated_sharpe_value(best.is_sharpe, n_trials=n, n_observations=best.n_is)
    # crude expectation of naive-significant noise winners (one-sided p<0.05)
    expected_false = n * 0.05

    confirmed = [
        s for s in scores
        if deflated_sharpe_ratio(s.is_sharpe, n_trials=n, n_observations=s.n_is) >= dsr_threshold
        and s.oos_sharpe > 0 and (s.is_sharpe > 0) == (s.oos_sharpe > 0)
    ]
    leaderboard = sorted(scores, key=lambda s: s.oos_sharpe, reverse=True)[:top_k]
    return LabReport(n, split, best, dsr, defl, expected_false, confirmed, leaderboard)


def format_report(rep: LabReport) -> str:
    lines = [
        "# Strategy-Mining Lab — multiple-testing-corrected",
        "",
        f"- Variants tested (N): **{rep.n_trials}**",
        f"- IS/OOS split: {rep.split}",
        f"- Naive 'winners' expected from pure noise (p<0.05): **~{rep.expected_false_winners_p05:.0f}**",
        "",
    ]
    if rep.best:
        verdict = "✅ REAL (after correction)" if rep.best_dsr >= 0.95 else "❌ noise (fails deflation)"
        lines += [
            "## Best in-sample variant (the one mining would 'find')",
            f"- `{rep.best.name}` — IS Sharpe **{rep.best.is_sharpe:.2f}**, OOS Sharpe {rep.best.oos_sharpe:.2f}",
            f"- **Deflated-Sharpe probability it's real: {rep.best_dsr:.1%}** → {verdict}",
            f"- Deflated Sharpe (point est.): {rep.best_deflated_sharpe:.2f}",
            "",
        ]
    lines += [
        f"## Survivors — cleared deflation AND held up OOS: **{len(rep.oos_confirmed)}**",
        "",
    ]
    if rep.oos_confirmed:
        lines += ["| variant | family | IS Sharpe | OOS Sharpe |", "|---|---|---|---|"]
        for s in rep.oos_confirmed:
            lines.append(f"| {s.name} | {s.family} | {s.is_sharpe:.2f} | {s.oos_sharpe:.2f} |")
    else:
        lines.append("_None. The best 'winners' don't survive the selection correction "
                     "and/or fall apart out-of-sample — exactly what noise looks like._")
    lines += [
        "",
        "## Leaderboard by OUT-OF-SAMPLE Sharpe (the honest ranking)",
        "| variant | family | IS Sharpe | OOS Sharpe |", "|---|---|---|---|",
    ]
    for s in rep.leaderboard:
        lines.append(f"| {s.name} | {s.family} | {s.is_sharpe:.2f} | {s.oos_sharpe:.2f} |")
    return "\n".join(lines) + "\n"
