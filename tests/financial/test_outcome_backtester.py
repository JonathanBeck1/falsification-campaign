from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trader.backtesting.outcomes import (
    EntryTimeMode,
    OutcomeConfig,
    aggregate_outcomes,
    compute_outcomes,
    event_entry_time,
    format_outcome_report,
    parse_horizons,
)
from trader.normalization.models import Event
from trader.storage.snapshot import Bar


def _bar(ts: datetime, close: float) -> Bar:
    return Bar(timestamp=ts, open=close, high=close, low=close, close=close, volume=1_000)


def _event() -> Event:
    published = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    observed = datetime(2026, 5, 20, 12, 5, tzinfo=UTC)
    classified = datetime(2026, 5, 20, 12, 9, tzinfo=UTC)
    return Event(
        event_id="evt_ts",
        source="demo_news",
        title="Fed comments move markets",
        summary="Powell says policy is restrictive.",
        published_at=published,
        observed_at=observed,
        ingested_at=observed,
        classified_at=classified,
        event_type="fed_commentary",
        sentiment="negative",
        sentiment_score=-0.4,
        urgency="high",
    )


def test_event_entry_time_defaults_to_observed_at():
    assert event_entry_time(_event()) == datetime(2026, 5, 20, 12, 5, tzinfo=UTC)
    assert event_entry_time(_event(), EntryTimeMode.OBSERVED_AT) == datetime(2026, 5, 20, 12, 5, tzinfo=UTC)


def test_event_entry_time_supports_published_and_classified_modes():
    event = _event()
    assert event_entry_time(event, EntryTimeMode.PUBLISHED_AT) == event.published_at
    assert event_entry_time(event, EntryTimeMode.CLASSIFIED_AT) == event.classified_at


def test_classified_mode_returns_none_when_classified_at_missing():
    event = _event().model_copy(update={"classified_at": None})
    assert event_entry_time(event, EntryTimeMode.CLASSIFIED_AT) is None


def test_parse_horizons_defaults_to_v1_set():
    horizons = parse_horizons(None)
    assert list(horizons) == ["5m", "15m", "30m", "1h", "4h", "1d", "3d", "5d"]
    assert horizons["15m"] == timedelta(minutes=15)
    assert horizons["3d"] == timedelta(days=3)


def test_parse_horizons_rejects_unknown_units():
    with pytest.raises(ValueError, match="Unsupported horizon"):
        parse_horizons("10x")


def test_compute_outcomes_uses_observed_at_and_avoids_published_at_leakage():
    event = _event()
    bars = [
        _bar(datetime(2026, 5, 20, 12, 0, tzinfo=UTC), 100.0),
        _bar(datetime(2026, 5, 20, 12, 5, tzinfo=UTC), 105.0),
        _bar(datetime(2026, 5, 20, 12, 10, tzinfo=UTC), 107.1),
    ]

    run = compute_outcomes(
        [event],
        bars,
        OutcomeConfig(benchmark="SPY", horizons={"5m": timedelta(minutes=5)}),
    )

    assert run.coverage.events_seen == 1
    assert run.coverage.events_with_entry == 1
    assert len(run.results) == 1
    result = run.results[0]
    assert result.entry_time == event.observed_at
    assert result.entry_price == 105.0
    assert result.exit_price == 107.1
    assert round(result.return_pct, 4) == 2.0


def test_compute_outcomes_counts_missing_entry_and_horizon_bars():
    event = _event()
    bars = [_bar(datetime(2026, 5, 20, 11, 0, tzinfo=UTC), 100.0)]

    run = compute_outcomes(
        [event],
        bars,
        OutcomeConfig(benchmark="SPY", horizons={"5m": timedelta(minutes=5)}),
    )

    assert run.results == []
    assert run.coverage.events_seen == 1
    assert run.coverage.missing_entry_bar == 1
    assert run.coverage.missing_horizon_bar == 0


def test_compute_outcomes_treats_zero_entry_price_as_missing_entry_bar():
    event = _event()
    bars = [
        _bar(datetime(2026, 5, 20, 12, 5, tzinfo=UTC), 0.0),
        _bar(datetime(2026, 5, 20, 12, 10, tzinfo=UTC), 105.0),
    ]

    run = compute_outcomes(
        [event],
        bars,
        OutcomeConfig(benchmark="SPY", horizons={"5m": timedelta(minutes=5)}),
    )

    assert run.results == []
    assert run.coverage.events_with_entry == 0
    assert run.coverage.missing_entry_bar == 1
    assert run.coverage.missing_horizon_bar == 0


def test_compute_outcomes_counts_missing_horizon_bars_after_entry_exists():
    event = _event()
    bars = [_bar(datetime(2026, 5, 20, 12, 5, tzinfo=UTC), 105.0)]

    run = compute_outcomes(
        [event],
        bars,
        OutcomeConfig(benchmark="SPY", horizons={"5m": timedelta(minutes=5)}),
    )

    assert run.results == []
    assert run.coverage.events_with_entry == 1
    assert run.coverage.missing_horizon_bar == 1


def test_compute_outcomes_measures_horizon_from_actual_entry_bar():
    event = _event().model_copy(update={"observed_at": datetime(2026, 5, 20, 21, 0, tzinfo=UTC)})
    bars = [
        _bar(datetime(2026, 5, 21, 13, 30, tzinfo=UTC), 100.0),
        _bar(datetime(2026, 5, 21, 13, 35, tzinfo=UTC), 101.0),
    ]

    run = compute_outcomes(
        [event],
        bars,
        OutcomeConfig(benchmark="SPY", horizons={"5m": timedelta(minutes=5)}),
    )

    assert run.coverage.events_with_entry == 1
    assert run.coverage.missing_horizon_bar == 0
    assert len(run.results) == 1
    assert run.results[0].entry_time == datetime(2026, 5, 21, 13, 30, tzinfo=UTC)
    assert run.results[0].exit_time == datetime(2026, 5, 21, 13, 35, tzinfo=UTC)
    assert run.results[0].return_pct == 1.0


