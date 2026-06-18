# Horse-Race Phase 4: Classical + SentimentMomentum risk variants

## Decision

Add risk-profile variants for the two existing **deterministic baseline brains**
that don't yet have them: `ClassicalBrain` and `SentimentMomentumBrain`. Each
gets a Conservative + Aggressive variant. Phase 4 of the 5-phase horse race
plan.

Total brains per cycle after Phase 4: **19** (was 15 after Phase 3).

## Why

- Phases 1-3 added 12 variant brains across three strategies (VIX regime,
  Hybrid, MacroEvent, EarningsTone). The two existing baselines
  (`ClassicalBrain` + `SentimentMomentumBrain`) still run as single instances
  with hardcoded thresholds, so they're absent from the risk-profile axis
  of the horse race.
- For the leaderboard in Phase 5 to give us a clean answer about whether
  the *risk-profile dial* matters across strategies, every non-`BuyAndHold`
  brain needs a Conservative + Aggressive pairing. Without that, Classical
  and SentimentMomentum would always look "different" purely because of
  threshold values, not because of strategy logic.
- This is the most mechanical of the four implementation phases — both
  brains already exist, both already support an instance `name` parameter
  from the Phase 1 refactor. Phase 4 mostly adds **constructor kwargs**
  to parameterize the previously-hardcoded thresholds, then adds factory
  helpers and variant configs.

## Non-Goals (Phase 4)

- **NOT** changing the *base* (single-instance) ClassicalBrain or
  SentimentMomentumBrain behavior. Default constructor kwargs MUST
  preserve current behavior exactly. Existing tests pass unchanged.
- **NOT** adding LLM features to either brain — both stay deterministic
  (`uses_llm = False`).
- **NOT** adding new data sources. Classical uses snapshot fields it
  already uses (price, SMA-200, RSI, VIX, yield curve); SentimentMomentum
  uses the same `news_events` source.
- **NOT** the leaderboard. That's Phase 5.
- **NOT** changing the existing single-instance baselines' presence in
  `all_brains()` — they stay. The new variants ADD to the roster, they
  don't replace.

## Architecture Reuse

Phase 4 leans on infrastructure already shipped in Phases 1-3:
- `BrainVariantConfig` already supports any `strategy` + `risk_profile`.
- `phase_4_variants()` adds 4 configs.
- `all_phase_variants()` extends to include Phase 4.
- `build_brain()` gets two new branches (`"classical"` and
  `"sentiment_momentum"`).
- `variant_requires_store()` extends — `sentiment_momentum` requires
  the store; `classical` does not.
- The LLM call cap + inter-call sleep do nothing here because
  `uses_llm = False`.
- Per-variant `RiskGate` works via `risk_gate_for()` — adding variant
  names just works.

## ClassicalBrain — Parameterization

**File:** `src/trader/signals/classical.py` (modify)
**Strategy literal:** add `"classical"`.

### New constructor kwargs (all backward-compatible defaults)

```python
class ClassicalBrain:
    uses_llm = False

    def __init__(
        self,
        *,
        name: str = "ClassicalBrain",
        # NEW knobs — defaults match current hardcoded behavior:
        sma_buffer_pct: float = 0.0,        # require price > SMA200 * (1 + buffer) to BUY
        rsi_overbought: float = 75.0,        # current hardcoded value
        rsi_overbought_target: float = 0.5,  # target when overbought trims fire
        vix_crisis_threshold: float = 30.0,  # current hardcoded value
        vix_crisis_target: float = 0.30,     # current hardcoded value
        curve_inversion_threshold: float = -0.5,  # current hardcoded value
        curve_inversion_target: float = 0.30,     # current hardcoded value
        long_target: float = 1.0,            # full-long target when trend is up
        downtrend_target: float = 0.0,       # target when price < SMA200
    ) -> None:
        # ... validation (see below) ...
```

### Constructor validation

- `sma_buffer_pct >= 0`
- `rsi_overbought` in (0, 100)
- All target_pct values in [0, 1]
- `vix_crisis_threshold > 0`

