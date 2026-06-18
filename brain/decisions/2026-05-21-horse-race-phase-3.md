# Horse-Race Phase 3: EarningsToneBrain (top-10 QQQ 8-Ks × Haiku + 4o-mini × 2 risk)

## Decision

Add an `EarningsToneBrain` that reads SEC 8-K earnings filings for the
top-10 QQQ constituents (already configured in `settings.sec_tickers`),
asks an LLM to extract structured **earnings-tone features** (single call
per cycle, not per filing), and translates those features through a
profile-specific policy into a target position weight. Ship 4 variants:
2 LLM models × 2 risk profiles. Phase 3 of the 5-phase horse race plan.

Total brains per cycle after Phase 3: **15** (was 11 after Phase 2).

## Why

- The top-10 QQQ constituents (AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA,
  AVGO, plus 2 more) account for roughly 50% of QQQ weighting. During
  earnings season (~6 weeks per quarter) the index basically *is* those
  tickers' results.
- SEC 8-K filings for `earnings_surprise`, `guidance_raise`, and
  `guidance_lower` event types are already fetched + normalized by
  [`src/trader/normalization/sec.py`](src/trader/normalization/sec.py)
  and persisted to `news_events`. The raw signal is there.
- The earnings-tone *interpretation* benefits from LLM reasoning: "beat
  but guidance lowered" is bearish even though the headline says beat.
  Sentiment-score alone can't capture that nuance. This is precisely
  the LLM-feature-extraction use case `brain/10_llm_agent_boundaries.md`
  blesses.
- Two LLM models (Haiku + 4o-mini) gives us a genuine **model horse race
  on a task where reasoning matters more than for the Hybrid brain's
  broad-news case**. Earnings tone is text-heavy and structured; this is
  where we'd most expect model differences to show up.

## Non-Goals (Phase 3)

- **NOT** making a separate LLM call per 8-K filing. One call per cycle
  per brain variant. The LLM aggregates across the bundle of recent
  earnings 8-Ks.
- **NOT** adding individual-stock position management. Output is still
  a target_pct for the trade ticker (QQQ).
- **NOT** adding analyst-estimate / consensus data. The LLM reads the
  8-K headlines/summaries we already have and reasons about beat-vs-miss
  *tone* without external consensus context.
- **NOT** changing the per-cycle LLM call cap (stays at 10). Phase 3
  brings total LLM calls per cycle from 4 (Hybrid x 4) to 8 (Hybrid x 4
  + EarningsTone x 4), still under the cap.
- **NOT** persisting LLM-extracted earnings-tone features. Each cycle
  re-extracts. Caching is a Phase-3.5 improvement if cost becomes a
  concern.
- **NOT** the leaderboard. Phase 5.

## Architecture Reuse

Phase 3 leans heavily on Phase 1/2 infrastructure:
- `BrainVariantConfig` already supports `llm_model` → just add an
  `"earnings_tone"` strategy literal value.
- `phase_3_variants()` adds 4 configs (2 LLM models × 2 risk profiles).
- `all_phase_variants()` extends to include Phase 3.
- `build_brain()` gets a new `earnings_tone` branch.
- The LLM call cap + inter-call sleep already cover the new brains
  because they have `uses_llm = True`.

## EarningsToneBrain — Strategy

**File:** `src/trader/signals/earnings_tone.py` (new)
**File:** `src/trader/llm/prompts/earnings_tone.py` (new, prompts)
**File:** `src/trader/signals/earnings_tone_features.py` (new, schema)
**Inputs:** `LLMClient`, `Store`, plus profile-specific dial values.
**LLM:** YES. `uses_llm = True`. One call per cycle per variant instance.
**Output:** `Decision(action, target_pct, confidence, reasoning, llm_*)`.

### Cycle flow

1. Pull recent `news_events` from store filtered by:
   - `source = "sec_edgar"`
   - `event_type IN ("earnings_surprise", "guidance_raise", "guidance_lower")`
   - `published_at >= now - lookback_days`
   - Limit to the configured `sec_tickers` (top-10 QQQ).
2. If fewer than `min_events_for_signal` 8-K events found → `HOLD` low-confidence
   ("no recent earnings activity"). No LLM call.
3. Format the events into a compact bundle for the LLM (ticker, event_type,
   title, published date — one line per event, no body text).
