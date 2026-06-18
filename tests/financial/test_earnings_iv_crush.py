"""Network-free unit tests for T23 single-name earnings IV crush.

Every test builds synthetic in-memory option chains and asserts the pure core
(parity spot, ATM selection, honest bid/ask straddle P&L, tail report, gate).
No disk, no network.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from trader.catalysts.earnings_iv_crush import (
    COMMISSION_PER_STRADDLE,
    CONTRACT_MULTIPLIER,
    CohortStats,
    CrushEvent,
    aggregate,
    atm_strike,
    compute_crush_event,
    evaluate_gate,
    is_amc,
    mean,
    parity_spot,
    pearson,
    select_front_expiration,
    straddle_quote,
    t_stat_one_sample,
    tail_report,
    welch_t,
)


# --------------------------------------------------------------------------- #
# synthetic chain builders
# --------------------------------------------------------------------------- #
def _chain(
    trade_date: str,
    expiration: str,
    rows: list[tuple[float, str, float, float]],
    ticker: str = "TST",
) -> pd.DataFrame:
    """rows = [(strike, right, bid, ask), ...]."""

    return pd.DataFrame(
        {
            "trade_date": [pd.Timestamp(trade_date)] * len(rows),
            "root": [ticker] * len(rows),
            "expiration": [pd.Timestamp(expiration)] * len(rows),
            "strike": [r[0] for r in rows],
            "right": [r[1] for r in rows],
            "bid": [r[2] for r in rows],
            "ask": [r[3] for r in rows],
        }
    )


def _symmetric_chain(
    trade_date: str,
    expiration: str,
    spot: float,
    strikes: list[float],
    straddle_at_spot: float,
    spread: float = 0.10,
) -> pd.DataFrame:
    """A clean chain where call-put = spot-strike (parity) and the ATM straddle
    mid equals ``straddle_at_spot``. Intrinsic + a symmetric time value bump."""

    rows: list[tuple[float, str, float, float]] = []
    half_tv = straddle_at_spot / 2.0  # time value split evenly call/put at ATM
    for k in strikes:
        # time value decays with |k - spot| (toy), floored at 0.05
        tv = max(half_tv - 0.02 * abs(k - spot), 0.05)
        call_mid = max(spot - k, 0.0) + tv
        put_mid = max(k - spot, 0.0) + tv
        rows.append((k, "C", call_mid - spread / 2, call_mid + spread / 2))
        rows.append((k, "P", put_mid - spread / 2, put_mid + spread / 2))
    return _chain(trade_date, expiration, rows)


# --------------------------------------------------------------------------- #
# tiny stats
# --------------------------------------------------------------------------- #
def test_mean_and_t_stat_basic():
    assert mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)
    # constant series -> zero std -> t defined as 0
    assert t_stat_one_sample([0.05, 0.05, 0.05]) == 0.0
    # one obs -> 0
    assert t_stat_one_sample([0.1]) == 0.0


def test_welch_t_sign():
    a = [0.1, 0.12, 0.11, 0.09]
    b = [0.0, 0.01, -0.01, 0.0]
    assert welch_t(a, b) > 0  # a's mean clearly exceeds b's
    assert welch_t(b, a) < 0


def test_pearson_perfect_and_degenerate():
    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert pearson([1, 1, 1], [1, 2, 3]) != pearson([1, 1, 1], [1, 2, 3])  # NaN


def test_is_amc_rules():
    assert is_amc(None) is True  # missing -> AMC
    assert is_amc(16) is True
    assert is_amc(13) is True
    assert is_amc(9) is False
    assert is_amc(12) is False


# --------------------------------------------------------------------------- #
# parity spot — the provenance-clean anchor (the data-wall fix)
# --------------------------------------------------------------------------- #
def test_parity_spot_recovers_true_spot():
    # spot 326.44: parity must recover it from the chain, NOT any external series.
    chain = _symmetric_chain(
        "2023-01-18", "2023-01-20", spot=326.44, strikes=[320, 325, 327.5, 330, 335],
        straddle_at_spot=30.0,
    )
    assert parity_spot(chain) == pytest.approx(326.44, abs=0.5)


def test_parity_spot_ignores_one_sided_quotes():
    # A strike with a zero bid (one-sided) must not break the anchor.
    rows = [
        (100.0, "C", 0.0, 0.5),  # one-sided call -> dropped
        (100.0, "P", 0.0, 0.5),  # one-sided put -> dropped
        (110.0, "C", 4.0, 4.2),
        (110.0, "P", 4.0, 4.2),  # C-P=0 at K=110 -> spot ~110
    ]
    chain = _chain("2023-01-18", "2023-01-20", rows)
    assert parity_spot(chain) == pytest.approx(110.0, abs=0.2)


def test_parity_spot_nan_without_pairs():
    rows = [(100.0, "C", 4.0, 4.2), (105.0, "C", 2.0, 2.2)]  # no puts
    chain = _chain("2023-01-18", "2023-01-20", rows)
    assert parity_spot(chain) != parity_spot(chain)  # NaN


# --------------------------------------------------------------------------- #
# expiration + ATM selection
# --------------------------------------------------------------------------- #
def test_select_front_expiration_skips_too_near():
    rows = [(100.0, "C", 1.0, 1.1), (100.0, "P", 1.0, 1.1)]
    # two expirations: 2d away (too near) and 9d away (ok)
    near = _chain("2023-01-18", "2023-01-20", rows)
    far = _chain("2023-01-18", "2023-01-27", rows)
    chain = pd.concat([near, far], ignore_index=True)
    chosen = select_front_expiration(chain, date(2023, 1, 18), min_days=5)
    assert chosen == pd.Timestamp("2023-01-27")


def test_select_front_expiration_none_when_all_too_near():
    rows = [(100.0, "C", 1.0, 1.1), (100.0, "P", 1.0, 1.1)]
    chain = _chain("2023-01-18", "2023-01-20", rows)  # only 2 days
    assert select_front_expiration(chain, date(2023, 1, 18), min_days=5) is None


def test_atm_strike_nearest_with_both_legs():
    chain = _symmetric_chain(
        "2023-01-18", "2023-01-27", spot=103.0, strikes=[95, 100, 105, 110],
        straddle_at_spot=8.0,
    )
    # spot 103 -> nearest strike with both legs is 105
    assert atm_strike(chain, 103.0) == 105.0


def test_atm_strike_requires_both_legs():
    rows = [
        (100.0, "C", 5.0, 5.2),  # call only at 100 (nearest to spot)
        (105.0, "C", 2.0, 2.2),
        (105.0, "P", 2.0, 2.2),  # both legs only at 105
    ]
    chain = _chain("2023-01-18", "2023-01-27", rows)
    assert atm_strike(chain, 100.5) == 105.0  # 100 skipped (no put)


# --------------------------------------------------------------------------- #
# straddle quote — honest bid/ask crossing
# --------------------------------------------------------------------------- #
def test_straddle_quote_legs_and_fills():
    rows = [(100.0, "C", 3.0, 3.4), (100.0, "P", 2.0, 2.4)]
    chain = _chain("2023-01-18", "2023-01-27", rows)
    q = straddle_quote(chain, 100.0, 100.0, pd.Timestamp("2023-01-27"))
    assert q is not None
    assert q.sell_proceeds == pytest.approx(3.0 + 2.0)  # sell to the bid
    assert q.buy_cost == pytest.approx(3.4 + 2.4)  # buy at the ask
    assert q.mid == pytest.approx((3.0 + 3.4 + 2.0 + 2.4) / 2.0)
    assert q.priced_move == pytest.approx(q.mid / 100.0)


def test_straddle_quote_none_if_leg_missing():
    rows = [(100.0, "C", 3.0, 3.4)]  # no put
    chain = _chain("2023-01-18", "2023-01-27", rows)
    assert straddle_quote(chain, 100.0, 100.0, pd.Timestamp("2023-01-27")) is None


# --------------------------------------------------------------------------- #
# the headline: a full crush event's after-cost P&L
# --------------------------------------------------------------------------- #
def test_crush_event_small_move_is_a_win():
    """IV overstated the move: priced 8%, realized ~0% -> short straddle wins."""

    entry = _symmetric_chain(
        "2023-01-18", "2023-01-27", spot=100.0, strikes=[90, 95, 100, 105, 110],
        straddle_at_spot=8.0, spread=0.10,
    )
    # next session: spot barely moved, IV crushed -> straddle worth ~1.0
    exit_ = _symmetric_chain(
        "2023-01-19", "2023-01-27", spot=100.5, strikes=[90, 95, 100, 105, 110],
        straddle_at_spot=1.0, spread=0.10,
    )
    ev = compute_crush_event(
        ticker="TST", earnings_date=date(2023, 1, 18),
        entry_chain=entry, exit_chain=exit_,
        entry_date=date(2023, 1, 18), exit_date=date(2023, 1, 19),
    )
    assert ev is not None
    assert ev.strike == 100.0
    assert ev.after_cost_return > 0  # crush win
    assert ev.realized_move == pytest.approx(0.005, abs=0.001)
    assert ev.priced_move > ev.realized_move  # IV overstated the move
    assert ev.crush_gap > 0


def test_crush_event_big_gap_is_a_blowup():
    """A huge earnings gap: realized move >> priced -> catastrophic short loss."""

    entry = _symmetric_chain(
        "2023-01-18", "2023-01-27", spot=100.0, strikes=[80, 90, 100, 110, 120],
        straddle_at_spot=8.0, spread=0.10,
    )
    # -25% gap; the short put is now deep ITM and expensive to buy back.
    exit_ = _symmetric_chain(
        "2023-01-19", "2023-01-27", spot=75.0, strikes=[80, 90, 100, 110, 120],
        straddle_at_spot=2.0, spread=0.10,
    )
    ev = compute_crush_event(
        ticker="TST", earnings_date=date(2023, 1, 18),
        entry_chain=entry, exit_chain=exit_,
        entry_date=date(2023, 1, 18), exit_date=date(2023, 1, 19),
    )
    assert ev is not None
    assert ev.after_cost_return < 0  # blew up
    assert ev.realized_move == pytest.approx(0.25, abs=0.001)
    assert ev.crush_gap < 0  # realized exceeded priced


def test_crush_event_commission_reduces_return():
    entry = _symmetric_chain(
        "2023-01-18", "2023-01-27", spot=100.0, strikes=[95, 100, 105],
        straddle_at_spot=6.0,
    )
    exit_ = _symmetric_chain(
        "2023-01-19", "2023-01-27", spot=100.0, strikes=[95, 100, 105],
        straddle_at_spot=2.0,
    )
    ev = compute_crush_event(
        ticker="TST", earnings_date=date(2023, 1, 18),
        entry_chain=entry, exit_chain=exit_,
        entry_date=date(2023, 1, 18), exit_date=date(2023, 1, 19),
        commission_per_straddle=0.0,
    )
    ev_cost = compute_crush_event(
        ticker="TST", earnings_date=date(2023, 1, 18),
        entry_chain=entry, exit_chain=exit_,
        entry_date=date(2023, 1, 18), exit_date=date(2023, 1, 19),
        commission_per_straddle=COMMISSION_PER_STRADDLE,
    )
    assert ev is not None and ev_cost is not None
    expected_gap = COMMISSION_PER_STRADDLE / (ev.pre_spot * CONTRACT_MULTIPLIER)
    assert ev.after_cost_return - ev_cost.after_cost_return == pytest.approx(
        expected_gap, abs=1e-9
    )


def test_crush_event_bid_ask_crossing_costs_money_when_flat():
    """If spot and straddle value are unchanged, the bid/ask round trip alone is
    a loss (you sell the bid, buy the ask) — proves we cross the spread."""

    entry = _symmetric_chain(
        "2023-01-18", "2023-01-27", spot=100.0, strikes=[95, 100, 105],
        straddle_at_spot=5.0, spread=0.40,
    )
    exit_ = _symmetric_chain(
        "2023-01-19", "2023-01-27", spot=100.0, strikes=[95, 100, 105],
        straddle_at_spot=5.0, spread=0.40,  # identical mids
    )
    ev = compute_crush_event(
        ticker="TST", earnings_date=date(2023, 1, 18),
        entry_chain=entry, exit_chain=exit_,
        entry_date=date(2023, 1, 18), exit_date=date(2023, 1, 19),
        commission_per_straddle=0.0,
    )
    assert ev is not None
    # mid-to-mid is exactly 0, but bid/ask-crossed return is negative by the spread.
    assert ev.mid_to_mid_return == pytest.approx(0.0, abs=1e-9)
    assert ev.after_cost_return < 0


def test_crush_event_none_when_expiration_missing_at_exit():
    entry = _symmetric_chain(
        "2023-01-18", "2023-01-27", spot=100.0, strikes=[95, 100, 105],
        straddle_at_spot=5.0,
    )
    exit_ = _symmetric_chain(
        "2023-01-19", "2023-02-17", spot=100.0, strikes=[95, 100, 105],  # diff exp
        straddle_at_spot=5.0,
    )
    ev = compute_crush_event(
        ticker="TST", earnings_date=date(2023, 1, 18),
        entry_chain=entry, exit_chain=exit_,
        entry_date=date(2023, 1, 18), exit_date=date(2023, 1, 19),
    )
    assert ev is None


# --------------------------------------------------------------------------- #
# aggregate + tail report
# --------------------------------------------------------------------------- #
def _ev(ticker: str, d: date, ret: float) -> CrushEvent:
    return CrushEvent(
        ticker=ticker, earnings_date=d, entry_date=d, exit_date=d,
        expiration=pd.Timestamp("2023-01-27"), strike=100.0,
        pre_spot=100.0, post_spot=100.0, priced_move=0.08, realized_move=0.01,
        entry_proceeds=8.0, exit_cost=1.0, after_cost_return=ret,
        mid_to_mid_return=ret,
    )


def test_aggregate_stats():
    s = aggregate([0.02, 0.03, -0.01, 0.04], label="earn")
    assert isinstance(s, CohortStats)
    assert s.n == 4
    assert s.mean == pytest.approx(0.02)
    assert s.win_rate == pytest.approx(0.75)


def test_tail_report_deaths_dominate_flag():
    # many small wins, swamped by a few huge losses -> negative full mean,
    # positive mean-ex-worst-5 => deaths dominate.
    wins = [_ev("A", date(2023, 1, i + 1), 0.01) for i in range(20)]
    deaths = [_ev("NFLX", date(2022, 4, 19), -0.40) for _ in range(5)]
    events = wins + deaths
    tr = tail_report(events)
    assert tr.worst_return == pytest.approx(-0.40)
    assert tr.n_losses == 5
    assert tr.mean_ex_worst5 == pytest.approx(0.01)
    full_mean = mean([e.after_cost_return for e in events])
    assert full_mean < 0
    assert tr.deaths_dominate is True


def test_tail_report_healthy_when_no_dominating_deaths():
    events = [_ev("A", date(2023, 1, i + 1), 0.02) for i in range(20)]
    tr = tail_report(events)
    assert tr.deaths_dominate is False  # full mean already positive
    assert tr.n_losses == 0


def test_tail_report_empty():
    tr = tail_report([])
    assert tr.n_losses == 0
    assert tr.deaths_dominate is False


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #
def test_gate_all_pass():
    g = evaluate_gate(
        n_events=120, after_cost_mean=0.01, after_cost_t=3.5,
        is_mean=0.011, is_n=60, oos_mean=0.009, oos_n=60,
        placebo_mean=0.001, earnings_minus_placebo_t=2.6,
    )
    assert g.passed is True
    assert all("PASS" in r for r in g.reasons)


def test_gate_fails_on_low_n():
    g = evaluate_gate(
        n_events=20, after_cost_mean=0.01, after_cost_t=3.0,
        is_mean=0.01, is_n=10, oos_mean=0.01, oos_n=10,
        placebo_mean=0.0, earnings_minus_placebo_t=3.0,
    )
    assert g.passed is False
    assert any("N=20" in r and "FAIL" in r for r in g.reasons)


def test_gate_fails_on_oos_sign_flip():
    g = evaluate_gate(
        n_events=100, after_cost_mean=0.005, after_cost_t=2.2,
        is_mean=0.02, is_n=50, oos_mean=-0.01, oos_n=50,  # sign flip
        placebo_mean=0.0, earnings_minus_placebo_t=3.0,
    )
    assert g.passed is False
    assert any("OOS sign stability" in r and "FAIL" in r for r in g.reasons)


def test_gate_fails_when_placebo_absorbs():
    g = evaluate_gate(
        n_events=100, after_cost_mean=0.01, after_cost_t=3.0,
        is_mean=0.01, is_n=50, oos_mean=0.01, oos_n=50,
        placebo_mean=0.009, earnings_minus_placebo_t=0.5,  # earnings ~ placebo
    )
    assert g.passed is False
    assert any("placebo" in r and "FAIL" in r for r in g.reasons)


def test_gate_fails_on_negative_mean():
    g = evaluate_gate(
        n_events=100, after_cost_mean=-0.004, after_cost_t=-2.3,
        is_mean=-0.004, is_n=50, oos_mean=-0.004, oos_n=50,
        placebo_mean=0.0, earnings_minus_placebo_t=-1.0,
    )
    assert g.passed is False
    assert any("after-cost short-straddle mean" in r and "FAIL" in r for r in g.reasons)
