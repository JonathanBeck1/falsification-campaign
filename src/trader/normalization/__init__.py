"""Transform raw source payloads into stable internal records.

Raw adapter outputs → structured `Event` records. See `models.py` for the
schema and `brain/08_news_event_schema.md` for the design rationale.
"""

from trader.normalization.alpaca_news import alpaca_news_to_events
from trader.normalization.fed import fed_news_to_events
from trader.normalization.finnhub import finnhub_news_to_events
from trader.normalization.models import Entity, Event, EvidenceSnippet, ModelOutputMeta, stable_event_id
from trader.normalization.sec import sec_news_to_events
from trader.normalization.yahoo import yahoo_news_to_events

__all__ = [
    "Entity",
    "Event",
    "EvidenceSnippet",
    "ModelOutputMeta",
    "alpaca_news_to_events",
    "fed_news_to_events",
    "finnhub_news_to_events",
    "sec_news_to_events",
    "stable_event_id",
    "yahoo_news_to_events",
]
