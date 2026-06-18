"""Brain protocol — every decision-maker implements `decide(snapshot)`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from trader.storage.snapshot import DailySnapshot

Action = Literal["BUY", "SELL", "HOLD"]


@dataclass(frozen=True)
class Decision:
    action: Action
    target_pct: float  # desired portfolio weight in [0, 1]
    confidence: float  # in [0, 1]
    reasoning: str
    llm_cost_usd: float = 0.0  # 0 for non-LLM brains
    llm_model: str | None = None
    llm_prompt_hash: str | None = None
    llm_input_tokens: int | None = None
    llm_output_tokens: int | None = None
    llm_cached_tokens: int = 0
    llm_latency_ms: int | None = None


class Brain(Protocol):
    """Decision module.

    A Brain may be deterministic, LLM-assisted, or a baseline. The name does not
    imply the module gets unchecked authority to trade; risk gates and execution
    boundaries still sit downstream.

    `name` is the unique identifier used as the SQLite portfolio key. Variants
    of the same strategy (e.g., conservative vs aggressive HybridBrain with
    different LLM models) MUST set distinct `name` values at construction time.

    `uses_llm` lets the runner gate LLM-using brains on data freshness, daily
    budget, and per-cycle call cap without hardcoding brain-name strings.
    """

    name: str
    uses_llm: bool

    def decide(self, snapshot: DailySnapshot) -> Decision: ...
