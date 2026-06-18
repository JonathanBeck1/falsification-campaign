from __future__ import annotations

from pathlib import Path

from trader.research.cycle import ResearchCycleConfig, ResearchCycleDeps, run_research_cycle
from trader.storage.store import Store


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    def send(self, title: str, body: str, *, error: bool = False) -> None:
        self.calls.append((title, body, error))


def test_research_cycle_runs_steps_and_writes_manifest(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    calls: list[str] = []

    def fetch_events() -> dict[str, int]:
        calls.append("fetch")
        return {"demo": 2}

    def enrich() -> tuple[int, int]:
        calls.append("enrich")
        return (2, 0)

    def score(output: Path) -> int:
        calls.append("score")
        output.write_text("# Candidates\n", encoding="utf-8")
        return 1

    def context(output: Path) -> int:
        calls.append("context")
        output.write_text("# Context\n", encoding="utf-8")
        return 1

    def outcome(output: Path) -> None:
        calls.append("outcome")
        output.write_text("# Event Outcome Backtest: SPY\n\n## Run Metadata\n\n- benchmark: SPY\n", encoding="utf-8")

    def review(input_path: Path, output: Path) -> None:
        calls.append(f"review:{input_path.name}")
        output.write_text("# Outcome Review\n", encoding="utf-8")

    notifier = RecordingNotifier()
    result = run_research_cycle(
        store=store,
        config=ResearchCycleConfig(
            reports_dir=tmp_path / "reports",
            benchmark="SPY",
            entry_time="observed_at",
            horizons="5m,15m",
            group_by="event_type",
            since=None,
            until=None,
            data_provider="yahoo",
            mock_llm=True,
            fetch_first=True,
            candidate_context=True,
        ),
        deps=ResearchCycleDeps(
            fetch_events=fetch_events,
            enrich=enrich,
            score=score,
            candidate_context=context,
            outcome_backtest=outcome,
            outcome_review=review,
        ),
        notifier=notifier,
    )

    assert calls == ["fetch", "enrich", "score", "context", "outcome", "review:outcomes.md"]
    assert result.status == "succeeded"
    assert result.manifest_path.exists()
    assert "Research Cycle Manifest" in result.manifest_path.read_text(encoding="utf-8")
    assert store.list_research_runs(limit=1)[0]["status"] == "succeeded"
    assert notifier.calls
    assert notifier.calls[0][0] == "Research cycle succeeded"
    assert "candidates=1" in notifier.calls[0][1]
    assert notifier.calls[0][2] is False


def test_research_cycle_artifacts_are_scoped_per_run(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")

    def fetch_events() -> dict[str, int]:
        return {"demo": 0}

    def enrich() -> tuple[int, int]:
        return (0, 0)

    def score(output: Path) -> int:
        output.write_text("# Candidates\n", encoding="utf-8")
        return 0

    def outcome(output: Path) -> None:
        output.write_text("# Event Outcome Backtest: SPY\n\n## Run Metadata\n\n- benchmark: SPY\n", encoding="utf-8")

    def review(input_path: Path, output: Path) -> None:
        output.write_text("# Outcome Review\n", encoding="utf-8")

    deps = ResearchCycleDeps(
        fetch_events=fetch_events,
        enrich=enrich,
        score=score,
        outcome_backtest=outcome,
        outcome_review=review,
    )
    config = ResearchCycleConfig(reports_dir=tmp_path / "reports", benchmark="SPY")

    first = run_research_cycle(store=store, config=config, deps=deps)
    second = run_research_cycle(store=store, config=config, deps=deps)

    first_paths = {row["path"] for row in store.list_research_run_artifacts(first.run_id)}
    second_paths = {row["path"] for row in store.list_research_run_artifacts(second.run_id)}
    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert first.run_id != second.run_id
    assert first_paths
    assert second_paths
    assert first_paths.isdisjoint(second_paths)
    for artifact_path in first_paths:
        path = Path(artifact_path)
        if path.name != f"research-cycle-{first.run_id}.md":
            assert path.parent == config.reports_dir / first.run_id
    for artifact_path in second_paths:
        path = Path(artifact_path)
        if path.name != f"research-cycle-{second.run_id}.md":
            assert path.parent == config.reports_dir / second.run_id


def test_research_cycle_records_artifact_sha256(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")

    def fetch_events() -> dict[str, int]:
        return {"demo": 1}

    def enrich() -> tuple[int, int]:
        return (1, 0)

    def score(output: Path) -> int:
        output.write_text("# Candidates\n", encoding="utf-8")
        return 1

    def context(output: Path) -> int:
        output.write_text("# Context\n", encoding="utf-8")
        return 1

    def outcome(output: Path) -> None:
        output.write_text("# Event Outcome Backtest: SPY\n\n## Run Metadata\n\n- benchmark: SPY\n", encoding="utf-8")

    def review(input_path: Path, output: Path) -> None:
        output.write_text("# Outcome Review\n", encoding="utf-8")

    result = run_research_cycle(
        store=store,
        config=ResearchCycleConfig(
            reports_dir=tmp_path / "reports",
            benchmark="SPY",
            candidate_context=True,
        ),
        deps=ResearchCycleDeps(
            fetch_events=fetch_events,
            enrich=enrich,
            score=score,
            candidate_context=context,
            outcome_backtest=outcome,
            outcome_review=review,
        ),
    )

    assert result.status == "succeeded"
    artifacts = store.list_research_run_artifacts(result.run_id)
    assert artifacts
    for row in artifacts:
        assert len(row["sha256"]) == 64
        int(row["sha256"], 16)


def test_research_cycle_records_failure(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")

    def fail_fetch() -> dict[str, int]:
        raise RuntimeError("source down")

    notifier = RecordingNotifier()
    result = run_research_cycle(
        store=store,
        config=ResearchCycleConfig(reports_dir=tmp_path / "reports"),
        deps=ResearchCycleDeps(fetch_events=fail_fetch),
        notifier=notifier,
    )

    row = store.list_research_runs(limit=1)[0]
    assert result.status == "failed"
    assert row["status"] == "failed"
    assert "source down" in row["error"]
    assert notifier.calls
    assert notifier.calls[0][0] == "Research cycle failed"
    assert "source down" in notifier.calls[0][1]
    assert notifier.calls[0][2] is True
