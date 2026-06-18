from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ResearchCycleArtifact:
    kind: str
    path: str


@dataclass(frozen=True)
class ResearchCycleManifest:
    run_id: str
    status: str
    benchmark: str
    entry_time: str
    events_before: int
    events_after: int
    enriched_count: int
    rejected_count: int
    candidate_count: int
    artifacts: list[ResearchCycleArtifact] = field(default_factory=list)
    error: str = ""


def format_manifest(manifest: ResearchCycleManifest) -> str:
    lines = [
        "# Research Cycle Manifest",
        "",
        "Research-only run manifest. This is an audit artifact, not a trading signal.",
        "",
        "## Run",
        "",
        f"- run_id: {manifest.run_id}",
        f"- status: {manifest.status}",
        f"- benchmark: {manifest.benchmark}",
        f"- entry_time: {manifest.entry_time}",
        f"- events_before: {manifest.events_before}",
        f"- events_after: {manifest.events_after}",
        f"- enriched_count: {manifest.enriched_count}",
        f"- rejected_count: {manifest.rejected_count}",
        f"- candidate_count: {manifest.candidate_count}",
    ]
    if manifest.error:
        lines.append(f"- error: {manifest.error}")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "| kind | path |",
            "|---|---|",
        ]
    )
    if manifest.artifacts:
        for artifact in manifest.artifacts:
            lines.append(f"| {artifact.kind} | {artifact.path} |")
    else:
        lines.append("| none | - |")
    return "\n".join(lines) + "\n"
