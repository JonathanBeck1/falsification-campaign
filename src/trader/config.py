"""Centralized configuration with paper-vs-live guard.

Loads from environment / .env via pydantic-settings. The `Settings` object is
the single source of truth for credentials, broker mode, and strategy params.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    # Trading mode
    trader_live: bool = False
    trader_i_understand_the_risk: bool = False

    # Alpaca
    alpaca_paper_key_id: SecretStr | None = None
    alpaca_paper_secret_key: SecretStr | None = None
    alpaca_live_key_id: SecretStr | None = None
    alpaca_live_secret_key: SecretStr | None = None

    # LLM
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    trader_llm_model: str = "claude-haiku-4-5-20251001"
    # Per brain/20_llm_decision_boundary_adr.md, the cost cap must be
    # preventive — checked BEFORE adding HybridBrain to the roster, not after
    # the LLM call. Default $1.00/day matches brain/15's cost-cap principle.
    trader_llm_daily_budget_usd: float = 1.0
    # Tier-1 deterministic short-circuit: when the classical signal is this
    # confident AND no breaking events were observed in `breaking_lookback_hours`,
    # skip the LLM call entirely. Saves spend on quiet days.
    trader_hybrid_classical_confidence_threshold: float = 0.7
    trader_hybrid_breaking_lookback_hours: int = 24
    # Horse-race Phase 1 guardrails. Hard cap on LLM calls per daily cycle,
    # regardless of how many LLM brain variants are configured. Belt-and-
    # suspenders alongside the existing daily-dollar budget gate.
    trader_max_llm_calls_per_cycle: int = 10

    # Data
    finnhub_api_key: SecretStr | None = None
    fred_api_key: SecretStr | None = None
    # Path to a local ThetaData credentials file (kept outside the repo).
    thetadata_credentials_file: str | None = None
    # Option-quote lake roots. The lakes are large + licensed (ThetaData-derived)
    # and are NOT shipped in the repo; point these at wherever you keep them.
    # Defaults (when unset) are repo-relative ``lake/`` subdirs — see the
    # ``eod_lake_root`` / ``intraday_lake_root`` resolvers below.
    trader_eod_lake_root: str | None = None
    trader_lake_root: str | None = None

    # Notify
    discord_webhook_url: SecretStr | None = None
    ntfy_topic: str | None = None
    ntfy_server_url: str = "https://ntfy.sh"
    ntfy_token: SecretStr | None = None
    trader_alerts_enabled: bool = False

    # Strategy
    trader_ticker: str = Field(default="QQQ")
    # Comma-separated list of additional tickers we pull *news* for, to give the
    # LLM brains broader market context. Does NOT change what we trade.
    trader_context_tickers: str = Field(default="QQQ,SPY")
    # Tickers we pull SEC 8-K filings for. Defaults are top QQQ/SPY constituents.
    trader_sec_tickers: str = Field(default="AAPL,MSFT,NVDA,AMZN,META,GOOGL,TSLA,AVGO")
    # SEC requires a User-Agent identifying yourself + contact email.
    # See https://www.sec.gov/os/accessing-edgar-data
    trader_sec_user_agent: str = Field(default="trader your-email@example.com")
    trader_starting_cash: float = 100_000.0
    trader_max_position_pct: float = 0.95
    trader_max_daily_loss_pct: float = 0.03
    trader_kill_switch_file: str = ".kill_switch"

    # Project paths (computed)
    project_root: Path = Field(default_factory=lambda: Path.cwd())

    @model_validator(mode="after")
    def _validate_live_safety(self) -> Settings:
        """Refuse to enable live trading without explicit acknowledgement."""
        if self.trader_live and not self.trader_i_understand_the_risk:
            raise ValueError(
                "TRADER_LIVE=true requires TRADER_I_UNDERSTAND_THE_RISK=true. Re-read the runbook before flipping this."
            )
        if self.trader_live and (self.alpaca_live_key_id is None or self.alpaca_live_secret_key is None):
            raise ValueError("Live mode requested but ALPACA_LIVE_KEY_ID/SECRET are missing.")
        return self

    @property
    def alpaca_key_id(self) -> str:
        key = self.alpaca_live_key_id if self.trader_live else self.alpaca_paper_key_id
        if key is None:
            raise RuntimeError("Alpaca key missing; check .env")
        return key.get_secret_value()

    @property
    def alpaca_secret_key(self) -> str:
        key = self.alpaca_live_secret_key if self.trader_live else self.alpaca_paper_secret_key
        if key is None:
            raise RuntimeError("Alpaca secret missing; check .env")
        return key.get_secret_value()

    @property
    def alpaca_base_url(self) -> str:
        return "https://api.alpaca.markets" if self.trader_live else "https://paper-api.alpaca.markets"

    @property
    def sqlite_path(self) -> Path:
        return self.project_root / "data" / "trader.sqlite"

    @property
    def kill_switch_path(self) -> Path:
        return self.project_root / self.trader_kill_switch_file

    @property
    def context_tickers(self) -> list[str]:
        return [t.strip().upper() for t in self.trader_context_tickers.split(",") if t.strip()]

    @property
    def sec_tickers(self) -> list[str]:
        return [t.strip().upper() for t in self.trader_sec_tickers.split(",") if t.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# --------------------------------------------------------------------------- #
# Data-lake path resolvers (portable; env-overridable)
# --------------------------------------------------------------------------- #
# The option-quote lakes are large, licensed (ThetaData-derived), and NOT shipped
# in the repo. To keep the code portable — and to avoid baking any contributor's
# machine path (and username) into source — the lake roots are resolved here from
# the ``TRADER_EOD_LAKE_ROOT`` / ``TRADER_LAKE_ROOT`` settings (read from the env
# or a git-ignored ``.env`` via pydantic-settings), defaulting to repo-relative
# ``lake/`` subdirs. See ``.env.example`` and ``docs/DATA.md``.
def _repo_root() -> Path:
    """Repo root = the directory two levels above ``src/trader/config.py``."""
    return Path(__file__).resolve().parents[2]


def eod_lake_root() -> Path:
    """Root of the single-name **EOD** option-quote lake (T22-T26 foundation).

    Override with ``TRADER_EOD_LAKE_ROOT`` (env or ``.env``); defaults to
    ``<repo>/lake/option_eod_quotes``. Layout: ``root=TICKER/trade_year=YYYY/
    TICKER_YYYY-MM-DD.parquet`` (see ``trader.catalysts.vol_surface_data``).
    """
    configured = get_settings().trader_eod_lake_root
    return Path(configured) if configured else _repo_root() / "lake" / "option_eod_quotes"


def intraday_lake_root() -> Path:
    """Root of the **1-minute** option-quote-bar lake (intraday feature mining).

    Override with ``TRADER_LAKE_ROOT`` (env or ``.env``); defaults to
    ``<repo>/lake/option_quote_bars_1m``.
    """
    configured = get_settings().trader_lake_root
    return Path(configured) if configured else _repo_root() / "lake" / "option_quote_bars_1m"


def banner() -> str:
    s = get_settings()
    mode = "LIVE  ⚠️" if s.trader_live else "PAPER"
    return (
        f"\n{'=' * 60}\n"
        f"  STOCK TRADER  —  mode: {mode}  —  ticker: {s.trader_ticker}\n"
        f"  base: {s.alpaca_base_url}\n"
        f"{'=' * 60}\n"
    )


def print_banner_or_die() -> None:
    """Print a clear banner on startup so live mode is never silent."""
    sys.stderr.write(banner())
    sys.stderr.flush()
