"""ThesisEngine routing tests.

Pins how (event_type, sentiment, urgency, entities) maps to buckets.
Each test reflects a row from brain/21's taxonomy and is the spec for
the routing rules.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trader.normalization.models import Entity, Event
from trader.thesis.engine import ThesisEngine


def _event(
    *,
    event_type: str,
    sentiment: str = "neutral",
    sentiment_score: float = 0.0,
    urgency: str = "normal",
    title: str = "Headline",
    summary: str = "",
    novelty_score: float = 0.7,
    entity_tickers: list[str] | None = None,
    index_exposure: list[str] | None = None,
    asset_scope: list[str] | None = None,
    now: datetime | None = None,
) -> Event:
    now = now or datetime.now(UTC)
    return Event(
        event_id="evt_test",
        source="scenario",
        source_url="",
        title=title,
        summary=summary,
        published_at=now,
        observed_at=now,
        ingested_at=now,
        classified_at=now,
        entities=[
            Entity(name=t, ticker=t, confidence=1.0, role="primary")
            for t in (entity_tickers or [])
        ],
        asset_scope=asset_scope or ["macro"],
        index_exposure=index_exposure or [],
        event_type=event_type,
        sentiment=sentiment,
        sentiment_score=sentiment_score,
        urgency=urgency,
        novelty_score=novelty_score,
        source_credibility=0.9,
        evidence=[],
        model_outputs=[],
        raw_artifact_path="",
    )


def test_fed_bullish_high_urgency_to_dovish_surprise():
    engine = ThesisEngine()
    e = _event(event_type="fed_commentary", sentiment="positive", urgency="high")
    t = engine.classify(e)
    assert t is not None
    assert t.template.bucket == "fed_dovish_surprise"


def test_fed_bearish_breaking_urgency_to_hawkish_surprise():
    engine = ThesisEngine()
    e = _event(event_type="fed_commentary", sentiment="negative", urgency="breaking")
    t = engine.classify(e)
    assert t is not None
    assert t.template.bucket == "fed_hawkish_surprise"


def test_fed_low_urgency_is_ignored():
    """Routine non-chair Fed commentary should not produce a thesis."""
    engine = ThesisEngine()
    e = _event(event_type="fed_commentary", sentiment="positive", urgency="low", novelty_score=0.4)
    assert engine.classify(e) is None


def test_cpi_bullish_to_cooler_than_expected():
    engine = ThesisEngine()
    e = _event(
        event_type="macro_surprise",
        sentiment="positive",
        urgency="breaking",
        title="US CPI prints cooler than expected",
        summary="Consumer Price Index rose less than economists expected.",
    )
    t = engine.classify(e)
    assert t is not None
    assert t.template.bucket == "cpi_cooler_than_expected"


def test_cpi_bearish_to_hotter_than_expected():
    engine = ThesisEngine()
    e = _event(
        event_type="macro_surprise",
        sentiment="negative",
        urgency="breaking",
        title="US CPI runs hot in latest reading",
        summary="Inflation report shows acceleration in consumer prices.",
    )
    t = engine.classify(e)
    assert t is not None
    assert t.template.bucket == "cpi_hotter_than_expected"


def test_macro_surprise_with_jobs_keyword_routes_to_nfp_bucket():
    engine = ThesisEngine()
    e = _event(
        event_type="macro_surprise",
        sentiment="negative",
        urgency="breaking",
        title="Nonfarm payrolls miss by 100k",
        summary="The monthly jobs report showed weaker hiring than forecast.",
    )
    t = engine.classify(e)
    assert t is not None
    assert t.template.bucket == "nfp_strong_miss"


def test_megacap_guidance_raise_routes_to_beat_and_raise():
    engine = ThesisEngine()
    e = _event(
        event_type="guidance_raise",
        sentiment="positive",
        sentiment_score=0.85,
        urgency="breaking",
        entity_tickers=["NVDA"],
        index_exposure=["QQQ", "SPY"],
        asset_scope=["single_name"],
    )
    t = engine.classify(e)
    assert t is not None
    assert t.template.bucket == "megacap_earnings_beat_and_raise"


def test_megacap_guidance_lower_routes_to_miss_or_cut():
    engine = ThesisEngine()
    e = _event(
        event_type="guidance_lower",
        sentiment="negative",
        sentiment_score=-0.7,
        urgency="breaking",
        entity_tickers=["AAPL"],
        index_exposure=["QQQ", "SPY"],
        asset_scope=["single_name"],
    )
    t = engine.classify(e)
    assert t is not None
    assert t.template.bucket == "megacap_earnings_miss_or_cut"


def test_non_megacap_earnings_is_ignored():
    """Earnings of small-cap names (not in MEGACAP_TICKERS) must not produce a
    broad-index thesis."""
    engine = ThesisEngine()
    e = _event(
        event_type="earnings_surprise",
        sentiment="positive",
        sentiment_score=0.7,
        urgency="high",
        entity_tickers=["RIVN"],  # not in MEGACAP_TICKERS
        asset_scope=["single_name"],
    )
    assert engine.classify(e) is None


def test_geopolitical_breaking_bearish_routes_to_escalation_major():
    engine = ThesisEngine()
    e = _event(
        event_type="geopolitical_shock",
        sentiment="negative",
        urgency="breaking",
        novelty_score=0.95,
    )
    t = engine.classify(e)
    assert t is not None
    assert t.template.bucket == "geopol_escalation_major"


def test_regulatory_action_against_megacap_routes_correctly():
    engine = ThesisEngine()
    e = _event(
        event_type="regulatory_action",
        sentiment="negative",
        urgency="high",
        entity_tickers=["GOOGL"],
        asset_scope=["single_name"],
    )
    t = engine.classify(e)
    assert t is not None
    assert t.template.bucket == "regulatory_action_megacap"


def test_unmapped_event_type_returns_none():
    engine = ThesisEngine()
    e = _event(event_type="unusual_social_velocity", sentiment="positive", urgency="high")
    assert engine.classify(e) is None


def test_classification_note_explains_bucket():
    """Every emitted thesis must carry a non-empty classification_note for audit."""
    engine = ThesisEngine()
    e = _event(event_type="fed_commentary", sentiment="positive", urgency="high")
    t = engine.classify(e)
    assert t is not None
    assert len(t.classification_note) > 5


def test_thesis_created_at_uses_event_classification_time():
    """Thesis timestamps are point-in-time audit data; they should come from
    the event, not the process wall clock."""
    engine = ThesisEngine()
    observed = datetime(2024, 1, 15, 13, tzinfo=UTC)
    e = _event(event_type="fed_commentary", sentiment="positive", urgency="high", now=observed)
    t = engine.classify(e)
    assert t is not None
    assert t.created_at == observed
