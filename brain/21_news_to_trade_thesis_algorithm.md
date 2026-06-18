# News-to-Trade-Thesis Algorithm

Date: 2026-05-20
Status: proposal for discussion. Doc-only.
Owner: a collaborator (via Claude Code).

This is the blueprint for how news becomes a position. It is intentionally
opinionated about *where intelligence lives* in the system: the rules carry
the trading thesis, the model is a text-to-bucket translator. This document
does not propose code yet — it proposes a design that we can build against.

## TL;DR

1. Markets are efficient at speed and data. We can't beat them on either.
   The only edge available to us is **discipline**: a system that ignores
   what most retail traders react to, and reacts to what most retail traders
   ignore.

2. Every news event maps to a small, fixed set of **trading-thesis buckets**.
   Each bucket has a known historical reaction pattern for SPY/QQQ
   (direction, magnitude, time horizon, typical fade window).

3. The LLM **classifies** each event into a bucket. The rules **decide**
   what to do with the bucket. The LLM cannot pick direction, size,
   timing, or whether to trade.

4. We trade **shares of SPY/QQQ only** for the foreseeable future. Options
   are added only after we prove the signal works on shares. Pay-per-trade
   is $0 on Alpaca for shares; spread cost is the real tax.

5. The next things to build are: the `ThesisEngine` that consumes enriched
   events and emits structured theses, a `compare-enrichment-models` CLI
   that A/Bs Haiku vs 4o-mini, and a per-event-type backtester that
   validates whether the historical reaction patterns we encode actually
   hold on our event corpus.

## Design principle: rules-first, model-as-text-decoder

The decision should be clear *before* the model is consulted. The model's
only job is to read text and put it in a labeled box. The boxes, and what
to do with each box, are written down in this document and in code that we
can read, audit, and backtest.

This sounds restrictive. It is. Here's why:

- **LLM hallucinations have unbounded blast radius unless boxed**.
  A model that emits `regime_sentiment = -0.73` directly moves a position.
  A model that emits `sentiment_label = "bearish"` moves a position only
  through a rule we wrote that maps `"bearish" → halve exposure`. We can
  read the rule. We can backtest the rule. We can change the rule on
  Tuesday without re-running the model.

- **Backtesting requires determinism**. If "what the model thinks of this
  headline" changes between Haiku and 4o-mini, between today and next
  Tuesday, between API versions, our backtest is fiction. If the model
  outputs a discrete enum and we compute the thesis from a rule, the
  backtest replays exactly given the same enums.

- **Cost discipline**. A model that's "smart" enough to decide is also
  expensive enough that we can't run it on every event. A model that's
  narrow enough to classify is cheap enough to run on every event,
  cached, with multiple providers as fallback.

- **The market has 30 years of empirical reaction patterns**. We should
  encode those, not re-derive them per request via an LLM.

This is not novel — it's how every actual quant fund works. Citadel does
not ask GPT-5 "should I buy SPY today." Citadel has a thousand rules,
some of which use ML models as feature inputs.

## What the market is and isn't efficient at

We are designing for SPY/QQQ (high-volume, megacap-weighted, deeply
liquid). Be honest about what this means:

**Market IS efficient at:**

- *Speed*. By the time a headline hits our feed, market makers and quant
  funds have already adjusted quotes. Co-located trading systems beat
  retail by ~100ms+. We will not beat this.
- *First-derivative information*. "Fed cuts rates" is priced in within
  seconds. "By how much will the cut move SPY" is consensus within
  minutes. We will not beat this either.
- *Major company-specific announcements during market hours*. Earnings
  before open, M&A press releases — gaps adjust before retail can react.

**Market IS NOT efficient at:**

- *Interpretation under ambiguity*. "Powell said 'patient'" — does that
  mean dovish (no rush to cut) or hawkish (no rush to hike)? The market
  initially settles on a consensus, then **re-prices over 1-4 hours**
  as analysts publish takes. This re-pricing is the window we can play.
- *Multi-source confirmation*. A single Twitter source posts a rumor;
  the market reacts; then real news confirms or denies. Watching for
  confirmation/denial in the 15-60 minute window is a documented edge.
