from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trader.normalization.models import Entity, Event, EvidenceSnippet
from trader.storage.store import Store


def demo_events(*, limit: int = 5) -> list[Event]:
    base_time = datetime(2026, 5, 20, 13, 0, tzinfo=UTC)
    templates = [
        {
            "event_id": "evt_demo_fed_patience",
            "title": "Fed comments move SPY",
            "summary": "Powell said the Fed will be patient on interest rates.",
            "event_type": "fed_commentary",
            "urgency": "high",
            "entities": [Entity(name="SPY", ticker="SPY", confidence=0.8, role="mentioned")],
            "asset_scope": ["index", "macro"],
            "index_exposure": ["SPY", "QQQ"],
        },
        {
            "event_id": "evt_demo_aapl_guidance",
            "title": "Apple raises guidance after services strength",
            "summary": "Apple raised its outlook after stronger services revenue.",
            "event_type": "guidance_raise",
            "urgency": "high",
            "entities": [Entity(name="Apple Inc.", ticker="AAPL", confidence=0.95, role="primary")],
            "asset_scope": ["single_name"],
            "index_exposure": [],
        },
        {
            "event_id": "evt_demo_nvda_chip",
            "title": "Nvidia announces new AI accelerator",
            "summary": "Nvidia unveiled a new AI chip for data centers.",
            "event_type": "product_launch",
            "urgency": "normal",
            "entities": [Entity(name="Nvidia", ticker="NVDA", confidence=0.95, role="primary")],
            "asset_scope": ["single_name"],
            "index_exposure": [],
        },
        {
            "event_id": "evt_demo_msft_probe",
            "title": "Regulators open Microsoft cloud investigation",
            "summary": "Regulators opened an investigation into Microsoft cloud licensing practices.",
            "event_type": "investigation",
            "urgency": "high",
            "entities": [Entity(name="Microsoft", ticker="MSFT", confidence=0.95, role="primary")],
            "asset_scope": ["single_name"],
            "index_exposure": [],
        },
        {
            "event_id": "evt_demo_spy_inflation",
            "title": "Stocks fall after hotter inflation report",
            "summary": "Stocks fell after inflation data came in hotter than economists expected.",
            "event_type": "macro_surprise",
            "urgency": "breaking",
            "entities": [Entity(name="SPY", ticker="SPY", confidence=0.75, role="mentioned")],
            "asset_scope": ["index", "macro"],
            "index_exposure": ["SPY", "QQQ"],
        },
        {
            "event_id": "evt_demo_aapl_prior_services",
            "title": "Apple services revenue lifts prior guidance",
            "summary": "Apple services revenue helped lift prior guidance in an earlier update.",
            "event_type": "guidance_raise",
            "urgency": "normal",
            "entities": [Entity(name="Apple Inc.", ticker="AAPL", confidence=0.95, role="primary")],
            "asset_scope": ["single_name"],
            "index_exposure": [],
            "minutes_offset": -30,
        },
    ]
    events: list[Event] = []
    for index, template in enumerate(templates[:limit]):
        published_at = base_time + timedelta(minutes=int(template.get("minutes_offset", index * 5)))
        events.append(
            Event(
                event_id=str(template["event_id"]),
                source="demo_news",
                source_url="",
                title=str(template["title"]),
                summary=str(template["summary"]),
                published_at=published_at,
                observed_at=published_at,
                ingested_at=published_at,
                classified_at=published_at,
                entities=list(template["entities"]),
                asset_scope=list(template["asset_scope"]),
                index_exposure=list(template["index_exposure"]),
                event_type=str(template["event_type"]),
                sentiment="neutral",
                sentiment_score=0.0,
                urgency=str(template["urgency"]),
                novelty_score=0.5,
                source_credibility=0.5,
                evidence=[EvidenceSnippet(text=str(template["summary"]), location="demo")],
                model_outputs=[],
                raw_artifact_path="",
            )
        )
    return events


def seed_demo_events(store: Store, *, limit: int = 5) -> int:
    events = demo_events(limit=limit)
    for event in events:
        store.save_news_event(event)
    return len(events)
