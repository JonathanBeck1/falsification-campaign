from __future__ import annotations

from trader.research.run_manifest import ResearchCycleArtifact, ResearchCycleManifest, format_manifest


def test_format_manifest_includes_artifacts_and_counts():
    manifest = ResearchCycleManifest(
        run_id="run-1",
        status="succeeded",
        benchmark="SPY",
        entry_time="observed_at",
        events_before=10,
        events_after=12,
        enriched_count=8,
        rejected_count=1,
        candidate_count=3,
        artifacts=[
            ResearchCycleArtifact(kind="outcome_report", path="output/reports/outcomes.md"),
            ResearchCycleArtifact(kind="outcome_review", path="output/reports/outcome-review.md"),
        ],
        error="",
    )

    markdown = format_manifest(manifest)

    assert "# Research Cycle Manifest" in markdown
    assert "- run_id: run-1" in markdown
    assert "- status: succeeded" in markdown
    assert "- events_after: 12" in markdown
    assert "| outcome_report | output/reports/outcomes.md |" in markdown
