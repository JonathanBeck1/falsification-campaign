"""Unit tests for the provider-neutral IPO lock-up dataset builder."""

from __future__ import annotations

from datetime import date

import pytest

from trader.catalysts.ipo_lockup import (
    IpoFilingProvider,
    RawIpoFiling,
    build_ipo_lockup_events,
    compute_lockup_expiry,
    events_to_dataframe,
)


@pytest.fixture(autouse=True)
def _isolate_env() -> None:
    """Keep this pure module independent of the trading-config fixture."""


class FakeProvider(IpoFilingProvider):
    """In-memory IPO filing provider that never performs network calls."""

    def recent_ipo_filings(self, since: date, until: date) -> list[RawIpoFiling]:
        return [
            RawIpoFiling(
                cik="0000000002",
                company="Second Company",
                filing_date=date(2024, 3, 15),
                form="424B4",
                ticker=None,
            ),
            RawIpoFiling(
                cik="0000000001",
                company="First Company",
                filing_date=date(2024, 1, 10),
                form="424B4",
                ticker="FIRST",
            ),
            RawIpoFiling(
                cik="0000000001",
                company="First Company Duplicate",
                filing_date=date(2024, 1, 10),
                form="424B1",
                ticker="DUP",
            ),
        ]


def test_compute_lockup_expiry_default_and_custom_days() -> None:
    assert compute_lockup_expiry(date(2024, 1, 1)) == date(2024, 6, 29)
    assert compute_lockup_expiry(date(2024, 2, 20), 90) == date(2024, 5, 20)


def test_build_ipo_lockup_events_deduplicates_keeps_missing_ticker_and_sorts() -> None:
    events = build_ipo_lockup_events(
        date(2024, 1, 1),
        date(2024, 12, 31),
        provider=FakeProvider(),
    )

    assert len(events) == 2
    assert [event.ipo_date for event in events] == [date(2024, 1, 10), date(2024, 3, 15)]
    assert events[0].company == "First Company"
    assert events[0].ticker == "FIRST"
    assert events[0].lockup_expiry_date == date(2024, 7, 8)
    assert events[0].source == "edgar"
    assert events[0].prospectus_form == "424B4"
    assert events[1].ticker is None
    assert events[1].lockup_expiry_date == date(2024, 9, 11)


def test_events_to_dataframe_has_stable_columns_and_row_count() -> None:
    events = build_ipo_lockup_events(
        date(2024, 1, 1),
        date(2024, 12, 31),
        provider=FakeProvider(),
    )

    frame = events_to_dataframe(events)

    assert list(frame.columns) == [
        "ticker",
        "cik",
        "company",
        "ipo_date",
        "lockup_expiry_date",
        "lockup_days",
        "source",
        "prospectus_form",
    ]
    assert len(frame) == 2
