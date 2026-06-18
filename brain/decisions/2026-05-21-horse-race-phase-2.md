# Horse-Race Phase 2: MacroEventBrain (Fed-only, Conservative + Aggressive)

## Decision

Add a `MacroEventBrain` to the horse race that trades the SPY/QQQ index off
**Fed monetary-policy events only** (`source="federalreserve.gov"`,
`event_type="fed_commentary"`). Ship two variants: Conservative (high bar,
long lookback, small adjustments) and Aggressive (low bar, short lookback,
large adjustments). Phase 2 of the 5-phase horse race plan from
[`2026-05-21-horse-race-phase-1.md`](2026-05-21-horse-race-phase-1.md).

Total brains per cycle after Phase 2: **11** (was 9 after Phase 1).

## Why

- Of the four signal classes I recommended for SPY/QQQ, **macro event windows
  are the cleanest tradeable channel** — Fed events have a known schedule,
  produce real surprise-vs-consensus moves, and the Fed press-release feed is
  already wired and normalized in `news_events`.
- The existing `SentimentMomentumBrain` is a *broad* news brain (Finnhub +
  Alpaca + Yahoo + Fed + Web all mixed). A Fed-only brain isolates the
  highest-signal channel from the rest, which lets the horse race learn
  whether single-source macro discipline beats noise-mixed sentiment.
- Conservative vs Aggressive on the same Fed feed lets us measure whether
  the *threshold + lookback dial* is what matters, or whether the underlying
  signal is just bad regardless of dial.
- This brain stays deterministic — no LLM. The LLM model axis (Haiku vs
  4o-mini) lives on `HybridBrain` and (Phase 3) `EarningsToneBrain`.

## Non-Goals (Phase 2)

- **NOT** adding CPI/NFP/FOMC-calendar event windows. Those need a calendar
  source we don't currently fetch. Phase 2 is Fed press releases only.
- **NOT** adding surprise-vs-consensus tracking. Requires a consensus
  estimate source (e.g., Bloomberg consensus or BLS embargoed numbers).
  Defer to Phase 2.5 if/when we add such a source.
- **NOT** changing any baseline brain, `RiskGate` hard limit, kill switch,
  or the `BrainVariantConfig` system shipped in Phase 1.
- **NOT** adding LLM features to `MacroEventBrain`.
- **NOT** the leaderboard / horse-race scoring command. Phase 5.

## Architecture Reuse

Phase 1 shipped the foundational machinery so Phase 2 is mostly a new brain
file + two factory rows. Specifically:
- `BrainVariantConfig` already exists. Add a new `strategy` literal value
  `"macro_event"` and extend `build_brain()`.
- `phase_1_variants()` becomes `phase_1_variants()` *plus* `phase_2_variants()`,
  with `all_phase_variants()` (or inline concatenation in `all_brains`) as
  the combined roster.
- Per-variant `RiskGate` already does the right thing via `risk_gate_for()`
  — adding two more variant names just works.
- The Phase 1 LLM-call cap + inter-call sleep don't apply since this brain
  is deterministic (`uses_llm = False`).

## MacroEventBrain — Strategy

**File:** `src/trader/signals/macro_event.py` (new)
**Inputs:** `Store` (reads `news_events` directly, like `SentimentMomentumBrain`)
**Filters applied in store query:**
- `source = "federalreserve.gov"`
- `event_type = "fed_commentary"`
- `published_at >= now - lookback`
**Output:** `Decision(action, target_pct, confidence, reasoning)`
**LLM:** none. `uses_llm = False`.

### Algorithm

1. Pull Fed events in the lookback window.
2. If fewer than `min_events_for_signal` Fed events found → `HOLD` low-confidence
   ("no recent Fed activity; deferring").
3. Compute aggregate sentiment = sum(sentiment_score x recency_weight x credibility) /
   sum(weight). Recency weight uses an exponential decay with profile-specific
   half-life.
4. If `aggregate_sentiment > buy_threshold` and a confirming check passes
   (variant-specific) → bullish: `BUY @ target_long`.
5. If `aggregate_sentiment < sell_threshold` and confirming check passes →
   bearish: `SELL @ target_short` (target_short = 0.0 for both profiles in v0).
6. Else `HOLD @ neutral_target`.

The "confirming check" is the **data interpretation** dial:
- **Conservative** confirming check: requires `>=2` events in the lookback
  with the *same* directional sentiment sign, OR one event with
  `urgency = "breaking"` and `source_credibility >= 0.8`. Single weak Fed
  blurb does NOT move the needle.
- **Aggressive** confirming check: a single event in the lookback with
  `|sentiment_score| >= 0.2` is enough.

This makes the two variants behaviorally distinct — they don't just trade
the same idea at different sizes, they trade *different setups*.

### Conservative dial values

| Param | Value |
|---|---|
| `lookback_days` | 90 |
| `recency_half_life_days` | 14.0 |
| `min_events_for_signal` | 1 |
| `buy_threshold` (aggregate sentiment) | +0.30 |
| `sell_threshold` (aggregate sentiment) | -0.30 |
| `target_long` (on bullish signal) | 0.60 |
| `target_short` (on bearish signal) | 0.00 |
| `neutral_target` (on HOLD) | 0.40 |
| Confirming check | `>=2` same-direction events OR breaking+credible |
| `max_position_pct` (RiskGate) | 0.40 (from existing profile lookup) |

### Aggressive dial values