def test_compute_outcomes_groups_by_event_type_sentiment_and_urgency():
    event = _event()
    bars = [
        _bar(datetime(2026, 5, 20, 12, 5, tzinfo=UTC), 100.0),
        _bar(datetime(2026, 5, 20, 12, 10, tzinfo=UTC), 101.0),
    ]

    run = compute_outcomes(
        [event],
        bars,
        OutcomeConfig(
            benchmark="SPY",
            horizons={"5m": timedelta(minutes=5)},
            group_by=("event_type", "sentiment", "urgency"),
        ),
    )

    assert run.results[0].group_values == {
        "event_type": "fed_commentary",
        "sentiment": "negative",
        "urgency": "high",
    }


def test_compute_outcomes_groups_by_thesis_bucket():
    event = _event().model_copy(update={"sentiment": "positive", "urgency": "high"})
    bars = [
        _bar(datetime(2026, 5, 20, 12, 5, tzinfo=UTC), 100.0),
        _bar(datetime(2026, 5, 20, 12, 10, tzinfo=UTC), 101.0),
    ]

    run = compute_outcomes(
        [event],
        bars,
        OutcomeConfig(
            benchmark="SPY",
            horizons={"5m": timedelta(minutes=5)},
            group_by=("thesis_bucket",),
        ),
    )

    assert run.results[0].group_values == {"thesis_bucket": "fed_dovish_surprise"}


def test_compute_outcomes_group_values_do_not_alias_between_horizons():
    event = _event()
    bars = [
        _bar(datetime(2026, 5, 20, 12, 5, tzinfo=UTC), 100.0),
        _bar(datetime(2026, 5, 20, 12, 10, tzinfo=UTC), 101.0),
        _bar(datetime(2026, 5, 20, 12, 20, tzinfo=UTC), 102.0),
    ]

    run = compute_outcomes(
        [event],
        bars,
        OutcomeConfig(
            benchmark="SPY",
            horizons={
                "5m": timedelta(minutes=5),
                "15m": timedelta(minutes=15),
            },
        ),
    )

    assert len(run.results) == 2
    assert run.results[0].group_values is not run.results[1].group_values

    run.results[0].group_values["event_type"] = "changed"

    assert run.results[1].group_values == {"event_type": "fed_commentary"}


def test_compute_outcomes_groups_unmatched_thesis_bucket_as_ignored():
    event = _event().model_copy(update={"event_type": "analyst_upgrade"})
    bars = [
        _bar(datetime(2026, 5, 20, 12, 5, tzinfo=UTC), 100.0),
        _bar(datetime(2026, 5, 20, 12, 10, tzinfo=UTC), 101.0),
    ]

    run = compute_outcomes(
        [event],
        bars,
        OutcomeConfig(
            benchmark="SPY",
            horizons={"5m": timedelta(minutes=5)},
            group_by=("thesis_bucket",),
        ),
    )

    assert run.results[0].group_values == {"thesis_bucket": "ignored"}


def test_aggregate_outcomes_computes_stats_by_group_and_horizon():
    event = _event()
    bars = [
        _bar(datetime(2026, 5, 20, 12, 5, tzinfo=UTC), 100.0),
        _bar(datetime(2026, 5, 20, 12, 10, tzinfo=UTC), 101.0),
    ]
    run = compute_outcomes(
        [event],
        bars,
        OutcomeConfig(benchmark="SPY", horizons={"5m": timedelta(minutes=5)}),
    )

    stats = aggregate_outcomes(run.results)

    assert len(stats) == 1
    assert stats[0].group_label == "event_type=fed_commentary"
    assert stats[0].horizon == "5m"
    assert stats[0].n == 1
    assert stats[0].hit_rate == 1.0
    assert stats[0].mean_return_pct == 1.0


def test_format_outcome_report_includes_metadata_coverage_warnings_and_examples():
    event = _event()
    bars = [
        _bar(datetime(2026, 5, 20, 12, 5, tzinfo=UTC), 100.0),
        _bar(datetime(2026, 5, 20, 12, 10, tzinfo=UTC), 101.0),
    ]
    config = OutcomeConfig(
        benchmark="SPY",
        horizons={"5m": timedelta(minutes=5)},
        min_sample=10,
    )
    run = compute_outcomes([event], bars, config)

    report = format_outcome_report(
        run,
        config=config,
        metadata={"source": "demo_news", "bar_count": 2},
    )

    assert "# Event Outcome Backtest: SPY" in report
    assert "entry_time: observed_at" in report
    assert "missing_entry_bar: 0" in report
    assert "Low sample groups" in report
    assert "Fed comments move markets" in report


def test_format_outcome_report_escapes_markdown_table_cells():
    event = _event().model_copy(update={"title": "Fed | update\nnext"})
    bars = [
        _bar(datetime(2026, 5, 20, 12, 5, tzinfo=UTC), 100.0),
        _bar(datetime(2026, 5, 20, 12, 10, tzinfo=UTC), 101.0),
    ]
    config = OutcomeConfig(
        benchmark="SPY",
        horizons={"5m": timedelta(minutes=5)},
        min_sample=10,
    )
    run = compute_outcomes([event], bars, config)
    run.results[0].group_values["event_type"] = "fed|comment\nnext"

    report = format_outcome_report(run, config=config)

    assert "Fed \\| update next" in report
    assert "event_type=fed\\|comment next" in report
