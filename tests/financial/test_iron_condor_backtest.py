from __future__ import annotations

from datetime import date, timedelta

from trader.options.backtest import IronCondorBacktestConfig, run_iron_condor_backtest
from trader.options.models import OptionQuote


def _quote(
    trade_date: date,
    strike: float,
    call_put: str,
    delta: float,
    bid: float,
    ask: float,
    *,
    expiration: date,
) -> OptionQuote:
    return OptionQuote(
        trade_date=trade_date,
        ticker="SPY",
        expiration=expiration,
        strike=strike,
        call_put=call_put,
        bid=bid,
        ask=ask,
        implied_vol=0.18,
        delta=delta,
        gamma=None,
        theta=None,
        vega=None,
        rho=None,
    )


def _chain(
    trade_date: date,
    *,
    short_bid: float,
    short_ask: float,
    long_bid: float,
    long_ask: float,
    expiration: date,
):
    return [
        _quote(trade_date, 555, "Put", -0.10, long_bid, long_ask, expiration=expiration),
        _quote(trade_date, 560, "Put", -0.16, short_bid, short_ask, expiration=expiration),
        _quote(trade_date, 610, "Call", 0.16, short_bid, short_ask, expiration=expiration),
        _quote(trade_date, 615, "Call", 0.10, long_bid, long_ask, expiration=expiration),
    ]


