"""Sample news scenarios for testing the thesis pipeline end-to-end.

Each scenario is a list of realistic Event objects with manually-set labels
representing what an enricher would produce. Running a scenario through
ThesisEngine + ThesisAggregator demonstrates how the system reacts to a
real-world news situation without needing a live LLM call.

When PR #24's enricher merges, these same scenarios still work — the
enricher would produce the same labels (or the test catches the
divergence). The scenarios are the spec.
"""

from trader.scenarios.samples import (
    SCENARIO_NAMES,
    SCENARIOS,
    Scenario,
    ScenarioEvent,
    build_scenario_events,
)

__all__ = [
    "SCENARIOS",
    "SCENARIO_NAMES",
    "Scenario",
    "ScenarioEvent",
    "build_scenario_events",
]
