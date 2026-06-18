from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from trader.options.iron_condor import (
    IronCondor,
    bounded_close_debit,
    condor_intrinsic_debit,
    mark_condor_close_debit,
)
from trader.options.models import OptionQuote, OptionQuoteBar

TRADE_DATE = date(2026, 5, 22)
EXPIRATION = date(2026, 6, 26)


def _quote(
    strike: float,
    call_put: str,
    bid: float | None = None,
    ask: float | None = None,
) -> OptionQuote:
    return OptionQuote(
        trade_date=TRADE_DATE,
        ticker="SPY",
        expiration=EXPIRATION,
        strike=strike,
        call_put=call_put,
        bid=bid,
        ask=ask,
        implied_vol=None,
        delta=None,
        gamma=None,
        theta=None,
        vega=None,
        rho=None,
    )


def _standard_condor() -> IronCondor:
    long_put = _quote(300, "Put")
    short_put = _quote(305, "Put")
    short_call = _quote(355, "Call")
    long_call = _quote(360, "Call")
    return IronCondor(
        ticker="SPY",
        trade_date=TRADE_DATE,
        expiration=EXPIRATION,
        short_put=short_put,
        long_put=long_put,
        short_call=short_call,
        long_call=long_call,
        entry_credit=1.00,
    )


def test_condor_intrinsic_debit_is_bounded_by_wing_width():
    condor = _standard_condor()

    assert condor_intrinsic_debit(condor, 330) == 0.0
    assert condor_intrinsic_debit(condor, 300) == 5.0
    assert condor_intrinsic_debit(condor, 290) == 5.0
    assert condor_intrinsic_debit(condor, 360) == 5.0


def test_bounded_close_debit_clamps_raw_quote_debit_above_wing():
    condor = _standard_condor()

    debit = bounded_close_debit(
        condor,
        short_put=_quote(305, "Put", bid=9.75, ask=9.85),
        long_put=_quote(300, "Put", bid=0.10, ask=0.15),
        short_call=_quote(355, "Call", bid=0.05, ask=0.10),
        long_call=_quote(360, "Call", bid=0.00, ask=0.05),
        underlying_price=300,
    )

    assert debit == 5.0


def test_bounded_close_debit_floors_stale_favorable_quote_to_intrinsic():
    condor = _standard_condor()

    debit = bounded_close_debit(
        condor,
        short_put=_quote(305, "Put", bid=0.01, ask=0.02),
        long_put=_quote(300, "Put", bid=0.00, ask=0.01),
        short_call=_quote(355, "Call", bid=0.01, ask=0.02),
        long_call=_quote(360, "Call", bid=0.02, ask=0.03),
        underlying_price=300,
    )

    assert debit == 5.0


def test_bounded_close_debit_settles_from_underlying_when_all_leg_quotes_missing():
    condor = _standard_condor()

    debit = bounded_close_debit(
        condor,
        short_put=None,
        long_put=None,
        short_call=None,
        long_call=None,
        underlying_price=300,
    )

    assert debit == 5.0


def test_bounded_close_debit_does_not_fabricate_otm_settlement_when_disallowed():
    """Regression: marking an OPEN condor (settle_missing_as_intrinsic=False),
    an OTM position whose four leg quotes are all missing must NOT settle to its
    zero intrinsic -- doing so books a fabricated max-profit win on a data gap.
    It returns None so the caller keeps the trade open."""
    condor = _standard_condor()  # shorts 305 / 355

    debit = bounded_close_debit(
        condor,
        short_put=None,
        long_put=None,
        short_call=None,
        long_call=None,
        underlying_price=330,  # between the shorts -> zero intrinsic
        settle_missing_as_intrinsic=False,
    )

    assert debit is None