- *Holding through noise*. Most retail traders react to every headline.
  A system that classifies "this is noise" vs "this is signal" and
  holds positions through noise outperforms not by being smarter but
  by **trading less**.
- *Time-decay of news*. The same headline produces different optimal
  trades at t+10min vs t+2h vs t+24h. Most retail systems treat all
  news as instantly actionable.

**Where our edge actually is:**

- Interpretation in the 15-60 minute window when consensus is forming.
- Discipline to ignore noise and hold through it.
- Time-aware response: knowing *when* a signal is actionable, not just
  whether it's actionable.
- Multi-source confirmation thresholds.

That's the entire honest universe of edge available to a retail system on
SPY/QQQ. Everything else is either too fast or too well-priced.

## The news taxonomy

This is the heart of the design. Every event we ingest maps to one of
these buckets. Each bucket has:

- A **direction implication** (long, short, neutral) for SPY/QQQ
- A **time horizon** when the implication is actionable
- A **confidence prior** based on how reliably this pattern has held
- A **confirmation requirement** (yes/no, what counts)
- A **fade behavior** (does the move mean-revert; over what window)

### Macro events (drive SPY/QQQ directly)

**FOMC/Fed events:**

| Sub-bucket | Direction | Horizon | Confidence | Notes |
|---|---|---|---|---|
| `fed_dovish_surprise` | LONG | 1-4h | high | QQQ outperforms SPY (growth > value), bonds rally, USD weakens |
| `fed_hawkish_surprise` | SHORT | 1-4h | high | Growth hit harder than value; SPY outperforms QQQ on the way down |
| `fed_in_line` | NEUTRAL | — | high | Small intraday move, fades in 4-6h. Don't trade. |
| `fomc_minutes_release` | DEPENDS | 1-2h | medium | Wait for first 30min of price action; then trade in direction of move with stop above the pre-release price |
| `fed_chair_speech` | DEPENDS | 1-4h | medium | Same as minutes — first move is consensus interpretation. |

**Macro releases (CPI / PCE / NFP / GDP / Retail Sales):**

| Sub-bucket | Direction | Horizon | Confidence | Notes |
|---|---|---|---|---|
| `cpi_cooler_than_expected` | LONG | 1-2h | high | Equity rally (Fed-easing path); bonds rally |
| `cpi_hotter_than_expected` | SHORT | 1-2h | high | Equity drop on growth fears; banks/value relatively better |
| `nfp_strong_beat` | DEPENDS | 1-4h | medium | Was historically equity-bullish (economy strong); now often bearish (Fed-hawkish risk) — context-dependent on rate cycle |
| `nfp_strong_miss` | SHORT | 1-2h | medium | Recession fear; flight to bonds |
| `gdp_above_consensus` | LONG | 1-4h | low | Less reactive than CPI/NFP; small moves typical |
| `gdp_below_consensus` | SHORT | 1-4h | low | Same — small moves unless dramatic miss |
| `retail_sales_strong` | LONG | 1h | low | Mostly priced in pre-release |
| `retail_sales_weak` | SHORT | 1h | low | Same |

**Geopolitical:**

| Sub-bucket | Direction | Horizon | Confidence | Notes |
|---|---|---|---|---|
| `geopol_escalation_major` | SHORT then mean-revert | -2h, then +24-72h | high | Initial flight to quality; if no further escalation, full mean-reversion |
| `geopol_escalation_minor` | NEUTRAL | — | medium | Most "minor" headlines fade within hours; don't trade |
| `geopol_de_escalation` | LONG | 1-4h | medium | Relief rally; durability depends on how broken the prior status was |
| `trade_policy_tariff_announcement` | SECTOR | 1-2 days | medium | Sector-specific (semis on chip tariffs, autos on auto tariffs); broad index moves only on omnibus tariff packages |

**Regulatory:**

| Sub-bucket | Direction | Horizon | Confidence | Notes |
|---|---|---|---|---|
| `regulatory_action_megacap` | SHORT (named) + SECTOR (contagion) | 1-2 days | medium | Name-specific selloff; sector contagion size depends on whether the stated rationale generalizes |
| `new_rule_announcement` | SECTOR | 1-2 days | medium | Industry-wide reaction; magnitude depends on whether the rule is concrete or aspirational |

