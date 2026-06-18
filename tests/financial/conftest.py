"""Shared fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Force each test into a clean tmp project root with no .env loaded."""
    # Wipe Settings-relevant env vars so tests are deterministic.
    for k in list(os.environ):
        if k.startswith(
            ("TRADER_", "ALPACA_", "FINNHUB_", "FRED_", "DISCORD_", "ANTHROPIC_", "OPENAI_", "THETADATA_")
        ):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TRADER_TICKER", "TEST")
    monkeypatch.chdir(tmp_path)
    # Reset cached settings between tests.
    from trader import config

    config.get_settings.cache_clear()
    yield


@pytest.fixture
def kill_switch_path(tmp_path: Path) -> Path:
    return tmp_path / ".kill_switch"
