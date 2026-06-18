from __future__ import annotations

from trader.research.edge_report import build_edge_rows_from_outcome_report, format_edge_report
from trader.research.edge_stats import EdgeBucket, EdgeVerdict


def test_format_edge_report_lists_verdicts():
    rows = [
        (
            EdgeBucket(
                bucket="event_type=guidance_raise, sentiment=positive, urgency=high",
                horizon="1h",
                n=40,
                mean_bps=18.0,
                net_mean_bps=16.0,
                median_bps=11.0,
                hit_rate=0.65,
                stdev_bps=35.0,
                t_stat=2.89,
                cost_bps=2.0,
            ),
            EdgeVerdict("candidate_edge", "n=40, net_mean_bps=16.00, t_stat=2.89, hit_rate=0.65"),
        )
    ]

    report = format_edge_report(
        rows,
        source_path="output/reports/smoke-outcomes.md",
        min_n=30,
        cost_bps=2.0,
    )

    assert report.startswith("# Edge Validation Report")
    assert "event_type=guidance_raise, sentiment=positive, urgency=high" in report
    assert "candidate_edge" in report
    assert "This is research-only" in report


def test_build_edge_rows_from_outcome_report_classifies_candidate_and_no_edge():
    markdown = """# Event Outcome Backtest: SPY

Research-only historical event-outcome analysis.

## Run Metadata

- benchmark: SPY
- entry_time: observed_at
- horizons: 1h
- group_by: event_type, sentiment, urgency

## Coverage

- events_seen: 44
- events_missing_entry_time: 0
- events_with_entry: 44
- missing_entry_bar: 0
- missing_horizon_bar: 0

## Grouped Stats

| group | horizon | n | hit_rate | mean% | median% | stdev% | min% | max% |
|---|---|---|---|---|---|---|---|---|
| event_type=guidance_raise, sentiment=positive, urgency=high | 1h | 40 | 65% | +0.18 | +0.11 | 0.35 | -0.20 | +1.10 |
| event_type=fed_commentary, sentiment=neutral, urgency=normal | 1h | 32 | 51% | +0.01 | +0.01 | 0.22 | -0.40 | +0.50 |

## Low sample groups

No groups below min_sample=30.
"""

    rows = build_edge_rows_from_outcome_report(markdown, min_n=30, cost_bps=2.0)

    assert [verdict.verdict for _bucket, verdict in rows] == ["candidate_edge", "no_edge"]
    candidate, _candidate_verdict = rows[0]
    assert candidate.bucket == "event_type=guidance_raise, sentiment=positive, urgency=high"
    assert candidate.horizon == "1h"
    assert candidate.n == 40
    assert candidate.mean_bps == 18.0
    assert candidate.net_mean_bps == 16.0
