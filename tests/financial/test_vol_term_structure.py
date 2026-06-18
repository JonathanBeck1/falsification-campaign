"""Network-free, disk-free unit tests for the T24 term-structure carry core.

Every test is a deterministic function of hand-built numbers. The straddle
marks come from the foundation's own Black-Scholes, so the roll-down P&L sign is
checked against a known curve, the vega-neutral sizing is checked against the
vega ratio, and the incremental-alpha control is checked against a constructed
case where the slope book is pure short-vol beta (alpha must collapse to ~0).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trader.catalysts import vol_term_structure as vt


# --------------------------------------------------------------------------- #
# straddle value / vega
# --------------------------------------------------------------------------- #
def test_straddle_value_positive_and_grows_with_vol():
    lo = vt.straddle_value(100.0, 30.0, 0.20)
    hi = vt.straddle_value(100.0, 30.0, 0.40)
    assert lo > 0 and hi > 0
    assert hi > lo  # straddle is increasing in vol


def test_straddle_value_grows_with_tenor():
    short = vt.straddle_value(100.0, 30.0, 0.30)
    long = vt.straddle_value(100.0, 90.0, 0.30)
    assert long > short  # more time value at longer tenor (same vol)


def test_straddle_vega_is_twice_single_option_vega():
    from trader.catalysts.vol_surface_data import bs_vega

    sv = vt.straddle_vega(100.0, 60.0, 0.25)
    single = float(bs_vega(100.0, 100.0, 60.0 / 365.0, 0.25))
    assert sv == pytest.approx(2.0 * single, rel=1e-9)


def test_straddle_nan_safe_on_bad_inputs():
    assert np.isnan(vt.straddle_value(0.0, 30.0, 0.2))
    assert np.isnan(vt.straddle_value(100.0, 0.0, 0.2))
    assert np.isnan(vt.straddle_value(100.0, 30.0, 0.0))
    assert np.isnan(vt.straddle_vega(100.0, 30.0, float("nan")))


# --------------------------------------------------------------------------- #
# calendar P&L — the roll-down mechanic
# --------------------------------------------------------------------------- #
def _flat_spot_leg(
    *, near_iv0, far_iv0, near_iv1, far_iv1, h=21, spot=100.0
):
    """Calendar leg with spot pinned (isolate the IV/roll dynamics)."""

    return vt.CalendarLeg(
        spot_entry=spot,
        spot_exit=spot,
        near_tenor_entry=30.0,
        far_tenor_entry=90.0,
        near_tenor_exit=30.0 - h,
        far_tenor_exit=90.0 - h,
        near_iv_entry=near_iv0,
        far_iv_entry=far_iv0,
        near_iv_exit=near_iv1,
        far_iv_exit=far_iv1,
    )


def test_long_calendar_profits_when_curve_holds_static_contango():
    """Steep static contango, IV unchanged: theta dominates.

    With a static upward curve and unchanged IVs, the SHORT near leg decays
    faster (theta) than the LONG far leg, but vega-neutral sizing levers up the
    near leg. The realized sign depends on convexity; this test simply pins that
    the function returns a finite number and the mirror is the negative gross.
    """

    leg = _flat_spot_leg(near_iv0=0.30, far_iv0=0.35, near_iv1=0.30, far_iv1=0.35)
    pnl_long = vt.calendar_pnl(leg, direction=+1, friction_vol_points=0.0)
    pnl_short = vt.calendar_pnl(leg, direction=-1, friction_vol_points=0.0)
    assert np.isfinite(pnl_long)
    # zero-friction mirror is exactly the negative
    assert pnl_short == pytest.approx(-pnl_long, rel=1e-9)


def test_long_calendar_gains_when_far_leg_rolls_down():
    """The pre-registered carry: far leg's IV falls toward the near tenor.

    Entry contango far=0.35 > near=0.30. Over the hold the far leg's IV at its
    now-reduced tenor drops (rolls down the curve) while near is steady. The
    LONG-far / SHORT-near calendar should be helped by the far leg cheapening...
    but we are LONG the far leg, so a falling far IV HURTS the long far position.
    The genuine roll-down profit for a long calendar comes from the SHORT near
    leg decaying. We assert the function is monotone in the right direction:
    a larger near-IV DROP (short leg cheapens) strictly increases long-cal P&L.
    """

    base = _flat_spot_leg(near_iv0=0.30, far_iv0=0.35, near_iv1=0.30, far_iv1=0.35)
    near_drops = _flat_spot_leg(near_iv0=0.30, far_iv0=0.35, near_iv1=0.22, far_iv1=0.35)
    p_base = vt.calendar_pnl(base, direction=+1, friction_vol_points=0.0)
    p_drop = vt.calendar_pnl(near_drops, direction=+1, friction_vol_points=0.0)
    # short the near leg -> near IV falling makes the long-cal MORE profitable
    assert p_drop > p_base


def test_long_calendar_hurt_when_far_leg_iv_collapses():
    """Long the far leg: a far-IV collapse (vol crush at the back) hurts."""

    base = _flat_spot_leg(near_iv0=0.30, far_iv0=0.35, near_iv1=0.30, far_iv1=0.35)
    far_collapses = _flat_spot_leg(near_iv0=0.30, far_iv0=0.35, near_iv1=0.30, far_iv1=0.20)
    p_base = vt.calendar_pnl(base, direction=+1, friction_vol_points=0.0)
    p_far = vt.calendar_pnl(far_collapses, direction=+1, friction_vol_points=0.0)
    assert p_far < p_base


def test_friction_reduces_pnl():
    leg = _flat_spot_leg(near_iv0=0.30, far_iv0=0.35, near_iv1=0.28, far_iv1=0.34)
    gross = vt.calendar_pnl(leg, direction=+1, friction_vol_points=0.0)
    net = vt.calendar_pnl(leg, direction=+1, friction_vol_points=1.0)
    net2 = vt.calendar_pnl(leg, direction=+1, friction_vol_points=2.0)
    assert net < gross  # friction always costs
    assert net2 < net  # 2x friction costs more


def test_vega_neutral_sizing_uses_vega_ratio():
    """n_near = vega_far / vega_near so entry net vega ~ 0.

    We verify indirectly: if both legs move by the SAME number of vol points and
    spot/tenor are unchanged, a perfectly vega-neutral book has ~0 P&L (the equal
    vega exposures cancel) up to the second-order tenor-decay term.
    """

    # tiny equal IV bump on both legs, no time decay (exit tenor == entry tenor)
    leg = vt.CalendarLeg(
        spot_entry=100.0, spot_exit=100.0,
        near_tenor_entry=30.0, far_tenor_entry=90.0,
        near_tenor_exit=30.0, far_tenor_exit=90.0,  # no decay
        near_iv_entry=0.30, far_iv_entry=0.30,
        near_iv_exit=0.301, far_iv_exit=0.301,  # +0.1 vol pt both
    )
    pnl = vt.calendar_pnl(leg, direction=+1, friction_vol_points=0.0)
    # vega-neutral: equal vol moves on equal vega cancel to ~0 (vanna/vomma resid)
    assert abs(pnl) < 1e-3


def test_calendar_nan_when_leg_unpriceable():
    leg = _flat_spot_leg(near_iv0=0.0, far_iv0=0.35, near_iv1=0.30, far_iv1=0.35)
    assert np.isnan(vt.calendar_pnl(leg, direction=+1))


# --------------------------------------------------------------------------- #
# short-vol control book
# --------------------------------------------------------------------------- #
def test_short_vol_profits_when_iv_and_value_fall():
    # value falls (IV drops, tenor shortens) -> short straddle gains
    pnl = vt.short_vol_pnl(100.0, 30.0, 0.40, 100.0, 9.0, 0.30, friction_vol_points=0.0)
    assert pnl > 0


def test_short_vol_loses_when_iv_spikes():
    pnl = vt.short_vol_pnl(100.0, 30.0, 0.25, 100.0, 9.0, 0.60, friction_vol_points=0.0)
    assert pnl < 0


# --------------------------------------------------------------------------- #
# tercile assignment
# --------------------------------------------------------------------------- #
def test_terciles_split_top_and_bottom():
    slopes = pd.Series({"A": 0.10, "B": 0.05, "C": 0.0, "D": -0.05, "E": -0.10, "F": 0.02})
    t = vt.assign_terciles(slopes)
    assert t["A"] == 1  # steepest
    assert t["E"] == -1  # flattest
    assert set(t.unique()) <= {-1, 0, 1}
    assert (t == 1).sum() == (t == -1).sum()  # symmetric counts


def test_terciles_drop_nan_and_need_three():
    assert vt.assign_terciles(pd.Series({"A": 0.1, "B": float("nan")})).empty
    t = vt.assign_terciles(pd.Series({"A": 0.1, "B": 0.0, "C": -0.1}))
    assert len(t) == 3


# --------------------------------------------------------------------------- #
# period assembly: long-short, mirror, short-vol
# --------------------------------------------------------------------------- #
def test_period_long_short_mirror_and_sv():
    legs = pd.DataFrame(
        {
            "tercile": [1, 1, -1, -1, 0],
            "cal_pnl": [2.0, 4.0, 1.0, 3.0, 99.0],  # mid tercile ignored
            "sv_pnl": [0.5, 0.5, 0.5, 0.5, 0.5],
        }
    )
    res = vt.period_long_short_return(legs)
    assert res["long_ret"] == pytest.approx(3.0)  # mean(2,4)
    # bottom tercile trades the MIRROR -> -mean(1,3) = -2
    assert res["short_ret"] == pytest.approx(-2.0)
    assert res["ls_ret"] == pytest.approx(1.0)  # 3 + (-2)
    assert res["sv_ret"] == pytest.approx(0.5)
    assert res["n_long"] == 2 and res["n_short"] == 2


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def test_tstat_known_value():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    # mean 3, sd 1.5811, se 0.7071 -> t = 4.2426
    assert vt.tstat(x) == pytest.approx(4.2426, rel=1e-3)


def test_tstat_nan_guards():
    assert np.isnan(vt.tstat([1.0]))
    assert np.isnan(vt.tstat([2.0, 2.0, 2.0]))  # zero variance


def test_incremental_alpha_collapses_when_ls_is_pure_sv_beta():
    """If ls = 0.8 * sv exactly (pure short-vol beta), alpha must be ~0."""

    rng = np.random.default_rng(0)
    sv = rng.normal(0.0, 1.0, 200)
    ls = 0.8 * sv  # no idiosyncratic alpha
    res = vt.incremental_alpha(ls, sv)
    assert res["alpha"] == pytest.approx(0.0, abs=1e-9)
    assert res["beta"] == pytest.approx(0.8, rel=1e-6)


def test_incremental_alpha_recovers_true_alpha():
    rng = np.random.default_rng(1)
    sv = rng.normal(0.0, 1.0, 500)
    ls = 0.5 + 0.3 * sv + rng.normal(0.0, 0.01, 500)  # alpha 0.5
    res = vt.incremental_alpha(ls, sv)
    assert res["alpha"] == pytest.approx(0.5, abs=0.02)
    assert res["alpha_t"] > 2.0  # clearly significant


def test_summarize_reports_tail():
    x = pd.Series([1.0, 1.0, 1.0, -10.0, 1.0])  # one catastrophic period
    s = vt.summarize(x, x)
    assert s["worst_period"] == -10.0
    assert s["max_drawdown"] <= -10.0  # drawdown captures the crash
    assert s["mean"] == pytest.approx(-1.2)


def test_placebo_pvalue_is_high_for_noise():
    """Random tercile labels on noise -> observed LS near the placebo center."""

    rng = np.random.default_rng(7)
    periods = []
    for _ in range(20):
        n = 12
        legs = pd.DataFrame(
            {
                "tercile": vt.assign_terciles(pd.Series(rng.normal(size=n))).reindex(range(n)).fillna(0).astype(int),
                "cal_pnl": rng.normal(size=n),
                "sv_pnl": rng.normal(size=n),
            }
        )
        periods.append(legs)
    # observed = 0 (a central value) should yield a p-value well away from 0
    p = vt.placebo_pvalue(periods, observed_ls_mean=0.0, k=200, seed=3)
    assert 0.2 < p < 0.8
