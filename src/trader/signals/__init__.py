"""Signal construction, scoring, and feature logic.

Per `brain/01_system_architecture.md`, signals are deterministic outputs from
evidence and features. An LLM can help classify events, but the signal record
must be structured and testable. Per `brain/10_llm_agent_boundaries.md`, LLMs
do not place trades and do not override risk gates.

`ClassicalBrain` is a pure-rule signal generator (no LLM). `HybridBrain` uses
an LLM only to extract structured features; a deterministic rule decides.
`SentimentMomentumBrain` consumes stored `news_events` to produce a
sentiment-weighted momentum signal; no LLM.
"""

from trader.signals.base import Brain, Decision
from trader.signals.classical import ClassicalBrain
from trader.signals.hybrid import HybridBrain
from trader.signals.sentiment_momentum import SentimentMomentumBrain

__all__ = ["Brain", "ClassicalBrain", "Decision", "HybridBrain", "SentimentMomentumBrain"]