def test_bounded_close_debit_default_settles_otm_to_zero_at_expiration():
    """The default (settle_missing_as_intrinsic=True) is the expiration-only
    settlement path: an OTM condor settles to zero intrinsic. This documents the
    trap -- the live-marking caller must disable it before expiry (dte > 0)."""
    condor = _standard_condor()

    debit = bounded_close_debit(
        condor,
        short_put=None,
        long_put=None,
        short_call=None,
        long_call=None,
        underlying_price=330,
    )

    assert debit == 0.0


def test_bounded_close_debit_returns_none_without_quotes_or_underlying():
    condor = _standard_condor()

    debit = bounded_close_debit(
        condor,
        short_put=None,
        long_put=None,
        short_call=None,
        long_call=None,
        underlying_price=None,
    )

    assert debit is None


def test_bounded_close_debit_keeps_normal_in_bounds_quote_debit():
    condor = _standard_condor()

    debit = bounded_close_debit(
        condor,
        short_put=_quote(305, "Put", bid=0.50, ask=0.60),
        long_put=_quote(300, "Put", bid=0.10, ask=0.15),
        short_call=_quote(355, "Call", bid=0.75, ask=0.80),
        long_call=_quote(360, "Call", bid=0.10, ask=0.15),
        underlying_price=330,
    )

    assert debit == pytest.approx(1.20)


# ── shared marking core (audit A2/B3) ──────────────────────────────────────────


def _normal_close_legs() -> dict[str, OptionQuote]:
    return {
        "short_put": _quote(305, "Put", bid=0.50, ask=0.60),
        "long_put": _quote(300, "Put", bid=0.10, ask=0.15),
        "short_call": _quote(355, "Call", bid=0.75, ask=0.80),
        "long_call": _quote(360, "Call", bid=0.10, ask=0.15),
    }


def test_mark_condor_close_debit_matches_bounded_close_debit_midlife():
    condor = _standard_condor()
    legs = _normal_close_legs()

    debit = mark_condor_close_debit(condor, underlying_price=330, dte=35, **legs)

    assert debit == pytest.approx(1.20)


def test_mark_condor_close_debit_adds_exit_slippage_per_leg_capped_at_wing():
    condor = _standard_condor()
    legs = _normal_close_legs()

    debit = mark_condor_close_debit(condor, underlying_price=330, dte=35, slippage_per_contract=0.02, **legs)
    assert debit == pytest.approx(1.28)  # 1.20 + 0.02 * 4 legs

    # A near-wing debit cannot be inflated past the wing: loss stays <= max_risk.
    deep = mark_condor_close_debit(
        condor,
        short_put=_quote(305, "Put", bid=4.90, ask=4.98),
        long_put=_quote(300, "Put", bid=0.02, ask=0.05),
        short_call=_quote(355, "Call", bid=0.01, ask=0.02),
        long_call=_quote(360, "Call", bid=0.00, ask=0.01),
        underlying_price=300,
        dte=35,
        slippage_per_contract=0.02,
    )
    assert deep == 5.0


def test_mark_condor_close_debit_refuses_intrinsic_settlement_midlife():
    condor = _standard_condor()

    debit = mark_condor_close_debit(
        condor,
        short_put=None,
        long_put=None,
        short_call=None,
        long_call=None,
        underlying_price=330,
        dte=35,
    )

    assert debit is None


def test_mark_condor_close_debit_settles_intrinsic_at_expiration():
    condor = _standard_condor()

    debit = mark_condor_close_debit(
        condor,
        short_put=None,
        long_put=None,
        short_call=None,
        long_call=None,
        underlying_price=303,
        dte=0,
    )

    assert debit == 2.0


# ── engine marking parity (audit A2/B3): EOD and intraday paths must price the
#    same condor close identically for identical inputs ─────────────────────────


def _eod_chain(trade_date: date, *, short_bid: float, short_ask: float, long_bid: float, long_ask: float, expiration: date):
    def quote(strike: float, call_put: str, delta: float, bid: float, ask: float) -> OptionQuote:
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

    return [
        quote(555, "Put", -0.10, long_bid, long_ask),
        quote(560, "Put", -0.16, short_bid, short_ask),
        quote(610, "Call", 0.16, short_bid, short_ask),
        quote(615, "Call", 0.10, long_bid, long_ask),
    ]