### Conservative dial values

| Knob | Value | vs default |
|---|---|---|
| `sma_buffer_pct` | 0.01 | requires price > SMA200 * 1.01 (1% buffer) to BUY |
| `rsi_overbought` | 65.0 | trim earlier than default 75 |
| `rsi_overbought_target` | 0.30 | trim deeper (vs default 0.5) |
| `vix_crisis_threshold` | 25.0 | enter crisis mode earlier |
| `vix_crisis_target` | 0.0 | flat in crisis (vs default 0.30) |
| `curve_inversion_threshold` | -0.25 | act on shallower inversion |
| `curve_inversion_target` | 0.0 | flat on inversion (vs default 0.30) |
| `long_target` | 0.70 | not fully long even in good times |
| `downtrend_target` | 0.0 | unchanged |
| `max_position_pct` (RiskGate) | 0.40 | from profile lookup |

### Aggressive dial values

| Knob | Value | vs default |
|---|---|---|
| `sma_buffer_pct` | 0.0 | no buffer (act on any uptrend) |
| `rsi_overbought` | 80.0 | tolerate more overbought |
| `rsi_overbought_target` | 0.7 | trim shallower |
| `vix_crisis_threshold` | 35.0 | enter crisis mode later |
| `vix_crisis_target` | 0.30 | unchanged |
| `curve_inversion_threshold` | -0.5 | unchanged |
| `curve_inversion_target` | 0.30 | unchanged |
| `long_target` | 1.0 | fully long when uptrend |
| `downtrend_target` | 0.0 | unchanged |
| `max_position_pct` (RiskGate) | 1.00 | from profile lookup |

### Factory helpers

```python
def classical_conservative(name: str = "ClassicalConservative") -> ClassicalBrain:
    return ClassicalBrain(
        name=name,
        sma_buffer_pct=0.01,
        rsi_overbought=65.0,
        rsi_overbought_target=0.30,
        vix_crisis_threshold=25.0,
        vix_crisis_target=0.0,
        curve_inversion_threshold=-0.25,
        curve_inversion_target=0.0,
        long_target=0.70,
    )


def classical_aggressive(name: str = "ClassicalAggressive") -> ClassicalBrain:
    return ClassicalBrain(
        name=name,
        rsi_overbought=80.0,
        rsi_overbought_target=0.7,
        vix_crisis_threshold=35.0,
    )
```

## SentimentMomentumBrain — Parameterization

**File:** `src/trader/signals/sentiment_momentum.py` (modify)
**Strategy literal:** add `"sentiment_momentum"`.

The brain already has parameters in its constructor: `lookback_hours`,
`recency_half_life_hours`, `buy_threshold`, `sell_threshold`,
`min_events_for_signal`. Phase 4 adds **one more knob** (`credibility_floor`)
and two factory helpers that supply profile-specific values.

### New constructor kwarg (backward-compatible default)

```python
credibility_floor: float = 0.0,  # current behavior: no filtering
```

`_contribution_for()` should return `None` (skip) when
`event.source_credibility < credibility_floor`.

### Constructor validation (add)

- `credibility_floor` in [0.0, 1.0]
- Existing param validation stays.

### Conservative dial values

| Knob | Value | vs current default |
|---|---|---|
| `lookback_hours` | 24 | tighter than current 48 |
| `recency_half_life_hours` | 4.0 | tighter than current 8.0 |
| `buy_threshold` | 0.30 | higher bar than current 0.15 |
| `sell_threshold` | -0.30 | symmetric |
| `min_events_for_signal` | 5 | higher bar than current 3 |
| `credibility_floor` | 0.7 | reject low-credibility sources |
| `max_position_pct` (RiskGate) | 0.40 | from profile lookup |

### Aggressive dial values

| Knob | Value | vs current default |
|---|---|---|
| `lookback_hours` | 72 | wider window |
| `recency_half_life_hours` | 12.0 | slower decay |
| `buy_threshold` | 0.10 | act on weaker signal |
| `sell_threshold` | -0.10 | symmetric |
| `min_events_for_signal` | 2 | act on fewer events |
| `credibility_floor` | 0.0 | accept all sources |
| `max_position_pct` (RiskGate) | 1.00 | from profile lookup |

