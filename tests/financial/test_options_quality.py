from __future__ import annotations

from datetime import date

from trader.options.models import OptionQuote
from trader.options.quality import format_option_coverage_report, summarize_option_coverage


def _quote(
    trade_date: date,
    *,
    ticker: str = "SPY",
    expiration: date = date(2026, 6, 26),
    strike: float = 560.0,
    call_put: str = "Put",
    bid: float | None = 1.0,
    ask: float | None = 1.1,
) -> OptionQuote:
    return OptionQuote(
        trade_date=trade_date,
        ticker=ticker,
        expiration=expiration,
        strike=strike,
        call_put=call_put,
        bid=bid,
        ask=ask,
        implied_vol=0.18,
        delta=-0.16 if call_put == "Put" else 0.16,
        gamma=None,
        theta=None,
        vega=None,
        rho=None,
    )


def test_summarize_option_coverage_counts_dates_rows_and_missing_quotes():
    quotes = [
        _quote(date(2026, 5, 1), strike=560),
        _quote(date(2026, 5, 1), strike=565, call_put="Call"),
        _quote(date(2026, 5, 2), strike=560, bid=None, ask=1.1),
    ]

    summary = summarize_option_coverage(quotes, ticker="SPY")

    assert summary.ticker == "SPY"
    assert summary.start == date(2026, 5, 1)
    assert summary.end == date(2026, 5, 2)
    assert summary.trade_dates == 2
    assert summary.option_rows == 3
    assert summary.missing_bid_ask_rows == 1
    assert summary.min_rows_per_date == 1
    assert summary.max_rows_per_date == 2
    assert summary.average_rows_per_date == 1.5


def test_format_option_coverage_report_exposes_low_depth_warning():
    summary = summarize_option_coverage([_quote(date(2026, 5, 1))], ticker="SPY", min_rows_per_date_warning=10)

    report = format_option_coverage_report(summary)

    assert "# SPY Options Coverage" in report
    assert "option_rows: 1" in report
    assert "low_contract_depth" in report