### Single-name megacap events (drive SPY/QQQ via weight)

Note: the top 10 names in QQQ are ~50% of the index. AAPL, MSFT, NVDA,
GOOGL, AMZN, META alone are ~40%. Megacap-specific news is broad-index
relevant. Single-name news for sub-1%-weight names is NOT a broad-index
signal.

| Sub-bucket | Direction (single-name) | Broad-index spillover | Horizon | Confidence | Notes |
|---|---|---|---|---|---|
| `megacap_earnings_beat_and_raise` | LONG | 0.2-0.5x | 1 day | high | Stock gaps up; holds gains 3-5 days unless other shoes drop |
| `megacap_earnings_beat_flat_guide` | LONG → fade | -0.1x by EOD | 1 hour, then fade | medium | Gap up; gives back over the day. Don't chase. |
| `megacap_earnings_miss_or_cut` | SHORT | 0.3-0.6x | 1-2 days | high | Sharp gap down; contagion to peers if reason is structural (e.g., AI demand falling) vs idiosyncratic (e.g., supply-chain hiccup) |
| `megacap_ceo_change` | NEUTRAL | — | — | low | Usually no broad-index impact |
| `megacap_major_mna_acquirer` | SHORT (acquirer) | 0.1x | 1 day | medium | Acquirers typically dip on the deal; broad index muted |
| `megacap_major_mna_target` | LONG (target) | 0.0x | — | high | Target rallies; broad-index irrelevant |
| `megacap_scandal_or_lawsuit` | DEPENDS | 0.1x | 1-3 days | low | Severity-dependent; broad-index contagion only if it implicates a sector pattern (e.g., another big-tech antitrust suit) |

### Earnings season patterns

Not single events but a **regime shift** that lasts ~3 weeks per quarter.
The model classifies us into one of these regimes from event clustering:

| Regime | Direction tilt | Confidence | Notes |
|---|---|---|---|
| `earnings_season_strong_start` | LONG | medium | First-week megacaps beating sets the tone; broad index typically grinds higher |
| `earnings_season_weak_start` | SHORT | medium | Early disappointments cascade; broad index reverts |
| `earnings_season_mixed` | NEUTRAL | — | Range-bound; don't trade earnings on broad index |

### Events we explicitly IGNORE

These produce sentiment labels in the enricher but the rules **never act
on them alone**. They can serve as confirmation when other signals align.

- Opinion pieces and op-eds (no new information)
- Analyst notes published during market hours (priced in by close)
- "Whispers" from anonymous sources (unreliable, often plants)
- Retail forum chatter (Reddit, Stocktwits) — too noisy for SPY/QQQ
- Single-name news for non-megacap stocks (weight too low)
- Recycled wire stories (novelty_score < 0.3)