### Factory helpers

```python
def sentiment_momentum_conservative(
    *, store: Store, name: str = "SentimentMomentumConservative"
) -> SentimentMomentumBrain:
    return SentimentMomentumBrain(
        store=store,
        lookback_hours=24,
        recency_half_life_hours=4.0,
        buy_threshold=0.30,
        sell_threshold=-0.30,
        min_events_for_signal=5,
        credibility_floor=0.7,
        name=name,
    )


def sentiment_momentum_aggressive(
    *, store: Store, name: str = "SentimentMomentumAggressive"
) -> SentimentMomentumBrain:
    return SentimentMomentumBrain(
        store=store,
        lookback_hours=72,
        recency_half_life_hours=12.0,
        buy_threshold=0.10,
        sell_threshold=-0.10,
        min_events_for_signal=2,
        credibility_floor=0.0,
        name=name,
    )
```

## Variant Wiring

`src/trader/signals/variants.py` changes:

```python
Strategy = Literal[
    "vix_regime", "hybrid", "macro_event", "earnings_tone",
    "classical", "sentiment_momentum",
]


def phase_4_variants() -> list[BrainVariantConfig]:
    return [
        BrainVariantConfig(name="ClassicalConservative", strategy="classical", risk_profile="conservative"),
        BrainVariantConfig(name="ClassicalAggressive",   strategy="classical", risk_profile="aggressive"),
        BrainVariantConfig(name="SentimentMomentumConservative", strategy="sentiment_momentum", risk_profile="conservative"),
        BrainVariantConfig(name="SentimentMomentumAggressive",   strategy="sentiment_momentum", risk_profile="aggressive"),
    ]


def all_phase_variants() -> list[BrainVariantConfig]:
    return [*phase_1_variants(), *phase_2_variants(), *phase_3_variants(), *phase_4_variants()]


def variant_requires_store(config: BrainVariantConfig) -> bool:
    if config.llm_model is not None:
        return True
    return config.strategy in {"macro_event", "earnings_tone", "sentiment_momentum"}


def build_brain(config, *, store, daily_budget_usd):
    # ... existing branches ...
    if config.strategy == "classical":
        if config.llm_model is not None:
            raise ValueError(f"classical is deterministic; llm_model must be None (got {config.llm_model!r})")
        if config.risk_profile == "conservative":
            return classical_conservative(name=config.name)
        return classical_aggressive(name=config.name)

    if config.strategy == "sentiment_momentum":
        if config.llm_model is not None:
            raise ValueError(f"sentiment_momentum is deterministic; llm_model must be None (got {config.llm_model!r})")
        if store is None:
            raise ValueError("sentiment_momentum strategy requires a Store (reads news_events)")
        if config.risk_profile == "conservative":
            return sentiment_momentum_conservative(store=store, name=config.name)
        return sentiment_momentum_aggressive(store=store, name=config.name)
```

No changes needed in `runner.py` — it already enumerates `all_phase_variants()` and uses `risk_gate_for()` which already does the right thing for any variant name.

## Acceptance Criteria

