"""ClassicalBrain — deterministic SMA/RSI/macro rules, no LLM.

This is the honest "can simple rules beat buy-and-hold?" baseline. Costs $0/day.

Rule:
- If price > SMA-200 * (1 + sma_buffer_pct) AND RSI not overbought AND macro
  not stressed: target `long_target` (default 100% long).
- If RSI > rsi_overbought: trim to `rsi_overbought_target` (take some risk off).
- If price < SMA-200: target `downtrend_target` (default flat).
- If yield curve deeply inverted (< curve_inversion_threshold): target
  `curve_inversion_target`.
- If VIX > vix_crisis_threshold (panic): defensive — cap at
  `vix_crisis_target`.

Defaults match the original hardcoded thresholds (75/30/-0.5/0.5/0.3/1.0/0.0).
Phase 4 of the horse race parameterizes these as constructor kwargs so the
brain can be instantiated as Conservative + Aggressive variants without
forking the class. See `brain/decisions/2026-05-21-horse-race-phase-4.md`.
"""

from __future__ import annotations

from trader.signals.base import Decision
from trader.storage.snapshot import DailySnapshot


def _check_target_pct(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0.0, 1.0]; got {value!r}")


class ClassicalBrain:
    uses_llm = False

    def __init__(
        self,
        *,
        name: str = "ClassicalBrain",
        sma_buffer_pct: float = 0.0,
        rsi_overbought: float = 75.0,
        rsi_overbought_target: float = 0.5,
        vix_crisis_threshold: float = 30.0,
        vix_crisis_target: float = 0.30,
        curve_inversion_threshold: float = -0.5,
        curve_inversion_target: float = 0.30,
        long_target: float = 1.0,
        downtrend_target: float = 0.0,
    ) -> None:
        if sma_buffer_pct < 0.0:
            raise ValueError(f"sma_buffer_pct must be >= 0; got {sma_buffer_pct!r}")
        if not 0.0 < rsi_overbought < 100.0:
            raise ValueError(f"rsi_overbought must be in (0, 100); got {rsi_overbought!r}")
        if vix_crisis_threshold <= 0.0:
            raise ValueError(f"vix_crisis_threshold must be > 0; got {vix_crisis_threshold!r}")
        _check_target_pct("rsi_overbought_target", rsi_overbought_target)
        _check_target_pct("vix_crisis_target", vix_crisis_target)
        _check_target_pct("curve_inversion_target", curve_inversion_target)
        _check_target_pct("long_target", long_target)
        _check_target_pct("downtrend_target", downtrend_target)

        self.name = name
        self._sma_buffer_pct = sma_buffer_pct
        self._rsi_overbought = rsi_overbought
        self._rsi_overbought_target = rsi_overbought_target
        self._vix_crisis_threshold = vix_crisis_threshold
        self._vix_crisis_target = vix_crisis_target
        self._curve_inversion_threshold = curve_inversion_threshold
        self._curve_inversion_target = curve_inversion_target
        self._long_target = long_target
        self._downtrend_target = downtrend_target

    def decide(self, snapshot: DailySnapshot) -> Decision:
        price = snapshot.latest_bar.close
        sma200 = snapshot.sma_200
        rsi = snapshot.rsi_14
        vix = snapshot.macro.vix
        curve = snapshot.macro.yield_curve_10y_2y

        # Insufficient data → flat.
        if sma200 is None or rsi is None:
            return Decision("HOLD", 0.0, 0.3, "Not enough history yet (need 200d SMA).")

        # Crisis regime
        if vix is not None and vix > self._vix_crisis_threshold:
            return Decision(
                "SELL",
                target_pct=self._vix_crisis_target,
                confidence=0.7,
                reasoning=(
                    f"VIX={vix:.1f} > {self._vix_crisis_threshold:.1f}, defensive mode, "
                    f"cap exposure to {self._vix_crisis_target:.0%}."
                ),
            )

        # Hard downtrend
        if price < sma200:
            return Decision(
                "SELL",
                target_pct=self._downtrend_target,
                confidence=0.6,
                reasoning=(
                    f"Price {price:.2f} < SMA200 {sma200:.2f}, downtrend → "
                    f"{self._downtrend_target:.0%}."
                ),
            )

        # Deep yield curve inversion (recession signal)
        if curve is not None and curve < self._curve_inversion_threshold:
            return Decision(
                "SELL",
                target_pct=self._curve_inversion_target,
                confidence=0.55,
                reasoning=(
                    f"Yield curve 10y-2y = {curve:.2f} < {self._curve_inversion_threshold:.2f}, "
                    f"inverted → {self._curve_inversion_target:.0%}."
                ),
            )

        # Overbought
        if rsi > self._rsi_overbought:
            return Decision(
                "SELL",
                target_pct=self._rsi_overbought_target,
                confidence=0.5,
                reasoning=(
                    f"RSI {rsi:.1f} > {self._rsi_overbought:.1f}, overbought → "
                    f"{self._rsi_overbought_target:.0%}."
                ),
            )

        # SMA-200 buffer (Conservative requires price to clear SMA by a margin
        # before going long; default 0.0 buffer preserves original behavior).
        sma_threshold = sma200 * (1.0 + self._sma_buffer_pct)
        if price <= sma_threshold:
            return Decision(
                "HOLD",
                target_pct=self._downtrend_target,
                confidence=0.4,
                reasoning=(
                    f"Price {price:.2f} above SMA200 {sma200:.2f} but below "
                    f"buffer threshold {sma_threshold:.2f} ({self._sma_buffer_pct:.1%}); "
                    f"hold at {self._downtrend_target:.0%}."
                ),
            )

        # Trend up, not overbought, no macro stress → long target.
        return Decision(
            "BUY",
            target_pct=self._long_target,
            confidence=0.6,
            reasoning=(
                f"Uptrend (px {price:.2f} > SMA200*{1.0 + self._sma_buffer_pct:.2f}={sma_threshold:.2f}), "
                f"RSI {rsi:.1f}, no macro red flag → {self._long_target:.0%}."
            ),
        )


def classical_conservative(name: str = "ClassicalConservative") -> ClassicalBrain:
    """Conservative dial: buffer SMA200 by 1%, trim at RSI 65, flat in VIX > 25
    or curve < -0.25, max long target 0.70."""
    return ClassicalBrain(
        name=name,
        sma_buffer_pct=0.01,
        rsi_overbought=65.0,
        rsi_overbought_target=0.30,
        vix_crisis_threshold=25.0,
        vix_crisis_target=0.0,
        curve_inversion_threshold=-0.25,
        curve_inversion_target=0.0,
        long_target=0.70,
    )


def classical_aggressive(name: str = "ClassicalAggressive") -> ClassicalBrain:
    """Aggressive dial: no SMA buffer, tolerate RSI up to 80, full long, only
    defensive in VIX > 35 (other macro knobs at default)."""
    return ClassicalBrain(
        name=name,
        rsi_overbought=80.0,
        rsi_overbought_target=0.7,
        vix_crisis_threshold=35.0,
    )
