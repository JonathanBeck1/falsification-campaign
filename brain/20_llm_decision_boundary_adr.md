# ADR: LLM-as-Analyst Boundary, Cost-Cap Order, Point-in-Time Discipline

Date: 2026-05-19
Status: proposal for discussion. Doc-only. No code yet.
Owner: a collaborator (via Claude Code).

This ADR names three architectural drifts that surfaced during the
post-PR-#10 code review and proposes the smallest set of changes that
re-aligns the codebase with the brain docs the maintainer has already written.
Each drift is small enough that nobody would call it out in a single PR
review — but together they erode the rules `brain/10` / `brain/15` / `brain/16`
were written to enforce.

## Context

After today's seven merged PRs, three rules in the brain docs are being
quietly broken by the code that's supposed to honor them:

1. `brain/10_llm_agent_boundaries.md`: *"LLMs do not make trade decisions."*
2. `brain/15_event_driven_news_trading_system.md` LLM Layer: *"deterministic
   filters first; small/cheap LLM for extraction only when rules are
   uncertain; never let LLM output directly place orders; LLM cost cap."*
3. `brain/08_news_event_schema.md`: *"Latency matters... required timestamps:
   `published_at`, `observed_at`, `ingested_at`, `classified_at`."*

The three drifts are:

### Drift 1 — HybridBrain treats LLM output as a position-sizer

[`src/trader/signals/hybrid.py:50-66`](../src/trader/signals/hybrid.py):

```python
# Risk-off sentiment → trim further
if regime < -0.3 and base.action != "SELL":
    target *= 0.5
    notes.append(f"risk-off (regime={regime:+.2f}) → halved exposure")

# Strong risk-on with bullish technical → keep target
elif regime > 0.5 and base.action == "BUY":
    notes.append(f"risk-on confirmed (regime={regime:+.2f})")

# High event severity → cap exposure
if severity > 0.7:
    target = min(target, 0.5)
    ...

# Fed day → halve risk for the day
if is_fed_day:
    target *= 0.5
```

The LLM's free-form outputs `regime_sentiment`, `event_severity`, and
`is_fed_day` directly multiply `target_pct`. A single hallucinated
`is_fed_day=true` on a random Tuesday silently halves exposure. A
malicious news headline that nudges the LLM toward `regime = -0.9`
silently produces a SELL or a halved position. The audit trail is just
the reasoning string.

This is the LLM functioning as a discretionary risk-sizer with no
versioned policy in between. `brain/10` is explicit that LLMs should
extract structured features and a deterministic rule should decide.

### Drift 2 — Cost cap is reactive, not preventive

The risk gate's `llm_cost_today_usd` check (`brain/15`) is only consulted
*after* `HybridBrain.decide()` has already issued the LLM call. A buggy
retry loop, a multi-brain run, or simply scaling to N brains running on
the same daily snapshot can blow the daily cap before the gate ever
fires. There is also no tier-1 deterministic short-circuit (`brain/15`
"tiered LLM calls"): every run issues one LLM call per HybridBrain
instance, even when the classical signal is highly confident and the
news is sparse.

### Drift 3 — `classified_at` is never populated

Every normalizer (`fed.py`, `yahoo.py`, `finnhub.py`, `sec.py`,
`alpaca_news.py`, `web.py`) sets `observed_at` and `ingested_at` but
leaves `classified_at = None`. `brain/08` requires this timestamp so a
backtest can filter to *"events the classifier had labeled before T"*.
Without it, any backtest that filters by classification state can't be
written, and Milestone 4's honest-backtesting target sits on a foundation
that silently lies about when labels existed.

## Decision

