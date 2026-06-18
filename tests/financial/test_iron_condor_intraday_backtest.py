from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from trader.options.greeks import black_scholes_price
from trader.options.intraday import (
    IntradayIronCondorBacktestConfig,
    IntradayIronCondorSelectorConfig,
    build_intraday_quote_replay_data,
    format_intraday_iron_condor_report,
    run_intraday_iron_condor_backtest,
)
from trader.options.models import OptionQuoteBar


def _bar(
    timestamp: datetime,
    strike: float,
    call_put: str,
    bid: float,
    ask: float,
    *,
    expiration: date = date(2026, 6, 26),
    underlying_price: float | None = None,
) -> OptionQuoteBar:
    return OptionQuoteBar(
        timestamp=timestamp,
        ticker="SPY",
        expiration=expiration,
        strike=strike,
        call_put=call_put,
        bid=bid,
        ask=ask,
        underlying_price=underlying_price,
        bid_size=10,
        ask_size=10,
        bid_exchange=22,
        ask_exchange=73,
        bid_condition=50,
        ask_condition=50,
        source="unit-test",
    )


def _condor_snapshot(timestamp: datetime, *, short_bid: float, short_ask: float, long_bid: float, long_ask: float):
    return [
        _bar(timestamp, 555, "Put", long_bid, long_ask),
        _bar(timestamp, 560, "Put", short_bid, short_ask),
        _bar(timestamp, 610, "Call", short_bid, short_ask),
        _bar(timestamp, 615, "Call", long_bid, long_ask),
        _bar(timestamp, 540, "Put", 0.2, 0.25),
        _bar(timestamp, 630, "Call", 0.2, 0.25),
    ]


def test_intraday_iron_condor_backtest_opens_at_entry_time_and_exits_at_profit_target():
    eastern = ZoneInfo("America/New_York")
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    exit_ts = datetime(2026, 5, 22, 10, 15, tzinfo=eastern)
    quotes = [
        *_condor_snapshot(entry_ts, short_bid=1.20, short_ask=1.30, long_bid=0.50, long_ask=0.55),
        *_condor_snapshot(exit_ts, short_bid=0.60, short_ask=0.65, long_bid=0.35, long_ask=0.40),
    ]

    result = run_intraday_iron_condor_backtest(
        quotes,
        IntradayIronCondorBacktestConfig(
            ticker="SPY",
            start=date(2026, 5, 22),
            end=date(2026, 5, 22),
            selector=IntradayIronCondorSelectorConfig(
                min_dte=30,
                max_dte=45,
                wing_width=5.0,
                target_short_bid=1.20,
                min_credit=0.05,
            ),
            entry_time="09:45:00",
            profit_target_pct=0.50,
            stop_loss_credit_multiple=2.0,
        ),
    )

    assert result.summary.trade_count == 1
    assert result.summary.total_pnl == 70.0
    trade = result.trades[0]
    assert trade.entry_ts == entry_ts
    assert trade.exit_ts == exit_ts
    assert trade.entry_credit == 1.3
    assert trade.exit_debit == 0.6
    assert trade.exit_reason == "profit_target"
    assert trade.max_favorable_pnl == 70.0
    assert trade.max_adverse_pnl == 70.0
    assert trade.mark_count == 1

    report = format_intraday_iron_condor_report(result)
    assert "| entry_ts | exit_ts | expiration | strikes | put_delta | call_delta |" in report
    assert "| 2026-05-22T09:45:00-04:00 | 2026-05-22T10:15:00-04:00 |" in report


