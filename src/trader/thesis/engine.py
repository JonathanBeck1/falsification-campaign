"""ThesisEngine — classifies an enriched event into a thesis bucket.

The engine reads the already-labeled fields on an `Event` (sentiment,
event_type, urgency, asset_scope) and routes it to one of the buckets in
`THESIS_TABLE`. The fields can be populated by:

- The deterministic normalizers (today)
- The LLM enricher (after PR #24 merges) — overwrites the same fields
- A scenario file (manual labels, for testing)

The engine doesn't care which produced the labels. The boundary is the
labels themselves.

Buckets in `IGNORE_BUCKETS` return None — no thesis is emitted and the
event has zero effect on position. This is the discipline that brain/21
argues is the actual source of edge.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from trader.normalization.models import Event
from trader.thesis.taxonomy import (
    IGNORE_BUCKETS,
    THESIS_TABLE,
    Thesis,
    ThesisTemplate,
)

# Note: event-time stamping for Thesis.created_at lives in
# ThesisEngine._event_time() (merged via PR #30). Per Codex review
# 2026-05-20, that helper preserves the stale-event guard the original
# datetime.now(UTC) stamping defeated. No standalone helper needed here.

# Major QQQ / SPY constituents whose news materially affects the broad index.
# Threshold: ≥1% index weight as of 2026Q1. Below this, single-name news is
# in the IGNORE set per brain/21.
MEGACAP_TICKERS: frozenset[str] = frozenset(
    {"AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO", "ORCL"}
)


class ThesisEngine:
    """Maps a classified Event to a Thesis using THESIS_TABLE."""

    def classify(self, event: Event) -> Thesis | None:
        bucket, note = self._pick_bucket(event)
        if bucket is None or bucket in IGNORE_BUCKETS:
            return None
        template = THESIS_TABLE.get(bucket)
        if template is None:
            return None
        # Buckets that require confirmation start "pending" — excluded from
        # the aggregator's direction_sum until a second source confirms.
        # Buckets that don't require confirmation are constructed already
        # "confirmed" so they aggregate immediately.
        confirmation_state = "pending" if template.confirmation_required else "confirmed"
        return Thesis(
            thesis_id=f"th_{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            template=template,
            created_at=self._event_time(event),
            classification_note=note,
            confirmation_state=confirmation_state,
            confirmed_sources=1,
        )

    @staticmethod
    def _event_time(event: Event) -> datetime:
        ts = event.classified_at or event.observed_at
        if ts.tzinfo is None or ts.utcoffset() is None:
            return ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)

    def _pick_bucket(self, event: Event) -> tuple[str | None, str]:
        """Returns (bucket_name, classification_note). bucket_name=None means
        the event is in the IGNORE set or is unclassifiable."""

        # Routing by event_type. The event_type vocabulary lives in
        # normalization/models.py and is already constrained.
        if event.event_type == "fed_commentary":
            return self._route_fed(event)
        if event.event_type == "macro_surprise":
            return self._route_macro(event)
        if event.event_type in {"earnings_surprise", "guidance_raise", "guidance_lower"}:
            return self._route_earnings(event)
        if event.event_type == "geopolitical_shock":
            return self._route_geopolitical(event)
        if event.event_type in {"regulatory_action", "investigation", "lawsuit"}:
            return self._route_regulatory(event)
        if event.event_type == "mna":
            return self._route_mna(event)

        # Anything else (analyst_upgrade, unusual_social_velocity,
        # product_launch, etc.) we currently treat as IGNORE for SPY/QQQ
        # broad-index trading. Document in brain/21 if we add buckets for any.
        return None, f"event_type={event.event_type} not mapped to a bucket"

    # ── Routing helpers ─────────────────────────────────────────────────────

    def _route_fed(self, event: Event) -> tuple[str | None, str]:
        # Bullish + high/breaking severity => dovish surprise
        # Bearish + high/breaking severity => hawkish surprise
        # Anything else => in_line (IGNORE) or minutes-style (await direction)
        if event.urgency in {"high", "breaking"} or event.novelty_score >= 0.7:
            if event.sentiment in {"positive"}:
                return "fed_dovish_surprise", "fed_commentary + bullish + high-urgency"
            if event.sentiment in {"negative"}:
                return "fed_hawkish_surprise", "fed_commentary + bearish + high-urgency"
            # Mixed/neutral with high urgency = minutes-style "wait and see"
            return "fomc_minutes_release", "fed_commentary + ambiguous sentiment + high-urgency"
        # Low urgency Fed commentary is mostly noise (speeches by non-chair governors etc.)
        return "in_line_expectations", "fed_commentary + low urgency -> IGNORE"

    def _route_macro(self, event: Event) -> tuple[str | None, str]:
        # macro_surprise covers CPI, NFP, GDP, retail sales, etc.
        # We use keyword hints in title + summary to pick the specific sub-bucket.
        text = f"{event.title} {event.summary}".lower()

        if any(k in text for k in ("cpi", "consumer price", "inflation report")):
            if event.sentiment == "positive":
                return "cpi_cooler_than_expected", "macro_surprise + CPI keyword + bullish"
            if event.sentiment == "negative":
                return "cpi_hotter_than_expected", "macro_surprise + CPI keyword + bearish"
            return "in_line_expectations", "macro_surprise + CPI + neutral -> IGNORE"

        if any(k in text for k in ("jobs report", "payroll", "nfp", "unemployment")):
            if event.sentiment == "negative":
                return "nfp_strong_miss", "macro_surprise + jobs keyword + bearish"
            if event.sentiment == "positive":
                return "nfp_strong_beat", "macro_surprise + jobs keyword + bullish"
            return "in_line_expectations", "macro_surprise + jobs + neutral -> IGNORE"

        if "gdp" in text:
            if event.sentiment == "positive":
                return "gdp_above_consensus", "macro_surprise + GDP keyword + bullish"
            if event.sentiment == "negative":
                return "gdp_below_consensus", "macro_surprise + GDP keyword + bearish"
            return "in_line_expectations", "macro_surprise + GDP + neutral -> IGNORE"

        return None, "macro_surprise but no recognized sub-keyword"

    def _route_earnings(self, event: Event) -> tuple[str | None, str]:
        if not self._is_megacap_event(event):
            return "non_megacap_single_name", "earnings event but non-megacap -> IGNORE"

        if event.event_type == "guidance_lower":
            return "megacap_earnings_miss_or_cut", "megacap + guidance_lower"

        # Distinguish beat+raise from beat+flat by sentiment strength.
        if event.event_type == "guidance_raise":
            return "megacap_earnings_beat_and_raise", "megacap + guidance_raise"

        # event_type == "earnings_surprise" — direction depends on sentiment.
        if event.sentiment == "positive" and event.sentiment_score >= 0.4:
            return "megacap_earnings_beat_and_raise", "megacap + earnings + strong bullish"
        if event.sentiment == "positive":
            return "megacap_earnings_beat_flat_guide", "megacap + earnings + mild bullish"
        if event.sentiment == "negative":
            return "megacap_earnings_miss_or_cut", "megacap + earnings + bearish"

        return "in_line_expectations", "megacap earnings + neutral -> IGNORE"

    def _route_geopolitical(self, event: Event) -> tuple[str | None, str]:
        if event.urgency == "breaking" or event.novelty_score >= 0.8:
            if event.sentiment == "negative":
                return "geopol_escalation_major", "geopolitical + breaking + bearish"
            if event.sentiment == "positive":
                return "geopol_de_escalation", "geopolitical + breaking + bullish (de-escalation)"
        # Lower-urgency geopol is usually noise
        return None, "geopolitical + low urgency -> IGNORE"

    def _route_regulatory(self, event: Event) -> tuple[str | None, str]:
        if not self._is_megacap_event(event):
            return "non_megacap_single_name", "regulatory event but non-megacap -> IGNORE"
        return "regulatory_action_megacap", "regulatory event against megacap"

    def _route_mna(self, event: Event) -> tuple[str | None, str]:
        # All M&A targets get the same neutral-for-index thesis. Acquirers
        # could be routed separately but the rule is the same: broad index
        # is unaffected.
        return "megacap_mna_target", "M&A event -> broad index neutral"

    def _is_megacap_event(self, event: Event) -> bool:
        if any(e.ticker and e.ticker.upper() in MEGACAP_TICKERS for e in event.entities):
            return True
        # Some events are tagged in index_exposure without an entity ticker;
        # if it's in the index exposure list, treat as megacap-relevant.
        return any(t.upper() in MEGACAP_TICKERS for t in event.index_exposure)


# Backward-compatibility re-export for callers that want the template type.
__all__ = ["MEGACAP_TICKERS", "ThesisEngine", "ThesisTemplate"]
