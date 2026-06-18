"""The campaign's universal gate checklist, as reusable pure functions.

Brain/30 codified the eight-step gate every edge claim must pass before it may
be written down anywhere. Until now each test re-implemented the numeric core
by hand (see ``catalysts/fomc_drift.evaluate_gate``,
``catalog/phase2.evaluate_drift_gate``, ``scripts/run_product_news_control.py``).
Hand-rolling means a test can silently *skip* a gate. This module makes the gate
a single shared object so a future test cannot quietly drop a step: it either
calls :func:`evaluate_gate` and gets every line, or it does not and the omission
is obvious.

The statistical conventions match what the campaign already used:

* one-sample t vs null=0, ``ddof=1`` (sample std) — same as the catalysts.
* after-cost expectancy = mean(pnl) - cost_per_trade — friction realism.
* OOS sign stability = early/late split, same sign, both halves N≥10.
* matched-control permutation = composition-matched seeded placebo cohorts;
  p = fraction of placebo means ≥ observed (one-sided), exactly as the
  product_news matched-control test (seed-driven ``np.random.default_rng``).
* too-good tripwire = Sharpe>3 OR win>85% OR |median-mean| large → flag.

Gate numbering follows brain/30's mandatory checklist. Steps that need
artifacts a pure function cannot see — (1) pre-registration and (8) data
provenance — are documentation gates, surfaced here as explicit acknowledgement
flags so a caller still has to assert them rather than forget them.

Everything here is pure and deterministic. The only randomness is the seeded RNG
inside :func:`permutation_pvalue`, which takes an explicit ``seed`` and never
touches global RNG state.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

# --------------------------------------------------------------------------- #
# Default thresholds (brain/30 gate). Override per-test only with a pre-reg.
# --------------------------------------------------------------------------- #
MIN_N = 30
T_THRESHOLD = 2.0
OOS_MIN_HALF_N = 10
PERM_ALPHA = 0.05
DEFAULT_PERMUTATIONS = 2000

# too-good tripwire thresholds (brain/30 step 7)
SHARPE_TRIPWIRE = 3.0
WINRATE_TRIPWIRE = 0.85
# |median - mean| measured in robust (median-absolute-deviation) units. MAD is
# used deliberately instead of std: the very outlier we want to catch (the
# Tiingo 224% row, the stablecoin death) inflates the std and masks itself, but
# barely moves the MAD — so a single monster row blows the mean far from the
# median in MAD units while the std-scaled gap stays small. >3 MADs ≈ "the mean
# is being dragged by rows the median doesn't see."
MEDIAN_MEAN_GAP_TRIPWIRE = 3.0
# Top-contributor concentration: if the single largest-magnitude row supplies
# more than this fraction of the total absolute deviation from the median, the
# mean is a one-row artifact (brain/30: "inspect top-5 contributors by hand").
# This catches the case the MAD gap misses — a constant core (MAD≈0) with one
# monster row, e.g. the 224% Tiingo glitch among ~zero-return CEF days.
TOP_CONTRIBUTOR_FRACTION_TRIPWIRE = 0.5


# --------------------------------------------------------------------------- #
# Core statistics — match the campaign's existing helpers exactly.
# --------------------------------------------------------------------------- #
def _clean(values: Sequence[float]) -> list[float]:
    """Drop non-finite values (NaN and ±inf) and coerce to float.

    The campaign convention drops NaN; we also drop ±inf, which the depeg /
    delisting studies can produce (a return with a price→0 denominator, a
    log-return on a zeroed token). Retaining inf would overstate N and make the
    tripwire's concentration divide emit a RuntimeWarning; dropping it keeps N
    honest and never changes a finite-data verdict.
    """
    return [float(v) for v in values if v == v and math.isfinite(v)]


def t_stat(values: Sequence[float], *, null: float = 0.0) -> float:
    """One-sample t-statistic of ``values`` against ``null`` (ddof=1).

    Returns 0.0 for N<2 or zero variance — the same degenerate handling the
    catalysts use, so a flat or empty series never produces a spurious |t|.
    """
    vals = _clean(values)
    n = len(vals)
    if n < 2:
        return 0.0
    arr = np.asarray(vals, dtype=float)
    sd = float(arr.std(ddof=1))
    if sd == 0.0:
        return 0.0
    return float((arr.mean() - null) / (sd / math.sqrt(n)))


def welch_t(a: Sequence[float], b: Sequence[float]) -> float:
    """Welch (unequal-variance) two-sample t for ``mean(a) - mean(b)``.

    Positive ⇒ a's mean exceeds b's. Returns 0.0 if either side has < 2 usable
    obs or the pooled SE is 0 — the campaign's degenerate convention, matching the
    matched-control (event vs non-event) tests that each re-rolled this by hand
    (earnings_premium, earnings_iv_crush, buyback_drift, sell_in_may). Non-finite
    values are dropped (via :func:`_clean`).
    """
    va, vb = _clean(a), _clean(b)
    na, nb = len(va), len(vb)
    if na < 2 or nb < 2:
        return 0.0
    ma, mb = sum(va) / na, sum(vb) / nb
    sa2 = sum((x - ma) ** 2 for x in va) / (na - 1)
    sb2 = sum((x - mb) ** 2 for x in vb) / (nb - 1)
    denom = math.sqrt(sa2 / na + sb2 / nb)
    if denom == 0.0:
        return 0.0
    return (ma - mb) / denom


def after_cost_expectancy(pnls: Sequence[float], cost_per_trade: float) -> float:
    """Mean per-trade P&L net of round-trip friction.

    Friction realism (gate step 2): the *only* metric the campaign ranks on.
    Returns NaN for an empty series so callers cannot mistake "no data" for 0.
    """
    vals = _clean(pnls)
    if not vals:
        return float("nan")
    return float(np.mean(vals)) - float(cost_per_trade)


def sharpe(values: Sequence[float], *, periods_per_year: float | None = None) -> float:
    """Mean/std Sharpe of a per-trade (or per-period) return series.

    If ``periods_per_year`` is given, annualize by sqrt(periods_per_year).
    Used by the too-good tripwire. Returns 0.0 for N<2 or zero variance.
    """
    vals = _clean(values)
    if len(vals) < 2:
        return 0.0
    arr = np.asarray(vals, dtype=float)
    sd = float(arr.std(ddof=1))
    if sd == 0.0:
        return 0.0
    s = float(arr.mean() / sd)
    if periods_per_year is not None:
        s *= math.sqrt(periods_per_year)
    return s


def win_rate(values: Sequence[float]) -> float:
    """Fraction of strictly-positive entries (the campaign's hit-rate)."""
    vals = _clean(values)
    if not vals:
        return 0.0
    return sum(1 for v in vals if v > 0) / len(vals)


def permutation_pvalue(
    observed_mean: float,
    placebo_cells: Sequence[Sequence[float]],
    *,
    seed: int,
    n_permutations: int = DEFAULT_PERMUTATIONS,
    require_positive: bool = True,
) -> float:
    """Composition-matched permutation p-value with finite-sample correction.

    ``placebo_cells`` is one array of eligible control values per event — e.g.
    every same-(ticker, year) non-event day for that event, as built by the
    product_news matched-control test. Each placebo cohort draws one value from
    each cell and takes the mean; the p-value is the fraction of placebo cohort
    means at least as extreme as ``observed_mean`` *in the hypothesized
    direction*. A real edge sits in the tail (small p); an artifact sits inside
    the placebo band (large p).

    **Tail follows the hypothesis sign.** For a positive (bullish) edge
    (``require_positive=True``) the extreme tail is ``placebo >= observed``; for
    a negative (bearish) edge it is ``placebo <= observed``. Hardwiring the upper
    tail would hand a genuine negative edge p≈1.0 and fail it spuriously while the
    sign-aware after-cost/baseline gates pass it — an internal contradiction this
    parameter removes.

    **Finite-sample correction.** The estimator is the standard
    ``(1 + #extreme) / (1 + n_permutations)`` so the minimum reportable p is
    ``1/(1+n)``, never exactly 0 — a finite resample can never license a hard
    probability-zero significance claim (the degenerate near-constant-placebo
    regime, e.g. CEF constant days + one glitch row, is exactly where the
    uncorrected estimator would print p=0.0).

    Seeded and deterministic: uses a fresh ``np.random.default_rng(seed)`` and
    never reads or mutates global RNG state, so re-running reproduces the value.

    Returns 1.0 if any cell is empty (no eligible control → cannot reject H0).
    """
    cells = [np.asarray(_clean(c), dtype=float) for c in placebo_cells]
    if not cells or any(len(c) == 0 for c in cells):
        return 1.0
    rng = np.random.default_rng(seed)
    placebo_means = np.empty(n_permutations, dtype=float)
    for i in range(n_permutations):
        draw = [float(c[rng.integers(0, len(c))]) for c in cells]
        placebo_means[i] = float(np.mean(draw))
    if require_positive:
        n_extreme = int((placebo_means >= observed_mean).sum())
    else:
        n_extreme = int((placebo_means <= observed_mean).sum())
    return float((1 + n_extreme) / (1 + n_permutations))


# --------------------------------------------------------------------------- #
# Gate result containers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateStep:
    """One step of the checklist: did it pass, and the numbers behind it."""

    name: str
    passed: bool
    detail: str

    def line(self) -> str:
        return f"{'PASS' if self.passed else 'FAIL'}: {self.name} — {self.detail}"


@dataclass(frozen=True)
class GateResult:
    """The full checklist verdict for one cohort/claim.

    ``passed`` is True only if every *blocking* step passed. The too-good
    tripwire is a flag, not a hard fail: when it fires it does not by itself
    sink the claim, but it forces a placebo run + top-contributor inspection
    (brain/30 step 7), so we surface it loudly via ``tripwire_flag``.
    """

    cohort: str
    n: int
    steps: list[GateStep] = field(default_factory=list)
    tripwire_flag: bool = False
    tripwire_detail: str = ""

    @property
    def passed(self) -> bool:
        return all(s.passed for s in self.steps)

    @property
    def reasons(self) -> list[str]:
        out = [s.line() for s in self.steps]
        tag = "FLAG" if self.tripwire_flag else "clear"
        out.append(f"{tag}: too-good tripwire — {self.tripwire_detail}")
        return out

    def verdict(self) -> str:
        return "PASS" if self.passed else "FAIL"

    def report_lines(self) -> list[str]:
        """Markdown-ready PASS/FAIL lines, one per gate step (+ tripwire)."""
        return [f"- **{r.split(':', 1)[0]}**:{r.split(':', 1)[1]}" for r in self.reasons]


# --------------------------------------------------------------------------- #
# Individual gate evaluators (each returns a GateStep)
# --------------------------------------------------------------------------- #
def gate_sample_size(n: int, *, min_n: int = MIN_N) -> GateStep:
    return GateStep(
        name="sample size",
        passed=n >= min_n,
        detail=f"N={n} (need >= {min_n})",
    )


def gate_after_cost(
    pnls: Sequence[float],
    cost_per_trade: float,
    *,
    t_threshold: float = T_THRESHOLD,
    require_positive: bool = True,
) -> GateStep:
    """Gate 2: after-cost expectancy positive AND |t|>=threshold.

    The t-stat is on the *gross* per-trade series (its dispersion is what the
    test statistic needs); the expectancy sign check is on the *net* mean. This
    matches fomc_drift: ``(after_cost_mean > 0) and (abs(t_stat) >= threshold)``.
    """
    net = after_cost_expectancy(pnls, cost_per_trade)
    t = t_stat(pnls)
    sign_ok = (net > 0) if require_positive else (net == net)  # NaN-safe
    passed = sign_ok and abs(t) >= t_threshold
    sign_clause = ">0 & " if require_positive else ""
    return GateStep(
        name="after-cost signal",
        passed=passed,
        detail=(
            f"net mean={net:+.5f} t={t:+.2f} "
            f"(need {sign_clause}|t|>={t_threshold})"
        ),
    )


def gate_oos_sign_stability(
    early: Sequence[float],
    late: Sequence[float],
    *,
    min_half_n: int = OOS_MIN_HALF_N,
) -> GateStep:
    """Gate 4: early/late split same sign, both halves N>=min_half_n."""
    e = _clean(early)
    la = _clean(late)
    e_mean = float(np.mean(e)) if e else float("nan")
    l_mean = float(np.mean(la)) if la else float("nan")
    n_ok = len(e) >= min_half_n and len(la) >= min_half_n
    same_sign = (e_mean > 0 and l_mean > 0) or (e_mean < 0 and l_mean < 0)
    return GateStep(
        name="OOS sign stable",
        passed=n_ok and same_sign,
        detail=(
            f"early={e_mean:+.5f} (N={len(e)}) late={l_mean:+.5f} (N={len(la)}) "
            f"(need same sign, both N>={min_half_n})"
        ),
    )


def gate_baseline_net(
    cohort_mean: float,
    baseline_mean: float,
    *,
    require_positive: bool = True,
) -> GateStep:
    """Gate 5: cohort return minus pooled / matched-control baseline.

    The cohort must beat its own universe baseline (pooled-baseline
    contamination is artifact class 5/6). Passes when net is the right sign.
    """
    net = cohort_mean - baseline_mean
    passed = (net > 0) if require_positive else (net != 0)
    return GateStep(
        name="baseline net",
        passed=passed,
        detail=(
            f"cohort={cohort_mean:+.5f} - baseline={baseline_mean:+.5f} "
            f"= net {net:+.5f} (need net {'>0' if require_positive else '!=0'})"
        ),
    )


def gate_placebo(
    observed_t: float,
    placebo_t: float,
) -> GateStep:
    """Gate 5b/6 (band form): observed |t| must exceed the placebo |t| band.

    Mirrors fomc_drift's placebo line: an effect that sits *inside* the placebo
    band (random windows look as significant) is absorbed → FAIL.
    """
    passed = abs(observed_t) > abs(placebo_t)
    return GateStep(
        name="placebo band",
        passed=passed,
        detail=(
            f"observed |t|={abs(observed_t):.2f} vs placebo |t|={abs(placebo_t):.2f} "
            f"(need observed > placebo)"
        ),
    )


def gate_permutation(
    p_value: float,
    *,
    alpha: float = PERM_ALPHA,
) -> GateStep:
    """Gate 6 (p form): matched-control permutation p < alpha.

    The product_news form: claim requires perm p < 0.05. An artifact's observed
    mean sits inside the placebo distribution → large p → FAIL.
    """
    passed = p_value < alpha
    return GateStep(
        name="matched-control permutation",
        passed=passed,
        detail=f"perm p={p_value:.4f} (need < {alpha})",
    )


def too_good_tripwire(
    values: Sequence[float],
    *,
    sharpe_max: float = SHARPE_TRIPWIRE,
    winrate_max: float = WINRATE_TRIPWIRE,
    gap_max: float = MEDIAN_MEAN_GAP_TRIPWIRE,
    top_contributor_max: float = TOP_CONTRIBUTOR_FRACTION_TRIPWIRE,
    periods_per_year: float | None = None,
) -> tuple[bool, str]:
    """Gate 7: flag a result that is suspiciously good.

    Fires if any of:
      * Sharpe > sharpe_max,
      * win rate > winrate_max,
      * |median - mean| large in robust (MAD) units, or
      * one row supplies > top_contributor_max of the total absolute deviation
        from the median.
    The last two both target outliers driving the mean (the Tiingo 224% /
    stablecoin-tail pattern); the concentration check catches the case the MAD
    gap misses — a near-constant core (MAD≈0) with a single monster row. A flag
    is not an automatic kill, but per brain/30 it mandates a placebo run +
    by-hand top-contributor inspection before the result may be recorded.
    """
    vals = _clean(values)
    if len(vals) < 2:
        return False, "N<2, tripwire not evaluable"
    arr = np.asarray(vals, dtype=float)
    s = sharpe(vals, periods_per_year=periods_per_year)
    wr = win_rate(vals)
    mean = float(arr.mean())
    median = float(np.median(arr))
    # MAD scaled to be a consistent estimator of std under normality (x 1.4826),
    # so the threshold is interpretable as "this many normal-equivalent sigmas".
    mad = float(np.median(np.abs(arr - median))) * 1.4826
    gap = abs(median - mean) / mad if mad > 0 else 0.0
    # Concentration: share of total |deviation from median| held by the single
    # largest row. 1/N for a uniform spread; ->1 when one row dominates.
    dev = np.abs(arr - median)
    total_dev = float(dev.sum())
    top_share = float(dev.max() / total_dev) if total_dev > 0 else 0.0

    flags: list[str] = []
    if abs(s) > sharpe_max:
        flags.append(f"Sharpe={s:+.2f}>{sharpe_max}")
    if wr > winrate_max:
        flags.append(f"win={wr:.0%}>{winrate_max:.0%}")
    if gap > gap_max:
        flags.append(f"|median-mean|/MAD={gap:.2f}>{gap_max}")
    if top_share > top_contributor_max:
        flags.append(f"top-row share={top_share:.0%}>{top_contributor_max:.0%}")

    if flags:
        return True, "TRIPPED: " + ", ".join(flags) + " — run placebo + inspect top contributors"
    return False, (
        f"Sharpe={s:+.2f}, win={wr:.0%}, |median-mean|/MAD={gap:.2f}, "
        f"top-row share={top_share:.0%} — none exceeded"
    )


# --------------------------------------------------------------------------- #
# The full checklist
# --------------------------------------------------------------------------- #
def evaluate_gate(
    cohort: str,
    per_event_pnls: Sequence[float],
    *,
    cost_per_trade: float,
    oos_split: tuple[Sequence[float], Sequence[float]],
    baseline_mean: float,
    placebo_cells: Sequence[Sequence[float]] | None = None,
    placebo_t: float | None = None,
    seed: int = 7,
    n_permutations: int = DEFAULT_PERMUTATIONS,
    min_n: int = MIN_N,
    t_threshold: float = T_THRESHOLD,
    require_positive: bool = True,
    preregistered: bool = False,
    provenance_documented: bool = False,
    periods_per_year: float | None = None,
) -> GateResult:
    """Run brain/30's full universal gate on one cohort and return the verdict.

    Steps (numbered as in brain/30):

      1. pre-registration       — acknowledgement flag (``preregistered``).
      2. friction realism       — after-cost expectancy positive & |t|>=thresh.
      3. (look-ahead audit)     — design gate; not numerically checkable here.
      4. OOS sign stability     — early/late same sign, both N>=10.
      5. pooled / matched net   — cohort minus baseline; right sign.
      6. matched-control perm   — either a composition-matched permutation
                                   (``placebo_cells``, seeded) OR a placebo |t|
                                   band (``placebo_t``). At least one is required.
      7. too-good tripwire      — Sharpe>3 / win>85% / |median-mean| large → flag.
      8. data provenance        — acknowledgement flag (``provenance_documented``).

    Steps 1 and 8 are documentation gates: a pure function cannot inspect a
    pre-reg commit or a data-source doc, so the caller must *assert* them by
    passing the flags. Defaulting to False means a forgetful caller FAILS the
    gate rather than silently passing it — that is the whole point.

    ``placebo_cells`` and ``placebo_t`` are alternatives; pass whichever the
    test produced. If both are given, both are checked. If neither is given the
    permutation gate FAILS (you cannot claim an edge without a placebo).
    """
    pnls = list(per_event_pnls)
    early, late = oos_split
    n = len(_clean(pnls))
    cohort_mean = float(np.mean(_clean(pnls))) if _clean(pnls) else float("nan")
    observed_t = t_stat(pnls)

    steps: list[GateStep] = []

    # (1) pre-registration
    steps.append(
        GateStep(
            name="pre-registration",
            passed=preregistered,
            detail="hypothesis/cohort/windows/N/kill-criteria committed before results"
            if preregistered
            else "NOT acknowledged — pass preregistered=True only with a committed pre-reg",
        )
    )

    # (2) friction realism + (N gate from brain/30 step that pairs with it)
    steps.append(gate_sample_size(n, min_n=min_n))
    steps.append(
        gate_after_cost(
            pnls,
            cost_per_trade,
            t_threshold=t_threshold,
            require_positive=require_positive,
        )
    )

    # (4) OOS sign stability
    steps.append(gate_oos_sign_stability(early, late))

    # (5) pooled / matched baseline net
    steps.append(
        gate_baseline_net(cohort_mean, baseline_mean, require_positive=require_positive)
    )

    # (6) matched-control permutation and/or placebo band
    if placebo_cells is None and placebo_t is None:
        steps.append(
            GateStep(
                name="matched-control permutation",
                passed=False,
                detail="no placebo supplied (need placebo_cells or placebo_t) — cannot claim edge",
            )
        )
    else:
        if placebo_cells is not None:
            p = permutation_pvalue(
                cohort_mean,
                placebo_cells,
                seed=seed,
                n_permutations=n_permutations,
                require_positive=require_positive,
            )
            steps.append(gate_permutation(p))
        if placebo_t is not None:
            steps.append(gate_placebo(observed_t, placebo_t))

    # (8) data provenance
    steps.append(
        GateStep(
            name="data provenance",
            passed=provenance_documented,
            detail="source/construction/staleness documented"
            if provenance_documented
            else "NOT acknowledged — pass provenance_documented=True only with a provenance note",
        )
    )

    # (7) too-good tripwire — a flag, evaluated last, never blocks on its own
    flagged, detail = too_good_tripwire(pnls, periods_per_year=periods_per_year)

    return GateResult(
        cohort=cohort,
        n=n,
        steps=steps,
        tripwire_flag=flagged,
        tripwire_detail=detail,
    )


def gate_summary(result: GateResult) -> str:
    """One-line human summary: PASS/FAIL plus the first failing reason."""
    if result.passed:
        tail = " (tripwire FLAGGED — inspect)" if result.tripwire_flag else ""
        return f"{result.cohort}: PASS{tail}"
    first_fail = next((s for s in result.steps if not s.passed), None)
    why = first_fail.line() if first_fail else "unknown"
    return f"{result.cohort}: FAIL — {why}"


__all__ = [
    "GateResult",
    "GateStep",
    "after_cost_expectancy",
    "evaluate_gate",
    "gate_after_cost",
    "gate_baseline_net",
    "gate_oos_sign_stability",
    "gate_permutation",
    "gate_placebo",
    "gate_sample_size",
    "gate_summary",
    "permutation_pvalue",
    "sharpe",
    "t_stat",
    "too_good_tripwire",
    "welch_t",
    "win_rate",
]


# Mapping export so callers can introspect default thresholds programmatically.
DEFAULT_THRESHOLDS: Mapping[str, float] = {
    "min_n": MIN_N,
    "t_threshold": T_THRESHOLD,
    "oos_min_half_n": OOS_MIN_HALF_N,
    "perm_alpha": PERM_ALPHA,
    "sharpe_tripwire": SHARPE_TRIPWIRE,
    "winrate_tripwire": WINRATE_TRIPWIRE,
    "median_mean_gap_tripwire": MEDIAN_MEAN_GAP_TRIPWIRE,
    "top_contributor_fraction_tripwire": TOP_CONTRIBUTOR_FRACTION_TRIPWIRE,
}
