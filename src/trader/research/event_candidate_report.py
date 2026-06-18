from __future__ import annotations

from trader.research.event_candidates import EventCandidate


def format_candidate_report(candidates: list[EventCandidate], *, title: str = "Event Candidates") -> str:
    lines = [
        f"# {title}",
        "",
        "Research-only candidate list. This is not a trading signal and does not place orders.",
        "",
        "| score | direction | ticker | confidence | actionable | type | urgency | source | title | reasons |",
        "|---:|---|---|---:|---|---|---|---|---|---|",
    ]
    for candidate in candidates:
        reasons = ", ".join(candidate.reasons).replace("|", "\\|")
        title_text = candidate.title.replace("|", "\\|")
        lines.append(
            f"| {candidate.score:+.2f} | {candidate.direction} | {candidate.ticker} | "
            f"{candidate.confidence:.2f} | {candidate.is_actionable} | {candidate.event_type} | "
            f"{candidate.urgency} | {candidate.source} | {title_text} | {reasons} |"
        )
    if candidates:
        lines.extend(["", "## Key Claims", ""])
        for candidate in candidates:
            for claim in candidate.key_claims:
                lines.append(f"- `{candidate.event_id}` {claim}")
    return "\n".join(lines) + "\n"