def test_run_iron_condor_backtest_opens_and_exits_at_profit_target():
    d0 = date(2026, 5, 1)
    expiration = d0 + timedelta(days=35)
    quotes = [
        *_chain(d0, short_bid=1.20, short_ask=1.30, long_bid=0.50, long_ask=0.55, expiration=expiration),
        *_chain(
            d0 + timedelta(days=1),
            short_bid=0.60,
            short_ask=0.65,
            long_bid=0.35,
            long_ask=0.40,
            expiration=expiration,
        ),
    ]

    result = run_iron_condor_backtest(
        quotes,
        IronCondorBacktestConfig(
            ticker="SPY",
            start=d0,
            end=d0 + timedelta(days=1),
            profit_target_pct=0.50,
            stop_loss_credit_multiple=2.0,
            max_concurrent_trades=1,
        ),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_date == d0
    assert trade.exit_date == d0 + timedelta(days=1)
    assert trade.exit_reason == "profit_target"
    assert trade.entry_credit == 1.3
    assert trade.exit_debit == 0.6
    assert trade.pnl == 70.0
    assert result.summary.trade_count == 1
    assert result.summary.opened_count == 1
    assert result.summary.closed_count == 1
    assert result.summary.unclosed_count == 0
    assert result.summary.win_rate == 1.0
    assert result.summary.total_pnl == 70.0


def test_run_iron_condor_backtest_caps_stale_quote_debit_at_wing():
    """Audit A2: a stale/deep-ITM mark can never cost more than the wing, so the
    loss can never exceed max_risk (here entry 1.30, wing 5 -> pnl floor -370)."""

    d0 = date(2026, 5, 1)
    d1 = d0 + timedelta(days=1)
    expiration = d0 + timedelta(days=35)
    quotes = [
        *_chain(d0, short_bid=1.20, short_ask=1.30, long_bid=0.50, long_ask=0.55, expiration=expiration),
        # Stale wing quotes: raw close debit 9.85 + 0.10 - 0.10 - 0.00 = 9.85 > wing 5.
        _quote(d1, 560, "Put", -0.90, 9.75, 9.85, expiration=expiration),
        _quote(d1, 555, "Put", -0.85, 0.10, 0.15, expiration=expiration),
        _quote(d1, 610, "Call", 0.01, 0.05, 0.10, expiration=expiration),
        _quote(d1, 615, "Call", 0.01, 0.00, 0.05, expiration=expiration),
    ]

    result = run_iron_condor_backtest(
        quotes,
        IronCondorBacktestConfig(ticker="SPY", start=d0, end=d1),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_debit == 5.0
    assert trade.exit_reason == "stop_loss"
    assert trade.pnl == -370.0  # exactly -max_risk * multiplier
    assert trade.pnl == -trade.max_risk * 100


def test_run_iron_condor_backtest_floors_stale_favorable_quotes_to_intrinsic():
    """Audit A2: a breach hidden behind stale near-zero quotes must be realized
    when the underlying close says the spread is in the money."""

    d0 = date(2026, 5, 1)
    d1 = d0 + timedelta(days=1)
    expiration = d0 + timedelta(days=35)
    quotes = [
        *_chain(d0, short_bid=1.20, short_ask=1.30, long_bid=0.50, long_ask=0.55, expiration=expiration),
        # Stale, absurdly favorable quotes despite the underlying crashing to 540.
        *_chain(d1, short_bid=0.01, short_ask=0.02, long_bid=0.00, long_ask=0.01, expiration=expiration),
    ]
    config = IronCondorBacktestConfig(ticker="SPY", start=d0, end=d1)

    # Without an underlying close the stale quotes book a fake profit-target win.
    blind = run_iron_condor_backtest(quotes, config)
    assert blind.trades[0].exit_reason == "profit_target"

    # With the underlying close the intrinsic floor realizes the breach.
    floored = run_iron_condor_backtest(quotes, config, underlying_closes={d1: 540.0})
    trade = floored.trades[0]
    assert trade.exit_debit == 5.0  # put spread 560/555 fully in the money
    assert trade.exit_reason == "stop_loss"
    assert trade.pnl == -370.0


def test_run_iron_condor_backtest_settles_intrinsic_from_underlying_at_expiration():
    """Audit A2: at expiration (dte <= 0) missing leg quotes settle to intrinsic
    from the underlying close instead of leaving the trade unclosed."""

    d0 = date(2026, 5, 1)
    expiration = d0 + timedelta(days=35)
    quotes = [
        *_chain(d0, short_bid=1.20, short_ask=1.30, long_bid=0.50, long_ask=0.55, expiration=expiration),
        # On expiration day the condor legs no longer quote; only an unrelated row.
        _quote(expiration, 600, "Call", 0.50, 1.0, 1.1, expiration=expiration + timedelta(days=30)),
    ]

    result = run_iron_condor_backtest(
        quotes,
        IronCondorBacktestConfig(ticker="SPY", start=d0, end=expiration),
        underlying_closes={expiration: 558.0},  # short put 560 is $2 ITM
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "expiration"
    assert trade.exit_debit == 2.0
    assert trade.pnl == -70.0  # (1.30 - 2.00) * 100


def test_run_iron_condor_backtest_deducts_commission_and_slippage():
    """Audit A2: the EOD path now carries the same friction model as intraday --
    round-trip commission on 8 contract-sides plus slippage on 4 legs at entry
    and exit (exit-side slippage baked into the mark debit)."""

    d0 = date(2026, 5, 1)
    d1 = d0 + timedelta(days=1)
    expiration = d0 + timedelta(days=35)
    quotes = [
        *_chain(d0, short_bid=1.20, short_ask=1.30, long_bid=0.50, long_ask=0.55, expiration=expiration),
        *_chain(d1, short_bid=0.60, short_ask=0.65, long_bid=0.35, long_ask=0.40, expiration=expiration),
    ]

    result = run_iron_condor_backtest(
        quotes,
        IronCondorBacktestConfig(
            ticker="SPY",
            start=d0,
            end=d1,
            commission_per_contract=0.65,
            slippage_per_contract=0.02,
        ),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    # Exit-side slippage inflates the 0.60 quote debit to 0.68, pushing it past
    # the 0.65 profit-target threshold: the thin winner no longer exits early.
    assert trade.exit_debit == 0.68
    assert trade.exit_reason == "final_mark"
    # (1.30 - 0.68) * 100 - commission 0.65*4*2 - entry slippage 0.02*4*100
    assert trade.pnl == 48.8


def test_run_iron_condor_backtest_counts_unclosed_trades_when_marks_are_missing():
    d0 = date(2026, 5, 1)
    expiration = d0 + timedelta(days=35)
    quotes = [
        *_chain(d0, short_bid=1.20, short_ask=1.30, long_bid=0.50, long_ask=0.55, expiration=expiration),
        # Next day has no matching contracts, mirroring the DoltHub coverage gap we observed.
        _quote(d0 + timedelta(days=1), 600, "Call", 0.16, 1.0, 1.1, expiration=expiration),
    ]

    result = run_iron_condor_backtest(
        quotes,
        IronCondorBacktestConfig(ticker="SPY", start=d0, end=d0 + timedelta(days=1)),
    )

    assert result.summary.opened_count == 1
    assert result.summary.closed_count == 0
    assert result.summary.unclosed_count == 1
    assert result.trades[0].exit_reason == "unclosed_missing_mark"
