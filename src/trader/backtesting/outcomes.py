"""Research-only outcome backtesting helpers.

This module supports historical event-outcome analysis only. It is not trading
advice and must not be used as a live execution signal without separate
validation, controls, and review.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from statistics import mean, median, stdev

from trader.normalization.models import Event
from trader.storage.snapshot import Bar
from trader.thesis.engine import ThesisEngine


class EntryTimeMode(StrEnum):
    OBSERVED_AT = "observed_at"
    PUBLISHED_AT = "published_at"
    CLASSIFIED_AT = "classified_at"


DEFAULT_OUTCOME_HORIZONS: dict[str, timedelta] = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "3d": timedelta(days=3),
    "5d": timedelta(days=5),
}

SUPPORTED_GROUP_FIELDS = {"event_type", "sentiment", "urgency", "thesis_bucket"}


@dataclass
class OutcomeConfig:
    benchmark: str = "SPY"
    entry_time: EntryTimeMode = EntryTimeMode.OBSERVED_AT
    horizons: Mapping[str, timedelta] = field(default_factory=lambda: dict(DEFAULT_OUTCOME_HORIZONS))
    group_by: tuple[str, ...] = ("event_type",)
    min_sample: int = 10


@dataclass
class OutcomeResult:
    event_id: str
    event_type: str
    sentiment: str
    urgency: str
    benchmark: str
    horizon: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    return_pct: float
    group_values: dict[str, str]
    title: str


@dataclass
class OutcomeCoverage:
    events_seen: int = 0
    events_missing_entry_time: int = 0
    events_with_entry: int = 0
    missing_entry_bar: int = 0
    missing_horizon_bar: int = 0


@dataclass
class OutcomeRun:
    results: list[OutcomeResult]
    coverage: OutcomeCoverage


@dataclass
class OutcomeStats:
    group_label: str
    horizon: str
    n: int
    hit_rate: float
    mean_return_pct: float
    median_return_pct: float
    stdev_return_pct: float
    min_return_pct: float
    max_return_pct: float


def _as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def event_entry_time(event: Event, mode: EntryTimeMode = EntryTimeMode.OBSERVED_AT) -> datetime | None:
    if mode == EntryTimeMode.OBSERVED_AT:
        return _as_utc(event.observed_at)
    if mode == EntryTimeMode.PUBLISHED_AT:
        return _as_utc(event.published_at)
    if mode == EntryTimeMode.CLASSIFIED_AT:
        return _as_utc(event.classified_at) if event.classified_at else None
    raise ValueError(f"Unsupported entry time mode: {mode}")


def _bar_at_or_after(bars: Sequence[Bar], timestamps: Sequence[datetime], ts: datetime) -> Bar | None:
    target = _as_utc(ts)
    index = bisect_left(timestamps, target)
    if index >= len(bars):
        return None
    return bars[index]


def parse_group_by(raw_values: list[str] | None) -> tuple[str, ...]:
    if raw_values is None:
        return ("event_type",)

    fields: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        for group_field in (part.strip() for part in raw_value.split(",")):
            if not group_field or group_field in seen:
                continue
            if group_field not in SUPPORTED_GROUP_FIELDS:
                raise ValueError(f"Unsupported group field: {group_field}")
            fields.append(group_field)
            seen.add(group_field)

    return tuple(fields) if fields else ("event_type",)


def _group_values_for_event(event: Event, group_by: Sequence[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    thesis_engine: ThesisEngine | None = None

    for field_name in group_by:
        if field_name == "event_type":
            values[field_name] = event.event_type
        elif field_name == "sentiment":
            values[field_name] = event.sentiment
        elif field_name == "urgency":
            values[field_name] = event.urgency
        elif field_name == "thesis_bucket":
            if thesis_engine is None:
                thesis_engine = ThesisEngine()
            thesis = thesis_engine.classify(event)
            values[field_name] = thesis.template.bucket if thesis else "ignored"
        else:
            raise ValueError(f"Unsupported group field: {field_name}")

    return values


def _group_label(group_values: Mapping[str, str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in group_values.items())


def compute_outcomes(events: Sequence[Event], bars: Sequence[Bar], config: OutcomeConfig) -> OutcomeRun:
    sorted_pairs = sorted(((_as_utc(bar.timestamp), bar) for bar in bars), key=lambda pair: pair[0])
    timestamps = [timestamp for timestamp, _bar in sorted_pairs]
    sorted_bars = [bar for _timestamp, bar in sorted_pairs]
    coverage = OutcomeCoverage()
    results: list[OutcomeResult] = []

    for event in events:
        coverage.events_seen += 1
        entry_time = event_entry_time(event, config.entry_time)
        if entry_time is None:
            coverage.events_missing_entry_time += 1
            continue

        entry_bar = _bar_at_or_after(sorted_bars, timestamps, entry_time)
        if entry_bar is None:
            coverage.missing_entry_bar += 1
            continue

        entry_price = entry_bar.close
        if entry_price == 0:
            coverage.missing_entry_bar += 1
            continue

        coverage.events_with_entry += 1
        group_values = _group_values_for_event(event, config.group_by)
        actual_entry_time = _as_utc(entry_bar.timestamp)
        for horizon, delta in config.horizons.items():
            exit_bar = _bar_at_or_after(sorted_bars, timestamps, actual_entry_time + delta)
            if exit_bar is None:
                coverage.missing_horizon_bar += 1
                continue

            exit_price = exit_bar.close
            results.append(
                OutcomeResult(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    sentiment=event.sentiment,
                    urgency=event.urgency,
                    benchmark=config.benchmark,
                    horizon=horizon,
                    entry_time=actual_entry_time,
                    exit_time=_as_utc(exit_bar.timestamp),
                    entry_price=entry_price,
                    exit_price=exit_price,
                    return_pct=((exit_price - entry_price) / entry_price) * 100,
                    group_values=dict(group_values),
                    title=event.title,
                )
            )

    return OutcomeRun(results=results, coverage=coverage)


def parse_horizons(raw: str | None) -> dict[str, timedelta]:
    if raw is None:
        return dict(DEFAULT_OUTCOME_HORIZONS)

    horizons: dict[str, timedelta] = {}
    for label in (part.strip() for part in raw.split(",")):
        if not label:
            continue
        horizons[label] = _parse_horizon(label)

    if not horizons:
        raise ValueError("At least one horizon is required")
    return horizons


def _parse_horizon(label: str) -> timedelta:
    value = label[:-1]
    unit = label[-1:]
    if not value.isdecimal():
        raise ValueError(f"Unsupported horizon: {label}")

    amount = int(value)
    if amount <= 0:
        raise ValueError(f"Unsupported horizon: {label}")
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    raise ValueError(f"Unsupported horizon: {label}")


def aggregate_outcomes(results: Sequence[OutcomeResult]) -> list[OutcomeStats]:
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for result in results:
        buckets[(_group_label(result.group_values), result.horizon)].append(result.return_pct)

    stats: list[OutcomeStats] = []
    for (group_label, horizon), returns in sorted(buckets.items()):
        stats.append(
            OutcomeStats(
                group_label=group_label,
                horizon=horizon,
                n=len(returns),
                hit_rate=sum(1 for return_pct in returns if return_pct > 0) / len(returns),
                mean_return_pct=mean(returns),
                median_return_pct=median(returns),
                stdev_return_pct=stdev(returns) if len(returns) > 1 else 0.0,
                min_return_pct=min(returns),
                max_return_pct=max(returns),
            )
        )
    return stats


def format_outcome_report(
    run: OutcomeRun,
    *,
    config: OutcomeConfig,
    metadata: Mapping[str, object] | None = None,
) -> str:
    stats = aggregate_outcomes(run.results)
    lines = [
        f"# Event Outcome Backtest: {config.benchmark}",
        "",
        "Research-only historical event-outcome analysis. This is not trading advice,",
        "a live execution signal, or a claim of future performance.",
        "",
        "## Run Metadata",
        "",
        f"- benchmark: {config.benchmark}",
        f"- entry_time: {config.entry_time.value}",
        f"- horizons: {', '.join(config.horizons)}",
        f"- group_by: {', '.join(config.group_by)}",
    ]

    if metadata:
        for key in sorted(metadata):
            lines.append(f"- {key}: {metadata[key]}")

    lines.extend(["", "## Coverage", ""])
    for field_name in OutcomeCoverage.__dataclass_fields__:
        lines.append(f"- {field_name}: {getattr(run.coverage, field_name)}")

    lines.extend(
        [
            "",
            "## Grouped Stats",
            "",
            "| group | horizon | n | hit_rate | mean% | median% | stdev% | min% | max% |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    if stats:
        for stat in stats:
            lines.append(_format_stats_row(stat))
    else:
        lines.append("| no results | - | 0 | - | - | - | - | - | - |")

    low_sample_stats = [stat for stat in stats if stat.n < config.min_sample]
    lines.extend(["", "## Low sample groups", ""])
    if low_sample_stats:
        lines.extend(
            [
                "| group | horizon | n | min_sample |",
                "|---|---|---|---|",
            ]
        )
        for stat in low_sample_stats:
            lines.append(
                f"| {_format_table_cell(stat.group_label)} | {_format_table_cell(stat.horizon)} | "
                f"{stat.n} | {config.min_sample} |"
            )
    else:
        lines.append(f"No groups below min_sample={config.min_sample}.")

    lines.extend(["", "## Event Examples", ""])
    if run.results:
        examples = _example_results(run.results)
        lines.extend(
            [
                "| example | title | group | horizon | return% | entry_time | exit_time |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for label, result in examples:
            group_label = _group_label(result.group_values)
            lines.append(
                f"| {_format_table_cell(label)} | {_format_table_cell(result.title)} | "
                f"{_format_table_cell(group_label)} | {_format_table_cell(result.horizon)} | "
                f"{result.return_pct:+.2f} | {_format_table_cell(result.entry_time.isoformat())} | "
                f"{_format_table_cell(result.exit_time.isoformat())} |"
            )
    else:
        lines.append("No result rows available for event examples.")

    return "\n".join(lines) + "\n"


def _format_stats_row(stat: OutcomeStats) -> str:
    return (
        f"| {_format_table_cell(stat.group_label)} | {_format_table_cell(stat.horizon)} | {stat.n} | {stat.hit_rate:.0%} | "
        f"{stat.mean_return_pct:+.2f} | {stat.median_return_pct:+.2f} | "
        f"{stat.stdev_return_pct:.2f} | {stat.min_return_pct:+.2f} | "
        f"{stat.max_return_pct:+.2f} |"
    )


def _format_table_cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _example_results(results: Sequence[OutcomeResult]) -> list[tuple[str, OutcomeResult]]:
    best = max(results, key=lambda result: result.return_pct)
    worst = min(results, key=lambda result: result.return_pct)
    if best is worst:
        return [("best/worst", best)]
    return [("best", best), ("worst", worst)]
