from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from trader.notify.base import Notifier
from trader.research.run_manifest import ResearchCycleArtifact, ResearchCycleManifest, format_manifest
from trader.storage.store import Store

T = TypeVar("T", bound=Callable[..., object])


class FetchEventsFn(Protocol):
    def __call__(self) -> dict[str, int]:
        raise NotImplementedError


class EnrichFn(Protocol):
    def __call__(self) -> tuple[int, int]:
        raise NotImplementedError


class ScoreFn(Protocol):
    def __call__(self, output: Path) -> int:
        raise NotImplementedError


class CandidateContextFn(Protocol):
    def __call__(self, output: Path) -> int:
        raise NotImplementedError


class OutcomeBacktestFn(Protocol):
    def __call__(self, output: Path) -> None:
        raise NotImplementedError


class OutcomeReviewFn(Protocol):
    def __call__(self, input_path: Path, output: Path) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class ResearchCycleConfig:
    reports_dir: Path
    benchmark: str = "SPY"
    entry_time: str = "observed_at"
    horizons: str = "5m,15m,30m,1h,4h,1d"
    group_by: str = "event_type,thesis_bucket"
    since: str | None = None
    until: str | None = None
    data_provider: str = "yahoo"
    mock_llm: bool = True
    fetch_first: bool = True
    candidate_context: bool = False


@dataclass
class ResearchCycleDeps:
    fetch_events: FetchEventsFn | None = None
    enrich: EnrichFn | None = None
    score: ScoreFn | None = None
    candidate_context: CandidateContextFn | None = None
    outcome_backtest: OutcomeBacktestFn | None = None
    outcome_review: OutcomeReviewFn | None = None


@dataclass(frozen=True)
class ResearchCycleResult:
    run_id: str
    status: str
    manifest_path: Path
    error: str = ""


def _required(dep: T | None, name: str) -> T:
    if dep is None:
        raise RuntimeError(f"Missing research cycle dependency: {name}")
    return dep


def _notify_research_cycle(
    notifier: Notifier | None,
    *,
    title: str,
    body: str,
    error: bool,
) -> None:
    if notifier is None:
        return
    with contextlib.suppress(Exception):
        notifier.send(title, body, error=error)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_research_cycle(
    *,
    store: Store,
    config: ResearchCycleConfig,
    deps: ResearchCycleDeps,
    notifier: Notifier | None = None,
) -> ResearchCycleResult:
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    events_before = store.count_news_events()
    run_id = store.create_research_run(
        command={
            "command": "research-cycle",
            "benchmark": config.benchmark,
            "entry_time": config.entry_time,
            "horizons": config.horizons,
            "group_by": config.group_by,
            "since": config.since,
            "until": config.until,
            "data_provider": config.data_provider,
            "mock_llm": config.mock_llm,
            "fetch_first": config.fetch_first,
            "candidate_context": config.candidate_context,
        },
        benchmark=config.benchmark,
        entry_time=config.entry_time,
        horizons=config.horizons,
        group_by=config.group_by,
        since=config.since,
        until=config.until,
        data_provider=config.data_provider,
        events_before=events_before,
    )
    run_dir = config.reports_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = config.reports_dir / f"research-cycle-{run_id}.md"
    artifacts: list[ResearchCycleArtifact] = []

    try:
        if config.fetch_first:
            _required(deps.fetch_events, "fetch_events")()
        enriched_count, rejected_count = _required(deps.enrich, "enrich")()

        candidate_report = run_dir / "event-candidates.md"
        candidate_count = _required(deps.score, "score")(candidate_report)
        artifacts.append(ResearchCycleArtifact("candidate_report", str(candidate_report)))
        store.record_research_run_artifact(
            run_id,
            artifact_type="candidate_report",
            path=str(candidate_report),
            sha256=_sha256_file(candidate_report),
        )

        if config.candidate_context:
            context_report = run_dir / "candidate-context.md"
            _required(deps.candidate_context, "candidate_context")(context_report)
            artifacts.append(ResearchCycleArtifact("candidate_context", str(context_report)))
            store.record_research_run_artifact(
                run_id,
                artifact_type="candidate_context",
                path=str(context_report),
                sha256=_sha256_file(context_report),
            )

        outcome_report = run_dir / "outcomes.md"
        _required(deps.outcome_backtest, "outcome_backtest")(outcome_report)
        artifacts.append(ResearchCycleArtifact("outcome_report", str(outcome_report)))
        store.record_research_run_artifact(
            run_id,
            artifact_type="outcome_report",
            path=str(outcome_report),
            sha256=_sha256_file(outcome_report),
        )

        review_report = run_dir / "outcome-review.md"
        _required(deps.outcome_review, "outcome_review")(outcome_report, review_report)
        artifacts.append(ResearchCycleArtifact("outcome_review", str(review_report)))
        store.record_research_run_artifact(
            run_id,
            artifact_type="outcome_review",
            path=str(review_report),
            sha256=_sha256_file(review_report),
        )

        events_after = store.count_news_events()
        manifest = ResearchCycleManifest(
            run_id=run_id,
            status="succeeded",
            benchmark=config.benchmark,
            entry_time=config.entry_time,
            events_before=events_before,
            events_after=events_after,
            enriched_count=enriched_count,
            rejected_count=rejected_count,
            candidate_count=candidate_count,
            artifacts=[*artifacts, ResearchCycleArtifact("manifest", str(manifest_path))],
        )
        manifest_path.write_text(format_manifest(manifest), encoding="utf-8")
        store.record_research_run_artifact(
            run_id,
            artifact_type="manifest",
            path=str(manifest_path),
            sha256=_sha256_file(manifest_path),
        )
        store.finish_research_run(
            run_id,
            status="succeeded",
            events_after=events_after,
            enriched_count=enriched_count,
            rejected_count=rejected_count,
            candidate_count=candidate_count,
            outcome_report_path=str(outcome_report),
            review_report_path=str(review_report),
            manifest_path=str(manifest_path),
        )
        _notify_research_cycle(
            notifier,
            title="Research cycle succeeded",
            body=f"run_id={run_id}\ncandidates={candidate_count}\nmanifest={manifest_path}",
            error=False,
        )
        return ResearchCycleResult(run_id=run_id, status="succeeded", manifest_path=manifest_path)
    except Exception as exc:
        error = str(exc)
        events_after = store.count_news_events()
        manifest = ResearchCycleManifest(
            run_id=run_id,
            status="failed",
            benchmark=config.benchmark,
            entry_time=config.entry_time,
            events_before=events_before,
            events_after=events_after,
            enriched_count=0,
            rejected_count=0,
            candidate_count=0,
            artifacts=[ResearchCycleArtifact("manifest", str(manifest_path))],
            error=error,
        )
        manifest_path.write_text(format_manifest(manifest), encoding="utf-8")
        store.record_research_run_artifact(
            run_id,
            artifact_type="manifest",
            path=str(manifest_path),
            sha256=_sha256_file(manifest_path) if manifest_path.exists() else "",
        )
        store.finish_research_run(
            run_id,
            status="failed",
            events_after=events_after,
            enriched_count=0,
            rejected_count=0,
            candidate_count=0,
            outcome_report_path="",
            review_report_path="",
            manifest_path=str(manifest_path),
            error=error,
        )
        _notify_research_cycle(
            notifier,
            title="Research cycle failed",
            body=f"run_id={run_id}\nerror={error}\nmanifest={manifest_path}",
            error=True,
        )
        return ResearchCycleResult(run_id=run_id, status="failed", manifest_path=manifest_path, error=error)
