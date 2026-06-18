"""Inter-LLM-call sleep injection in the runner.

Per brain/decisions/2026-05-21-horse-race-phase-1.md, the runner pauses
500ms between successive LLM brain calls to avoid TPM bursts. The pause
fires only between LLM brains, never around deterministic brains, and
not before the first LLM brain. Tests inject a recorder so we can
assert exactly when sleep was called without slowing CI.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from trader import runner
from trader.signals.base import Decision
from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot


class _LLMBrain:
    uses_llm = True

    def __init__(self, name: str) -> None:
        self.name = name

    def decide(self, snapshot: DailySnapshot) -> Decision:
        return Decision(action="HOLD", target_pct=0.0, confidence=0.5, reasoning="stub")


class _DetBrain:
    uses_llm = False

    def __init__(self, name: str) -> None:
        self.name = name

    def decide(self, snapshot: DailySnapshot) -> Decision:
        return Decision(action="HOLD", target_pct=0.0, confidence=0.5, reasoning="det")


class _SilentNotifier:
    def send(self, title: str, body: str) -> None:
        pass


def _snapshot() -> DailySnapshot:
    bar = Bar(
        timestamp=datetime(2026, 5, 18, 20, 0, tzinfo=UTC),
        open=400.0,
        high=400.0,
        low=400.0,
        close=400.0,
        volume=1_000_000,
    )
    return DailySnapshot(
        snapshot_id=f"sleep-test-{datetime.now(UTC).isoformat()}",
        trade_date=date(2026, 5, 18),
        ticker="TEST",
        latest_bar=bar,
        recent_bars=[bar],
        sma_50=400.0,
        sma_200=400.0,
        rsi_14=50.0,
        realized_vol_20d=0.1,
        news=[],
        macro=MacroSnapshot(vix=15.0),
    )


@pytest.fixture
def isolated_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class _NotStale:
        should_skip_llm = False
        stale_sources: tuple[str, ...] = ()

    monkeypatch.setattr(runner, "gate_llm_brains_on_freshness", lambda *_a, **_k: _NotStale())
    monkeypatch.setattr(runner, "build_notifier", lambda: _SilentNotifier())
    return tmp_path


def test_sleep_fires_between_consecutive_llm_brains(isolated_tmp, monkeypatch):
    brains = [_LLMBrain("LLM_A"), _LLMBrain("LLM_B"), _LLMBrain("LLM_C")]
    monkeypatch.setattr(runner, "all_brains", lambda settings, store=None: brains)

    sleeps: list[float] = []
    runner.run_one_day(_snapshot(), sleep_fn=lambda s: sleeps.append(s))

    # 3 LLM brains -> sleep before 2nd and before 3rd -> 2 sleeps.
    assert sleeps == [runner.INTER_LLM_CALL_SLEEP_SECONDS, runner.INTER_LLM_CALL_SLEEP_SECONDS]


def test_sleep_does_not_fire_for_deterministic_brains(isolated_tmp, monkeypatch):
    brains = [_DetBrain("DET_A"), _DetBrain("DET_B"), _DetBrain("DET_C")]
    monkeypatch.setattr(runner, "all_brains", lambda settings, store=None: brains)

    sleeps: list[float] = []
    runner.run_one_day(_snapshot(), sleep_fn=lambda s: sleeps.append(s))

    assert sleeps == []


def test_sleep_only_fires_after_first_llm_brain(isolated_tmp, monkeypatch):
    # Mixed roster: deterministic, LLM, deterministic, LLM.
    # Sleep should fire exactly once — before the SECOND LLM brain.
    brains = [_DetBrain("D1"), _LLMBrain("L1"), _DetBrain("D2"), _LLMBrain("L2")]
    monkeypatch.setattr(runner, "all_brains", lambda settings, store=None: brains)

    sleeps: list[float] = []
    runner.run_one_day(_snapshot(), sleep_fn=lambda s: sleeps.append(s))

    assert sleeps == [runner.INTER_LLM_CALL_SLEEP_SECONDS]


def test_sleep_does_not_fire_when_only_one_llm_brain(isolated_tmp, monkeypatch):
    brains = [_LLMBrain("LLM_solo")]
    monkeypatch.setattr(runner, "all_brains", lambda settings, store=None: brains)

    sleeps: list[float] = []
    runner.run_one_day(_snapshot(), sleep_fn=lambda s: sleeps.append(s))

    assert sleeps == []


def test_default_sleep_fn_is_time_sleep():
    # Smoke check: the default param is time.sleep. We don't actually invoke
    # it here — just verify the signature/default exists.
    import inspect

    sig = inspect.signature(runner.run_one_day)
    assert "sleep_fn" in sig.parameters
    assert sig.parameters["sleep_fn"].default is None  # defaults to time.sleep inside
