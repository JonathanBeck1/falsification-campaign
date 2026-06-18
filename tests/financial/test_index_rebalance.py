"""Network-free tests for the index-rebalance event study.

Covers: the pure snapshot-diff parser, CSV parsing, the CAR math on synthetic
series with a known injected jump, aggregation/t-stats, and the gate logic. No
I/O — the provider seam is exercised with a fake in-memory provider.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from trader.catalysts.index_rebalance import (
    DefaultIndexChangeProvider,
    IndexChange,
    StudyResult,
    WindowAgg,
    aggregate,
    changes_from_snapshots,
    compute_event_metrics,
    evaluate_gate,
    load_changes,
    parse_snapshot_csv,
)


# --------------------------------------------------------------------------- #
# snapshot diff parser
# --------------------------------------------------------------------------- #
def test_changes_from_snapshots_detects_add_and_delete():
    snaps = [
        (date(2020, 1, 1), frozenset({"AAA", "BBB"})),
        (date(2020, 2, 1), frozenset({"AAA", "CCC"})),  # +CCC, -BBB
    ]
    changes = changes_from_snapshots(snaps)
    assert IndexChange("CCC", date(2020, 2, 1), "add") in changes
    assert IndexChange("BBB", date(2020, 2, 1), "delete") in changes
    assert len(changes) == 2


def test_changes_from_snapshots_first_snapshot_seeds_no_events():
    snaps = [(date(2020, 1, 1), frozenset({"AAA", "BBB"}))]
    assert changes_from_snapshots(snaps) == []


def test_changes_from_snapshots_sorts_unordered_input():
    snaps = [
        (date(2020, 2, 1), frozenset({"AAA", "CCC"})),
        (date(2020, 1, 1), frozenset({"AAA", "BBB"})),
    ]
    changes = changes_from_snapshots(snaps)
    # despite reversed input, the change is dated to the later snapshot
    assert all(c.effective_date == date(2020, 2, 1) for c in changes)


def test_changes_no_event_when_membership_unchanged():
    snaps = [
        (date(2020, 1, 1), frozenset({"AAA", "BBB"})),
        (date(2020, 2, 1), frozenset({"BBB", "AAA"})),
    ]
    assert changes_from_snapshots(snaps) == []


def test_parse_snapshot_csv_roundtrip_and_diff():
    text = 'date,tickers\n2020-01-01,"AAA,BBB"\n2020-02-01,"AAA,CCC"\n'
    snaps = parse_snapshot_csv(text)
    assert snaps[0][0] == date(2020, 1, 1)
    assert snaps[0][1] == frozenset({"AAA", "BBB"})
    changes = changes_from_snapshots(snaps)
    kinds = {(c.ticker, c.kind) for c in changes}
    assert kinds == {("CCC", "add"), ("BBB", "delete")}


def test_parse_snapshot_csv_skips_garbage_rows():
    text = 'date,tickers\nnot-a-date,"AAA"\n2020-01-01,"AAA,BBB"\n2020-02-01,\n'
    snaps = parse_snapshot_csv(text)
    assert len(snaps) == 1
    assert snaps[0][0] == date(2020, 1, 1)


def test_load_changes_uses_provider_seam_no_network():
    class FakeProvider:
        def fetch(self) -> str:
            return 'date,tickers\n2020-01-01,"AAA,BBB"\n2020-02-01,"AAA,CCC"\n'

    changes = load_changes(FakeProvider())
    assert {(c.ticker, c.kind) for c in changes} == {("CCC", "add"), ("BBB", "delete")}


def test_default_provider_url_points_at_updated_components_file():
    # guard against an accidental URL edit; no network call.
    assert "Components" in DefaultIndexChangeProvider().url


# --------------------------------------------------------------------------- #
# CAR math on synthetic series
# --------------------------------------------------------------------------- #
def _series(start: date, n: int, daily_ret: float, *, name: str) -> pd.Series:
    idx = pd.bdate_range(start, periods=n)
    px = 100.0 * (1.0 + daily_ret) ** np.arange(n)
    return pd.Series(px, index=idx, name=name)


def test_car_is_zero_when_stock_tracks_market():
    # stock and SPY identical -> abnormal return ~0 in every window.
    start = date(2020, 1, 1)
    stock = _series(start, 80, 0.001, name="AAA")
    spy = _series(start, 80, 0.001, name="SPY")
    ev = compute_event_metrics(stock, spy, date(2020, 2, 1), kind="add")
    assert ev is not None
    assert abs(ev.car_0_p21) < 1e-9
    assert abs(ev.car_m5_m1) < 1e-9


def test_car_captures_injected_jump_in_window():
    start = date(2020, 1, 1)
    idx = pd.bdate_range(start, periods=80)
    base = 100.0 * np.ones(80)
    stock = pd.Series(base.copy(), index=idx, name="AAA")
    spy = pd.Series(base.copy(), index=idx, name="SPY")
    # find t0 = first bday on/after 2020-02-01, inject +5% abnormal at t0+3.
    t0 = int(idx.searchsorted(pd.Timestamp(date(2020, 2, 1)), side="left"))
    stock.iloc[t0 + 3 :] *= 1.05  # one +5% abnormal jump inside [0,+5] and [0,+21]
    ev = compute_event_metrics(stock, spy, date(2020, 2, 1), kind="add")
    assert ev is not None
    assert ev.car_0_p5 > 0.04  # ~5% abnormal cumulative
    assert ev.car_0_p21 > 0.04
    assert abs(ev.car_m5_m1) < 1e-9  # nothing before t0


def test_compute_drops_event_with_absurd_daily_glitch():
    # A single +700% one-day print (yfinance split glitch) must drop the event,
    # not blow up the CAR. Mirrors the real CBE 2011 case.
    start = date(2020, 1, 1)
    idx = pd.bdate_range(start, periods=80)
    stock = pd.Series(100.0 * np.ones(80), index=idx, name="AAA")
    spy = pd.Series(100.0 * np.ones(80), index=idx, name="SPY")
    t0 = int(idx.searchsorted(pd.Timestamp(date(2020, 2, 1)), side="left"))
    stock.iloc[t0 + 2] = 800.0  # +700% then back -> giant abnormal return
    stock.iloc[t0 + 3 :] = 100.0
    assert compute_event_metrics(stock, spy, date(2020, 2, 1), kind="add") is None


def test_compute_keeps_event_with_large_but_plausible_move():
    # A +40% one-day move is large but below the glitch cap -> event is KEPT.
    start = date(2020, 1, 1)
    idx = pd.bdate_range(start, periods=80)
    stock = pd.Series(100.0 * np.ones(80), index=idx, name="AAA")
    spy = pd.Series(100.0 * np.ones(80), index=idx, name="SPY")
    t0 = int(idx.searchsorted(pd.Timestamp(date(2020, 2, 1)), side="left"))
    stock.iloc[t0 + 2 :] *= 1.40
    ev = compute_event_metrics(stock, spy, date(2020, 2, 1), kind="add")
    assert ev is not None
    assert ev.car_0_p5 > 0.30


def test_compute_returns_none_when_window_incomplete():
    start = date(2020, 1, 1)
    stock = _series(start, 80, 0.0, name="AAA")
    spy = _series(start, 80, 0.0, name="SPY")
    # event near the very end -> no room for +21 window.
    late = stock.index[-2].date()
    assert compute_event_metrics(stock, spy, late, kind="add") is None


def test_compute_returns_none_when_series_too_short():
    start = date(2020, 1, 1)
    stock = _series(start, 5, 0.0, name="AAA")
    spy = _series(start, 5, 0.0, name="SPY")
    assert compute_event_metrics(stock, spy, date(2020, 1, 3), kind="add") is None


def test_offset_shifts_t0_into_placebo_position():
    start = date(2020, 1, 1)
    idx = pd.bdate_range(start, periods=120)
    stock = pd.Series(100.0 * np.ones(120), index=idx, name="AAA")
    spy = pd.Series(100.0 * np.ones(120), index=idx, name="SPY")
    ev = date(2020, 4, 1)
    real = compute_event_metrics(stock, spy, ev, kind="add")
    shifted = compute_event_metrics(stock, spy, ev, kind="add", offset_trading_days=-10)
    assert real is not None and shifted is not None
    assert shifted.t0_date < real.t0_date


# --------------------------------------------------------------------------- #
# aggregation + gate
# --------------------------------------------------------------------------- #
def _fake_result(label: str, n: int, mean: float, t: float) -> StudyResult:
    w = WindowAgg("car_0_p21", n, mean, mean, 0.6, t)
    others = {
        name: WindowAgg(name, n, 0.0, 0.0, 0.5, 0.0)
        for name in ("car_m5_m1", "car_m1_p1", "car_0_p5")
    }
    return StudyResult(label=label, n_events=n, windows={**others, "car_0_p21": w})


def test_aggregate_computes_mean_and_positive_tstat():
    start = date(2020, 1, 1)
    spy = pd.Series(100.0 * np.ones(80), index=pd.bdate_range(start, periods=80), name="SPY")
    metrics = []
    for i in range(40):
        idx = pd.bdate_range(start, periods=80)
        s = pd.Series(100.0 * np.ones(80), index=idx, name=f"T{i}")
        t0 = int(idx.searchsorted(pd.Timestamp(date(2020, 2, 1)), side="left"))
        s.iloc[t0:] *= 1.0 + 0.02 + 0.001 * i  # all positive abnormal at t0
        m = compute_event_metrics(s, spy, date(2020, 2, 1), kind="add")
        assert m is not None
        metrics.append(m)
    res = aggregate(metrics, label="adds")
    assert res.n_events == 40
    assert res.windows["car_0_p21"].mean > 0
    assert res.windows["car_0_p21"].t_stat > 2.0
    assert res.windows["car_0_p21"].pct_positive == 1.0


def test_gate_passes_on_strong_consistent_signal():
    real = _fake_result("real", 50, 0.03, 3.5)
    early = _fake_result("early", 25, 0.04, 2.5)
    late = _fake_result("late", 25, 0.02, 2.1)
    v = evaluate_gate(real, early, late)
    assert v.passed is True


def test_gate_fails_on_insufficient_n():
    real = _fake_result("real", 10, 0.03, 3.5)
    early = _fake_result("early", 5, 0.04, 2.5)
    late = _fake_result("late", 5, 0.02, 2.1)
    v = evaluate_gate(real, early, late)
    assert v.passed is False
    assert any("N=10" in r for r in v.reasons)


def test_gate_fails_on_weak_tstat():
    real = _fake_result("real", 50, 0.005, 0.4)  # near-null, classic decayed effect
    early = _fake_result("early", 25, 0.01, 0.8)
    late = _fake_result("late", 25, 0.001, 0.1)
    v = evaluate_gate(real, early, late)
    assert v.passed is False


def test_gate_fails_on_oos_sign_flip():
    real = _fake_result("real", 50, 0.03, 3.5)
    early = _fake_result("early", 25, 0.05, 2.5)
    late = _fake_result("late", 25, -0.02, -2.1)  # decayed/flipped recently
    v = evaluate_gate(real, early, late)
    assert v.passed is False
    assert any("OOS sign" in r and "FAIL" in r for r in v.reasons)