Adopt the three changes below before either the enricher (PR #12 design)
or candidate scoring (Milestone 3) lands more code on top of the current
drift.

### 1. Replace `HybridBrain` sizing with a versioned deterministic policy

**Shape**:

```python
@dataclass(frozen=True)
class LLMFeatures:
    """Strict, schema-validated output the LLM is allowed to produce.
    No free numerics that directly become positions."""
    sentiment_label: Literal["bullish", "bearish", "neutral", "mixed"]
    event_tags: list[Literal["fomc", "earnings", "macro_release", "geopolitical", "none"]]
    severity_bucket: Literal["low", "medium", "high", "breaking"]  # discrete, not float
    abstain_reason: str | None


@dataclass(frozen=True)
class SizingPolicy:
    """Versioned policy that maps LLMFeatures + classical signal → position.

    All thresholds + multipliers are config, not literals. Bumping a
    threshold bumps the policy version. The policy is the audit unit, not
    the LLM."""
    version: str  # e.g. "hybrid-policy-v1"
    risk_off_multiplier: float = 0.5
    high_severity_cap: float = 0.5
    fomc_event_multiplier: float = 0.5

    def size(self, base: Decision, features: LLMFeatures) -> tuple[float, list[str]]:
        ...
```

The current `HybridBrain.decide` body becomes a call into `SizingPolicy.size`,
with the LLM only ever producing `LLMFeatures`. The LLM cannot directly
emit a multiplier or a target_pct. Free-form floats like
`regime_sentiment = -0.73` are replaced by a discrete enum that maps to
known constants via the policy version.

**Why**: the policy version is auditable (a backtest run links to a
specific policy version), the LLM is bound by a strict output schema, and
a hallucinated label has bounded blast radius (one bucket up or down,
not an arbitrary float).

### 2. Tiered LLM calls with preventive cost gate

**Shape**:

```python
def all_brains(settings: Settings) -> list[Brain]:
    ...
    if not _llm_budget_available(store, settings):
        log.info("llm_budget_exhausted_skipping_hybrid", today_cost=store.llm_cost_today())
        return brains  # no HybridBrain
    if _classical_high_confidence_and_no_breaking_news(...):
        log.info("classical_already_decisive_skipping_hybrid")
        return brains  # no HybridBrain
    brains.append(HybridBrain(...))
    return brains
```

Concrete rules:

- Read `store.llm_cost_today()` **before** appending HybridBrain to the
  brain roster, not after the call. The current order means we can spend
  past the cap before the gate fires.
- Tier-1 deterministic short-circuit: if the classical signal's
  confidence > 0.7 AND there are no `urgency=breaking` events in the
  snapshot, the LLM is not invoked. Saves spend on quiet days; matches
  `brain/15`'s "deterministic filters first" rule.
- Optional `TRADER_LLM_DAILY_BUDGET_USD` setting (default $1.00 to match
  `brain/15` LLM cost-cap principle).

### 3. Set `classified_at` in every normalizer

**Shape**: every `*_news_to_events()` function appends
`classified_at=now` to the constructed `Event` records, right after
`event_type` is decided. One-line change per normalizer (6 files). The
schema already has the column.

**Why**: makes `brain/08`'s point-in-time filter writable. Milestone 4
backtests can then filter `WHERE classified_at < as_of` without falling
back to "use `observed_at` and hope nothing reclassifies." Also unblocks
the retrieval primitive in `brain/19` which depends on a real
classification timestamp.

## What this is NOT

- Not a rewrite of `HybridBrain` end-to-end. The classical signal stays
  identical; the LLM-feature-extraction path stays. What changes is the
  *boundary* — what the LLM is allowed to emit and how that's consumed.
- Not a new LLM provider, model, or prompt strategy. The enricher
  proposal (`brain/18`) handles those.
- Not a SaaS-feature-style refactor. These are surgical fixes inside
  existing files.
- Not Milestone 3 candidate scoring. The candidate scorer (which
  `brain/16` puts at Milestone 3) consumes the corrected boundary, but
  this ADR doesn't propose the scorer itself.

## Open questions for the maintainer

1. **Severity buckets**: `low / medium / high / breaking` — agree with the
   four-bucket schema, or want a different granularity? The current
   continuous float `event_severity ∈ [0, 1]` is exactly the surface that
   lets the LLM silently move position size in 0.01 increments.
2. **Tier-1 short-circuit threshold**: I proposed *"classical confidence
   > 0.7 AND no breaking-urgency events."* You may have a stricter or
   looser threshold in mind.
3. **`classified_at` source-of-truth**: should we set it to `now()` (when
   the deterministic classifier ran) or to the future enricher's
   `classified_at` (when the LLM enricher runs)? Proposal: the
   normalizer sets it to `now()` now; when the enricher runs, it stamps a
   new field `enriched_at` so the two are distinguishable.
4. **Sizing policy versioning**: bump the policy version on any threshold
   change? Or only on schema changes? My instinct is the former — every
   policy change wants a clean audit row.

## What this enables once landed

- The enricher proposal (`brain/18`) inherits a clean `LLMFeatures`
  schema to populate. No more free-form severity floats.
- The retrieval proposal (`brain/19`) gets a reliable `classified_at`
  to anchor point-in-time filters against.
- Milestone 3's candidate scorer consumes the deterministic
  `SizingPolicy` instead of having to ignore HybridBrain's
  multiplicative LLM output.
- The cost cap actually caps cost, instead of being a post-facto
  observation.
