"""Network-free unit tests for T25 — single-name 25-delta skew dynamics.

All tests inject synthetic in-memory panels; nothing here touches the lake,
yfinance, or the clock. They pin the PURE core: statistics helpers, the
cross-sectional long-short, the placebo, the IS/OOS split, the up/down symmetry
smoking-gun, the short-put premium proxy + tail, and the KEY disguise
regression (premium = short-vol + short-delta beta?).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trader.catalysts import vol_skew as vk


# --------------------------------------------------------------------------- #
# Panel builders
# --------------------------------------------------------------------------- #
def _panel(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in ("atm_iv", "mkt_fwd_ret"):
        if c not in df.columns:
            df[c] = np.nan
    return df


def _signal_panel(
    n_dates: int, n_names: int, *, beta: float, seed: int = 0,
    base: str = "2022-01-03", step_days: int = 7,
) -> pd.DataFrame:
    """Panel where fwd_ret = -beta*skew + noise (a clean low-skew-outperforms signal).

    With beta>0, LOW skew names have HIGH fwd_ret -> long-low/short-high is +.
    ``step_days`` controls calendar spacing so a test can straddle the IS/OOS
    boundary (vk.OOS_START = 2024-04-01) when it needs both halves populated.
    """

    rng = np.random.default_rng(seed)
    rows = []
    base_ts = pd.Timestamp(base)
    for d in range(n_dates):
        dt = base_ts + pd.Timedelta(days=step_days * d)
        skews = rng.uniform(-0.02, 0.12, size=n_names)
        noise = rng.normal(0, 0.001, size=n_names)
        for i in range(n_names):
            rows.append({
                "ticker": f"NM{i:02d}",
                "snapshot_date": dt,
                "skew": float(skews[i]),
                "atm_iv": 0.30,
                "fwd_ret": float(-beta * skews[i] + noise[i]),
            })
    return _panel(rows)


# --------------------------------------------------------------------------- #
# Statistics helpers
# --------------------------------------------------------------------------- #
def test_t_stat_matches_definition():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    expected = x.mean() / (x.std(ddof=1) / np.sqrt(x.size))
    assert vk._t_stat(x) == pytest.approx(expected)


def test_t_stat_nan_for_degenerate():
    assert np.isnan(vk._t_stat(np.array([5.0])))         # n<2
    assert np.isnan(vk._t_stat(np.array([2.0, 2.0])))    # std=0


def test_max_drawdown_is_nonpositive_and_correct():
    # cumulative: +1, +1-3=-2, -2+1=-1 -> peak 1 at idx0, trough -2 -> dd=-3
    pnl = np.array([1.0, -3.0, 1.0])
    assert vk._max_drawdown(pnl) == pytest.approx(-3.0)
    assert vk._max_drawdown(np.array([1.0, 1.0, 1.0])) == 0.0  # monotone up -> no dd


def test_summarize_fields():
    s = vk.summarize(np.array([0.01, -0.02, 0.03, 0.0]))
    assert s.n == 4
    assert s.mean == pytest.approx(0.005)
    assert s.win == pytest.approx(0.5)  # 2 of 4 strictly > 0
    assert s.worst == pytest.approx(-0.02)
    assert s.best == pytest.approx(0.03)


def test_summarize_empty_is_safe():
    s = vk.summarize(np.array([]))
    assert s.n == 0
    assert np.isnan(s.mean)
    assert s.maxdd == 0.0


# --------------------------------------------------------------------------- #
# Panel validation
# --------------------------------------------------------------------------- #
def test_validate_panel_drops_nan_skew_and_fwd():
    p = _panel([
        {"ticker": "A", "snapshot_date": "2022-01-03", "skew": 0.05, "fwd_ret": 0.01},
        {"ticker": "B", "snapshot_date": "2022-01-03", "skew": np.nan, "fwd_ret": 0.01},
        {"ticker": "C", "snapshot_date": "2022-01-03", "skew": 0.03, "fwd_ret": np.nan},
    ])
    out = vk.validate_panel(p)
    assert list(out["ticker"]) == ["A"]


def test_validate_panel_requires_columns():
    with pytest.raises(ValueError, match="missing required columns"):
        vk.validate_panel(pd.DataFrame({"ticker": ["A"], "snapshot_date": ["2022-01-03"]}))


# --------------------------------------------------------------------------- #
# Tertile long-short mechanics
# --------------------------------------------------------------------------- #
def test_tertile_long_short_sign_and_value():
    # 6 names, sort_fraction=1/3 -> k=2. demeaned fwd correlates with -skew.
    skew = np.array([0.0, 0.01, 0.02, 0.03, 0.04, 0.05])
    demeaned = np.array([0.03, 0.02, 0.01, -0.01, -0.02, -0.03])  # low skew -> high ret
    ls = vk._tertile_long_short_one_date(skew, demeaned, sort_fraction=1 / 3)
    # long lowest 2 (mean .025) minus short highest 2 (mean -.025) = .05
    assert ls == pytest.approx(0.05)


def test_tertile_returns_none_when_too_few_names():
    skew = np.array([0.0, 0.1])  # n=2, k=0 -> None
    demeaned = np.array([0.01, -0.01])
    assert vk._tertile_long_short_one_date(skew, demeaned, sort_fraction=1 / 3) is None


def test_signal_long_short_recovers_positive_with_beta():
    p = _signal_panel(n_dates=40, n_names=12, beta=0.5, seed=1)
    ls = vk.signal_long_short(p, min_names=12)
    assert len(ls) == 40
    # constructed so low-skew outperforms -> long-low/short-high positive
    assert ls["gross"].mean() > 0
    # cost is subtracted: net < gross
    assert (ls["net"] < ls["gross"]).all()


def test_signal_long_short_near_zero_without_signal():
    p = _signal_panel(n_dates=60, n_names=12, beta=0.0, seed=7)
    ls = vk.signal_long_short(p, min_names=12)
    # no skew->ret link: t-stat should be small
    assert abs(vk._t_stat(ls["gross"].to_numpy())) < 2.5


def test_signal_skips_sparse_dates():
    # one date with only 3 names (< min_names) is dropped
    p = _panel([
        {"ticker": f"N{i}", "snapshot_date": "2022-01-03", "skew": 0.01 * i, "fwd_ret": 0.001 * i}
        for i in range(3)
    ])
    ls = vk.signal_long_short(p, min_names=12)
    assert ls.empty


# --------------------------------------------------------------------------- #
# Placebo
# --------------------------------------------------------------------------- #
def test_placebo_detects_real_signal():
    p = _signal_panel(n_dates=50, n_names=12, beta=0.6, seed=3)
    res = vk.placebo_long_short(p, n_perm=100, min_names=12)
    # real signal -> observed mean far from the shuffle null -> small p
    assert res["p_value"] < 0.05
    assert abs(res["perm_mean"]) < abs(res["obs_mean"])


def test_placebo_null_for_no_signal():
    p = _signal_panel(n_dates=50, n_names=12, beta=0.0, seed=11)
    res = vk.placebo_long_short(p, n_perm=100, min_names=12)
    # no signal -> observed is just one draw from the shuffle -> p not tiny
    assert res["p_value"] > 0.05


def test_placebo_is_deterministic():
    p = _signal_panel(n_dates=30, n_names=12, beta=0.3, seed=5)
    a = vk.placebo_long_short(p, n_perm=50, seed=99, min_names=12)
    b = vk.placebo_long_short(p, n_perm=50, seed=99, min_names=12)
    assert a["p_value"] == b["p_value"]


# --------------------------------------------------------------------------- #
# IS/OOS split + symmetry
# --------------------------------------------------------------------------- #
def test_is_oos_split_partitions_by_calendar():
    rows = [
        {"snapshot_date": "2022-06-01", "net": 0.01},
        {"snapshot_date": "2023-06-01", "net": 0.02},
        {"snapshot_date": "2025-06-01", "net": -0.01},  # OOS (>= 2024-04)
    ]
    splits = vk.is_oos_split(pd.DataFrame(rows))
    assert splits["is"].n == 2
    assert splits["oos"].n == 1


def test_up_down_symmetry_antisymmetric():
    p = _signal_panel(n_dates=30, n_names=12, beta=0.5, seed=2)
    sym = vk.up_down_symmetry(p, min_names=12)
    # forward + reversed must sum to ~0 (antisymmetric long-short by construction)
    assert sym["sum"] == pytest.approx(0.0, abs=1e-12)
    assert sym["forward_mean"] == pytest.approx(-sym["reversed_mean"])


# --------------------------------------------------------------------------- #
# Premium proxy + tail + disguise control
# --------------------------------------------------------------------------- #
def test_short_put_premium_pnl_collects_skew_when_benign():
    # benign: fwd_ret >= 0 -> payout 0 -> pnl = skew - cost
    p = _panel([
        {"ticker": "A", "snapshot_date": "2022-01-03", "skew": 0.05, "atm_iv": 0.3, "fwd_ret": 0.02},
    ])
    out = vk.short_put_premium_pnl(p, cost_volpts=0.0)
    assert out["payout"].iloc[0] == 0.0
    assert out["pnl"].iloc[0] == pytest.approx(0.05)


def test_short_put_premium_pnl_pays_on_crash():
    # crash: fwd_ret=-0.20 -> payout 0.20 -> pnl = 0.05 - 0.20 = -0.15 (the tail)
    p = _panel([
        {"ticker": "A", "snapshot_date": "2022-06-13", "skew": 0.05, "atm_iv": 0.3, "fwd_ret": -0.20},
    ])
    out = vk.short_put_premium_pnl(p, cost_volpts=0.0)
    assert out["payout"].iloc[0] == pytest.approx(0.20)
    assert out["pnl"].iloc[0] == pytest.approx(-0.15)


def test_disguise_regression_kills_pure_beta_premium():
    # Build premium = 1.0*short_vol_leg + noise; alpha should be ~0 (disguised).
    rng = np.random.default_rng(0)
    n = 300
    short_vol = rng.normal(0, 1, n)
    beta = rng.normal(0, 1, n)
    premium = 1.0 * short_vol + 0.0 + rng.normal(0, 0.01, n)  # no intercept
    res = vk.disguise_regression(premium, short_vol, beta)
    assert abs(res["alpha_t"]) < 2.0          # residual alpha dies -> disguise confirmed
    assert res["beta_vol"] == pytest.approx(1.0, abs=0.05)


def test_disguise_regression_keeps_genuine_alpha():
    rng = np.random.default_rng(1)
    n = 300
    short_vol = rng.normal(0, 1, n)
    beta = rng.normal(0, 1, n)
    premium = 0.5 + 0.2 * short_vol + rng.normal(0, 0.05, n)  # real +0.5 intercept
    res = vk.disguise_regression(premium, short_vol, beta)
    assert res["alpha"] == pytest.approx(0.5, abs=0.05)
    assert res["alpha_t"] > 2.0


def test_drop_worst_month_isolates_the_tail():
    # one catastrophic month dominates; dropping it changes the mean materially
    rows = [{"snapshot_date": f"2022-01-{d:02d}", "pnl": 0.01} for d in range(1, 11)]
    rows += [{"snapshot_date": "2022-06-15", "pnl": -2.0}]  # the selloff
    df = pd.DataFrame(rows)
    res = vk.drop_worst_month(df)
    assert res["worst_month"] == "2022-06"
    assert res["drop_mean"] > res["full_mean"]


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #
def test_gate_passes_a_clean_strong_signal():
    # spaced ~4-weekly so the 60 dates straddle the IS/OOS boundary (2024-04)
    p = _signal_panel(n_dates=60, n_names=12, beta=0.8, seed=4, step_days=28)
    ls = vk.signal_long_short(p, min_names=12, cost_bps=0.0)
    placebo = vk.placebo_long_short(p, n_perm=100, min_names=12)
    gate = vk.evaluate_signal_gate(ls, placebo, value_col="net")
    assert gate.passed, gate.reasons


def test_gate_fails_on_no_signal():
    p = _signal_panel(n_dates=60, n_names=12, beta=0.0, seed=9)
    ls = vk.signal_long_short(p, min_names=12)
    placebo = vk.placebo_long_short(p, n_perm=100, min_names=12)
    gate = vk.evaluate_signal_gate(ls, placebo, value_col="net")
    assert not gate.passed
    assert any("|t|" in r or "placebo" in r for r in gate.reasons)


def test_gate_fails_on_too_few_obs():
    p = _signal_panel(n_dates=5, n_names=12, beta=0.8, seed=4)
    ls = vk.signal_long_short(p, min_names=12, cost_bps=0.0)
    placebo = vk.placebo_long_short(p, n_perm=50, min_names=12)
    gate = vk.evaluate_signal_gate(ls, placebo, min_n=30, value_col="net")
    assert not gate.passed
    assert any("N=" in r for r in gate.reasons)
