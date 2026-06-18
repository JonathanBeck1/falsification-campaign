from __future__ import annotations

from datetime import date

from trader.options.iron_condor import IronCondorConfig, select_iron_condor
from trader.options.models import OptionQuote


def _quote(strike: float, call_put: str, delta: float, bid: float, ask: float) -> OptionQuote:
    return OptionQuote(
        trade_date=date(2026, 5, 22),
        ticker="SPY",
        expiration=date(2026, 6, 26),
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


def test_select_iron_condor_chooses_16_delta_shorts_and_5_dollar_wings():
    chain = [
        _quote(555, "Put", -0.10, 0.60, 0.70),
        _quote(560, "Put", -0.16, 1.20, 1.30),
        _quote(565, "Put", -0.25, 2.00, 2.15),
        _quote(605, "Call", 0.24, 2.10, 2.25),
        _quote(610, "Call", 0.16, 1.10, 1.20),
        _quote(615, "Call", 0.10, 0.55, 0.65),
    ]

    condor = select_iron_condor(chain, IronCondorConfig(wing_width=5.0, target_delta=0.16))

    assert condor is not None
    assert condor.short_put.strike == 560
    assert condor.long_put.strike == 555
    assert condor.short_call.strike == 610
    assert condor.long_call.strike == 615
    assert condor.entry_credit == 0.95
    assert condor.max_risk == 4.05
    assert condor.dte == 35


def test_select_iron_condor_rejects_chain_without_positive_executable_credit():
    chain = [
        _quote(555, "Put", -0.10, 0.95, 1.05),
        _quote(560, "Put", -0.16, 1.00, 1.10),
        _quote(610, "Call", 0.16, 1.00, 1.10),
        _quote(615, "Call", 0.10, 0.95, 1.05),
    ]

    assert select_iron_condor(chain, IronCondorConfig(wing_width=5.0, min_credit=0.1)) is None


def test_select_iron_condor_allows_nearest_wings_but_rejects_far_delta_contracts():
    chain = [
        _quote(685, "Put", -0.10, 2.60, 2.70),
        _quote(701, "Put", -0.153, 3.90, 4.00),
        _quote(900, "Put", -1.0, 152.0, 156.0),
        _quote(775, "Call", 0.20, 3.40, 3.50),
        _quote(790, "Call", 0.09, 1.20, 1.30),
        _quote(895, "Call", 0.002, 0.02, 0.04),
    ]

    condor = select_iron_condor(
        chain,
        IronCondorConfig(
            wing_width=5.0,
            max_wing_width=20.0,
            target_delta=0.16,
            max_delta_deviation=0.08,
            min_credit=0.1,
        ),
    )

    assert condor is not None
    assert condor.short_put.strike == 701
    assert condor.long_put.strike == 685
    assert condor.short_call.strike == 775
    assert condor.long_call.strike == 790
    assert condor.short_put.delta == -0.153
    assert condor.short_call.delta == 0.20