| Param | Value |
|---|---|
| `lookback_days` | 14 |
| `recency_half_life_days` | 3.0 |
| `min_events_for_signal` | 1 |
| `buy_threshold` (aggregate sentiment) | +0.10 |
| `sell_threshold` (aggregate sentiment) | -0.10 |
| `target_long` (on bullish signal) | 1.00 |
| `target_short` (on bearish signal) | 0.00 |
| `neutral_target` (on HOLD) | 0.50 |
| Confirming check | single event with `|sentiment| >= 0.2` |
| `max_position_pct` (RiskGate) | 1.00 (from existing profile lookup) |

### Constructor validation

- `lookback_days > 0`
- `recency_half_life_days > 0`
- `min_events_for_signal >= 1`
- `buy_threshold > 0` and `sell_threshold < 0`
- All target_pct values in [0, 1]

## Variant Wiring

`src/trader/signals/variants.py` changes:

```python
Strategy = Literal["vix_regime", "hybrid", "macro_event"]


def phase_2_variants() -> list[BrainVariantConfig]:
    return [
        BrainVariantConfig(name="MacroEventConservative", strategy="macro_event", risk_profile="conservative"),
        BrainVariantConfig(name="MacroEventAggressive",   strategy="macro_event", risk_profile="aggressive"),
    ]


def all_phase_variants() -> list[BrainVariantConfig]:
    """Phases 1 + 2 combined. Adding a phase = adding one entry here."""
    return [*phase_1_variants(), *phase_2_variants()]


def build_brain(config, *, store, daily_budget_usd):
    # ... existing vix_regime + hybrid branches ...
    if config.strategy == "macro_event":
        if config.llm_model is not None:
            raise ValueError("macro_event is deterministic; llm_model must be None")
        if store is None:
            raise ValueError("macro_event requires a Store (reads news_events)")
        if config.risk_profile == "conservative":
            return macro_event_conservative(store=store, name=config.name)
        return macro_event_aggressive(store=store, name=config.name)
```

`src/trader/runner.py` change: one-line edit — `all_brains()` enumerates
`all_phase_variants()` instead of `phase_1_variants()`. `risk_gate_for()`
already does the right thing because it scans `phase_1_variants()` + ...
actually `risk_gate_for()` needs the same swap. (See acceptance criteria.)

## Acceptance Criteria

1. **`MacroEventBrain` in `src/trader/signals/macro_event.py`** with the
   algorithm + dial values + constructor validation above.
2. **`macro_event_conservative(store, name=...)` and `macro_event_aggressive(store, name=...)`** factory helpers that mirror `vix_regime_*`.
3. **Extend `Strategy` literal** in `variants.py` to include `"macro_event"`.
4. **Add `phase_2_variants()`** returning two configs (Conservative + Aggressive).
5. **Add `all_phase_variants()`** combining Phases 1+2; runner uses this.
6. **Extend `build_brain()`** with a `macro_event` branch that rejects
   `llm_model is not None` and requires `store is not None`.
7. **Update `runner.all_brains()`** to enumerate `all_phase_variants()`.
8. **Update `runner.risk_gate_for()`** to look up against `all_phase_variants()`.
9. **Tests** (in `tests/financial/`):
    - `test_macro_event_brain.py` — covers: empty store → HOLD; sub-threshold
      sentiment → HOLD; Conservative requires 2 events or breaking+credible;
      Aggressive triggers on single event; bullish → BUY @ target_long;
      bearish → SELL @ target_short; recency decay; constructor validation;
      filter excludes non-Fed events; determinism.
    - `test_variants_phase_2.py` — `phase_2_variants()` returns 2 unique
      names; `all_phase_variants()` returns 8 (6 Phase 1 + 2 Phase 2);
      `build_brain()` produces correct concrete instances; `build_brain`
      rejects invalid combinations for `macro_event`.
10. **All existing tests still pass.** No regressions in 666 tests.
11. **No ruff regressions in `src/trader tests/financial`.**

## Out of Scope (Will Cause PR Rejection If Included)

- LLM features on `MacroEventBrain`
- CPI / NFP / FOMC calendar fetching (Phase 2.5 if ever)
- Leaderboard command (Phase 5)
- Any change to `RiskGate` hard limits
- Any change to existing brain logic
- Reshuffling of `phase_1_variants()` ordering

## Rate-Limit Math

This brain is deterministic — no LLM calls. The per-cycle LLM cap stays at
10/cycle and is untouched. Adding 2 deterministic brains adds zero LLM cost.

## Phase 3-5 Roadmap (Context, Not Phase 2 Work)

| Phase | Brains added | Brains total after |
|-------|--------------|--------------------|
| 1 (shipped) | +6 | 9 |
| **2 (this spec)** | +2 (MacroEvent x {Cons, Agg}) | **11** |
| 3 | +4 (EarningsTone x 2 LLM x 2 risk) | 15 |
| 4 | +4 (Classical / SentimentMomentum risk variants) | 19 |
| 5 | — | `trader-daily leaderboard` command |

## Safety Boundaries

- No live trading. SimBroker only.
- No autonomous LLM order decisions (this brain has no LLM at all).
- Per-brain virtual portfolios remain isolated.
- Existing risk gates apply unchanged to the new variants.

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/ -q
.venv/bin/python -m ruff check src/trader tests/financial
PYTHONPATH=src .venv/bin/python -c "
from trader.signals.variants import all_phase_variants
print('Brain count:', 3 + len(all_phase_variants()))  # 3 baselines + variants
print([v.name for v in all_phase_variants()])
"
```

Expected: 11 brain names total, including `MacroEventConservative` and
`MacroEventAggressive`. All existing tests pass plus the new test file(s).
