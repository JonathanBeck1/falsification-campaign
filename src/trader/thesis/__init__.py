"""ThesisEngine — deterministic lookup from enriched event labels to a
trading thesis. Per `brain/21_news_to_trade_thesis_algorithm.md`.

The THESIS_TABLE in `taxonomy.py` IS the trading algorithm. Every entry is
a hypothesis we can read, audit, and backtest. The LLM enricher puts each
event into the right row of the table; the engine emits the Thesis; the
aggregator combines theses into a target position. No floats from the
model influence the position directly.
"""

from trader.thesis.aggregator import AggregateDecision, ThesisAggregator
from trader.thesis.engine import ThesisEngine
from trader.thesis.taxonomy import THESIS_TABLE, Thesis, ThesisTemplate

__all__ = [
    "THESIS_TABLE",
    "AggregateDecision",
    "Thesis",
    "ThesisAggregator",
    "ThesisEngine",
    "ThesisTemplate",
]