4. Call LLM with structured prompt, parse response as `EarningsToneFeatures`
   (Pydantic with `extra="forbid"`, Literal enums — same boundary pattern
   as `LLMFeatures`).
5. Apply `EarningsTonePolicy.size()` to convert features → target_pct.
   Conservative vs Aggressive differ in policy multipliers AND the
   minimum-confidence threshold required to leave the neutral target.

### LLM output schema (Pydantic, `extra="forbid"`)

```python
class EarningsToneFeatures(BaseModel):
    schema_version: Literal["earnings-tone-v1"]
    aggregate_tone: Literal["bullish", "bearish", "mixed", "neutral"]
    guidance_signal: Literal["raised", "unchanged", "lowered", "mixed", "none_visible"]
    breadth: Literal["all_aligned", "majority_aligned", "split", "single_name_only"]
    confidence: Literal["high", "medium", "low"]
    abstain_reason: str | None = None
```

The LLM is asked to extract these labels from the 8-K headline bundle;
it does NOT decide a trade. Policy decides.

### Policy → target_pct

Both policies start from `neutral_target` and adjust:

```python
@dataclass(frozen=True)
class EarningsTonePolicy:
    version: str
    neutral_target: float
    bullish_target: float       # applied on "bullish" tone + raised guidance
    bearish_target: float       # applied on "bearish" tone + lowered guidance
    require_high_confidence: bool  # Conservative: True; Aggressive: False
    require_majority_breadth: bool # Conservative: True; Aggressive: False
```

Logic:
- If `abstain_reason` is set → `HOLD @ neutral_target`.
- If `require_high_confidence` and `confidence != "high"` → `HOLD @ neutral_target`.
- If `require_majority_breadth` and `breadth in {"split", "single_name_only"}` →
  `HOLD @ neutral_target`.
- If `aggregate_tone == "bullish"`:
  - If `guidance_signal == "lowered"` → conflict → `HOLD @ neutral_target`.
  - Else → `BUY @ bullish_target`.
- If `aggregate_tone == "bearish"`:
  - If `guidance_signal == "raised"` → conflict → `HOLD @ neutral_target`.
  - Else → `SELL @ bearish_target`.
- Otherwise → `HOLD @ neutral_target`.

### Conservative dial values

| Param | Value |
|---|---|
| `lookback_days` | 30 |
| `min_events_for_signal` | 3 |
| `neutral_target` | 0.40 |
| `bullish_target` | 0.60 |
| `bearish_target` | 0.00 |
| `require_high_confidence` | True |
| `require_majority_breadth` | True |
| `max_position_pct` (RiskGate) | 0.40 (from profile lookup) |

### Aggressive dial values

| Param | Value |
|---|---|
| `lookback_days` | 14 |
| `min_events_for_signal` | 1 |
| `neutral_target` | 0.50 |
| `bullish_target` | 1.00 |
| `bearish_target` | 0.00 |
| `require_high_confidence` | False |
| `require_majority_breadth` | False |
| `max_position_pct` (RiskGate) | 1.00 (from profile lookup) |

### Constructor validation

- `lookback_days > 0`
- `min_events_for_signal >= 1`
- All target_pct values in [0, 1]
- LLM client required (cannot be None)
- Store required (reads news_events)

## Variant Wiring

```python
Strategy = Literal["vix_regime", "hybrid", "macro_event", "earnings_tone"]


def phase_3_variants() -> list[BrainVariantConfig]:
    return [
        BrainVariantConfig(
            name="EarningsToneHaikuConservative", strategy="earnings_tone",
            risk_profile="conservative", llm_model="claude-haiku-4-5-20251001",
        ),
        BrainVariantConfig(
            name="EarningsToneHaikuAggressive", strategy="earnings_tone",
            risk_profile="aggressive", llm_model="claude-haiku-4-5-20251001",
        ),
        BrainVariantConfig(
            name="EarningsToneGPT4oMiniConservative", strategy="earnings_tone",
            risk_profile="conservative", llm_model="gpt-4o-mini",
        ),
        BrainVariantConfig(
            name="EarningsToneGPT4oMiniAggressive", strategy="earnings_tone",
            risk_profile="aggressive", llm_model="gpt-4o-mini",
        ),
    ]


def all_phase_variants() -> list[BrainVariantConfig]:
    return [*phase_1_variants(), *phase_2_variants(), *phase_3_variants()]


# `variant_requires_store` already returns True for any LLM brain — no change needed.
```

