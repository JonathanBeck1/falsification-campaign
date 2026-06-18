"""Render a scenario run as a markdown report.

Takes the scenario + materialized events, walks them through the
ThesisEngine and ThesisAggregator one at a time (to show the running
aggregate), and produces a human-readable markdown report.
"""

from __future__ import annotations

from datetime import datetime

from trader.normalization.models import Event
from trader.scenarios.samples import Scenario
from trader.thesis.aggregator import AggregateDecision, ThesisAggregator
from trader.thesis.engine import ThesisEngine
from trader.thesis.taxonomy import POLICY_VERSION, Thesis


def render_scenario_report(
    scenario: Scenario,
    events_with_times: list[tuple[Event, datetime]],
    engine: ThesisEngine,
    aggregator: ThesisAggregator,
) -> str:
    lines: list[str] = []
    lines.append(f"# Scenario: {scenario.name}")
    lines.append("")
    lines.append("Research-only deterministic demo. This is not a trading order.")
    lines.append("")
    lines.append(f"**Policy version:** `{POLICY_VERSION}`")
    lines.append(f"**Baseline position:** {aggregator.baseline_pct:.0%}")
    lines.append("")
    lines.append("## Narrative")
    lines.append("")
    lines.append(scenario.narrative)
    lines.append("")
    lines.append("## Macro context")
    lines.append("")
    m = scenario.macro
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| VIX | {m.vix if m.vix is not None else 'n/a'} |")
    lines.append(
        f"| 10y-2y curve | {m.yield_curve_10y_2y if m.yield_curve_10y_2y is not None else 'n/a'} |"
    )
    lines.append(f"| Fed funds | {m.fed_funds if m.fed_funds is not None else 'n/a'} |")
    lines.append(f"| CPI YoY | {m.cpi_yoy if m.cpi_yoy is not None else 'n/a'} |")
    lines.append("")
    lines.append("## Event stream + running aggregate")
    lines.append("")
    lines.append("Each row shows one incoming event, the bucket the engine assigned,")
    lines.append("and the running aggregate after that event lands.")
    lines.append("")
    lines.append("| t+min | Headline | Bucket | Direction | Conf | Active | Target |")
    lines.append("|---:|---|---|---|---|---:|---:|")

    open_theses: list[Thesis] = []
    final_decision: AggregateDecision | None = None
    classification_notes: list[tuple[str, str]] = []

    start = events_with_times[0][1] if events_with_times else None

    for event, observed in events_with_times:
        t_min = int((observed - start).total_seconds() // 60) if start else 0
        thesis = engine.classify(event)
        if thesis is not None:
            open_theses.append(thesis)
            bucket = thesis.template.bucket
            direction = thesis.template.direction
            conf = thesis.template.confidence
            classification_notes.append((event.event_id, thesis.classification_note))
        else:
            bucket = "(IGNORED)"
            direction = "—"
            conf = "—"
            classification_notes.append((event.event_id, "no thesis emitted"))

        decision = aggregator.aggregate(open_theses, scenario.aggregate_inputs, now=observed)
        final_decision = decision

        headline = _shorten(event.title, 60)
        active = len(decision.active_theses)
        target = f"{decision.target_pct:.0%}"
        lines.append(
            f"| +{t_min} | {headline} | `{bucket}` | {direction} | {conf} | {active} | {target} |"
        )

    lines.append("")
    if final_decision is None:
        lines.append("_No events in this scenario._")
        return "\n".join(lines)

    lines.append("## Final decision")
    lines.append("")
    lines.append(f"- **Target position:** {final_decision.target_pct:.1%}")
    lines.append(f"- **Regime:** `{final_decision.regime_tag}`")
    lines.append(f"- **Direction sum (signed):** {final_decision.direction_sum:+.4f}")
    lines.append(f"- **Active theses:** {len(final_decision.active_theses)}")
    lines.append(f"- **Expired theses:** {len(final_decision.expired_theses)}")
    if final_decision.cost_filtered_theses:
        lines.append(
            f"- **Theses filtered (below cost threshold):** {len(final_decision.cost_filtered_theses)}"
        )
    if final_decision.holding_period_locked:
        lines.append("- **Holding-period lock:** active (position not flipped inside lock window)")
    lines.append(f"- **Regime cap:** {final_decision.regime_cap:.2f}")
    if final_decision.regime_reasons:
        lines.append("- **Regime reasons:**")
        for r in final_decision.regime_reasons:
            lines.append(f"  - {r}")
    else:
        lines.append("- **Regime reasons:** none (no macro stress detected)")
    lines.append("")
    lines.append("## Active theses at end of scenario")
    lines.append("")
    if not final_decision.active_theses:
        lines.append("_No active theses (all expired or none emitted)._")
    else:
        for t in final_decision.active_theses:
            lines.append(f"### `{t.template.bucket}` ({t.template.direction})")
            lines.append("")
            lines.append(f"- **Event:** `{t.event_id}`")
            lines.append(f"- **Confidence:** {t.template.confidence}")
            lines.append(f"- **Horizon:** {t.template.horizon_minutes} minutes")
            lines.append(f"- **Expected magnitude:** {t.template.expected_magnitude_pct:.2f}%")
            lines.append(f"- **Confirmation required:** {t.template.confirmation_required}")
            lines.append(f"- **Rationale:** {t.template.rationale}")
            lines.append("")

    lines.append("## Classification audit")
    lines.append("")
    lines.append("How each event was routed (or why it was ignored):")
    lines.append("")
    for event_id, note in classification_notes:
        lines.append(f"- `{event_id}`: {note}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated from `trader-daily run-scenario`. See `brain/21_news_to_trade_thesis_algorithm.md` for the design._"
    )
    return "\n".join(lines)


def _shorten(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"