def _intraday_snapshot(ts: datetime, *, short_bid: float, short_ask: float, long_bid: float, long_ask: float, expiration: date):
    def bar(strike: float, call_put: str, bid: float, ask: float) -> OptionQuoteBar:
        return OptionQuoteBar(
            timestamp=ts,
            ticker="SPY",
            expiration=expiration,
            strike=strike,
            call_put=call_put,
            bid=bid,
            ask=ask,
            underlying_price=None,
            source="unit-test",
        )

    return [
        bar(555, "Put", long_bid, long_ask),
        bar(560, "Put", short_bid, short_ask),
        bar(610, "Call", short_bid, short_ask),
        bar(615, "Call", long_bid, long_ask),
    ]


@pytest.mark.parametrize(
    ("commission", "slippage"),
    [(0.0, 0.0), (0.65, 0.02)],
    ids=["frictionless", "realistic-friction"],
)
def test_eod_and_intraday_engines_produce_identical_marks_for_identical_inputs(commission: float, slippage: float):
    """Both engines route through mark_condor_close_debit; for the same condor,
    the same close prices, and the same friction they must report the same
    entry credit, exit debit, and net P&L."""

    from trader.options.backtest import IronCondorBacktestConfig, run_iron_condor_backtest
    from trader.options.intraday import (
        IntradayIronCondorBacktestConfig,
        IntradayIronCondorSelectorConfig,
        run_intraday_iron_condor_backtest,
    )
    from trader.options.iron_condor import IronCondorConfig

    d0 = date(2026, 5, 1)
    d1 = date(2026, 5, 2)
    expiration = date(2026, 6, 5)  # 35 DTE at entry
    entry = {"short_bid": 1.20, "short_ask": 1.30, "long_bid": 0.50, "long_ask": 0.55}
    close = {"short_bid": 0.60, "short_ask": 0.65, "long_bid": 0.35, "long_ask": 0.40}

    eod_result = run_iron_condor_backtest(
        [
            *_eod_chain(d0, expiration=expiration, **entry),
            *_eod_chain(d1, expiration=expiration, **close),
        ],
        IronCondorBacktestConfig(
            ticker="SPY",
            start=d0,
            end=d1,
            selector=IronCondorConfig(min_dte=30, max_dte=45, target_delta=0.16, wing_width=5.0),
            profit_target_pct=0.50,
            stop_loss_credit_multiple=2.0,
            commission_per_contract=commission,
            slippage_per_contract=slippage,
        ),
    )

    eastern = ZoneInfo("America/New_York")
    intraday_result = run_intraday_iron_condor_backtest(
        [
            *_intraday_snapshot(datetime(2026, 5, 1, 9, 45, tzinfo=eastern), expiration=expiration, **entry),
            *_intraday_snapshot(datetime(2026, 5, 2, 9, 45, tzinfo=eastern), expiration=expiration, **close),
        ],
        IntradayIronCondorBacktestConfig(
            ticker="SPY",
            start=d0,
            end=d1,
            selector=IntradayIronCondorSelectorConfig(min_dte=30, max_dte=45, wing_width=5.0, target_short_bid=1.20),
            entry_time="09:45:00",
            profit_target_pct=0.50,
            stop_loss_credit_multiple=2.0,
            commission_per_contract=commission,
            slippage_per_contract=slippage,
        ),
    )

    assert len(eod_result.trades) == 1
    assert len(intraday_result.trades) == 1
    eod_trade = eod_result.trades[0]
    intraday_trade = intraday_result.trades[0]
    assert eod_trade.entry_credit == intraday_trade.entry_credit
    assert eod_trade.exit_debit == intraday_trade.exit_debit
    assert eod_trade.pnl == intraday_trade.pnl
    assert eod_trade.exit_reason == intraday_trade.exit_reason
