"""Per-cycle LLM call cap enforcement in the runner.

Per brain/decisions/2026-05-21-horse-race-phase-1.md, the runner refuses to
invoke more than `trader_max_llm_calls_per_cycle` LLM brains in a single
cycle, regardless of how many LLM brain variants are configured. Each
skip is logged + recorded as a `warn` event.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from trader import runner
from trader.signals.base import Decision
from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot


class _LLMBrain:
    uses_llm = True

    def __init__(self, name: str) -> None:
        self.name = name

    def decide(self, snapshot: DailySnapshot) -> Decision:
        return Decision(
            action="HOLD",
            target_pct=0.0,
            confidence=0.5,
            reasoning="stub",
            llm_cost_usd=0.0,
            llm_model="stub",
            llm_prompt_hash="stub-hash",
            llm_input_tokens=1,
            llm_output_tokens=1,
            llm_cached_tokens=0,
            llm_latency_ms=1,
        )


class _DeterministicBrain:
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
        snapshot_id=f"cap-test-{datetime.now(UTC).isoformat()}",
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


def _events(path: Path) -> list[dict]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM events").fetchall()]


@pytest.fixture
def isolated_tmp(tmp_path, monkeypatch):
    """Run the runner against an isolated SQLite + skip the freshness gate
    (otherwise our LLM stubs get skipped before the cap check)."""
    monkeypatch.chdir(tmp_path)

    class _NotStale:
        should_skip_llm = False
        stale_sources: tuple[str, ...] = ()

    monkeypatch.setattr(runner, "gate_llm_brains_on_freshness", lambda *_a, **_k: _NotStale())
    monkeypatch.setattr(runner, "build_notifier", lambda: _SilentNotifier())
    return tmp_path


def _patched_settings(monkeypatch, cap: int):
    """Return a fresh Settings instance with the LLM cap overridden, and
    patch the runner's get_settings() to return it. Avoids mutating the
    cached singleton (pydantic frozen-after-init makes that brittle)."""
    from trader.config import Settings

    fresh = Settings()
    object.__setattr__(fresh, "trader_max_llm_calls_per_cycle", cap)
    monkeypatch.setattr(runner, "get_settings", lambda: fresh)
    return fresh


def test_runner_skips_llm_brains_over_cap(isolated_tmp, monkeypatch):
    # 4 LLM brains; cap them at 2.
    brains = [_LLMBrain(name=f"LLM_{i}") for i in range(4)]
    monkeypatch.setattr(runner, "all_brains", lambda settings, store=None: brains)
    settings = _patched_settings(monkeypatch, cap=2)

    decisions = runner.run_one_day(_snapshot(), sleep_fn=lambda _s: None)

    # First 2 LLM brains ran, last 2 were capped.
    assert sorted(decisions.keys()) == ["LLM_0", "LLM_1"]

    events = _events(Path(settings.sqlite_path))
    cap_events = [e for e in events if "llm_skipped_call_cap" in (e.get("message") or "")]
    assert len(cap_events) == 2
    capped_brains = {e["source"] for e in cap_events}
    assert capped_brains == {"LLM_2", "LLM_3"}


def test_deterministic_brains_never_consume_llm_cap(isolated_tmp, monkeypatch):
    # 5 deterministic brains, cap=0 (no LLM calls allowed).
    brains = [_DeterministicBrain(name=f"DET_{i}") for i in range(5)]
    monkeypatch.setattr(runner, "all_brains", lambda settings, store=None: brains)
    settings = _patched_settings(monkeypatch, cap=0)

    decisions = runner.run_one_day(_snapshot(), sleep_fn=lambda _s: None)
    # All 5 deterministic brains ran despite cap=0.
    assert sorted(decisions.keys()) == [f"DET_{i}" for i in range(5)]

    events = _events(Path(settings.sqlite_path))
    cap_events = [e for e in events if "llm_skipped_call_cap" in (e.get("message") or "")]
    assert cap_events == []


def test_cap_above_brain_count_lets_all_llm_brains_run(isolated_tmp, monkeypatch):
    brains = [_LLMBrain(name=f"LLM_{i}") for i in range(3)]
    monkeypatch.setattr(runner, "all_brains", lambda settings, store=None: brains)
    settings = _patched_settings(monkeypatch, cap=10)

    decisions = runner.run_one_day(_snapshot(), sleep_fn=lambda _s: None)
    assert sorted(decisions.keys()) == ["LLM_0", "LLM_1", "LLM_2"]
    events = _events(Path(settings.sqlite_path))
    assert not any("llm_skipped_call_cap" in (e.get("message") or "") for e in events)
