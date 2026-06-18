"""BuyAndHoldBrain — control baseline. Always target 100% long."""

from __future__ import annotations

from collections.abc import Sequence

from trader.signals.base import Decision
from trader.storage.snapshot import DailySnapshot


def buy_and_hold_return(prices: Sequence[float]) -> float | None:
    """Total return of buying at the first price and holding to the last.

    Pure and I/O-free. Returns None when there are fewer than two prices or the
    first price is non-positive (can't form a return). This is the benchmark the
    options strategies must beat to claim alpha.
    """
    if len(prices) < 2:
        return None
    first = float(prices[0])
    last = float(prices[-1])
    if first <= 0:
        return None
    return round(last / first - 1.0, 6)


class BuyAndHoldBrain:
    uses_llm = False

    def __init__(self, *, name: str = "BuyAndHoldBrain") -> None:
        self.name = name

    def decide(self, snapshot: DailySnapshot) -> Decision:
        return Decision(
            action="BUY",
            target_pct=1.0,
            confidence=1.0,
            reasoning="Buy-and-hold baseline: always 100% long.",
        )
