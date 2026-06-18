"""Unit tests for event-driven study engines on synthetic series."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from trader.catalysts.event_driven import (
    PeadEvent,
    aggregate_cohort,
    classify_8k_items,
    compute_event_cars,
    compute_pead_event,
)


def _bdays(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2022-01-03", periods=n)


def _close_from_returns(
    idx: pd.DatetimeIndex,
    returns: dict[int, float],
    *,
    name: str = "TEST",
) -> pd.Series:
    values = [100.0]
    for position in range(1, len(idx)):
        values.append(values[-1] * (1 + returns.get(position, 0.0)))
    return pd.Series(values, index=idx, name=name)


def test_compute_pead_event_recovers_known_cars():
    idx = _bdays(140)
    t0 = 60
    close = _close_from_returns(idx, {i: -0.01 for i in range(t0, t0 + 6)})
    bench = pd.Series([100.0] * len(idx), index=idx, name="SPY")

    event = compute_pead_event(close, bench, idx[t0].date())

    assert event is not None
    assert event.t0_date == idx[t0].date()
    assert event.prev_day_reaction == pytest.approx(-0.01)
    assert event.car_0_p5 == pytest.approx(-0.06)
    assert event.car_0_p21 == pytest.approx(-0.06)
    assert event.car_m1_p1 == pytest.approx(-0.02)


def test_compute_pead_event_returns_none_when_window_short():
    idx = _bdays(80)
    close = _close_from_returns(idx, {})
    bench = pd.Series([100.0] * len(idx), index=idx, name="SPY")

    assert compute_pead_event(close, bench, idx[60].date()) is None


def test_compute_event_cars_handles_arbitrary_windows():
    idx = _bdays(100)
    t0 = 40
    close = _close_from_returns(idx, {t0: 0.01, t0 + 1: 0.02, t0 + 2: -0.005})
    bench = pd.Series([100.0] * len(idx), index=idx, name="SPY")

    cars = compute_event_cars(close, bench, idx[t0].date(), {"a": (0, 2)})

    assert cars == {"a": pytest.approx(0.025)}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "ITEM 2.02 Results of Operations\nItem 5.02 Departure of Directors",
            {"2.02", "5.02"},
        ),
        ("iTeM 1.01 Entry into an Agreement", {"1.01"}),
        ("No numbered disclosure headers are present.", set()),
    ],
)
def test_classify_8k_items_parses_headers(text: str, expected: set[str]):
    assert classify_8k_items(text) == expected


def test_classify_8k_items_multiple_occurrences_dedup():
    assert classify_8k_items("Item 2.02 first ... Item 2.02 again") == {"2.02"}


def test_aggregate_cohort_means_and_tstats():
    values = [-0.05, -0.04, -0.03, -0.06]
    events = [
        PeadEvent(
            ticker=f"T{i}",
            event_date=date(2022, 1, i + 1),
            t0_date=date(2022, 1, i + 1),
            prev_day_reaction=-0.01,
            car_m1_p1=value,
            car_0_p5=value,
            car_0_p21=value,
            car_0_p63=value,
        )
        for i, value in enumerate(values)
    ]

    stats = aggregate_cohort(events, "negative")

    assert stats.n == 4
    assert stats.means["car_0_p21"] == pytest.approx(-0.045)
    assert stats.t_stats["car_0_p21"] < 0
    assert abs(stats.t_stats["car_0_p21"]) > 2