def test_intraday_iron_condor_backtest_does_not_book_fake_win_when_legs_go_missing_midlife():
    """Regression for the PR #101 missing-leg fake-win.

    A condor opens normally, then on a later (mid-life, dte > 0) snapshot its four
    leg quotes are absent but an underlying price is present and sits *between*
    the short strikes (OTM). The old marking path settled the position to its zero
    intrinsic and booked a fabricated max-profit ``profit_target`` win. Correct
    behavior: the position cannot be marked from a data gap mid-life, so it stays
    open and is reported as ``unclosed_missing_mark`` (pnl=None), never a win.
    """
    eastern = ZoneInfo("America/New_York")
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    # Later, same day (expiration 2026-06-26 -> dte ~35 > 0): no condor legs quote,
    # only an unrelated bar carrying the underlying price between the shorts.
    gap_ts = datetime(2026, 5, 22, 14, 0, tzinfo=eastern)
    quotes = [
        *_condor_snapshot(entry_ts, short_bid=1.20, short_ask=1.30, long_bid=0.50, long_ask=0.55),
        _bar(gap_ts, 500, "Put", 0.01, 0.02, underlying_price=585.0),
    ]

    result = run_intraday_iron_condor_backtest(
        quotes,
        IntradayIronCondorBacktestConfig(
            ticker="SPY",
            start=date(2026, 5, 22),
            end=date(2026, 5, 22),
            selector=IntradayIronCondorSelectorConfig(
                min_dte=30,
                max_dte=45,
                wing_width=5.0,
                target_short_bid=1.20,
                min_credit=0.05,
            ),
            entry_time="09:45:00",
            profit_target_pct=0.50,
            stop_loss_credit_multiple=2.0,
        ),
    )

    assert result.summary.opened_count == 1
    # No fabricated win: nothing closes as a profit target off the missing-leg gap.
    assert [trade for trade in result.trades if trade.exit_reason == "profit_target"] == []
    # The trade is honestly reported as unclosed rather than a max-profit win.
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "unclosed_missing_mark"
    assert trade.pnl is None


def test_intraday_iron_condor_backtest_does_not_open_without_complete_entry_snapshot():
    eastern = ZoneInfo("America/New_York")
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    quotes = [
        _bar(entry_ts, 560, "Put", 1.20, 1.30),
        _bar(entry_ts, 610, "Call", 1.20, 1.30),
        _bar(entry_ts, 615, "Call", 0.50, 0.55),
    ]

    result = run_intraday_iron_condor_backtest(
        quotes,
        IntradayIronCondorBacktestConfig(
            ticker="SPY",
            start=date(2026, 5, 22),
            end=date(2026, 5, 22),
            selector=IntradayIronCondorSelectorConfig(wing_width=5.0, target_short_bid=1.20),
            entry_time="09:45:00",
        ),
    )

    assert result.summary.opened_count == 0
    assert result.trades == []


def _priced_bar(
    timestamp: datetime,
    strike: float,
    call_put: str,
    *,
    spot: float,
    volatility: float,
    expiration: date = date(2026, 6, 26),
) -> OptionQuoteBar:
    years = (expiration - timestamp.date()).days / 365
    mid = black_scholes_price(
        option_type=call_put,
        spot=spot,
        strike=strike,
        years_to_expiration=years,
        volatility=volatility,
        risk_free_rate=0.04,
        dividend_yield=0.0,
    )
    return _bar(
        timestamp,
        strike,
        call_put,
        max(mid - 0.02, 0.01),
        mid + 0.02,
        expiration=expiration,
        underlying_price=spot,
    )


