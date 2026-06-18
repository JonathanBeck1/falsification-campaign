"""Brain-variant config + factory for the paper-trading horse race.

Phase 1 ships 6 variant brains: VIXRegime x {Conservative, Aggressive} and
Hybrid x {Haiku, GPT4oMini} x {Conservative, Aggressive}. Per
`brain/decisions/2026-05-21-horse-race-phase-1.md`.

`BrainVariantConfig` is the single source of truth for variant identity:
- `name` becomes `brain.name` and the SQLite portfolio key (must be unique).
- `risk_profile` selects `SizingPolicy`, RiskGate `max_position_pct`, and
  HybridBrain confidence/lookback thresholds.
- `llm_model` is passed to `LLMClient(model=...)` for LLM strategies; `None`
  for deterministic strategies.

`build_brain()` is the only place that knows how to translate a config row
into a concrete brain instance. The runner enumerates configs and calls the
factory; it has no per-strategy knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from trader.llm.client import LLMClient
from trader.signals.base import Brain
from trader.signals.classical import classical_aggressive, classical_conservative
from trader.signals.earnings_tone import (
    earnings_tone_gpt4o_mini_aggressive,
    earnings_tone_gpt4o_mini_conservative,
    earnings_tone_haiku_aggressive,
    earnings_tone_haiku_conservative,
)
from trader.signals.hybrid import HybridBrain
from trader.signals.macro_event import macro_event_aggressive, macro_event_conservative
from trader.signals.sentiment_momentum import (
    sentiment_momentum_aggressive,
    sentiment_momentum_conservative,
)
from trader.signals.sizing_policy import (
    SIZING_POLICY_AGGRESSIVE,
    SIZING_POLICY_CONSERVATIVE,
)
from trader.signals.vix_regime import vix_regime_aggressive, vix_regime_conservative
from trader.storage.store import Store

RiskProfile = Literal["conservative", "aggressive"]
Strategy = Literal[
    "vix_regime",
    "hybrid",
    "macro_event",
    "earnings_tone",
    "classical",
    "sentiment_momentum",
]


@dataclass(frozen=True)
class BrainVariantConfig:
    """One row in the horse-race brain matrix."""

    name: str
    strategy: Strategy
    risk_profile: RiskProfile
    llm_model: str | None = None


# Risk-profile dial values for Hybrid. Conservative requires a more confident
# classical base before asking the LLM (saves spend on quiet days); Aggressive
# consults the LLM more often. Breaking-news lookback also varies: Conservative
# treats older breaking events as still gating the LLM, Aggressive only counts
# very recent ones.
_HYBRID_DIALS = {
    "conservative": {
        "classical_confidence_threshold": 0.85,
        "breaking_lookback_hours": 48,
        "policy": SIZING_POLICY_CONSERVATIVE,
    },
    "aggressive": {
        "classical_confidence_threshold": 0.55,
        "breaking_lookback_hours": 12,
        "policy": SIZING_POLICY_AGGRESSIVE,
    },
}


def phase_1_variants() -> list[BrainVariantConfig]:
    """The 6 brain variants shipping in Phase 1."""
    return [
        BrainVariantConfig(name="VIXRegimeConservative", strategy="vix_regime", risk_profile="conservative"),
        BrainVariantConfig(name="VIXRegimeAggressive", strategy="vix_regime", risk_profile="aggressive"),
        BrainVariantConfig(
            name="HybridHaikuConservative",
            strategy="hybrid",
            risk_profile="conservative",
            llm_model="claude-haiku-4-5-20251001",
        ),
        BrainVariantConfig(
            name="HybridHaikuAggressive",
            strategy="hybrid",
            risk_profile="aggressive",
            llm_model="claude-haiku-4-5-20251001",
        ),
        BrainVariantConfig(
            name="HybridGPT4oMiniConservative",
            strategy="hybrid",
            risk_profile="conservative",
            llm_model="gpt-4o-mini",
        ),
        BrainVariantConfig(
            name="HybridGPT4oMiniAggressive",
            strategy="hybrid",
            risk_profile="aggressive",
            llm_model="gpt-4o-mini",
        ),
    ]


def phase_2_variants() -> list[BrainVariantConfig]:
    """The 2 brain variants shipping in Phase 2.

    Deterministic Fed-only macro brain in two profiles. See
    `brain/decisions/2026-05-21-horse-race-phase-2.md`.
    """
    return [
        BrainVariantConfig(
            name="MacroEventConservative", strategy="macro_event", risk_profile="conservative"
        ),
        BrainVariantConfig(
            name="MacroEventAggressive", strategy="macro_event", risk_profile="aggressive"
        ),
    ]


def phase_3_variants() -> list[BrainVariantConfig]:
    """The 4 brain variants shipping in Phase 3.

    LLM-augmented earnings-tone brain over top-10 QQQ 8-Ks (Haiku +
    GPT-4o-mini) x (Conservative + Aggressive). See
    `brain/decisions/2026-05-21-horse-race-phase-3.md`.
    """
    return [
        BrainVariantConfig(
            name="EarningsToneHaikuConservative",
            strategy="earnings_tone",
            risk_profile="conservative",
            llm_model="claude-haiku-4-5-20251001",
        ),
        BrainVariantConfig(
            name="EarningsToneHaikuAggressive",
            strategy="earnings_tone",
            risk_profile="aggressive",
            llm_model="claude-haiku-4-5-20251001",
        ),
        BrainVariantConfig(
            name="EarningsToneGPT4oMiniConservative",
            strategy="earnings_tone",
            risk_profile="conservative",
            llm_model="gpt-4o-mini",
        ),
        BrainVariantConfig(
            name="EarningsToneGPT4oMiniAggressive",
            strategy="earnings_tone",
            risk_profile="aggressive",
            llm_model="gpt-4o-mini",
        ),
    ]


def phase_4_variants() -> list[BrainVariantConfig]:
    """The 4 brain variants shipping in Phase 4.

    Closes the risk-profile dial for the two remaining deterministic
    baseline brains (Classical + SentimentMomentum). See
    `brain/decisions/2026-05-21-horse-race-phase-4.md`.
    """
    return [
        BrainVariantConfig(name="ClassicalConservative", strategy="classical", risk_profile="conservative"),
        BrainVariantConfig(name="ClassicalAggressive", strategy="classical", risk_profile="aggressive"),
        BrainVariantConfig(
            name="SentimentMomentumConservative",
            strategy="sentiment_momentum",
            risk_profile="conservative",
        ),
        BrainVariantConfig(
            name="SentimentMomentumAggressive",
            strategy="sentiment_momentum",
            risk_profile="aggressive",
        ),
    ]


def all_phase_variants() -> list[BrainVariantConfig]:
    """Combined roster across all shipped phases. Add a phase = add an entry here."""
    return [
        *phase_1_variants(),
        *phase_2_variants(),
        *phase_3_variants(),
        *phase_4_variants(),
    ]


def variant_requires_store(config: BrainVariantConfig) -> bool:
    """Variants that read stored events need a Store at construction time.

    LLM brains need it for budget tracking and (earnings_tone) for event
    lookup; macro_event and sentiment_momentum read news_events directly.
    Only `vix_regime` and `classical` are store-free today.
    """
    if config.llm_model is not None:
        return True
    return config.strategy in {"macro_event", "earnings_tone", "sentiment_momentum"}


def max_position_pct_for_profile(profile: RiskProfile) -> float:
    """RiskGate cap per profile. Conservative = 40%, Aggressive = 100%.

    Hard limits (kill switch, daily loss, drawdown freeze, PDT) remain
    identical across profiles — only the sizing ceiling varies.
    """
    return 0.40 if profile == "conservative" else 1.00


def build_brain(
    config: BrainVariantConfig,
    *,
    store: Store | None,
    daily_budget_usd: float,
) -> Brain:
    """Construct a concrete brain instance from one variant config row.

    Single source of truth for strategy → class mapping. Adding a new strategy
    in a later phase means extending this function plus the `Strategy` Literal.

    `store` is required for LLM strategies (used for budget tracking and
    optional event lookups); deterministic strategies ignore it.
    """
    if config.strategy == "vix_regime":
        if config.llm_model is not None:
            raise ValueError(f"vix_regime is deterministic; llm_model must be None (got {config.llm_model!r})")
        if config.risk_profile == "conservative":
            return vix_regime_conservative(name=config.name)
        return vix_regime_aggressive(name=config.name)

    if config.strategy == "macro_event":
        if config.llm_model is not None:
            raise ValueError(f"macro_event is deterministic; llm_model must be None (got {config.llm_model!r})")
        if store is None:
            raise ValueError("macro_event strategy requires a Store (reads news_events)")
        if config.risk_profile == "conservative":
            return macro_event_conservative(store=store, name=config.name)
        return macro_event_aggressive(store=store, name=config.name)

    if config.strategy == "earnings_tone":
        if config.llm_model is None:
            raise ValueError("earnings_tone strategy requires llm_model")
        if store is None:
            raise ValueError("earnings_tone strategy requires a Store (reads news_events)")
        if config.llm_model == "claude-haiku-4-5-20251001":
            factory = (
                earnings_tone_haiku_conservative
                if config.risk_profile == "conservative"
                else earnings_tone_haiku_aggressive
            )
        elif config.llm_model == "gpt-4o-mini":
            factory = (
                earnings_tone_gpt4o_mini_conservative
                if config.risk_profile == "conservative"
                else earnings_tone_gpt4o_mini_aggressive
            )
        else:
            raise ValueError(
                f"earnings_tone strategy does not support llm_model={config.llm_model!r}"
            )
        return factory(store=store, daily_budget_usd=daily_budget_usd, name=config.name)

    if config.strategy == "hybrid":
        if config.llm_model is None:
            raise ValueError("hybrid strategy requires llm_model")
        if store is None:
            raise ValueError("hybrid strategy requires a Store for budget tracking")
        dials = _HYBRID_DIALS[config.risk_profile]
        return HybridBrain(
            llm=LLMClient(model=config.llm_model),
            policy=dials["policy"],
            store=store,
            daily_budget_usd=daily_budget_usd,
            classical_confidence_threshold=dials["classical_confidence_threshold"],
            breaking_lookback_hours=dials["breaking_lookback_hours"],
            name=config.name,
        )

    if config.strategy == "classical":
        if config.llm_model is not None:
            raise ValueError(
                f"classical is deterministic; llm_model must be None (got {config.llm_model!r})"
            )
        if config.risk_profile == "conservative":
            return classical_conservative(name=config.name)
        return classical_aggressive(name=config.name)

    if config.strategy == "sentiment_momentum":
        if config.llm_model is not None:
            raise ValueError(
                f"sentiment_momentum is deterministic; llm_model must be None "
                f"(got {config.llm_model!r})"
            )
        if store is None:
            raise ValueError(
                "sentiment_momentum strategy requires a Store (reads news_events)"
            )
        if config.risk_profile == "conservative":
            return sentiment_momentum_conservative(store=store, name=config.name)
        return sentiment_momentum_aggressive(store=store, name=config.name)

    raise ValueError(f"unknown strategy: {config.strategy!r}")