## Rate-Limit Math

- 4 Hybrid LLM brains + 4 EarningsTone LLM brains = **8 LLM calls per cycle**
- Per-cycle cap stays at 10 → headroom of 2 calls. Phase 4 doesn't add LLM
  brains, so no cap bump needed until Phase 5+ (if a Phase 5 LLM brain is
  added).
- Cost: 8 calls × ~$0.05 = **~$0.40/cycle**. Daily budget cap is $1.00,
  hard halt at $5.00.
- Inter-call sleep already covers this (500ms between LLM brains).

## Acceptance Criteria

1. **`EarningsToneBrain` in `src/trader/signals/earnings_tone.py`** implementing the cycle flow + policy.
2. **`EarningsTonePolicy` dataclass** with versioned multipliers + profile-specific instances.
3. **`EarningsToneFeatures` Pydantic schema** in `src/trader/signals/earnings_tone_features.py` (`extra="forbid"`, Literal enums).
4. **LLM prompt** in `src/trader/llm/prompts/earnings_tone.py` with `SYSTEM_EARNINGS_TONE` and `format_user(events)` helpers. Output ONLY JSON; deterministic policy decides.
5. **4 factory helpers**: `earnings_tone_haiku_conservative`, `earnings_tone_haiku_aggressive`, `earnings_tone_gpt4o_mini_conservative`, `earnings_tone_gpt4o_mini_aggressive`. Each takes `store` + `daily_budget_usd` + optional `name`.
6. **Strategy literal extended** to include `"earnings_tone"`.
7. **`phase_3_variants()`** returning 4 configs.
8. **`all_phase_variants()`** updated to include Phase 3.
9. **`build_brain()`** earnings_tone branch: requires `store` and `llm_model`.
10. **Tests** (in `tests/financial/`):
    - `test_earnings_tone_brain.py` — empty store → HOLD; sub-min events → HOLD (no LLM call); LLM returns abstain → HOLD; Conservative requires high+majority; Aggressive triggers on weak confidence; bullish+raised → BUY; bullish+lowered (conflict) → HOLD; bearish+lowered → SELL; bearish+raised (conflict) → HOLD; filter excludes non-8-K events; constructor validation; uses_llm=True. Use a `FakeLLMClient` returning canned `EarningsToneFeatures` JSON so tests are deterministic and don't hit the real API.
    - `test_earnings_tone_features.py` — schema accepts only Literal values; extra fields raise; `abstain_reason` is optional.
    - `test_variants_phase_3.py` — `phase_3_variants()` returns 4 unique names; `all_phase_variants()` returns 12 (6 + 2 + 4); `build_brain()` produces concrete instances; rejects earnings_tone without llm_model or without store.
11. **All existing tests still pass.** No regressions in 702 tests.
12. **Ruff clean.**

## Out of Scope (Will Cause PR Rejection If Included)

- LLM call per 8-K (must be aggregator pattern)
- LLM tone caching (Phase 3.5 improvement, not Phase 3)
- Per-ticker position management (output is QQQ target only)
- Analyst-consensus integration (no source wired)
- Leaderboard command (Phase 5)
- Any RiskGate hard-limit change

## Phase 4-5 Roadmap (Context)

| Phase | Brains added | Brains total after | LLM brains total |
|-------|--------------|--------------------|-------------------|
| 1 ✅ | +6 | 9 | 4 |
| 2 ✅ | +2 | 11 | 4 |
| **3 (this spec)** | +4 | **15** | **8** |
| 4 | +4 (Classical/SentimentMomentum risk variants) | 19 | 8 |
| 5 | leaderboard | — | — |

## Safety Boundaries

- No live trading. SimBroker only.
- No autonomous LLM order decisions — LLM extracts structured tone features
  only; deterministic `EarningsTonePolicy` sizes.
- Per-brain virtual portfolios remain isolated.
- Existing risk gates apply unchanged.
- LLM call cap + inter-call sleep already cover the 4 new LLM brains.

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

Expected: 15 brain names total including 4 `EarningsTone*` variants. All
existing tests pass plus the 3 new test files.