def test_intraday_iron_condor_backtest_can_select_by_estimated_target_delta():
    eastern = ZoneInfo("America/New_York")
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    exit_ts = datetime(2026, 5, 22, 10, 15, tzinfo=eastern)
    spot = 100.0
    volatility = 0.25
    entry_snapshot = [
        _priced_bar(entry_ts, 83, "Put", spot=spot, volatility=volatility),
        _priced_bar(entry_ts, 88, "Put", spot=spot, volatility=volatility),
        _priced_bar(entry_ts, 93, "Put", spot=spot, volatility=volatility),
        _priced_bar(entry_ts, 107, "Call", spot=spot, volatility=volatility),
        _priced_bar(entry_ts, 112, "Call", spot=spot, volatility=volatility),
        _priced_bar(entry_ts, 117, "Call", spot=spot, volatility=volatility),
    ]
    exit_snapshot = [
        _bar(exit_ts, 88, "Put", 0.05, 0.08, underlying_price=spot),
        _bar(exit_ts, 93, "Put", 0.20, 0.23, underlying_price=spot),
        _bar(exit_ts, 107, "Call", 0.05, 0.08, underlying_price=spot),
        _bar(exit_ts, 112, "Call", 0.01, 0.02, underlying_price=spot),
    ]

    result = run_intraday_iron_condor_backtest(
        [*entry_snapshot, *exit_snapshot],
        IntradayIronCondorBacktestConfig(
            ticker="SPY",
            start=date(2026, 5, 22),
            end=date(2026, 5, 22),
            selector=IntradayIronCondorSelectorConfig(
                min_dte=30,
                max_dte=45,
                wing_width=5.0,
                selection_mode="delta",
                target_delta=0.16,
                max_delta_deviation=0.08,
                risk_free_rate=0.04,
            ),
            entry_time="09:45:00",
            profit_target_pct=0.50,
        ),
    )

    assert result.summary.trade_count == 1
    trade = result.trades[0]
    assert trade.short_put_strike == 93
    assert trade.long_put_strike == 88
    assert trade.short_call_strike == 107
    assert trade.long_call_strike == 112
    assert trade.short_put_delta == pytest.approx(-0.16, abs=0.08)
    assert trade.short_call_delta == pytest.approx(0.16, abs=0.08)


def test_intraday_iron_condor_backtest_accepts_prebuilt_replay_data():
    eastern = ZoneInfo("America/New_York")
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    exit_ts = datetime(2026, 5, 22, 10, 15, tzinfo=eastern)
    quotes = [
        *_condor_snapshot(entry_ts, short_bid=1.20, short_ask=1.30, long_bid=0.50, long_ask=0.55),
        *_condor_snapshot(exit_ts, short_bid=0.60, short_ask=0.65, long_bid=0.35, long_ask=0.40),
    ]
    config = IntradayIronCondorBacktestConfig(
        ticker="SPY",
        start=date(2026, 5, 22),
        end=date(2026, 5, 22),
        selector=IntradayIronCondorSelectorConfig(
            min_dte=30,
            max_dte=45,
            wing_width=5.0,
            target_short_bid=1.20,
            min_credit=0.05,
        ),
        entry_time="09:45:00",
        profit_target_pct=0.50,
        stop_loss_credit_multiple=2.0,
    )

    list_result = run_intraday_iron_condor_backtest(quotes, config)
    replay_data = build_intraday_quote_replay_data(quotes, config)
    indexed_result = run_intraday_iron_condor_backtest(replay_data, config)

    assert indexed_result.summary == list_result.summary
    assert indexed_result.trades[0].entry_credit == list_result.trades[0].entry_credit
    assert indexed_result.trades[0].pnl == list_result.trades[0].pnl


