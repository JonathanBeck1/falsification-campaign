"""Realistic news scenarios with manual labels for thesis-engine testing.

Each scenario is a sequence of headlines that might arrive during a real
event — e.g., a Fed press conference produces multiple headlines over 30
minutes; an earnings miss has the initial report + follow-up details +
analyst reactions.

The labels (event_type, sentiment, urgency, etc.) are set MANUALLY here.
This is what the LLM enricher would produce. The scenario runner feeds
these through the thesis engine to demonstrate end-to-end behavior.

These are FICTIONAL events. Headlines are written to look realistic but
do not represent any specific real-world event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from trader.normalization.models import Entity, Event
from trader.storage.snapshot import MacroSnapshot
from trader.thesis.taxonomy import AggregateInputs


@dataclass(frozen=True)
class ScenarioEvent:
    """One labeled event in a scenario. The labels MUST match what the
    enricher would produce — if a scenario fails because we changed the
    enricher's vocabulary, the scenario is the spec and the change is
    intentional."""

    headline: str
    summary: str
    minutes_after_start: int  # when this hits relative to scenario start
    event_type: str  # must be a value from normalization/models.EventType
    sentiment: str  # "positive" | "negative" | "neutral" | "mixed"
    sentiment_score: float  # in [-1, 1]
    urgency: str  # "low" | "normal" | "high" | "breaking"
    novelty_score: float = 0.7
    source_credibility: float = 0.85
    source: str = "scenario"
    asset_scope: tuple[str, ...] = ("macro",)
    index_exposure: tuple[str, ...] = ()
    entity_tickers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    """A scenario: name, narrative, macro context, ordered events."""

    name: str
    narrative: str  # human-readable: what this scenario represents
    macro: MacroSnapshot
    events: list[ScenarioEvent]
    aggregate_inputs: AggregateInputs = field(default_factory=AggregateInputs)


def build_scenario_events(
    scenario: Scenario, *, start: datetime | None = None
) -> list[tuple[Event, datetime]]:
    """Materialize a scenario into a list of (Event, observed_at) tuples
    suitable for feeding to ThesisEngine."""
    start = start or datetime(2026, 5, 20, 14, 0, tzinfo=UTC)
    out: list[tuple[Event, datetime]] = []
    for i, se in enumerate(scenario.events):
        observed = start + timedelta(minutes=se.minutes_after_start)
        event = Event(
            event_id=f"scenario_{scenario.name}_{i:02d}",
            source=se.source,
            source_url="",
            title=se.headline,
            summary=se.summary,
            published_at=observed,
            observed_at=observed,
            ingested_at=observed,
            classified_at=observed,
            entities=[
                Entity(name=t, ticker=t, confidence=1.0, role="primary")
                for t in se.entity_tickers
            ],
            asset_scope=list(se.asset_scope),
            index_exposure=list(se.index_exposure),
            event_type=se.event_type,
            sentiment=se.sentiment,
            sentiment_score=se.sentiment_score,
            urgency=se.urgency,
            novelty_score=se.novelty_score,
            source_credibility=se.source_credibility,
            evidence=[],
            model_outputs=[],
            raw_artifact_path="",
        )
        out.append((event, observed))
    return out


# ── Scenarios ───────────────────────────────────────────────────────────────

SCENARIOS: dict[str, Scenario] = {
    "fed_dovish_press_conference": Scenario(
        name="fed_dovish_press_conference",
        narrative=(
            "FOMC meeting day. Statement comes out at 14:00 ET, press conference "
            "begins at 14:30. Powell signals patience and openness to cuts. Five "
            "headlines arrive over 35 minutes as the press conference unfolds."
        ),
        macro=MacroSnapshot(vix=15.0, yield_curve_10y_2y=0.3, fed_funds=5.25, cpi_yoy=3.0),
        aggregate_inputs=AggregateInputs(vix=15.0, yield_curve_10y_2y=0.3),
        events=[
            ScenarioEvent(
                headline="Fed holds rates steady, says inflation moderating",
                summary=(
                    "The Federal Open Market Committee voted to leave the federal "
                    "funds rate unchanged at 5.25%, citing continued moderation in "
                    "inflation."
                ),
                minutes_after_start=0,
                event_type="fed_commentary",
                sentiment="neutral",
                sentiment_score=0.05,
                urgency="high",
                novelty_score=0.6,
            ),
            ScenarioEvent(
                headline="Powell: 'We will be patient as we assess incoming data'",
                summary=(
                    "Fed Chair Jerome Powell opened the press conference by saying "
                    "the committee will be patient. Markets interpreted this as "
                    "dovish, with bonds rallying."
                ),
                minutes_after_start=30,
                event_type="fed_commentary",
                sentiment="positive",
                sentiment_score=0.5,
                urgency="high",
                novelty_score=0.85,
            ),
            ScenarioEvent(
                headline="Powell opens door to rate cuts if inflation continues to fall",
                summary=(
                    "When asked about the path of rates, Powell said the committee "
                    "is prepared to begin easing if inflation continues to decline "
                    "toward the 2% target."
                ),
                minutes_after_start=35,
                event_type="fed_commentary",
                sentiment="positive",
                sentiment_score=0.7,
                urgency="breaking",
                novelty_score=0.9,
            ),
        ],
    ),
    "cpi_hot_surprise": Scenario(
        name="cpi_hot_surprise",
        narrative=(
            "8:30 AM ET. CPI prints 0.4% MoM vs 0.2% consensus. The hottest "
            "reading in six months. Equity futures drop sharply pre-market."
        ),
        macro=MacroSnapshot(vix=18.0, yield_curve_10y_2y=0.1, fed_funds=5.25, cpi_yoy=3.4),
        aggregate_inputs=AggregateInputs(vix=18.0, yield_curve_10y_2y=0.1),
        events=[
            ScenarioEvent(
                headline="US CPI rises 0.4% in March, hotter than 0.2% expected",
                summary=(
                    "The Consumer Price Index rose 0.4% month-over-month in March, "
                    "the largest increase in six months. Core CPI also exceeded "
                    "expectations."
                ),
                minutes_after_start=0,
                event_type="macro_surprise",
                sentiment="negative",
                sentiment_score=-0.6,
                urgency="breaking",
                novelty_score=0.95,
            ),
            ScenarioEvent(
                headline="Bond yields spike on hot inflation print",
                summary=(
                    "The 10-year Treasury yield jumped 8 basis points in the first "
                    "minute after the CPI release, with rate-cut expectations being "
                    "pushed out by months."
                ),
                minutes_after_start=2,
                event_type="macro_surprise",
                sentiment="negative",
                sentiment_score=-0.5,
                urgency="high",
                novelty_score=0.7,
            ),
        ],
    ),
    "nvda_blowout_earnings": Scenario(
        name="nvda_blowout_earnings",
        narrative=(
            "NVDA reports after market close. Revenue and guidance both crush "
            "expectations. Stock gaps up 8% in after-hours. SPY/QQQ futures track "
            "higher overnight."
        ),
        macro=MacroSnapshot(vix=14.0, yield_curve_10y_2y=0.4, fed_funds=5.25, cpi_yoy=2.9),
        aggregate_inputs=AggregateInputs(vix=14.0, yield_curve_10y_2y=0.4),
        events=[
            ScenarioEvent(
                headline="NVIDIA beats Q3 estimates, raises Q4 guidance significantly",
                summary=(
                    "NVIDIA reported Q3 revenue of $35.1B vs $33.0B expected, with "
                    "data center revenue up 112% year-over-year. Q4 guidance raised "
                    "to $37.5B vs $36.0B consensus."
                ),
                minutes_after_start=0,
                event_type="guidance_raise",
                sentiment="positive",
                sentiment_score=0.85,
                urgency="breaking",
                novelty_score=0.95,
                entity_tickers=("NVDA",),
                index_exposure=("QQQ", "SPY"),
                asset_scope=("single_name",),
            ),
            ScenarioEvent(
                headline="NVDA shares surge 8% in after-hours trading",
                summary=(
                    "Shares of NVIDIA jumped to $148 in extended trading, on track "
                    "for an all-time high open tomorrow."
                ),
                minutes_after_start=5,
                event_type="earnings_surprise",
                sentiment="positive",
                sentiment_score=0.7,
                urgency="high",
                novelty_score=0.6,
                entity_tickers=("NVDA",),
                index_exposure=("QQQ", "SPY"),
                asset_scope=("single_name",),
            ),
        ],
    ),
    "aapl_guidance_cut": Scenario(
        name="aapl_guidance_cut",
        narrative=(
            "AAPL pre-announces weak Q4 guidance after the close. Cites China "
            "demand softness. Stock gaps down 4% AH. Sector contagion across "
            "consumer tech."
        ),
        macro=MacroSnapshot(vix=17.0, yield_curve_10y_2y=0.2, fed_funds=5.25, cpi_yoy=3.0),
        aggregate_inputs=AggregateInputs(vix=17.0, yield_curve_10y_2y=0.2),
        events=[
            ScenarioEvent(
                headline="Apple lowers Q4 revenue guidance citing China weakness",
                summary=(
                    "Apple Inc. issued a pre-announcement lowering Q4 revenue "
                    "guidance to $89B-$91B from prior $94B-$96B, citing weaker "
                    "than expected iPhone demand in China."
                ),
                minutes_after_start=0,
                event_type="guidance_lower",
                sentiment="negative",
                sentiment_score=-0.7,
                urgency="breaking",
                novelty_score=0.9,
                entity_tickers=("AAPL",),
                index_exposure=("QQQ", "SPY"),
                asset_scope=("single_name",),
            ),
        ],
    ),
    "geopol_escalation": Scenario(
        name="geopol_escalation",
        narrative=(
            "Major geopolitical headline mid-session. Initial flight to quality. "
            "By the next morning, partial mean-reversion if no further escalation."
        ),
        macro=MacroSnapshot(vix=22.0, yield_curve_10y_2y=-0.1, fed_funds=5.25, cpi_yoy=3.1),
        aggregate_inputs=AggregateInputs(vix=22.0, yield_curve_10y_2y=-0.1),
        events=[
            ScenarioEvent(
                headline="Breaking: missile strike reported in Middle East shipping lane",
                summary=(
                    "Multiple sources report a missile strike on a commercial vessel "
                    "in a major shipping lane. Oil futures spiking; equity futures dropping."
                ),
                minutes_after_start=0,
                event_type="geopolitical_shock",
                sentiment="negative",
                sentiment_score=-0.8,
                urgency="breaking",
                novelty_score=0.95,
            ),
            ScenarioEvent(
                headline="Officials confirm no casualties, isolated incident",
                summary=(
                    "Government officials briefing the press say the incident appears "
                    "isolated with no immediate further escalation expected. Markets "
                    "trimming losses."
                ),
                minutes_after_start=90,
                event_type="geopolitical_shock",
                sentiment="positive",
                sentiment_score=0.3,
                urgency="high",
                novelty_score=0.7,
            ),
        ],
    ),
    "quiet_day_noise": Scenario(
        name="quiet_day_noise",
        narrative=(
            "A normal trading day. Some analyst upgrades, a retail forum buzz "
            "story, a Yahoo recycled wire story. Nothing actionable. The system "
            "should IGNORE all of these and stay at baseline."
        ),
        macro=MacroSnapshot(vix=13.0, yield_curve_10y_2y=0.5, fed_funds=5.25, cpi_yoy=2.8),
        aggregate_inputs=AggregateInputs(vix=13.0, yield_curve_10y_2y=0.5),
        events=[
            ScenarioEvent(
                headline="Goldman raises ORCL price target to $145",
                summary="Goldman Sachs raised its price target on Oracle to $145 from $130, citing cloud strength.",
                minutes_after_start=0,
                event_type="analyst_upgrade",
                sentiment="positive",
                sentiment_score=0.4,
                urgency="normal",
                novelty_score=0.4,
                entity_tickers=("ORCL",),
            ),
            ScenarioEvent(
                headline="Reddit traders rally around small-cap biotech BIOX",
                summary="A small-cap biotech is the latest meme stock attracting WSB attention.",
                minutes_after_start=30,
                event_type="unusual_social_velocity",
                sentiment="positive",
                sentiment_score=0.5,
                urgency="normal",
                novelty_score=0.5,
                entity_tickers=("BIOX",),
            ),
            ScenarioEvent(
                headline="Reuters wire: tech sector mixed at midday",
                summary="A standard mid-day market wrap with no new information.",
                minutes_after_start=60,
                event_type="other",
                sentiment="neutral",
                sentiment_score=0.0,
                urgency="low",
                novelty_score=0.2,
            ),
        ],
    ),
    "vix_stress_with_bullish_news": Scenario(
        name="vix_stress_with_bullish_news",
        narrative=(
            "Bullish news (CPI cool) arrives during a high-VIX regime (VIX=32). "
            "The regime overlay should cap position despite the bullish signal. "
            "Demonstrates that macro stress wins over per-event signal."
        ),
        macro=MacroSnapshot(vix=32.0, yield_curve_10y_2y=-0.2, fed_funds=5.25, cpi_yoy=3.0),
        aggregate_inputs=AggregateInputs(vix=32.0, yield_curve_10y_2y=-0.2),
        events=[
            ScenarioEvent(
                headline="US CPI rises 0.1% vs 0.3% expected, cooler than forecast",
                summary="A cooler-than-expected CPI print suggests Fed easing is on track.",
                minutes_after_start=0,
                event_type="macro_surprise",
                sentiment="positive",
                sentiment_score=0.6,
                urgency="breaking",
                novelty_score=0.9,
            ),
        ],
    ),
}


SCENARIO_NAMES: list[str] = sorted(SCENARIOS.keys())
