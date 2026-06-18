from __future__ import annotations

from trader.research.outcome_review import format_outcome_review, parse_outcome_report, review_outcomes

SAMPLE_OUTCOME_REPORT = """# Event Outcome Backtest: SPY

Research-only historical event-outcome analysis.

## Run Metadata

- benchmark: SPY
- entry_time: observed_at
- horizons: 5m, 15m, 1h
- group_by: event_type, sentiment, urgency, thesis_bucket
- bars: 79
- data_provider: yahoo
- event_type: all
- events: 22
- minutes: 5
- source: all

## Coverage

- events_seen: 22
- events_missing_entry_time: 0
- events_with_entry: 22
- missing_entry_bar: 0
- missing_horizon_bar: 3

## Grouped Stats

| group | horizon | n | hit_rate | mean% | median% | stdev% | min% | max% |
|---|---|---|---|---|---|---|---|---|
| event_type=fed_commentary, sentiment=neutral, urgency=high, thesis_bucket=fomc_minutes_release | 15m | 12 | 67% | +0.20 | +0.10 | 0.30 | -0.10 | +0.80 |
| event_type=other, sentiment=neutral, urgency=normal, thesis_bucket=ignored | 15m | 14 | 50% | +0.01 | +0.01 | 0.02 | -0.02 | +0.04 |

## Low sample groups

| group | horizon | n | min_sample |
|---|---|---|---|
| event_type=earnings_surprise, sentiment=neutral, urgency=normal, thesis_bucket=ignored | 15m | 3 | 10 |

## Event Examples

No examples needed for this parser test.
"""


def test_parse_outcome_report_reads_metadata_coverage_stats_and_low_sample_rows():
    data = parse_outcome_report(SAMPLE_OUTCOME_REPORT)

    assert data.metadata["benchmark"] == "SPY"
    assert data.metadata["entry_time"] == "observed_at"
    assert data.metadata["events"] == "22"
    assert data.coverage["events_seen"] == 22
    assert data.coverage["missing_horizon_bar"] == 3
    assert len(data.grouped_stats) == 2
    assert data.grouped_stats[0].group == (
        "event_type=fed_commentary, sentiment=neutral, urgency=high, "
        "thesis_bucket=fomc_minutes_release"
    )
    assert data.grouped_stats[0].horizon == "15m"
    assert data.grouped_stats[0].n == 12
    assert data.grouped_stats[0].hit_rate == 0.67
    assert data.grouped_stats[0].mean_return_pct == 0.20
    assert len(data.low_sample_rows) == 1
    assert data.low_sample_rows[0].min_sample == 10


def test_review_outcomes_classifies_candidate_watchlist_and_junk_rows():
    data = parse_outcome_report(SAMPLE_OUTCOME_REPORT)

    review = review_outcomes(data, min_sample=10)

    assert review.has_usable_candidates is True
    assert [row.verdict for row in review.rows] == ["candidate", "junk"]
    assert review.candidate_rows[0].group.startswith("event_type=fed_commentary")
    assert review.junk_rows[0].group.startswith("event_type=other")
    assert any("bar coverage" in priority for priority in review.data_priorities)


def test_review_outcomes_focus_horizon_filters_rows():
    data = parse_outcome_report(SAMPLE_OUTCOME_REPORT)

    review = review_outcomes(data, min_sample=10, focus_horizon="1h")

    assert review.rows == []
    assert review.focus_horizon == "1h"
    assert review.has_usable_candidates is False


def test_review_outcomes_marks_low_sample_non_junk_as_watchlist():
    markdown = SAMPLE_OUTCOME_REPORT.replace(
        "| event_type=fed_commentary, sentiment=neutral, urgency=high, thesis_bucket=fomc_minutes_release | 15m | 12 | 67% | +0.20 | +0.10 | 0.30 | -0.10 | +0.80 |",
        "| event_type=fed_commentary, sentiment=neutral, urgency=high, thesis_bucket=fomc_minutes_release | 15m | 3 | 67% | +0.20 | +0.10 | 0.30 | -0.10 | +0.80 |",
    )
    data = parse_outcome_report(markdown)

    review = review_outcomes(data, min_sample=10)

    assert review.has_usable_candidates is False
    assert review.watchlist_rows[0].group.startswith("event_type=fed_commentary")
    assert "not enough evidence" in review.verdict_summary.lower()


def test_format_outcome_review_includes_sections_priorities_and_escaped_cells():
    markdown = SAMPLE_OUTCOME_REPORT.replace("event_type=fed_commentary", "event_type=fed\\|commentary next")
    data = parse_outcome_report(markdown)
    review = review_outcomes(data, min_sample=10)

    rendered = format_outcome_review(review)

    assert "# Outcome Review" in rendered
    assert "## Verdict" in rendered
    assert "## Candidate Groups" in rendered
    assert "## Watchlist Groups" in rendered
    assert "## Junk / Noise" in rendered
    assert "## Data Collection Priorities" in rendered
    assert "## Source Run" in rendered
    assert "event_type=fed\\|commentary next" in rendered
    assert "Do not infer edge" in rendered