1. **ClassicalBrain constructor extended** with the new kwargs above, all with backward-compatible defaults. Existing tests pass unchanged.
2. **ClassicalBrain decision logic uses the new kwargs** instead of the hardcoded literals (75.0, 30.0, -0.5, etc.).
3. **`classical_conservative()` and `classical_aggressive()` factory helpers** added.
4. **SentimentMomentumBrain constructor extended** with `credibility_floor` kwarg. Existing tests pass.
5. **SentimentMomentumBrain `_contribution_for()` filters on `credibility_floor`.**
6. **`sentiment_momentum_conservative()` and `sentiment_momentum_aggressive()` factory helpers** added.
7. **Strategy literal extended** to include `"classical"` and `"sentiment_momentum"`.
8. **`phase_4_variants()`** returning 4 configs.
9. **`all_phase_variants()`** updated to include Phase 4.
10. **`variant_requires_store()`** extended to mark `sentiment_momentum` as needing a store.
11. **`build_brain()`** gets `"classical"` and `"sentiment_momentum"` branches with appropriate validation.
12. **Constructor validation** in ClassicalBrain rejects `sma_buffer_pct < 0`, `rsi_overbought` out of (0, 100), target_pct values out of [0, 1].
13. **Constructor validation** in SentimentMomentumBrain rejects `credibility_floor` out of [0, 1].
14. **Tests** (in `tests/financial/`):
    - `test_classical_variant.py` — Conservative requires SMA buffer (price exactly at SMA200 does NOT BUY); Conservative trims at RSI=65 (Aggressive doesn't); Conservative goes flat at VIX=25 (Aggressive doesn't); Conservative goes flat on -0.25 curve inversion (Aggressive doesn't); Conservative's `long_target` is 0.70 not 1.0; Aggressive matches default behavior for unmodified knobs; factory helpers set expected dial values; constructor validation rejects bad params.
    - `test_sentiment_momentum_variant.py` — Conservative filters out events with credibility < 0.7; Aggressive accepts all credibility levels; Conservative uses shorter lookback; Aggressive uses longer lookback; factory helpers set expected dial values; constructor validation rejects bad `credibility_floor`.
    - `test_variants_phase_4.py` — `phase_4_variants()` returns 4 unique names; `all_phase_variants()` returns 16 (6+2+4+4); `build_brain()` produces concrete instances; rejects invalid combinations for both new strategies.
15. **All existing tests still pass.** No regressions in 747 tests.
16. **Ruff clean.**

## Out of Scope (Will Cause PR Rejection If Included)

- LLM features on either brain
- New data sources
- Replacing the existing single-instance ClassicalBrain or SentimentMomentumBrain in `all_brains()` — the new variants ADD; baselines stay.
- Leaderboard command (Phase 5)
- Any change to `RiskGate` hard limits
- Reshuffling earlier-phase variant orderings

## Rate-Limit Math

Both new brain classes are deterministic. Phase 4 adds **zero LLM calls per
cycle**. Total LLM calls per cycle stays at 8 (4 Hybrid + 4 EarningsTone),
under the 10/cycle cap.

## Phase 5 Roadmap (Context, Not Phase 4 Work)

After Phase 4 lands, Phase 5 ships the `trader-daily leaderboard` command
that ranks all 19 brains by Sharpe-adjusted return vs buy-and-hold over a
configurable window, with raw return, hit rate, and trade count columns.
M5-prep paper-trading horse race output. NOT M4 backtest evidence.

| Phase | Adds | Brains total | LLM brains |
|-------|------|-------------|-----------|
| 1 ✅ | +6 | 9 | 4 |
| 2 ✅ | +2 | 11 | 4 |
| 3 ✅ | +4 | 15 | 8 |
| **4 (this spec)** | +4 | **19** | 8 |
| 5 | leaderboard command | — | — |

## Safety Boundaries

- No live trading. SimBroker only.
- Both new brain classes are fully deterministic — no LLM.
- Existing risk gates apply unchanged.
- Per-variant `max_position_pct` (Conservative 0.40, Aggressive 1.00);
  hard limits (kill switch, daily loss, drawdown freeze) identical.
- The single-instance ClassicalBrain and SentimentMomentumBrain that
  already run in the daily cycle stay — the variants are additions.

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/ -q
.venv/bin/python -m ruff check src/trader tests/financial
PYTHONPATH=src .venv/bin/python -c "
from trader.signals.variants import all_phase_variants
print('Variant count:', len(all_phase_variants()))
print('Brain count (with store):', 3 + len(all_phase_variants()))  # 3 baselines + variants
"
```

Expected: 19 distinct brain names total including 4 new
`Classical{Conservative,Aggressive}` and `SentimentMomentum{Conservative,Aggressive}`.
All existing tests pass plus the 3 new test files.
