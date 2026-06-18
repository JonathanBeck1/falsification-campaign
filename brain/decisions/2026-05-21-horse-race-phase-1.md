# Horse-Race Phase 1: Brain Variant Wiring + VIXRegime + Hybrid Model/Risk Matrix

## Decision

Build a paper-trading **horse race** across multiple brain variants so we can learn
which strategies and which LLM models produce the cleanest risk-adjusted equity
curves. Phase 1 lands the foundational wiring (instance-based brain names,
variant config, per-variant equity curves) plus two strategy types as the first
horses on the track: a deterministic `VIXRegimeBrain` and the existing
`HybridBrain` matrixed over two LLM models and two risk profiles. Total new
brain instances on `main` after Phase 1: **6**.

## Why

- The codebase already supports per-brain virtual portfolios in `brain_portfolios`
  keyed on `brain.name`, but every brain's `name` is a class attribute. We can
  run exactly one instance per brain class today.
- To compare configurations honestly we need **independent equity curves** per
  variant. That requires `name` to become an instance attribute and the runner
  to enumerate variants from config rather than hardcoded constructors.
- Beyond the wiring, the project's edge-proof plan (`brain/16_edge_proof_mvp_build_plan.md`)
  M5 explicitly expects multiple paper strategies running side-by-side before
  any live trading. This is M5 preparation, not M4 evidence.
- VIX regime is a free, deterministic, low-risk first horse — the VIX is already
  in every snapshot and the rules are ~50 lines. Hybrid × LLM model × risk
  profile is the first LLM horse race because Hybrid already exists and the
  variation surface is purely config.

## Non-Goals (Phase 1)

- **NOT** building MacroEventBrain, EarningsToneBrain, or risk variants of
  Classical/SentimentMomentum — those are Phases 2-4.
- **NOT** building the leaderboard report — that is Phase 5.
- **NOT** enabling live trading. All variants ship as SimBroker-only.
- **NOT** changing kill-switch, daily-loss, drawdown-freeze, or PDT hard limits.
  Aggressive vs Conservative differ on signal + sizing, **not** on hard limits.
- **NOT** producing M4-grade backtest evidence. The horse race is a paper
  pruning tool. Any "winner" still requires the M4 walk-forward gate before
  it can be considered for live capital.

## Architecture Changes

### 1. `brain.name` becomes an instance attribute

Today every brain has `name = "ClassName"` as a class attribute. Change to:

```python
class HybridBrain:
    def __init__(self, *, name: str = "HybridBrain", ...):
        self.name = name
```

Defaults preserve the base name. Variants override at construction time
(e.g., `HybridBrain(name="HybridHaikuConservative", ...)`). The `Brain`
Protocol in `signals/base.py` already declares `name: str`, which matches
either class or instance attribute — no Protocol change needed.

Apply to: `ClassicalBrain`, `SentimentMomentumBrain`, `HybridBrain`,
`BuyAndHoldBrain`, plus the new `VIXRegimeBrain`.

### 2. `Brain.uses_llm` instance property replaces hardcoded name check

