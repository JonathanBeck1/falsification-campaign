"""The trading-thesis taxonomy. The lookup table IS the algorithm.

Per `brain/21_news_to_trade_thesis_algorithm.md`, every entry in
THESIS_TABLE is a hypothesis about how the market reacts to a class of
event. Adding, removing, or changing entries is a load-bearing change —
bump POLICY_VERSION and add a brain/decisions/ doc that explains why.

The `expected_magnitude_pct` numbers are *placeholders* awaiting empirical
calibration from real event-study data. They reflect rough historical
averages I (Claude) inferred from financial-domain knowledge; they need
validation against actual SPY/QQQ bar data before being trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Direction = Literal["long", "short", "neutral"]
Confidence = Literal["low", "medium", "high"]
ConfirmationState = Literal["pending", "confirmed"]

POLICY_VERSION = "thesis-table-v0"


@dataclass(frozen=True)
class ThesisTemplate:
    """A row in THESIS_TABLE. The rules for one bucket of news event."""

    bucket: str
    direction: Direction
    horizon_minutes: int  # window in which the thesis is actionable
    confidence: Confidence
    confirmation_required: bool  # need a 2nd source before acting?
    fade_window_minutes: int  # when the move typically mean-reverts
    expected_magnitude_pct: float  # historical avg % SPY/QQQ move; placeholder
    rationale: str  # human-readable, surfaces in dashboard + reports


@dataclass(frozen=True)
class Thesis:
    """An instance of a ThesisTemplate, bound to a specific event."""

    thesis_id: str
    event_id: str
    template: ThesisTemplate
    created_at: datetime
    policy_version: str = POLICY_VERSION
    # Note describing how the engine picked this bucket (for audit).
    classification_note: str = ""
    # Confirmation gating (brain/21 "Confirmation gating" section).
    # For buckets with template.confirmation_required=True, the thesis is
    # excluded from aggregation until confirmation_state flips to "confirmed".
    # Buckets with confirmation_required=False are aggregated regardless of
    # state (see is_aggregation_eligible).
    confirmation_state: ConfirmationState = "pending"
    confirmed_sources: int = 1

    @property
    def direction(self) -> Direction:
        return self.template.direction

    @property
    def horizon_minutes(self) -> int:
        return self.template.horizon_minutes

    @property
    def confidence(self) -> Confidence:
        return self.template.confidence

    @property
    def signed_magnitude(self) -> float:
        """How much this thesis would push position size, signed."""
        if self.template.direction == "long":
            sign = +1.0
        elif self.template.direction == "short":
            sign = -1.0
        else:
            sign = 0.0
        return sign * (self.template.expected_magnitude_pct / 100.0)

    @property
    def is_aggregation_eligible(self) -> bool:
        """Whether the aggregator should include this thesis in direction_sum.

        Buckets that don't require confirmation are always eligible.
        Buckets that do require confirmation are eligible only once
        confirmation_state flips to "confirmed" (set by the
        confirmation-matching pass — currently a future PR; today, the
        ThesisEngine constructs theses with state="pending" for
        confirmation_required buckets so they stay out of sizing until
        explicitly confirmed)."""
        if not self.template.confirmation_required:
            return True
        return self.confirmation_state == "confirmed"


# Confidence weights used by the aggregator. Pinned here so changes are
# auditable.
CONFIDENCE_WEIGHT: dict[Confidence, float] = {"high": 1.0, "medium": 0.5, "low": 0.25}


# Buckets explicitly in the IGNORE set per brain/21. The engine returns
# None for these — no thesis emitted, no position change.
IGNORE_BUCKETS: frozenset[str] = frozenset(
    {
        "opinion_piece",
        "analyst_note_during_hours",
        "anonymous_whisper",
        "retail_forum_chatter_single_name",
        "non_megacap_single_name",
        "recycled_wire",
        "in_line_expectations",
    }
)


# ── THE LOOKUP TABLE ────────────────────────────────────────────────────────
# Every entry is a hypothesis. Every entry should eventually be backed by
# empirical event-study data.
THESIS_TABLE: dict[str, ThesisTemplate] = {
    # ── Fed / FOMC ─────────────────────────────────────────────────────────
    "fed_dovish_surprise": ThesisTemplate(
        bucket="fed_dovish_surprise",
        direction="long",
        horizon_minutes=120,
        confidence="high",
        confirmation_required=False,
        fade_window_minutes=240,
        expected_magnitude_pct=0.7,
        rationale=(
            "Dovish Fed surprise -> equity rally; QQQ outperforms SPY (growth > value); "
            "bonds rally; USD weakens. Reaction continues 1-2h as analysts publish takes."
        ),
    ),
    "fed_hawkish_surprise": ThesisTemplate(
        bucket="fed_hawkish_surprise",
        direction="short",
        horizon_minutes=120,
        confidence="high",
        confirmation_required=False,
        fade_window_minutes=240,
        expected_magnitude_pct=0.7,
        rationale=(
            "Hawkish Fed surprise -> equity selloff; growth (QQQ) hit harder than value (SPY). "
            "Reaction continues 1-2h."
        ),
    ),
    "fomc_minutes_release": ThesisTemplate(
        bucket="fomc_minutes_release",
        direction="neutral",  # direction emerges from price action in first 30min
        horizon_minutes=120,
        confidence="medium",
        confirmation_required=True,  # wait for direction to emerge
        fade_window_minutes=180,
        expected_magnitude_pct=0.4,
        rationale=(
            "Minutes release: don't pre-judge direction. Wait 30min for consensus to form, "
            "then trade with the move with stop above/below the pre-release price."
        ),
    ),
    # ── Macro releases ─────────────────────────────────────────────────────
    "cpi_cooler_than_expected": ThesisTemplate(
        bucket="cpi_cooler_than_expected",
        direction="long",
        horizon_minutes=90,
        confidence="high",
        confirmation_required=False,
        fade_window_minutes=180,
        expected_magnitude_pct=0.6,
        rationale=(
            "Cooler CPI -> Fed-easing path priced in; equity rally; bonds rally. "
            "Strongest in growth (QQQ)."
        ),
    ),
    "cpi_hotter_than_expected": ThesisTemplate(
        bucket="cpi_hotter_than_expected",
        direction="short",
        horizon_minutes=90,
        confidence="high",
        confirmation_required=False,
        fade_window_minutes=180,
        expected_magnitude_pct=0.6,
        rationale=(
            "Hotter CPI -> growth fears + Fed-hawkish risk -> equity drop. "
            "QQQ hit harder than SPY."
        ),
    ),
    "nfp_strong_miss": ThesisTemplate(
        bucket="nfp_strong_miss",
        direction="short",
        horizon_minutes=120,
        confidence="medium",
        confirmation_required=False,
        fade_window_minutes=240,
        expected_magnitude_pct=0.5,
        rationale="Big NFP miss -> recession fear -> equity down, bonds rally.",
    ),
    "nfp_strong_beat": ThesisTemplate(
        bucket="nfp_strong_beat",
        direction="neutral",
        horizon_minutes=120,
        confidence="low",
        confirmation_required=True,
        fade_window_minutes=240,
        expected_magnitude_pct=0.3,
        rationale=(
            "Strong NFP beat is context-dependent on rate cycle: bullish (strong economy) "
            "in early cycle, bearish (Fed-hawkish risk) late cycle. Don't pre-judge."
        ),
    ),
    "gdp_above_consensus": ThesisTemplate(
        bucket="gdp_above_consensus",
        direction="long",
        horizon_minutes=120,
        confidence="low",
        confirmation_required=True,
        fade_window_minutes=180,
        expected_magnitude_pct=0.3,
        rationale="GDP surprises move markets less than CPI/NFP; small magnitude.",
    ),
    "gdp_below_consensus": ThesisTemplate(
        bucket="gdp_below_consensus",
        direction="short",
        horizon_minutes=120,
        confidence="low",
        confirmation_required=True,
        fade_window_minutes=180,
        expected_magnitude_pct=0.3,
        rationale="GDP misses are small movers unless very large miss.",
    ),
    # ── Geopolitical ───────────────────────────────────────────────────────
    "geopol_escalation_major": ThesisTemplate(
        bucket="geopol_escalation_major",
        direction="short",
        horizon_minutes=90,
        confidence="high",
        confirmation_required=True,  # rumor vs confirmed matters
        fade_window_minutes=2880,  # 48h — mean-reverts if no further escalation
        expected_magnitude_pct=1.2,
        rationale=(
            "Major geopolitical escalation (military strike, war headline) -> "
            "initial flight to quality; if no further escalation, mean-reverts 24-72h."
        ),
    ),
    "geopol_de_escalation": ThesisTemplate(
        bucket="geopol_de_escalation",
        direction="long",
        horizon_minutes=120,
        confidence="medium",
        confirmation_required=True,
        fade_window_minutes=480,
        expected_magnitude_pct=0.6,
        rationale=(
            "De-escalation / ceasefire -> relief rally. Durability depends on how "
            "broken the prior status was."
        ),
    ),
    # ── Regulatory ─────────────────────────────────────────────────────────
    "regulatory_action_megacap": ThesisTemplate(
        bucket="regulatory_action_megacap",
        direction="short",
        horizon_minutes=240,
        confidence="medium",
        confirmation_required=False,
        fade_window_minutes=1440,  # 24h
        expected_magnitude_pct=0.4,  # broad index ~0.4%; named stock 2-5%
        rationale=(
            "Regulator action against a megacap (>1% index weight) -> name selloff; "
            "broad index contagion ~0.2-0.5x of name move. Sector contagion depends on "
            "whether stated rationale generalizes."
        ),
    ),
    # ── Megacap single-name ────────────────────────────────────────────────
    "megacap_earnings_beat_and_raise": ThesisTemplate(
        bucket="megacap_earnings_beat_and_raise",
        direction="long",
        horizon_minutes=480,  # 8h — overnight + first hour
        confidence="high",
        confirmation_required=False,
        fade_window_minutes=4320,  # 3 days
        expected_magnitude_pct=0.5,  # broad index spillover
        rationale=(
            "Megacap beat + raised guidance -> name gaps up, broad index moves "
            "0.2-0.5x of name. Holds gains 3-5 days unless other shoes drop."
        ),
    ),
    "megacap_earnings_beat_flat_guide": ThesisTemplate(
        bucket="megacap_earnings_beat_flat_guide",
        direction="long",
        horizon_minutes=60,  # gives back over the day
        confidence="medium",
        confirmation_required=False,
        fade_window_minutes=480,
        expected_magnitude_pct=0.2,
        rationale=(
            "Beat with flat guidance: initial gap up fades over the day. Small short-horizon trade."
        ),
    ),
    "megacap_earnings_miss_or_cut": ThesisTemplate(
        bucket="megacap_earnings_miss_or_cut",
        direction="short",
        horizon_minutes=480,
        confidence="high",
        confirmation_required=False,
        fade_window_minutes=2880,
        expected_magnitude_pct=0.6,
        rationale=(
            "Megacap miss or guidance cut -> sharp gap down; broad index 0.3-0.6x of name. "
            "Contagion to peers if reason is structural (e.g., AI demand falling)."
        ),
    ),
    "megacap_mna_target": ThesisTemplate(
        bucket="megacap_mna_target",
        direction="neutral",  # target rallies; broad index unaffected
        horizon_minutes=60,
        confidence="high",
        confirmation_required=False,
        fade_window_minutes=240,
        expected_magnitude_pct=0.0,
        rationale="M&A target rallies; broad index typically unaffected. Don't trade broad index.",
    ),
    # ── Earnings-season regime (not a single event) ────────────────────────
    "earnings_season_strong_start": ThesisTemplate(
        bucket="earnings_season_strong_start",
        direction="long",
        horizon_minutes=20160,  # ~2 weeks of season
        confidence="medium",
        confirmation_required=True,
        fade_window_minutes=30240,
        expected_magnitude_pct=1.5,  # cumulative over the season
        rationale=(
            "First-week megacaps beating -> broad index typically grinds higher through "
            "the rest of earnings season. Sustained position, not a trade."
        ),
    ),
}


@dataclass(frozen=True)
class AggregateInputs:
    """Wraps state the aggregator needs beyond the theses themselves."""

    vix: float | None = None
    yield_curve_10y_2y: float | None = None
    realized_vol_20d: float | None = None
    # Other regime overlays can be added here as we wire tier-1 data
    # sources from brain/22.
    other_signals: dict[str, float] = field(default_factory=dict)
