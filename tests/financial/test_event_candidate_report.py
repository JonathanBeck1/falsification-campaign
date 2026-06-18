from __future__ import annotations

from datetime import UTC, datetime

from trader.research.event_candidate_report import format_candidate_report
from trader.research.event_candidates import EventCandidate


def test_format_candidate_report_renders_sorted_candidate_table():
    candidate = EventCandidate(
        event_id="evt_score",
        published_at=datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
        source="demo_news",
        title="Apple raises guidance",
        ticker="AAPL",
        direction="bullish",
        score=75.5,
        confidence=0.76,
        is_actionable=True,
        event_type="guidance_raise",
        urgency="high",
        reasons=["sentiment=+0.50", "actionable"],
        key_claims=["Apple raised guidance."],
    )

    md = format_candidate_report([candidate], title="Demo Candidates")

    assert "# Demo Candidates" in md
    assert "AAPL" in md
    assert "bullish" in md
    assert "+75.50" in md
    assert "Apple raised guidance" in md
