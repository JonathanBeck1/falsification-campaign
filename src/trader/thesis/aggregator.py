"""ThesisAggregator — combine open theses into a target position.

Multi-thesis snapshots are the normal case during big events (an FOMC
press conference produces 5-15 headlines in 20 minutes; earnings days
produce many simultaneous megacap events). The aggregator:

1. Filters to theses still within their actionable horizon.
2. Applies a per-thesis net-edge check (subtract estimated round-trip
   cost; theses with insufficient net edge are zeroed) — audit problem #8.
3. Weights each by confidence (high=1.0, medium=0.5, low=0.25).
4. Sums signed_magnitudes (long contributes +, short contributes -).
5. Applies the macro regime overlay AND a discrete regime classification
   tag — audit problem #7.
6. Enforces minimum holding period (won't flip an open position inside
   the lock window) — audit problem #8.
7. Returns a target_pct in [0, 1] for SPY/QQQ exposure.

The output is deterministic given the same inputs. The regime overlay
caps maximum exposure when macro stress is elevated; CRISIS regime
forces flat regardless of theses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from trader.thesis.taxonomy import CONFIDENCE_WEIGHT, AggregateInputs, Thesis

RegimeTag = Literal["LOW_VOL", "NORMAL", "HIGH_VOL", "CRISIS"]


@dataclass(frozen=True)
class RegimeClassification:
    """Discrete regime label derived from macro inputs. Passed to LLM
    prompts so the model knows what environment it's operating in
    (audit problem #7), and consumed by the aggregator to set the
    position cap and crisis-flat behavior."""

    tag: RegimeTag
    reasons: tuple[str, ...]


def classify_regime(
    inputs: AggregateInputs, *, baseline_realized_vol: float | None = None
) -> RegimeClassification:
    """Deterministic regime classification.

    CRISIS: VIX > 35 OR realized_vol > 3x baseline. System should go flat.
    HIGH_VOL: VIX > 25 OR deep curve inversion (10y-2y < -0.5).
    LOW_VOL: VIX < 15 AND curve > 0.
    NORMAL: everything in between.
    """
    reasons: list[str] = []

    if inputs.vix is not None and inputs.vix > 35:
        reasons.append(f"vix={inputs.vix:.1f}>35")
        return RegimeClassification(tag="CRISIS", reasons=tuple(reasons))
    if (
        inputs.realized_vol_20d is not None
        and baseline_realized_vol is not None
        and baseline_realized_vol > 0
        and inputs.realized_vol_20d / baseline_realized_vol > 3.0
    ):
        reasons.append(
            f"realized_vol={inputs.realized_vol_20d:.3f}>3x_baseline({baseline_realized_vol:.3f})"
        )
        return RegimeClassification(tag="CRISIS", reasons=tuple(reasons))

    if inputs.vix is not None and inputs.vix > 25:
        reasons.append(f"vix={inputs.vix:.1f}>25")
        return RegimeClassification(tag="HIGH_VOL", reasons=tuple(reasons))
    if inputs.yield_curve_10y_2y is not None and inputs.yield_curve_10y_2y < -0.5:
        reasons.append(f"curve={inputs.yield_curve_10y_2y:.2f}<-0.5")
        return RegimeClassification(tag="HIGH_VOL", reasons=tuple(reasons))

    if (
        inputs.vix is not None
        and inputs.vix < 15
        and inputs.yield_curve_10y_2y is not None
        and inputs.yield_curve_10y_2y > 0
    ):
        reasons.append(f"vix={inputs.vix:.1f}<15+curve_positive")
        return RegimeClassification(tag="LOW_VOL", reasons=tuple(reasons))

    return RegimeClassification(tag="NORMAL", reasons=("default",))


@dataclass(frozen=True)
class AggregateDecision:
    """The output. target_pct is the recommended position in [0, 1]."""

    target_pct: float
    direction_sum: float
    active_theses: list[Thesis]
    expired_theses: list[Thesis]
    regime_cap: float
    regime_reasons: list[str]
    regime_tag: RegimeTag
    baseline_pct: float
    cost_filtered_theses: list[Thesis] = field(default_factory=list)
    # Theses whose template.confirmation_required=True but
    # confirmation_state is still "pending" — excluded from direction_sum
    # per the brain/21 confirmation-gating rule. Surfaced so audit + UI
    # can show the user "this thesis is awaiting confirmation."
    pending_confirmation_theses: list[Thesis] = field(default_factory=list)
    holding_period_locked: bool = False
    pacing_clipped: bool = False
    note: str = ""


class ThesisAggregator:
    """Combine open theses + macro overlay into a target position."""

    def __init__(
        self,
        *,
        baseline_pct: float = 0.5,
        max_position_pct: float = 1.0,
        vix_stress_threshold: float = 30.0,
        vix_stress_cap: float = 0.5,
        yield_curve_stress_threshold: float = -0.5,
        yield_curve_stress_cap: float = 0.5,
        realized_vol_stress_ratio: float = 2.0,
        realized_vol_stress_cap: float = 0.5,
        # Per-trade round-trip cost estimate, in percent. Default 0.05%
        # reflects SPY/QQQ at typical liquidity (~0.005% spread + ~0%
        # commission on Alpaca, with margin for slippage). Theses whose
        # expected magnitude is below this are zeroed.
        round_trip_cost_pct: float = 0.05,
        # Minutes a position must be held before the aggregator is
        # allowed to flip direction. Anti-churn (audit problem #8).
        min_holding_minutes: int = 15,
        # Maximum absolute change in target_pct per cycle. Anti-spiral
        # pacing (audit problem #13): caps how quickly we can "average
        # down" or "average up" across consecutive snapshots. Default
        # 0.20 = ±20 percentage points per cycle. Set to 1.0 to disable.
        max_target_change_per_cycle: float = 0.20,
    ) -> None:
        if not 0 < max_target_change_per_cycle <= 1.0:
            raise ValueError("max_target_change_per_cycle must be in (0, 1]")
        self.baseline_pct = baseline_pct
        self.max_position_pct = max_position_pct
        self.vix_stress_threshold = vix_stress_threshold
        self.vix_stress_cap = vix_stress_cap
        self.yield_curve_stress_threshold = yield_curve_stress_threshold
        self.yield_curve_stress_cap = yield_curve_stress_cap
        self.realized_vol_stress_ratio = realized_vol_stress_ratio
        self.realized_vol_stress_cap = realized_vol_stress_cap
        self.round_trip_cost_pct = round_trip_cost_pct
        self.min_holding_minutes = min_holding_minutes
        self.max_target_change_per_cycle = max_target_change_per_cycle

    def aggregate(
        self,
        theses: list[Thesis],
        inputs: AggregateInputs,
        *,
        now: datetime | None = None,
        baseline_realized_vol: float | None = None,
        current_position_pct: float | None = None,
        position_opened_at: datetime | None = None,
        prior_target_pct: float | None = None,
    ) -> AggregateDecision:
        now = now or datetime.now(UTC)
        active, expired = self._split_by_horizon(theses, now)

        # Net-edge filter: drop theses whose expected magnitude doesn't
        # clear the round-trip cost. (audit problem #8)
        cost_filtered: list[Thesis] = []
        net_active: list[Thesis] = []
        for t in active:
            if abs(t.template.expected_magnitude_pct) < self.round_trip_cost_pct:
                cost_filtered.append(t)
            else:
                net_active.append(t)

        # Confirmation gating (brain/21 "Confirmation gating" section,
        # added per Codex review 2026-05-20): theses whose template
        # requires confirmation are excluded from direction_sum until
        # confirmation_state flips to "confirmed". The pending list is
        # surfaced on AggregateDecision so dashboards/audit can show
        # which signals are awaiting a second source.
        pending_confirmation: list[Thesis] = []
        confirmed_active: list[Thesis] = []
        for t in net_active:
            if t.is_aggregation_eligible:
                confirmed_active.append(t)
            else:
                pending_confirmation.append(t)

        direction_sum = sum(
            t.signed_magnitude * CONFIDENCE_WEIGHT[t.confidence]
            for t in confirmed_active
        )

        regime = classify_regime(inputs, baseline_realized_vol=baseline_realized_vol)

        # CRISIS regime forces flat regardless of theses (audit problem #7).
        if regime.tag == "CRISIS":
            return AggregateDecision(
                target_pct=0.0,
                direction_sum=round(direction_sum, 6),
                active_theses=net_active,
                expired_theses=expired,
                regime_cap=0.0,
                regime_reasons=list(regime.reasons),
                regime_tag="CRISIS",
                baseline_pct=self.baseline_pct,
                cost_filtered_theses=cost_filtered,
                pending_confirmation_theses=pending_confirmation,
                holding_period_locked=False,
                note=(
                    "CRISIS regime -> flat | "
                    f"regime_reasons=[{'; '.join(regime.reasons)}]"
                ),
            )

        cap, cap_reasons = self._regime_cap(inputs, baseline_realized_vol)
        nudge = max(-1.0, min(1.0, direction_sum * 3.0))
        target = self.baseline_pct + nudge * 0.5
        target = max(0.0, min(self.max_position_pct * cap, target))

        # Pacing clip (audit problem #13): if the new target would move
        # more than max_target_change_per_cycle from the prior target in
        # one cycle, clamp it. Prevents the LLM-induced "buy at $100,
        # buy more at $90, buy more at $80" spiral by giving us at least
        # one cycle's worth of breathing room before doubling down.
        pacing_clipped = False
        if prior_target_pct is not None:
            delta = target - prior_target_pct
            max_change = self.max_target_change_per_cycle
            if delta > max_change:
                target = prior_target_pct + max_change
                pacing_clipped = True
            elif delta < -max_change:
                target = prior_target_pct - max_change
                pacing_clipped = True
            if pacing_clipped:
                cap_reasons = [
                    *cap_reasons,
                    f"pacing_clip(prev={prior_target_pct:.0%},max_change={max_change:.0%})",
                ]

        # Min-holding-period enforcement (audit problem #8): if a
        # position was opened inside the lock window AND the new target
        # would flip direction, keep the current position.
        holding_locked = False
        if (
            current_position_pct is not None
            and position_opened_at is not None
            and (now - position_opened_at) < timedelta(minutes=self.min_holding_minutes)
            and self._would_flip_direction(current_position_pct, target)
        ):
            target = current_position_pct
            holding_locked = True
            cap_reasons = [
                *cap_reasons,
                f"holding_period_lock<{self.min_holding_minutes}m",
            ]

        note = self._build_note(
            net_active,
            direction_sum,
            cap,
            cap_reasons,
            regime,
            len(cost_filtered),
            len(pending_confirmation),
        )
        return AggregateDecision(
            target_pct=round(target, 4),
            direction_sum=round(direction_sum, 6),
            active_theses=net_active,
            expired_theses=expired,
            regime_cap=round(cap, 4),
            regime_reasons=cap_reasons,
            regime_tag=regime.tag,
            baseline_pct=self.baseline_pct,
            cost_filtered_theses=cost_filtered,
            pending_confirmation_theses=pending_confirmation,
            holding_period_locked=holding_locked,
            pacing_clipped=pacing_clipped,
            note=note,
        )

    @staticmethod
    def _would_flip_direction(current_pct: float, target_pct: float) -> bool:
        baseline = 0.5
        if current_pct > baseline and target_pct < baseline:
            return True
        return current_pct < baseline and target_pct > baseline

    def _split_by_horizon(
        self, theses: list[Thesis], now: datetime
    ) -> tuple[list[Thesis], list[Thesis]]:
        active: list[Thesis] = []
        expired: list[Thesis] = []
        for t in theses:
            horizon_end = t.created_at + timedelta(minutes=t.horizon_minutes)
            if now <= horizon_end:
                active.append(t)
            else:
                expired.append(t)
        return active, expired

    def _regime_cap(
        self, inputs: AggregateInputs, baseline_vol: float | None
    ) -> tuple[float, list[str]]:
        caps: list[float] = [1.0]
        reasons: list[str] = []

        if inputs.vix is not None and inputs.vix > self.vix_stress_threshold:
            caps.append(self.vix_stress_cap)
            reasons.append(f"VIX={inputs.vix:.1f} > {self.vix_stress_threshold}")

        if (
            inputs.yield_curve_10y_2y is not None
            and inputs.yield_curve_10y_2y < self.yield_curve_stress_threshold
        ):
            caps.append(self.yield_curve_stress_cap)
            reasons.append(
                f"10y-2y={inputs.yield_curve_10y_2y:.2f} < {self.yield_curve_stress_threshold}"
            )

        if (
            inputs.realized_vol_20d is not None
            and baseline_vol is not None
            and baseline_vol > 0
            and inputs.realized_vol_20d / baseline_vol > self.realized_vol_stress_ratio
        ):
            caps.append(self.realized_vol_stress_cap)
            reasons.append(
                f"realized_vol_20d={inputs.realized_vol_20d:.3f} > {self.realized_vol_stress_ratio}x baseline"
            )

        return min(caps), reasons

    @staticmethod
    def _build_note(
        active: list[Thesis],
        direction_sum: float,
        cap: float,
        reasons: list[str],
        regime: RegimeClassification,
        cost_filtered_count: int,
        pending_confirmation_count: int = 0,
    ) -> str:
        bullets = [
            f"regime={regime.tag}",
            f"theses_active={len(active)}",
            f"direction_sum={direction_sum:+.4f}",
            f"regime_cap={cap:.2f}",
        ]
        if cost_filtered_count:
            bullets.append(f"theses_cost_filtered={cost_filtered_count}")
        if pending_confirmation_count:
            bullets.append(f"theses_pending_confirmation={pending_confirmation_count}")
        if reasons:
            bullets.append("regime_reasons=[" + "; ".join(reasons) + "]")
        return " | ".join(bullets)
