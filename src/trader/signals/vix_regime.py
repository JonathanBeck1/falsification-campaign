"""VIXRegimeBrain — deterministic VIX-threshold position sizing.

Conservative tightens thresholds (de-risk earlier); Aggressive widens them
(tolerate higher vol before reducing). The two profiles are independent
brain instances with distinct names, so each gets its own paper portfolio
and equity curve in the horse race.

Per `brain/decisions/2026-05-21-horse-race-phase-1.md`.
"""

from __future__ import annotations

from dataclasses import dataclass

from trader.signals.base import Decision
from trader.storage.snapshot import DailySnapshot


@dataclass(frozen=True)
class VIXThresholdBand:
    """One row in a VIX → target_pct mapping. `vix_lt` is the strict upper bound."""

    vix_lt: float
    target_pct: float


# Conservative: de-risk earlier. Flat by VIX 28.
THRESHOLDS_CONSERVATIVE: tuple[VIXThresholdBand, ...] = (
    VIXThresholdBand(vix_lt=13.0, target_pct=1.00),
    VIXThresholdBand(vix_lt=17.0, target_pct=0.70),
    VIXThresholdBand(vix_lt=22.0, target_pct=0.40),
    VIXThresholdBand(vix_lt=28.0, target_pct=0.20),
)
# Anything >= 28 (Conservative) -> 0.00.
CONSERVATIVE_CRISIS_TARGET = 0.00

# Aggressive: tolerate higher vol. Flat only at VIX 32+.
THRESHOLDS_AGGRESSIVE: tuple[VIXThresholdBand, ...] = (
    VIXThresholdBand(vix_lt=18.0, target_pct=1.00),
    VIXThresholdBand(vix_lt=25.0, target_pct=0.70),
    VIXThresholdBand(vix_lt=32.0, target_pct=0.40),
)
# Anything >= 32 (Aggressive) -> 0.00.
AGGRESSIVE_CRISIS_TARGET = 0.00


def _resolve_target(
    vix: float, bands: tuple[VIXThresholdBand, ...], crisis_target: float
) -> tuple[float, str]:
    for band in bands:
        if vix < band.vix_lt:
            return band.target_pct, f"VIX={vix:.1f} < {band.vix_lt:.1f}"
    top = bands[-1].vix_lt
    return crisis_target, f"VIX={vix:.1f} >= {top:.1f} (crisis)"


class VIXRegimeBrain:
    """Deterministic VIX-regime brain. No LLM.

    Maps current VIX to a position target via a profile-specific threshold
    table. Returns HOLD with low confidence if VIX is missing from the
    snapshot (data gap) so RiskGate can size naturally.
    """

    uses_llm = False

    def __init__(
        self,
        *,
        thresholds: tuple[VIXThresholdBand, ...],
        crisis_target: float,
        name: str,
    ) -> None:
        if not thresholds:
            raise ValueError("thresholds must be non-empty")
        # Bands must be strictly ascending on vix_lt so the first-match scan is well-defined.
        prev = -float("inf")
        for band in thresholds:
            if band.vix_lt <= prev:
                raise ValueError("threshold vix_lt values must be strictly ascending")
            if not 0.0 <= band.target_pct <= 1.0:
                raise ValueError("threshold target_pct must be in [0, 1]")
            prev = band.vix_lt
        if not 0.0 <= crisis_target <= 1.0:
            raise ValueError("crisis_target must be in [0, 1]")
        self._thresholds = thresholds
        self._crisis_target = crisis_target
        self.name = name

    def decide(self, snapshot: DailySnapshot) -> Decision:
        vix = snapshot.macro.vix
        if vix is None:
            return Decision(
                action="HOLD",
                target_pct=0.0,
                confidence=0.2,
                reasoning="VIX missing from snapshot; deferring to RiskGate.",
            )

        target, reason = _resolve_target(vix, self._thresholds, self._crisis_target)
        if target >= 1.0:
            action = "BUY"
        elif target == 0.0:
            action = "SELL"
        else:
            # Mid-band targets are advisory; the runner / RiskGate translates
            # delta vs current position into BUY/SELL/HOLD. We default to BUY
            # so a fresh portfolio buys to the target rather than holding 0.
            action = "BUY"

        return Decision(
            action=action,
            target_pct=target,
            confidence=0.8,
            reasoning=f"{reason} → target {target:.0%}",
        )


def vix_regime_conservative(name: str = "VIXRegimeConservative") -> VIXRegimeBrain:
    return VIXRegimeBrain(
        thresholds=THRESHOLDS_CONSERVATIVE,
        crisis_target=CONSERVATIVE_CRISIS_TARGET,
        name=name,
    )


def vix_regime_aggressive(name: str = "VIXRegimeAggressive") -> VIXRegimeBrain:
    return VIXRegimeBrain(
        thresholds=THRESHOLDS_AGGRESSIVE,
        crisis_target=AGGRESSIVE_CRISIS_TARGET,
        name=name,
    )
