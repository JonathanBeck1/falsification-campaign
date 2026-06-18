from __future__ import annotations

from pathlib import Path

from trader.storage.store import Store


def test_research_run_lifecycle_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")

    run_id = store.create_research_run(
        command={"command": "research-cycle", "mock_llm": True},
        benchmark="SPY",
        entry_time="observed_at",
        horizons="5m,15m,1h",
        group_by="event_type,thesis_bucket",
        since="2026-05-01T00:00:00+00:00",
        until="2026-05-02T00:00:00+00:00",
        data_provider="yahoo",
        events_before=10,
    )

    store.finish_research_run(
        run_id,
        status="succeeded",
        events_after=14,
        enriched_count=8,
        rejected_count=1,
        candidate_count=3,
        outcome_report_path="output/reports/outcomes.md",
        review_report_path="output/reports/outcome-review.md",
        manifest_path="output/reports/research-cycle-manifest.md",
    )

    rows = store.list_research_runs(limit=5)

    assert len(rows) == 1
    assert rows[0]["run_id"] == run_id
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["events_before"] == 10
    assert rows[0]["events_after"] == 14
    assert rows[0]["candidate_count"] == 3
    assert rows[0]["finished_at"] is not None


def test_research_run_artifacts_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    run_id = store.create_research_run(
        command={"command": "research-cycle"},
        benchmark="QQQ",
        entry_time="observed_at",
        horizons="5m",
        group_by="event_type",
        since=None,
        until=None,
        data_provider="yahoo",
        events_before=0,
    )

    artifact_id = store.record_research_run_artifact(
        run_id,
        artifact_type="manifest",
        path="output/reports/run.md",
        sha256="abc123",
    )

    artifacts = store.list_research_run_artifacts(run_id)

    assert artifacts == [
        {
            "artifact_id": artifact_id,
            "run_id": run_id,
            "artifact_type": "manifest",
            "path": "output/reports/run.md",
            "sha256": "abc123",
            "created_at": artifacts[0]["created_at"],
        }
    ]