def test_exit_decisions_are_causal_at_the_decision_timestamp():
    """Audit A3: exit decisions must only use information available at the
    decision timestamp.

    Tape: entry 09:45 (credit 1.30), a 2x-credit stop breach at 11:00 (debit
    2.90), full reversion by 15:55 (debit 0.60).

    * Every-minute cadence (exit_decision_time=""): the stop fills at the FIRST
      breach minute, at that minute's debit -- never at a later, better price.
    * Daily 15:55 cadence: the decision uses ONLY the 15:55 mark. The midday
      breach is not retroactively applied (documented no-intraday-risk-control
      semantics) and survives only as reporting-only max_adverse_pnl; equally,
      the day's range/best minute is never cherry-picked for the fill.
    """

    eastern = ZoneInfo("America/New_York")
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    breach_ts = datetime(2026, 5, 22, 11, 0, tzinfo=eastern)
    decision_ts = datetime(2026, 5, 22, 15, 55, tzinfo=eastern)
    quotes = [
        *_condor_snapshot(entry_ts, short_bid=1.20, short_ask=1.30, long_bid=0.50, long_ask=0.55),
        # Breach: close debit 1.55 + 1.55 - 0.10 - 0.10 = 2.90 >= 2x credit (2.60).
        *_condor_snapshot(breach_ts, short_bid=1.45, short_ask=1.55, long_bid=0.10, long_ask=0.15),
        # Benign close: debit 0.60 + 0.60 - 0.30 - 0.30 = 0.60 <= profit target (0.65).
        *_condor_snapshot(decision_ts, short_bid=0.55, short_ask=0.60, long_bid=0.30, long_ask=0.35),
    ]
    base_config = IntradayIronCondorBacktestConfig(
        ticker="SPY",
        start=date(2026, 5, 22),
        end=date(2026, 5, 22),
        selector=IntradayIronCondorSelectorConfig(
            min_dte=30,
            max_dte=45,
            wing_width=5.0,
            target_short_bid=1.20,
            min_credit=0.05,
        ),
        entry_time="09:45:00",
        profit_target_pct=0.50,
        stop_loss_credit_multiple=2.0,
        exit_decision_time="",
    )

    # Every-minute cadence: stop fills at the first breach, at the breach price.
    minute_result = run_intraday_iron_condor_backtest(quotes, base_config)
    assert minute_result.summary.trade_count == 1
    minute_trade = minute_result.trades[0]
    assert minute_trade.exit_reason == "stop_loss"
    assert minute_trade.exit_ts == breach_ts
    assert minute_trade.exit_debit == 2.90
    assert minute_trade.pnl == -160.0

    # Daily 15:55 cadence: only the 15:55 mark drives the decision; the midday
    # breach is not realized and shows up only as max_adverse_pnl.
    daily_result = run_intraday_iron_condor_backtest(quotes, replace(base_config, exit_decision_time="15:55:00"))
    assert daily_result.summary.trade_count == 1
    daily_trade = daily_result.trades[0]
    assert daily_trade.exit_reason == "profit_target"
    assert daily_trade.exit_ts == decision_ts
    assert daily_trade.exit_debit == 0.60
    assert daily_trade.pnl == 70.0
    assert daily_trade.max_adverse_pnl == -160.0


def test_intraday_iron_condor_backtest_warns_when_exit_decision_snapshot_is_missing(caplog):
    eastern = ZoneInfo("America/New_York")
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    last_ts = datetime(2026, 5, 22, 10, 15, tzinfo=eastern)
    quotes = [
        *_condor_snapshot(entry_ts, short_bid=1.20, short_ask=1.30, long_bid=0.50, long_ask=0.55),
        *_condor_snapshot(last_ts, short_bid=0.60, short_ask=0.65, long_bid=0.35, long_ask=0.40),
    ]
    config = IntradayIronCondorBacktestConfig(
        ticker="SPY",
        start=date(2026, 5, 22),
        end=date(2026, 5, 22),
        selector=IntradayIronCondorSelectorConfig(
            min_dte=30,
            max_dte=45,
            wing_width=5.0,
            target_short_bid=1.20,
            min_credit=0.05,
        ),
        entry_time="09:45:00",
        profit_target_pct=0.50,
        stop_loss_credit_multiple=2.0,
        exit_decision_time="15:55:00",
    )

    with caplog.at_level(logging.WARNING):
        run_intraday_iron_condor_backtest(quotes, config)

    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if "open position but no snapshot at/after exit_decision_time" in record.getMessage()
    ]
    assert len(warning_messages) == 1
    assert "1 trading day(s)" in warning_messages[0]

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        run_intraday_iron_condor_backtest(quotes, replace(config, exit_decision_time=""))

    assert not [
        record
        for record in caplog.records
        if "open position but no snapshot at/after exit_decision_time" in record.getMessage()
    ]
