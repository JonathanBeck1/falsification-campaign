"""NBBO data-quality report flags planted bad rows on a tiny fixture."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from trader.options.models import OptionQuoteBar
from trader.options.quality import (
    format_nbbo_quality_report,
    summarize_nbbo_quality,
)
from trader.options.sources import SqliteQuoteSource
from trader.storage.store import Store

EASTERN = ZoneInfo("America/New_York")
EXP_A = date(2026, 6, 26)
EXP_B = date(2026, 7, 17)


def _bar(ts, strike, cp, bid, ask, *, expiration=EXP_A, bid_size=10, ask_size=10):
    return OptionQuoteBar(
        timestamp=ts,
        ticker="SPY",
        expiration=expiration,
        strike=strike,
        call_put=cp,
        bid=bid,
        ask=ask,
        underlying_price=585.0,
        bid_size=bid_size,
        ask_size=ask_size,
        bid_exchange=1,
        ask_exchange=1,
        bid_condition=0,
        ask_condition=0,
        source="unit-test",
    )


def _seed(tmp_path: Path) -> Store:
    store = Store(tmp_path / "trader.sqlite")
    t1 = datetime(2026, 5, 22, 9, 45, tzinfo=EASTERN)
    t2 = datetime(2026, 5, 22, 9, 46, tzinfo=EASTERN)
    t3 = datetime(2026, 5, 26, 9, 45, tzinfo=EASTERN)

    store.upsert_option_quote_bars_1m(
        "SPY",
        [
            # clean rows
            _bar(t1, 560, "Put", 1.20, 1.30),
            _bar(t1, 560, "Put", 1.21, 1.31, expiration=EXP_B),  # EXP_B present only on day 1 -> gap
            # crossed quote: bid > ask
            _bar(t1, 555, "Put", 1.50, 1.30),
            # locked quote: bid == ask > 0
            _bar(t2, 561, "Call", 1.00, 1.00),
            # non-positive size
            _bar(t2, 562, "Call", 1.00, 1.10, bid_size=0),
            # absurd spread: (2.0-0.10)/1.05 ~ 1.81 > 0.5
            _bar(t2, 563, "Call", 0.10, 2.00),
            # missing ask
            _bar(t2, 564, "Call", 0.50, None),
        ],
    )
    store.upsert_option_quote_bars_1m(
        "SPY",
        [
            _bar(t3, 560, "Put", 1.10, 1.20),  # only EXP_A on day 2
        ],
    )
    return store


def test_nbbo_quality_flags_each_planted_problem(tmp_path: Path):
    store = _seed(tmp_path)
    source = SqliteQuoteSource(store)

    report = summarize_nbbo_quality(source, ticker="SPY", start=date(2026, 5, 22), end=date(2026, 5, 26))

    assert report.days == 2
    assert report.crossed_quotes == 1
    assert report.locked_quotes == 1
    assert report.nonpositive_size_rows == 1
    assert report.absurd_spread_rows == 1
    assert report.missing_quote_rows == 1
    # EXP_B appears on day 1 only -> one expiration with a coverage gap
    assert report.expirations == 2
    assert report.expirations_with_gaps == 1
    for flag in (
        "crossed_quotes",
        "locked_quotes",
        "nonpositive_sizes",
        "absurd_spreads",
        "missing_quotes",
        "expiration_coverage_gaps",
    ):
        assert flag in report.warnings


def test_nbbo_quality_minutes_per_day(tmp_path: Path):
    store = _seed(tmp_path)
    source = SqliteQuoteSource(store)
    report = summarize_nbbo_quality(source, ticker="SPY", start=date(2026, 5, 22), end=date(2026, 5, 26))
    # day 1 has timestamps 09:45 and 09:46 -> 2 minutes; day 2 has 1 minute
    assert report.max_minutes_per_day == 2
    assert report.min_minutes_per_day == 1


def test_nbbo_quality_clean_dataset_has_no_warnings(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    t1 = datetime(2026, 5, 22, 9, 45, tzinfo=EASTERN)
    store.upsert_option_quote_bars_1m("SPY", [_bar(t1, 560, "Put", 1.20, 1.30)])
    report = summarize_nbbo_quality(SqliteQuoteSource(store), ticker="SPY", start=date(2026, 5, 22), end=date(2026, 5, 22))
    assert report.warnings == ()
    assert report.crossed_quotes == 0


def test_nbbo_quality_report_renders(tmp_path: Path):
    store = _seed(tmp_path)
    report = summarize_nbbo_quality(SqliteQuoteSource(store), ticker="SPY", start=date(2026, 5, 22), end=date(2026, 5, 26))
    rendered = format_nbbo_quality_report(report)
    assert "# SPY NBBO Quote Quality" in rendered
    assert "- crossed_quotes: 1" in rendered
    assert "## Flagged examples" in rendered