## The decision pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│  Raw news/filing                                                │
│  (Finnhub / Yahoo / Alpaca / SEC / Fed / web)                   │
└───────────────────┬─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  Normalizer (deterministic)                                     │
│  → Event row: entities, asset_scope, urgency, sentiment_score,  │
│    novelty_score, source_credibility, classified_at             │
└───────────────────┬─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  Enricher (LLM, PR #24)                                         │
│  → EnrichmentV1: validated sentiment_label, event_type,         │
│    severity, key_claims with quote grounding                    │
└───────────────────┬─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  ThesisEngine (deterministic) — TO BUILD                        │
│  → Trading-thesis row: bucket, direction, horizon, confidence,  │
│    confirmation_required, fade_window, source_event_id          │
└───────────────────┬─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  Aggregator + macro regime overlay (deterministic) — TO BUILD   │
│  → Combine all open theses for the snapshot                     │
│  → Apply VIX/curve/vol overlays                                 │
│  → Produce a target position                                    │
└───────────────────┬─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  RiskGate (existing) + SimBroker (existing)                     │
│  → Position bounds, kill switch, daily loss limit               │
│  → Paper execution; eventually real                             │
└─────────────────────────────────────────────────────────────────┘
```

The pieces in **TO BUILD** are the next milestone. Everything above them
either exists in main or is in PR #24.

### What ThesisEngine does

Inputs: a single `EnrichmentV1` validated row + the current `Event` row
plus a snapshot of macro context (current VIX, time-of-day, days since
last major event of this type).

Output: a `Thesis` record with:

```python
@dataclass(frozen=True)
class Thesis:
    thesis_id: str
    event_id: str                   # the source event
    bucket: str                     # taxonomy key, e.g. "fed_hawkish_surprise"
    direction: Literal["long", "short", "neutral"]
    horizon_minutes: int            # actionable window
    confidence: Literal["low", "medium", "high"]
    confirmation_required: bool
    fade_window_minutes: int        # when does the move typically mean-revert
    expected_magnitude_pct: float   # historical avg % move
    policy_version: str             # which version of this taxonomy
    created_at: datetime
    rationale: str                  # human-readable, for the dashboard
```

The mapping from (enriched event) → (thesis) is a **lookup table in code**.
No floats, no model calls, no LLM. It's the file you read when you ask
"why did we trade?"

Example:

```python
# In src/trader/thesis/rules.py
def thesis_for(enrichment: EnrichmentV1, event: Event, macro: MacroSnapshot) -> Thesis | None:
    bucket = _classify_bucket(enrichment, event)
    if bucket is None:
        return None  # event explicitly in the IGNORE set
    template = THESIS_TABLE[bucket]
    return Thesis(
        thesis_id=...,
        event_id=event.event_id,
        bucket=bucket,
        direction=template.direction,
        horizon_minutes=template.horizon_minutes,
        ...
    )

THESIS_TABLE = {
    "fed_dovish_surprise": ThesisTemplate(
        direction="long",
        horizon_minutes=120,
        confidence="high",
        confirmation_required=False,
        fade_window_minutes=240,
        expected_magnitude_pct=0.7,
    ),
    ...
}
```

That table IS the algorithm. Every line in it is a hypothesis that should
be backtestable.

### What Aggregator does

A single snapshot can have many open theses (especially during earnings
season). Aggregator:

1. Filters to theses still within their `horizon_minutes` window
2. **Filters out** theses with `confirmation_required=True` whose
   `confirmation_state` is still `"pending"` (see "Confirmation gating"
   below). Pending theses do not contribute to sizing.
3. Weights by confidence (high=1.0, medium=0.5, low=0.25)
4. Sums directional contributions (long=+1, short=-1, neutral=0) into
   a raw `direction_sum` in `[-N, +N]`
5. Applies the macro regime overlay:
   - VIX > 30 → max position halved
   - 10y-2y < -0.5 → max position halved
   - Recent realized vol > 2x trailing avg → max position halved
6. Maps `direction_sum` to `target_pct` in `[0, 1]` (the
   **signed-to-unsigned conversion**):
   - **We do not short shares of SPY/QQQ in v1.** Margin requirements
     and borrow costs are not worth modeling for our retail size, and
     paper trading on Alpaca doesn't simulate short-borrow either.
   - `direction_sum > 0`: scale to long exposure within the regime cap
   - `direction_sum <= 0`: `target_pct = 0` (flat). Short signals
     **reduce existing long**, never open a short.
   - When we someday support real shorting or inverse ETFs (SH/PSQ),
     this mapping changes to `[-1, 1]`. Until then, target_pct is
     unsigned and shorts only deleverage.

This is also a deterministic lookup-and-weight, no LLM.

> Per Codex review 2026-05-20: the signed-exposure rule (target_pct
> always ≥ 0 in v1) and the confirmation-gating filter are *concrete
> rules*, not open questions. They are codified here so the
> ThesisEngine and Aggregator implementations don't have to re-derive
> them from comments.

### Confirmation gating (concrete rule)

A thesis with `confirmation_required=True` enters the Aggregator's
`direction_sum` only after `confirmed_sources >= 2`, where
`confirmed_sources` counts distinct publishers that have reported
substantively the same event within a 6-hour window.

```python
@dataclass(frozen=True)
class Thesis:
    ...
    confirmation_required: bool
    confirmation_state: Literal["pending", "confirmed"] = "pending"
    confirmed_sources: int = 1            # the originating source counts as 1
    confirmation_window_hours: int = 6
```

Concrete rules:

- A bucket whose template has `confirmation_required=True` starts at
  `confirmation_state="pending"`, `confirmed_sources=1`.
- The ThesisEngine, when processing a new event, looks for prior open
  theses with the same `bucket` and overlapping entity scope within
  `confirmation_window_hours`. If found, it increments
  `confirmed_sources` on the existing thesis; when
  `confirmed_sources >= 2`, state flips to `"confirmed"` and the
  thesis becomes eligible for `direction_sum`.
- The Aggregator excludes any thesis with `confirmation_state="pending"`.
  Pending theses still exist (for matching purposes) but contribute 0
  to sizing.

### Required structured-macro data + abstention

Macro buckets (FOMC/Fed, CPI/PCE/NFP/GDP) require **actual values**, not
just scheduled times, to be classifiable. A bucket name like
`fed_dovish_surprise` implies a comparison to consensus — and a surprise
needs a consensus to compare against.

Each macro event must provide this structured payload before the
ThesisEngine will classify it:

```python
@dataclass(frozen=True)
class StructuredMacroData:
    event_type: str           # e.g. "cpi_release", "fomc_rate_decision"
    actual_value: float | None
    consensus_value: float | None
    prior_value: float | None
    revision: float | None     # for releases that revise prior periods
    release_timestamp: datetime
    parse_success: bool        # did we successfully parse the release payload
    provenance: str            # which source provided the structured data
```

**Abstention rules** for macro events:

- `parse_success == False` → ThesisEngine emits a null thesis with
  `abstain_reason="macro_parse_failure"`. No position change.
- `actual_value is None` or `consensus_value is None` → same: abstain.
- Structured data timestamp older than 60 minutes from release → abstain
  (stale data).
- A scheduled time on the economic calendar with **no** structured data
  attached triggers the pre-stage workflow from `brain/22` (alert +
  flat-bias), **not** a trade.

> Per Codex reviews (2026-05-20) of both this doc and `brain/22`: a
> calendar tells you *when*, not *what*. Macro buckets are not
> tradeable on timing alone — the actual-vs-consensus surprise data
> must be present and fresh, or the engine must abstain.

## What the model does and does NOT do

**Does:**

- Classify each event into a taxonomy bucket
  (`fed_hawkish_surprise`, `megacap_earnings_beat_and_raise`, etc.)
- Extract supporting quotes from the article text, grounded against the
  title/summary (PR #24's quote-grounding validator)
- Flag ambiguity via `abstain_reason` — a known case where the rules
  fall back to "ignore this event"

**Does NOT:**

- Pick direction
- Pick size
- Decide whether to execute
- Decide when to execute
- Override risk gates
- Choose between SPY and QQQ
- Compare events to each other
- Generate free-text trading rationale

This is a strict boundary. If a future enrichment schema tries to add a
"trade_recommendation" or "suggested_size" field, it gets rejected at
review.

## Trading mechanism: shares first, options later

For SPY/QQQ specifically, our choices are:

| Vehicle | Pros | Cons | Verdict for v1 |
|---|---|---|---|
| Shares | $0 commission on Alpaca, no theta, no expiry, tax-efficient at long-term | Linear exposure, requires more capital | **YES — default** |
| 0DTE options | Massive leverage on intraday moves | Massive theta, requires tight timing | NO — we don't have timing edge |
| Weekly options | Moderate leverage, ~5d window | Still meaningful theta | LATER — only after share strategy proves profitable |
| Monthly options | Less theta, time for thesis to play out | Capital efficiency vs shares is modest | LATER |
| LEAPS | Synthetic leveraged shares with low theta | Wide spreads, capital-intensive | NO — wrong tool for news-driven |

The reasoning: every option vehicle adds a *second dimension of risk*
(time/IV) that we are not designed to navigate. A news-driven strategy
that wins on direction can lose on theta even when the direction call
was correct. Until we have ≥6 months of paper-trading evidence that the
share strategy works, options are an unnecessary complication.

**When to revisit options:** if the share strategy shows a Sharpe ratio
above 1.0 over 6 months of paper trading with realistic execution costs,
weekly options become a tool for *amplifying* the highest-confidence
theses (high-confidence buckets only, 1-2 day horizon to match weekly
expiry). Never the medium-confidence or low-confidence buckets.

## Edge candidates: where we might actually find alpha

Be honest about which of these are likely to work vs hopeful.

**Likely:**

1. **The discipline of NOT trading noise**. If the rules say "this event
   is in the IGNORE set" and we hold our position, that is a measurable
   improvement over most retail systems. Backtestable: run the
   ClassicalBrain in parallel and measure return-on-event-day.

2. **Time-stop exits**. Most retail systems exit on price (stop loss /
   take profit). Our system exits on time (if the thesis isn't validated
   in `horizon_minutes`, exit). Time-stops handle the "your call was
   right but a different shoe dropped" case that price-stops miss.

3. **Multi-source confirmation thresholds**. Wait for 2+ sources reporting
   the same story before treating it as signal. Slows reaction but
   filters out plant rumors and Twitter noise.

**Maybe:**

4. **Fed-day mean-reversion**. The initial Fed press conference reaction
   reverses ~30% of the time within 4 hours. If we can classify "this
   was the over-reaction direction" we can fade. Backtestable.

5. **Earnings-season regime trades**. First-week megacap results predict
   the 3-week season. Strong signal historically but small sample size
   (only 4 seasons per year).

**Probably hopeful:**

6. **Single-event prediction**. "This specific headline will move SPY
   +0.5%." We will not consistently beat the market on per-event
   prediction. This is the thing most retail systems try and fail at.

7. **Outsmarting the LLM-driven crowd**. As LLM-driven retail tools
   proliferate, "ask Claude what this means" becomes priced in. Our
   bucket taxonomy is a defense against this — we react to known
   patterns, not to model commentary.

## Anti-patterns: what we explicitly will NOT do

1. **Free-text model output influences position size.** Already rejected
   in `brain/20` ADR drift 1. The LLM cannot emit floats that become
   target_pct.

2. **Trading on a single headline within 15 minutes of publication.**
   We can't beat HFT to the punch. The 15-60 minute interpretation
   window is where we play.

3. **Day-trading single names.** The fees are bigger than the edge.
   We trade broad index ETFs only.

4. **Adding new event types ad-hoc.** Every new bucket added to
   `THESIS_TABLE` is a backtest + code review + policy version bump.
   Buckets do not get added because "Claude thinks we should." Buckets
   get added because we observed a reliable pattern in historical data.

5. **Optimizing for backtest Sharpe.** The corpus is small and noisy;
   over-fitting is easy. Buckets are added based on financial reasoning
   first, then validated empirically. Not the other way around.

6. **Running multiple LLM brains in production.** One enricher, one
   policy version, one audit trail. Brain diversity (Classical vs
   Hybrid vs SentimentMomentum) is fine because each consumes
   deterministic inputs. LLM diversity is not, because their outputs
   can't be jointly audited.

## A/B harness spec (for when we have a key)

Per the collaborator's instruction, design (not implement) a CLI that lets us test
Haiku vs OpenAI 4o-mini / 4.1-mini empirically on the enrichment job.

### CLI shape

```bash
trader-daily compare-enrichment-models \
    --source demo_news \
    --limit 50 \
    --model-a claude-haiku-4-5-20251001 \
    --model-b gpt-4o-mini \
    --output output/reports/model-comparison-2026-05-20.md
```

### What it does

1. Pulls N events from the store (filtered by source / time / status)
2. For each event, runs the EnrichmentV1 prompt through model A and B
   in parallel (same prompt, same temperature 0.0, same schema)
3. Validates each output against the schema + quote grounding
4. Records: pass rate, cost per event, latency, output label
5. Computes pairwise agreement metrics:
   - Sentiment label agreement (% exact match)
   - Severity bucket agreement
   - Cohen's kappa on the label sets (corrects for chance agreement)
   - Cost ratio
6. Emits a markdown report with:
   - Summary table (model | pass_rate | avg_cost | avg_latency)
   - Disagreement examples (events where A and B disagreed; human can spot-check)
   - Recommendation: which model wins on cost-per-validated-event

### What "wins" looks like

| Metric | Threshold for "switch to cheaper model" |
|---|---|
| Validation pass rate | Within 5% of Haiku |
| Sentiment label agreement | ≥85% with Haiku |
| Severity bucket agreement | ≥80% with Haiku |
| Cost per validated event | ≥3x cheaper than Haiku |
| End-to-end thesis agreement | ≥90% (do the two label sets produce the same Thesis?) |

If all of these pass, switch. If some pass but thesis agreement is low,
investigate the specific disagreement classes — that's where label
quality actually impacts trades.

### Dependencies

- PR #24 enricher infrastructure (EnrichmentV1, prompts, validator)
- LLMClient with multi-provider support (exists)
- Real `ANTHROPIC_API_KEY` AND `OPENAI_API_KEY`

This harness is the thing that decides which model we run in production.
Build it after PR #24 merges.

## What needs to be built next

Ordered by dependency:

1. **PR #24 merges** (maintainer owns). Enricher + ThesisEngine inputs.

2. **A few days of real enrichment**. ~$2-3 of spend. Build the labeled
   corpus that everything downstream needs.

3. **`brain/22_thesis_engine_proposal.md`** + implementation. The
   `THESIS_TABLE` lookup, the bucket classifier, the Thesis record.

4. **A/B harness** as specified above.

5. **`brain/23_event_study_backtester.md`** + implementation. Tool that
   asks: "For each bucket in THESIS_TABLE, what did SPY/QQQ actually do
   in the historical window?" Validates the patterns empirically. This
   is where buckets get refined or removed.

6. **Aggregator brain + macro regime overlay**. Turns multi-thesis
   snapshots into a target position.

7. **6-month paper trade**. Measure Sharpe, max drawdown, hit rate per
   bucket, cost as % of return.

8. **Decision: do options open up?** Only if step 7 shows real edge.

## Open questions for the maintainer

1. **The taxonomy buckets above** — are there sub-buckets you'd add
   based on your prior work? In particular for single-name megacap
   events, the contagion-magnitude column is a placeholder; if you have
   empirical numbers from your prior project, those should override.

2. **`expected_magnitude_pct`** in the Thesis. Should this be a fixed
   historical average per bucket, or computed from realized volatility
   at decision time? Computed is more correct but more code.

3. **Confirmation requirements threshold.** v1 codifies "2+ distinct
   publishers within a 6-hour window" — see the "Confirmation gating"
   section above. Open question: should the threshold be higher (3+)
   for certain bucket categories (e.g., geopolitical), or should
   specific high-trust sources count as 2 on their own (e.g., a Fed
   official statement)? Default for v1 is the flat 2+ rule; refinement
   is a backtest question.

4. **Time-stop default**. The `horizon_minutes` field is in `Thesis`.
   When the horizon expires, should the position close automatically,
   or just stop being weighted by the aggregator (letting other theses
   keep it open)? I lean toward the latter (smoother position changes)
   but it's a design call.

5. **Does single-name news affect SPY/QQQ position?** I argued yes for
   megacap (>1% weight), no for sub-megacap. Is that the right cutoff?
   AAPL alone is 7% of QQQ; ORCL is 2%; both move the index but
   differently. Pick a weight threshold and we'll codify.

6. **The IGNORE set** — anything I missed that you definitely want
   excluded? In particular, do you want commentary / opinion pieces from
   major outlets (Bloomberg op-eds, WSJ analysis pieces) treated as
   ignore, or as low-confidence signal?

## What this is NOT

- Not the implementation. This is the algorithm description.
- Not a backtest. Backtests come after we have a labeled corpus.
- Not a profitability claim. This is an honest blueprint; whether it
  works is an empirical question.
- Not a permission to add more LLMs to the system. The number of
  LLM-driven brains in production stays at one (HybridBrain) or two
  (HybridBrain + Enricher). The taxonomy approach lets us add brains
  without adding LLMs.

## Closing note

The temptation with LLMs is to ask them more questions. The right move
is to ask them fewer, narrower questions, and put the trading
intelligence in code we can read. This document is the version of "what
the trading intelligence looks like" that we will build against. Every
PR from here onward should either implement a piece of this, refine the
taxonomy with empirical data, or explicitly amend this doc.
