"""Heartbeat / freshness-gate tests.

Pins: (1) a source with a recent successful fetch is fresh, (2) a source
that has never fetched is stale, (3) a source whose last fetch is older
than its budget is stale, (4) when ALL sources are stale the verdict
gates the LLM, (5) failed fetches don't refresh the heartbeat.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trader.ingestion.heartbeat import (
    DEFAULT_FRESHNESS_BUDGETS_MIN,
    HeartbeatTracker,
    _FrozenClock,
    gate_llm_brains_on_freshness,
)


def _tracker_with_clock(start: datetime | None = None) -> tuple[HeartbeatTracker, _FrozenClock]:
    clock = _FrozenClock(now=start or datetime(2026, 5, 20, 14, tzinfo=UTC))
    return HeartbeatTracker(now_fn=clock), clock


def test_empty_tracker_marks_every_source_stale():
    """No fetches recorded → no heartbeat → every source is stale."""
    tracker, _ = _tracker_with_clock()
    verdict = tracker.evaluate()
    assert verdict.all_stale is True
    assert set(verdict.stale_sources) == set(DEFAULT_FRESHNESS_BUDGETS_MIN.keys())
    assert verdict.fresh_sources == ()
    assert verdict.should_skip_llm is True


def test_recent_fetch_marks_source_fresh():
    tracker, _ = _tracker_with_clock()
    tracker.record_fetch("finnhub", item_count=3)
    verdict = tracker.evaluate(required_sources=["finnhub"])
    assert "finnhub" in verdict.fresh_sources
    assert verdict.all_stale is False


def test_empty_fetch_still_counts_as_heartbeat():
    """A successful fetch returning 0 items is still proof the adapter
    is alive. We should NOT mark it stale just because there's no news."""
    tracker, _ = _tracker_with_clock()
    tracker.record_fetch("finnhub", item_count=0)
    verdict = tracker.evaluate(required_sources=["finnhub"])
    assert "finnhub" in verdict.fresh_sources


def test_fetch_older_than_budget_is_stale():
    tracker, clock = _tracker_with_clock()
    tracker.record_fetch("finnhub", item_count=5)
    # finnhub budget is 30 min; advance 45
    clock.advance(45)
    verdict = tracker.evaluate(required_sources=["finnhub"])
    assert "finnhub" in verdict.stale_sources


def test_fetch_within_budget_is_fresh():
    tracker, clock = _tracker_with_clock()
    tracker.record_fetch("finnhub", item_count=5)
    clock.advance(20)
    verdict = tracker.evaluate(required_sources=["finnhub"])
    assert "finnhub" in verdict.fresh_sources


def test_error_does_not_refresh_heartbeat():
    """If a fetch fails entirely, that's NOT a heartbeat — the source
    stays stale."""
    tracker, _ = _tracker_with_clock()
    tracker.record_fetch("finnhub", item_count=0, error="503 from server")
    verdict = tracker.evaluate(required_sources=["finnhub"])
    assert "finnhub" in verdict.stale_sources
    assert tracker._health["finnhub"].last_error == "503 from server"


def test_all_stale_triggers_gate():
    """If every required source is stale, LLM brains should be skipped."""
    tracker, _ = _tracker_with_clock()
    verdict = tracker.evaluate(required_sources=["finnhub", "alpaca_news"])
    assert verdict.all_stale is True
    assert verdict.should_skip_llm is True


def test_at_least_one_fresh_source_clears_gate():
    """If even one source is fresh, LLM brains are allowed. The
    aggregator still sees the staleness of individual events; this gate
    is the last line of defense."""
    tracker, clock = _tracker_with_clock()
    tracker.record_fetch("finnhub", item_count=2)
    # alpaca_news has no heartbeat -> stale
    clock.advance(5)
    verdict = tracker.evaluate(required_sources=["finnhub", "alpaca_news"])
    assert verdict.all_stale is False
    assert verdict.should_skip_llm is False
    assert "finnhub" in verdict.fresh_sources
    assert "alpaca_news" in verdict.stale_sources


def test_consecutive_empty_fetches_tracked():
    """Three empty fetches in a row should be visible in source health
    for dashboard observability, even though the source is still 'fresh'."""
    tracker, _ = _tracker_with_clock()
    for _ in range(3):
        tracker.record_fetch("finnhub", item_count=0)
    h = tracker._health["finnhub"]
    assert h.consecutive_empty_fetches == 3


def test_one_nonempty_fetch_resets_consecutive_counter():
    tracker, _ = _tracker_with_clock()
    tracker.record_fetch("finnhub", item_count=0)
    tracker.record_fetch("finnhub", item_count=0)
    tracker.record_fetch("finnhub", item_count=2)
    assert tracker._health["finnhub"].consecutive_empty_fetches == 0


def test_custom_budgets_override_defaults():
    """A caller can pass tighter budgets, e.g. for live trading where
    we want stricter freshness."""
    tracker = HeartbeatTracker(budgets_min={"finnhub": 5}, now_fn=_FrozenClock())
    tracker.record_fetch("finnhub", item_count=1)
    # the tracker's clock advances via _FrozenClock; we need to reach into the closure
    # easier: use a fresh tracker with explicit clock
    clock = _FrozenClock()
    tracker = HeartbeatTracker(budgets_min={"finnhub": 5}, now_fn=clock)
    tracker.record_fetch("finnhub", item_count=1)
    clock.advance(6)
    verdict = tracker.evaluate(required_sources=["finnhub"])
    assert "finnhub" in verdict.stale_sources


def test_gate_helper_returns_verdict_unchanged():
    tracker, _ = _tracker_with_clock()
    verdict = gate_llm_brains_on_freshness(tracker, required_sources=["finnhub"])
    assert verdict.should_skip_llm is True


def test_default_budgets_reflect_brain22_polling_cadences():
    """Sanity check: the budgets we picked match brain/22's claim that
    free-tier polling sits at 10-30s for streaming, 5-60 min for polling.
    Budgets are 3x the realistic polling cadence."""
    assert DEFAULT_FRESHNESS_BUDGETS_MIN["alpaca_news"] <= 30
    assert DEFAULT_FRESHNESS_BUDGETS_MIN["finnhub"] <= 30
    assert DEFAULT_FRESHNESS_BUDGETS_MIN["yahoo_news"] <= 60
    # SEC and Fed have inherently slower cadences (regulatory filings)
    assert DEFAULT_FRESHNESS_BUDGETS_MIN["sec_edgar"] >= 60
    assert DEFAULT_FRESHNESS_BUDGETS_MIN["fed"] >= 60