Today [`runner.py:278`](src/trader/runner.py#L278):

```python
brain_uses_llm = brain.name in {"HybridBrain"}
```

This breaks the moment we have `HybridHaikuConservative`, etc. Replace with:

```python
class Brain(Protocol):
    name: str
    uses_llm: bool  # NEW
```

Base default `uses_llm = False`. `HybridBrain` and (Phase 3) `EarningsToneBrain`
override to `True`. Runner uses `brain.uses_llm` directly.

### 3. New `BrainVariantConfig` dataclass

Lives in `src/trader/signals/variants.py` (new file):

```python
from dataclasses import dataclass
from typing import Literal

RiskProfile = Literal["conservative", "aggressive"]

@dataclass(frozen=True)
class BrainVariantConfig:
    """One row in the horse-race brain matrix."""
    name: str                      # unique identifier; becomes brain.name + portfolio key
    strategy: str                  # "vix_regime" | "hybrid" | ... (Phase-2+ strategies added later)
    risk_profile: RiskProfile
    llm_model: str | None = None   # None for deterministic brains; "claude-haiku-4-5" or "gpt-4o-mini" for LLM brains
```

### 4. `phase_1_variants()` constructor list

Lives in `src/trader/signals/variants.py`:

```python
def phase_1_variants() -> list[BrainVariantConfig]:
    return [
        BrainVariantConfig(name="VIXRegimeConservative",     strategy="vix_regime", risk_profile="conservative"),
        BrainVariantConfig(name="VIXRegimeAggressive",       strategy="vix_regime", risk_profile="aggressive"),
        BrainVariantConfig(name="HybridHaikuConservative",   strategy="hybrid",     risk_profile="conservative", llm_model="claude-haiku-4-5"),
        BrainVariantConfig(name="HybridHaikuAggressive",     strategy="hybrid",     risk_profile="aggressive",   llm_model="claude-haiku-4-5"),
        BrainVariantConfig(name="HybridGPT4oMiniConservative", strategy="hybrid",   risk_profile="conservative", llm_model="gpt-4o-mini"),
        BrainVariantConfig(name="HybridGPT4oMiniAggressive",   strategy="hybrid",   risk_profile="aggressive",   llm_model="gpt-4o-mini"),
    ]
```

A `build_brain(config, store, settings)` factory function constructs the
right brain class from `config.strategy`, injects `LLMClient(model=config.llm_model)`
for LLM strategies, and applies risk-profile-specific tuning. The factory is
the single source of truth for variant → brain conversion.

### 5. `runner.all_brains()` switches to variant-driven

After the refactor, `all_brains()` returns:
- `BuyAndHoldBrain` (baseline, unchanged)
- Existing `ClassicalBrain` and `SentimentMomentumBrain` (unchanged, still single instances)
- The 6 Phase-1 variant brains, built from `phase_1_variants()`

Total brains per cycle after Phase 1: **9** (was 4).

### 6. Per-cycle LLM-call cap

New setting `trader_max_llm_calls_per_cycle: int = 10` in `config.py`.
Enforced in `runner.run_one_day()`: track call count across all LLM brains in
the cycle, skip any brain whose call would exceed the cap, log + record event.
This is belt-and-suspenders alongside the existing daily-budget gate.

### 7. Inter-LLM-call sleep

500ms `time.sleep(0.5)` between LLM brain calls in the runner loop. Cheap,
defensive, prevents bursting against TPM limits. Skippable in tests via a
`sleep_fn` injection.

## VIXRegimeBrain — Strategy + Dial Values

**File:** `src/trader/signals/vix_regime.py` (new)
**Inputs:** `snapshot.macro.vix` (already populated)
**Output:** `Decision(action, target_pct, confidence, reasoning)`
**LLM:** none. `uses_llm = False`.

Logic: VIX threshold → target_pct mapping. Conservative tightens thresholds
(de-risks earlier); Aggressive widens them (stays long longer).

### Conservative

| VIX | target_pct | rationale |
|-----|------------|-----------|
| < 13 | 1.00 | calm regime, full long |
| 13-17 | 0.70 | normal vol, reduce slightly |
| 17-22 | 0.40 | elevated vol, defensive |
| 22-28 | 0.20 | stressed, minimal exposure |
| ≥ 28 | 0.00 | crisis, flat |

### Aggressive

| VIX | target_pct | rationale |
|-----|------------|-----------|
| < 18 | 1.00 | tolerate higher vol, full long |
| 18-25 | 0.70 | mild reduction |
| 25-32 | 0.40 | defensive only when clearly stressed |
| ≥ 32 | 0.00 | flat only at full crisis |

If VIX is missing from the snapshot (data gap), return `HOLD` with low
confidence. Existing `RiskGate` then sizes naturally.

## HybridBrain Variants — Dial Values

`HybridBrain` already accepts `llm: LLMClient | None`, `policy: SizingPolicy | None`,
and threshold parameters. Variants pass:

### LLM model

Variant `llm_model` → `LLMClient(model=...)` → passed to `HybridBrain(llm=...)`.
Existing client already wraps LiteLLM and handles both providers.

### Risk profile → SizingPolicy

`SizingPolicy` is already versioned + multiplier-based ([`sizing_policy.py`](src/trader/signals/sizing_policy.py)).
Phase 1 adds two pre-built policies:

```python
SIZING_POLICY_CONSERVATIVE = SizingPolicy(
    version="hybrid-policy-conservative-v1",
    risk_off_multiplier=0.3,           # was 0.5; cut harder on bearish signal
    high_severity_cap=0.3,             # was 0.5; cap tighter on "high"
    breaking_severity_cap=0.15,        # was 0.3; cap tighter on "breaking"
    fomc_event_multiplier=0.3,         # was 0.5; cut harder around FOMC
)

SIZING_POLICY_AGGRESSIVE = SizingPolicy(
    version="hybrid-policy-aggressive-v1",
    risk_off_multiplier=0.7,
    high_severity_cap=0.7,
    breaking_severity_cap=0.5,
    fomc_event_multiplier=0.7,
)
```

### Risk profile → HybridBrain thresholds

- `classical_confidence_threshold`: Conservative `0.85` (LLM only triggers if classical is highly confident, otherwise skip-LLM short-circuit fires); Aggressive `0.55` (consult LLM more often)
- `breaking_lookback_hours`: Conservative `48` (older breaking events still gate LLM use); Aggressive `12` (only very recent breaking)

## RiskGate Per-Variant Sizing Caps

Hard limits (kill switch, daily loss, drawdown freeze, PDT) stay **identical**
across variants. The only RiskGate parameter that varies by risk profile is
`max_position_pct`:

- Conservative: `max_position_pct = 0.40` (caps every variant's position at 40%)
- Aggressive: `max_position_pct = 1.00` (full portfolio weight allowed)

The runner builds a `RiskGate` per variant from the profile. All other
RiskGate config (kill switch path, daily loss cap, drawdown freeze threshold,
PDT, LLM cost cap) is shared from `Settings`.

## Storage / Reporting

- `brain_portfolios` already keys on `brain.name` — no schema change. Each
  variant gets its own row, its own cash/position/avg/realized.
- `brain_equity_curve` already keys on `(brain, trade_date)` — no schema change.
- Starting cash per variant: `settings.trader_starting_cash` (currently same
  for all brains; keep that — uniform starting capital makes equity curves
  comparable).
- The Discord summary line in `runner.py` automatically extends to 9 brain
  lines once `all_brains()` returns 9. No new code there.

## Rate-Limit Math (For The Record)

- Anthropic Haiku 4.5 Tier 1: ~50 RPM, ~4000 TPM
- OpenAI 4o-mini Tier 1: 500 RPM
- Pipeline: 1 cycle/day × 4 Hybrid LLM brains = **4 LLM calls/day**
- Cost: 4 × ~$0.05 = ~$0.20/day. Current daily budget cap $1.00, hard halt at $5.00.
- Per-cycle cap: 10 calls. Won't trigger in Phase 1.
- Inter-call sleep: 500ms. Won't trigger TPM limits for any call size.

## Acceptance Criteria

Codex's Phase 1 PR must:

1. **Add `BrainVariantConfig`, `phase_1_variants()`, and `build_brain()` in `src/trader/signals/variants.py`**.
2. **Convert `brain.name` to instance attribute on all 5 existing brain classes**, preserving default class-name values.
3. **Add `uses_llm` property** to all brain classes (`False` everywhere except `HybridBrain` which returns `True`).
4. **Replace `brain.name in {"HybridBrain"}` in `runner.py:278` with `brain.uses_llm`.**
5. **Add `VIXRegimeBrain` in `src/trader/signals/vix_regime.py`** with the thresholds above. `uses_llm = False`.
6. **Add `SIZING_POLICY_CONSERVATIVE` and `SIZING_POLICY_AGGRESSIVE`** in `sizing_policy.py`.
7. **Refactor `runner.all_brains()`** to enumerate variants from `phase_1_variants()` plus the unchanged baseline brains.
8. **Build per-variant `RiskGate`** with the variant's `max_position_pct`.
9. **Add `trader_max_llm_calls_per_cycle: int = 10`** to settings.
10. **Enforce per-cycle LLM call cap** in `runner.run_one_day()` with structured-log warn and `events` row when triggered.
11. **Add 500ms inter-LLM-call sleep** (injectable for tests via a `sleep_fn` runner arg).
12. **Tests** (pytest, in `tests/financial/`):
    - `test_brain_variants.py` — `phase_1_variants()` returns 6 unique names; `build_brain()` produces correct concrete instances; names are unique across the matrix.
    - `test_vix_regime_brain.py` — covers each VIX threshold band for both profiles, missing-VIX → HOLD, edge values, deterministic same-input-same-output.
    - `test_hybrid_variant_construction.py` — Conservative & Aggressive Hybrid variants get correct `SizingPolicy.version`, correct `classical_confidence_threshold`, correct LLM model passed through to client.
    - `test_runner_llm_call_cap.py` — when 4 LLM brains exist and cap is 2, only 2 LLM brains run; cap-skipped events recorded.
    - `test_runner_inter_call_sleep.py` — sleep_fn injected, called between LLM brains, not called between deterministic brains.
13. **All existing tests still pass** — the refactor is backward-compatible because base brain names are preserved as defaults.
14. **No regressions in `ruff check src/trader tests/financial`.**

## Out of Scope (Will Cause PR Rejection If Included)

- Any leaderboard / scoring command
- Any new strategy beyond `VIXRegimeBrain`
- Any risk variant of `ClassicalBrain` or `SentimentMomentumBrain`
- Any change to `RiskGate` hard limits (drawdown freeze threshold, daily loss, kill switch logic)
- Any change to `TRADER_LIVE` default or AlpacaBroker call sites
- Any new external data fetch (Fed calendar, CPI/NFP calendar, earnings calendar)

## Phase 2-5 Roadmap (Context, Not Phase 1 Work)

| Phase | Brains added | Strategy | LLM axis | Risk axis |
|-------|--------------|----------|----------|-----------|
| **1 (this spec)** | 6 | VIXRegime + Hybrid | Hybrid only | Both |
| 2 | 2 | MacroEventBrain (deterministic, Fed-only first) | — | Both |
| 3 | 4 | EarningsToneBrain (top-10 QQQ 8-Ks) | Haiku + 4o-mini | Both |
| 4 | 4 | ClassicalBrain + SentimentMomentumBrain risk variants | — | Both |
| 5 | — | `trader-daily leaderboard` command: 20-row Sharpe-adjusted ranking vs buy-and-hold | — | — |

After Phase 4, total brains running per cycle: **~20** (BuyAndHold + 5 baseline single-instance + 14 matrix variants).

## Branch + PR Conventions

- This spec lives on `claude/horse-race-phase-1-spec` and is opened as a draft PR.
- Codex implements Phase 1 on `codex/horse-race-phase-1` and opens a draft PR
  referencing this spec.
- Subsequent phases get their own spec docs (`brain/decisions/2026-05-XX-horse-race-phase-N.md`)
  and their own paired `codex/horse-race-phase-N` branches.

## Safety Boundaries

- No live trading. `SimBroker` only.
- No autonomous LLM order decisions (per `brain/10_llm_agent_boundaries.md`).
  LLMs continue to extract features; `SizingPolicy` decides.
- Per-brain virtual portfolios remain isolated — one variant cannot affect
  another's cash, position, or equity.
- Existing risk gates apply unchanged to every variant.
- Existing kill switch halts every variant simultaneously.

## Verification (After Codex Lands)

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src/trader tests/financial
PYTHONPATH=src .venv/bin/python -m trader.cli run-once    # smoke: 9 brains run, 9 equity rows written
sqlite3 data/trader.sqlite "select brain, count(*) from brain_equity_curve group by brain order by brain;"
```

Expected: 9 distinct brain names with at least 1 equity row each (after one
successful run-once). No new failures versus pre-Phase-1 main.
