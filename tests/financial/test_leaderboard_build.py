"""build_leaderboard orchestrator tests with synthetic equity curves."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from trader.scoring.leaderboard import (
    LeaderboardRow,
    build_leaderboard,
    confidence_tier_for_days,
)
from trader.storage.store import Store


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path / "trader.sqlite")


def _seed_curve(store: Store, brain: str, equities: list[float], *, start: date | None = None) -> None:
    start = start or date(2026, 1, 1)
    for i, eq in enumerate(equities):
        store.record_equity(brain, (start + timedelta(days=i)).isoformat(), eq)


def _row_for(rows: list[LeaderboardRow], brain: str) -> LeaderboardRow:
    return next(r for r in rows if r.brain == brain)


# ── confidence_tier boundaries ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "days,expected",
    [
        (0, "insufficient"),
        (4, "insufficient"),
        (5, "early_read"),
        (19, "early_read"),
        (20, "directional"),
        (29, "directional"),
        (30, "useful"),
        (99, "useful"),
        (100, "m4_grade"),
        (365, "m4_grade"),
    ],
)
def test_confidence_tier_boundaries(days, expected):
    assert confidence_tier_for_days(days) == expected


# ── build_leaderboard ──────────────────────────────────────────────────────


def test_build_leaderboard_empty_store_returns_empty(tmp_path):
    store = _store(tmp_path)
    assert build_leaderboard(store) == []


def test_build_leaderboard_basic_three_brains(tmp_path):
    store = _store(tmp_path)
    # Baseline: realistic volatile gain — small dips along the way so the
    # baseline's Sharpe isn't pathologically high (smooth arithmetic curves
    # have artificially low variance which inflates Sharpe).
    _seed_curve(store, "BuyAndHoldBrain", [100.0, 102.0, 101.0, 103.0, 104.0])
    # Winner: bigger gain, also slightly volatile.
    _seed_curve(store, "WinnerBrain", [100.0, 103.0, 102.0, 106.0, 108.0])
    # Loser: clear loss.
    _seed_curve(store, "LoserBrain", [100.0, 99.0, 98.0, 97.0, 94.0])

    rows = build_leaderboard(store, baseline_brain="BuyAndHoldBrain")
    assert len(rows) == 3
    # LoserBrain (negative returns) should be last.
    assert rows[-1].brain == "LoserBrain"
    # WinnerBrain should outrank LoserBrain in absolute composite.
    winner = _row_for(rows, "WinnerBrain")
    loser = _row_for(rows, "LoserBrain")
    assert winner.composite_score > loser.composite_score
    assert winner.days == 5
    assert winner.confidence_tier == "early_read"
    assert pytest.approx(winner.total_return, rel=1e-6) == 0.08
    # +8% winner vs +4% baseline = +4pp
    assert pytest.approx(winner.vs_buy_and_hold_pp, rel=1e-6) == 4.0


def test_insufficient_rows_sorted_to_bottom(tmp_path):
    store = _store(tmp_path)
    _seed_curve(store, "Veteran", [100.0, 101.0, 102.0, 103.0, 104.0])
    _seed_curve(store, "Newbie", [100.0, 200.0])  # 2 days → insufficient

    rows = build_leaderboard(store, baseline_brain="MISSING_BASELINE")
    assert rows[0].brain == "Veteran"
    assert rows[-1].brain == "Newbie"
    assert rows[-1].confidence_tier == "insufficient"


def test_missing_baseline_does_not_crash_and_zeros_vs_bh(tmp_path):
    store = _store(tmp_path)
    _seed_curve(store, "OnlyBrain", [100.0, 110.0, 120.0, 130.0, 140.0])
    rows = build_leaderboard(store, baseline_brain="DoesNotExistBrain")
    assert len(rows) == 1
    assert rows[0].vs_buy_and_hold_pp == 0.0


def test_baseline_with_insufficient_data_does_not_crash(tmp_path):
    store = _store(tmp_path)
    # Baseline has only one point — insufficient for total_return.
    _seed_curve(store, "BuyAndHoldBrain", [100.0])
    _seed_curve(store, "OtherBrain", [100.0, 110.0, 120.0, 130.0, 140.0])
    rows = build_leaderboard(store, baseline_brain="BuyAndHoldBrain")
    other = _row_for(rows, "OtherBrain")
    # No baseline total_return → vs_buy_and_hold_pp = 0.0
    assert other.vs_buy_and_hold_pp == 0.0


def test_since_until_filter_honored(tmp_path):
    store = _store(tmp_path)
    _seed_curve(
        store,
        "BrainA",
        [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0],
        start=date(2026, 1, 1),
    )
    # Window the middle 5 days.
    rows = build_leaderboard(
        store,
        since=date(2026, 1, 3),
        until=date(2026, 1, 7),
        baseline_brain="MISSING",
    )
    a = _row_for(rows, "BrainA")
    assert a.days == 5
    # Window: equity goes 102 → 106 → total_return = (106/102 - 1)
    assert pytest.approx(a.total_return, rel=1e-9) == (106.0 / 102.0) - 1.0


def test_zero_variance_curve_gives_zero_sharpe(tmp_path):
    store = _store(tmp_path)
    _seed_curve(store, "FlatBrain", [100.0, 100.0, 100.0, 100.0, 100.0])
    rows = build_leaderboard(store, baseline_brain="MISSING")
    flat = _row_for(rows, "FlatBrain")
    assert flat.sharpe == 0.0
    assert flat.composite_score == 0.0


def test_blowup_penalized_by_drawdown(tmp_path):
    """A brain with high Sharpe but a 40%+ drawdown should have its
    composite zeroed by the drawdown penalty."""
    store = _store(tmp_path)
    # 100 → 200 → 100 (high vol, 50% drawdown from peak 200 → 100)
    _seed_curve(store, "BlowupBrain", [100.0, 150.0, 200.0, 150.0, 100.0])
    rows = build_leaderboard(store, baseline_brain="MISSING")
    blowup = _row_for(rows, "BlowupBrain")
    # max_drawdown = -0.50, penalty = min(1, 0.50 * 2.5) = min(1, 1.25) = 1, composite = 0
    assert pytest.approx(blowup.max_drawdown, rel=1e-9) == -0.50
    assert blowup.composite_score == 0.0


@pytest.mark.parametrize(
    "max_dd, expected_penalty",
    [
        (0.00, 0.00),
        (-0.10, 0.25),
        (-0.20, 0.50),  # 20% drawdown halves the Sharpe
        (-0.30, 0.75),
        (-0.40, 1.00),  # 40% drawdown zeroes the Sharpe
        (-0.50, 1.00),  # capped at 1.0
    ],
)
def test_drawdown_penalty_matches_documented_curve(max_dd, expected_penalty):
    """Pin the documented penalty curve (20% halves, 40% zeroes) so a future
    multiplier change can't silently drift from the spec again."""
    from trader.scoring.leaderboard import _composite_score, _drawdown_penalty

    assert _drawdown_penalty(max_dd) == pytest.approx(expected_penalty)
    # composite = sharpe * (1 - penalty): with sharpe = 2.0, a 20% dd halves it,
    # a 40% dd zeroes it.
    assert _composite_score(2.0, max_dd) == pytest.approx(2.0 * (1.0 - expected_penalty))


def test_sort_stable_when_composites_tie(tmp_path):
    store = _store(tmp_path)
    # Two flat brains — both will have composite=0
    _seed_curve(store, "BBrain", [100.0, 100.0, 100.0, 100.0, 100.0])
    _seed_curve(store, "ABrain", [100.0, 100.0, 100.0, 100.0, 100.0])
    rows = build_leaderboard(store, baseline_brain="MISSING")
    # Ties broken by name asc
    assert [r.brain for r in rows] == ["ABrain", "BBrain"]
