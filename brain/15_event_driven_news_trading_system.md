# Event-Driven, LLM-Augmented News Trading System

Date: 2026-05-19

Status: research/design memo. Not investment advice, not a claim of edge.

This memo assumes the 70 GitHub repos have already been inventoried. It focuses on the system built on top of those components.

## Executive Reality Check

The likely winning path is not "read a headline faster than Citadel." A solo developer on Alpaca cannot compete in the milliseconds-to-microseconds game. Nasdaq advertises sub-50 microsecond co-location round-trip paths for order acknowledgement and market-data tick latency, while Alpaca's own automated-trading risk disclosure says its market data and trade execution are not designed for high-frequency trading. Alpaca has improved its order-management layer, but the retail path still includes internet, broker, routing, spread, queue, and liquidity uncertainty.

The plausible solo edge is slower and narrower:

- underreaction drift after hard-to-parse filings, guidance, and niche company events;
- small/mid-cap situations where capacity is too small for large funds;
- better filtering of stale/duplicated/socially-amplified noise;
- disciplined non-trading when LLM confidence is not grounded in evidence;
- personal workflow edge: faster research and review, not magical autonomous alpha.

My honest prior:

- 5% to 15% chance of finding a small tradable edge before costs if you are disciplined and focus on narrow event classes;
- 1% to 5% chance it survives realistic live costs, slippage, market impact, taxes, and regime changes at meaningful size;
- 20% to 40% chance the infrastructure becomes a useful private research assistant even without autonomous edge;
- 10% to 25% chance of a SaaS fallback producing meaningful revenue if packaged as alerts/research workflow, not as "guaranteed signals";
- 50%+ chance neither trading edge nor SaaS takes off unless distribution, trust, and product focus become serious workstreams.

The fastest way to avoid wasting months: build the point-in-time event database and two honest event-window tests first. Do not build a beautiful autonomous agent before proving any signal survives costs.

## 1. Architecture

### Operating Model

Single server. Docker Compose. No Kubernetes.

Processes:

1. `collector-news`: RSS, news APIs, selected scrapers, Business Insider-style article extraction when allowed, X/Apify pulls.
2. `collector-sec`: SEC company submissions, 8-K, Form 4, 10-Q/10-K ingestion. Respect SEC fair access: max 10 requests/sec and declared User-Agent.
3. `collector-market`: Alpaca bars/quotes/trades, optional Polygon/Massive for richer historical or real-time data.
4. `event-normalizer`: raw payload -> canonical `Event`.
5. `ticker-resolver`: maps text/entities/CIK/source tags -> ticker candidates with confidence.
6. `sentiment-worker`: local FinBERT first; no generic VADER/TextBlob for trading signals.
7. `rag-indexer`: chunks filings and material docs, embeds them, stores vectors.
8. `llm-enrichment-worker`: interprets only selected events and outputs strict JSON with evidence references.
9. `feature-builder`: joins event, market, social, options, and historical context into strategy features.
10. `strategy-engine`: deterministic or ML models convert features into candidate signals.
11. `risk-engine`: hard gate before orders.
12. `execution-worker`: Alpaca paper/live order submission, idempotent client order IDs, fill reconciliation.
13. `monitor-alerts`: phone alerts via ntfy/Discord/Telegram/SMS for fills, drawdowns, errors, high-conviction signals.
14. `research-backtester`: offline walk-forward/event-window testing; not on the live critical path.
15. `dashboard-api`: local web dashboard, optional future SaaS API.

### Data Flow Diagram, In Text

1. Source emits item: article, filing, social post, option-flow row, macro release.
2. Collector saves raw artifact first: HTML/PDF/JSON plus `source_observed_at`.
3. Collector emits `raw_item.created` to Redis Stream.
4. Normalizer dedupes by deterministic content/source key and creates an `Event`.
5. Ticker resolver attaches entities with `confidence`, `role`, and reason.
6. FinBERT/local classifiers add sentiment, urgency, event type, novelty, and source credibility.
7. LLM enrichment runs only if the event is material or ambiguous.
8. RAG retrieves prior filings, prior guidance, recent 8-Ks, and company profile.
9. Feature builder computes market context: gap, volume, spread, volatility, sector move, options volume/OI if available.
10. Strategy engine emits `SignalCandidate`.
11. Risk engine approves, rejects, or converts to alert-only.
12. Execution worker submits Alpaca order and records lifecycle.
13. Monitoring emits alerts and daily audit report.
14. All outputs are queryable by event ID, signal ID, order ID, and run ID.

### Message Bus Choice

Use Redis Streams plus a Postgres outbox table.

Why Redis Streams:

- Redis Streams are append-only logs with consumer groups and acknowledgements, a good fit for small event pipelines.
- They are much lighter operationally than Kafka.
- They allow replay during development and isolate slow LLM workers from fast ingestion.

Why not Kafka now:

- Kafka is excellent for high-throughput, multi-team, long-retention systems. It is operational weight for a solo VPS.
- The current system probably processes hundreds to thousands of events/day, not millions/sec.

Why not NATS JetStream now:

- NATS JetStream is technically strong and gives persistent streams with at-least-once semantics.
- It is a good second choice, but Redis is simpler when you already need Redis for caching/rate limiting.

Why not only Postgres LISTEN/NOTIFY:

- Postgres NOTIFY is useful for lightweight notifications, but payloads are limited and it is not a durable work queue by itself. The official docs describe LISTEN/NOTIFY as simple interprocess communication with an 8000-byte default payload limit.
- Use Postgres as durable state and outbox, not as the entire event bus.

Recommended pattern:

```text
Postgres transaction:
  insert raw_item
  insert outbox_event
background relay:
  read outbox_event where unpublished
  XADD redis stream
  mark outbox_event published
workers:
  XREADGROUP, process, write durable state, XACK
```

This prevents losing a raw item if Redis restarts between scrape and downstream processing.

### Storage Layer

Phase 1:

- Postgres as system of record.
- TimescaleDB extension for bars, quotes, event-time series if volume grows.
- pgvector inside Postgres for RAG.
- Local filesystem or S3-compatible bucket for raw artifacts: compressed JSON, HTML, SEC documents, PDFs.
- DuckDB over Parquet snapshots for research/backtests.
- Redis Streams for event movement, not permanent truth.

Why:

- pgvector keeps vectors near event/entity/filing metadata and avoids managed vector DB spend.
- TimescaleDB hypertables are a clean Postgres-native path for time-series partitioning.
- DuckDB reads/writes Parquet efficiently and is excellent for offline research.

Keep SQLite only for the first local prototype. Move to Postgres before live trading.

### LLM Layer Without Bottleneck

LLM calls must be tiered:

1. Deterministic filters first: dedupe, source freshness, ticker mapping, known event-type regexes, FinBERT.
2. Small/cheap LLM for extraction only when rules are uncertain.
3. Strong LLM only for material events where interpretation changes action.
4. Never let LLM output directly place orders.

Critical-path rule:

- If the trade horizon is seconds to minutes, LLM is not in the order path.
- If the horizon is hours to days, LLM can enrich before signal.
- If LLM is unavailable, the system degrades to alert-only or deterministic strategies.

LLM outputs must include:

- structured JSON schema;
- cited evidence snippets;
- uncertainty;
- explicit "no trade" option;
- model name and prompt version;
- raw output hash;
- validation status.

### Caching

Cache aggressively:

- canonical URL resolution;
- content hash dedupe;
- ticker-resolution aliases;
- CIK-to-ticker mapping;
- SEC filing chunks and embeddings;
- LLM responses keyed by event hash + prompt version + context hash;
- source rate-limit metadata.

Do not cache:

- order/risk decisions;
- live prices beyond short TTL;
- current portfolio state;
- fill status;
- source freshness checks.

### Multi-Tenancy Seams

Do not build SaaS now. But avoid schema choices that make SaaS a rewrite.

[SAAS SEAM] Add nullable/default owner columns later:

```text
tenant_id default 'personal'
user_id nullable
strategy_id
account_id
```

Tables that should be tenant-aware later:

- `signals`
- `orders`
- `alerts`
- `strategy_configs`
- `watchlists`
- `user_api_keys`
- `notification_routes`
- `billing_entitlements`

Tables that can remain global/shared:

- raw public filings;
- normalized public events;
- company master;
- CIK/ticker mappings;
- market data bars;
- embeddings of public filings.

[SAAS SEAM] Separate public data from private decisions:

```text
global_events       shared
global_filings      shared
market_bars         shared
tenant_strategies   private
tenant_signals      private
tenant_orders       private
tenant_alerts       private
```

[SAAS SEAM] Store secrets outside DB now:

- `.env` for Phase 1;
- later Vault/Doppler/1Password/Cloud Secrets;
- schema should reference `credential_ref`, not store raw secret values.

[SAAS SEAM] Use Postgres row-level security later. Postgres supports row security policies that restrict rows per user once enabled.

Do not build now:

- auth;
- billing;
- admin panel;
- per-tenant rate limiting;
- public API;
- team permissions;
- onboarding funnels.

## 2. Latency Budget

### Realistic End-to-End Latency

After your system sees the item:

```text
no LLM, API source:          1 to 5 seconds
with LLM enrichment:         4 to 15 seconds
scraped website source:      30 to 120 seconds
SEC/RSS polling source:      5 to 60 seconds, depending on polling cadence
X/Apify batch actor:         often minutes unless streaming/near-continuous
```

Where seconds go:

```text
source delay/polling         0.5s to minutes
network fetch                100ms to 3s
parse/extract                20ms to 1s
dedupe/ticker mapping        5ms to 200ms
FinBERT/local model          20ms to 500ms CPU; faster on GPU
embedding                    50ms to 500ms API, or local batch
RAG lookup                   10ms to 200ms
LLM call                     1s to 8s typical, longer under load
risk/execution API           100ms to 1s from VPS; broker internals separate
exchange fill                spread/queue/liquidity dependent
```

Consumer hardware:

- Good for 5-second to multi-day horizons.
- Good for parsing, local FinBERT, embeddings batch, event research.
- Not good for headline-to-order races.

Colocation:

- Required for true latency competition.
- Nasdaq co-location advertises sub-50 microsecond order-to-ack and market-data order-to-tick latency.
- This is a different sport from a VPS plus Alpaca.

Honest assessment:

You will not beat institutional news traders on "AAPL headline crossed, buy in 15ms." Your available edge is:

- complexity edge: filings and guidance interpretation;
- patience edge: drift over hours/days;
- capacity edge: trades too small for large funds;
- filtering edge: avoiding stale/duplicated/irrelevant signals;
- risk edge: not forcing trades when the evidence is weak.

## 3. Cost Model

Sources checked:

- Alpaca Basic is free; Algo Trader Plus is $99/month and gives broader stock/options market coverage, including all US stock exchanges and OPRA for options in the current docs.
- Polygon/Massive stock plans: free, $29 Starter, $79 Developer, $199 Advanced for real-time stock data in public pricing.
- Alpaca options trading has no per-contract commission for API users, but regulatory/other fees can apply.
- OpenAI standard short-context prices: GPT-5.4 at $2.50/M input and $15/M output; GPT-5.4-mini at $0.75/M input and $4.50/M output; GPT-5.4-nano at $0.20/M input and $1.25/M output.
- Anthropic current pricing shows Claude Sonnet 4.6 at $3/M input and $15/M output, Opus 4.7 at $5/M input and $25/M output.

### Token Cost Assumption

Assume 500 relevant items/day, 30 days/month.

If every item gets 1,500 input tokens and 300 output tokens:

```text
items/month = 15,000
tokens/month input = 22.5M
tokens/month output = 4.5M
```

Approximate monthly LLM cost:

```text
GPT-5.4-nano      $10 to $20
GPT-5.4-mini      $35 to $60
GPT-5.4           $120 to $180
Claude Sonnet     $135 to $220
Claude Opus       $225 to $350
```

In a sane architecture, only 10% to 30% of items reach an LLM. Local FinBERT/rules handle the rest. That puts realistic Phase 1 LLM spend around $20 to $150/month unless you ask frontier models to read long filings all day.

Embeddings are not the cost problem. `text-embedding-3-small` is commonly listed around $0.02/M tokens; even 100M tokens/month is only a few dollars. Storage and retrieval quality matter more than embedding cost.

### Monthly Run Rate

Hobby / paper:

```text
server/local Mac/VPS          $0 to $20
Alpaca Basic                  $0
SEC/RSS/free news             $0
Apify X                       $5 to $30, depending on pulls
LLM                           $10 to $50
vector DB                     $0, pgvector
alerts                        $0 to $5
total                         $20 to $100/month
```

Starter / small live:

```text
VPS                           $20 to $60
Alpaca Algo Trader Plus        $99
optional Polygon Developer     $79, usually skip if Alpaca suffices
Apify/social                   $15 to $75
LLM                            $50 to $200
backups/monitoring             $5 to $25
vector DB                      $0, pgvector
total                          $190 to $450/month
```

Serious / $50k+ live:

```text
dedicated VPS/server           $80 to $200
Alpaca Algo Trader Plus        $99
Polygon/Massive Stocks Advanced $199, optional redundancy/richer history
options data add-on/vendor     $0 to $200+, depending on Alpaca vs external
paid news/API feeds            $100 to $500+ if added
LLM                            $150 to $600
monitoring/backups             $20 to $75
managed vector DB              $0 to $50, optional
total                          $650 to $1,800/month
```

For $50k capital, $650/month is a 15.6% annual cost hurdle before slippage and taxes. Keep infrastructure lean until edge is proven.

### Polygon vs Alpaca vs Free

Use free sources for research and paper trading.

Use Alpaca Algo Trader Plus first for live Phase 1 because it combines execution and market data for $99/month and keeps integration simple.

Add Polygon/Massive only if:

- you need cleaner historical research data;
- Alpaca rate limits or coverage block you;
- you need a second source to audit data quality;
- options chain history becomes central.

Do not pay for multiple premium feeds before a strategy has passed out-of-sample tests.

### Self-Hosting LLMs

Self-host FinBERT: yes.

Self-host a finance LLM: usually no for solo Phase 1.

Reasons:

- 500 items/day is too small to justify 24/7 GPU.
- APIs are cheaper than a reliable GPU box until volume or privacy constraints get serious.
- Open-weight models can be useful for offline batch experiments, but the operational burden is not the early bottleneck.

## 4. Strategy Inventory

These are research hypotheses, not trade recommendations.

### Earnings Surprise Reaction

Signal:

- standardized unexpected earnings;
- revenue surprise;
- guidance delta vs consensus;
- management tone shift;
- first-hour price/volume confirmation.

Holding period:

- 1 day to 20 trading days.

Position sizing:

- volatility target;
- cap by spread and ADV;
- avoid first minute after release;
- enter after initial liquidity stabilizes or next session.

Expected hit-rate range:

- 52% to 58% if filtered well;
- lower if trading raw "beat/miss" alone.

Why overcrowded:

- PEAD is one of the best-known anomalies.
- Large liquid names react fast.
- Consensus data is expensive and already arbitraged.

How to actually win:

- focus on guidance revisions and revisions vs expectations, not headline EPS;
- avoid mega-caps unless signal is multi-day drift;
- require post-announcement drift confirmation;
- account for concurrent macro events.

### 8-K Material Event Drift

Signal:

- 8-K item type and exhibit content;
- material agreement, CEO/CFO departure, bankruptcy, delisting, going-concern, restatement, cybersecurity incident, financing terms;
- LLM extracts "materiality and direction" with cited text.

Holding period:

- 1 day to 10 days for bad-news drift;
- up to 30 days for financing/restatement/leadership events.

Position sizing:

- small fixed-fractional;
- do not trade illiquid names without spread/volume guard;
- no shorting hard-to-borrow names unless borrow confirmed.

Expected hit-rate:

- 50% to 60% on selected event types;
- payoff asymmetry matters more than raw hit rate.

Why overcrowded:

- SEC filings are public and monitored by funds.

Why still possible:

- filings are verbose, ambiguous, and often underreacted to outside mega-caps.

### FDA Approval/Rejection Trades

Signal:

- PDUFA/adcom calendar;
- FDA approval, CRL, label restriction, safety warning;
- difference between event result and market-implied expectation.

Holding period:

- post-event: intraday to 3 days;
- pre-event: generally avoid unless options pricing is the strategy.

Position sizing:

- very small;
- options-defined risk preferred;
- avoid binary all-in bets.

Expected hit-rate:

- 45% to 60%, but distributions are fat-tailed.

Why overcrowded:

- biotech specialists, options markets, and event funds live here.

How to actually win:

- avoid guessing approval;
- trade post-event misinterpretation, label nuance, or overreaction;
- use options to cap downside.

### M&A Announcement Arbitrage

Signal:

- confirmed acquisition announcement;
- target spread vs offer price;
- deal type: cash, stock, mixed;
- financing, antitrust, shareholder vote, regulatory risk;
- acquirer price response.

Holding period:

- weeks to months.

Position sizing:

- risk-budget by deal break loss;
- diversify across deals;
- hedge acquirer for stock deals.

Expected hit-rate:

- 80% to 95% deal completion, but losers are large.

Why overcrowded:

- merger arb is a professional strategy with dedicated capital.

Solo angle:

- small deals too small for big funds;
- alert/research workflow more useful than autonomous trading.

### Guidance Revision Plays

Signal:

- raised/lowered FY/Q guidance;
- comparison to consensus;
- language changes in earnings call and press release;
- sector-relative confirmation.

Holding period:

- 2 to 30 days.

Position sizing:

- volatility target;
- scale in after confirmation;
- cap earnings-adjacent gap risk.

Expected hit-rate:

- 52% to 60% if consensus comparison is accurate.

Why overcrowded:

- easy headline guidance changes are instant.

Solo angle:

- nuanced guidance language and footnotes.

### Insider Buying Clusters From Form 4

Signal:

- 3+ insiders buying open-market shares within 14 to 30 days;
- exclude option exercises, grants, 10b5-1 mechanical trades, tiny token purchases;
- stronger if CFO/CEO buys after a drawdown.

Holding period:

- 20 to 90 trading days.

Position sizing:

- small portfolio sleeve;
- slow signal, no need for high-speed execution.

Expected hit-rate:

- 53% to 60% if filtered for true open-market cluster buys.

Why overcrowded:

- many screeners already surface Form 4s.

Solo angle:

- quality filters and patience.

### Short-Squeeze Precursor Detection

Signal:

- short interest/float;
- borrow fee/utilization if available;
- social velocity acceleration;
- unusual call volume/open-interest change;
- low float;
- current catalyst;
- price/volume confirmation.

Holding period:

- hours to several days.

Position sizing:

- tiny;
- options-defined risk or no trade;
- hard stop on failed momentum.

Expected hit-rate:

- 35% to 50%, with convex winners if caught early.

Why overcrowded:

- extremely crowded, noisy, and manipulation-prone.

Solo angle:

- use as alerting/research, not core autonomous strategy.

## 5. The Hard Problems

### Ticker Disambiguation

Solution:

1. Build a securities master table: ticker, CIK, exchange, company legal name, aliases, former tickers, products, executives, sector, market cap.
2. Use source metadata first: SEC CIK/ticker, API symbol tags, URL paths.
3. Use entity extraction second: company names, products, people.
4. Use context: "Apple" with iPhone, Tim Cook, Cupertino -> AAPL; "apple prices" in agriculture -> not AAPL.
5. Score each candidate with precision/recall tradeoff.
6. Require a confidence threshold for trading.
7. Allow multi-entity events with primary vs mentioned roles.

No-trade rule:

- If top ticker confidence < 0.85 for single-name strategies, alert-only.

### News That Moves Stocks vs News That Does Not

Raw sentiment is insufficient.

Use a meta-label:

```text
event moved stock if abnormal return or abnormal volume exceeds threshold
within event window after first_seen_at
```

Features:

- event type;
- source credibility;
- novelty vs prior articles;
- surprise vs expectations;
- entity role;
- market cap/liquidity;
- pre-event volatility;
- spread;
- time of day;
- sector/macro context;
- whether price already moved before you saw it.

### Stale News

Store both:

- `published_at`: what source claims.
- `first_seen_at`: when your system saw it.
- `source_first_seen_at`: when vendor says it first saw it, if available.

Trade eligibility:

```text
trade_age = now - max(published_at, first_seen_at)
if trade_age > strategy_max_age: reject
if canonical_url/content_hash already seen: reject duplicate
if article references old event without new facts: reject or alert-only
```

### Pre-Market and After-Hours

Rules:

- use limit orders only;
- reduce size by 50% to 90%;
- require max spread threshold;
- require minimum quote depth/volume;
- skip thin names;
- prefer next regular session for drift strategies.

### LLM Hallucination

Concrete mitigation:

- extraction-only JSON schema;
- evidence-cited claims;
- no evidence, no claim;
- separate "extract facts" from "score event";
- deterministic risk layer ignores unsupported claims;
- cross-check numbers against source text/API fields;
- validate outputs with Pydantic;
- log raw prompt/output;
- require `uncertainty_reason`;
- LLM cannot submit orders.

### Survivorship and Look-Ahead Bias

This is brutal.

Requirements:

- point-in-time universe, including delisted names;
- event `first_seen_at`, not just article `published_at`;
- source availability as it existed then;
- no revised financials unless revision date is modeled;
- no today's ticker list applied to 2019;
- no sentiment labels trained on future price movement unless properly split;
- no filtering by current options availability unless point-in-time availability exists;
- no "we know this was important because the stock moved" features.

### PDT Rule

As of 2026-05-19, the old FINRA pattern day trader rules still matter until the new intraday margin requirements become effective on 2026-06-04. Investor.gov says the new rules replace current PDT/day-trading margin requirements effective 2026-06-04, but brokers have a transition period until 2027-10-20. Your broker may continue old requirements during transition.

Action:

- query Alpaca account rules directly;
- build PDT/intraday-margin guard as broker-configurable;
- do not assume Reddit summaries are enough.

### Slippage for Thin Names

Model:

```text
expected_slippage_bps =
  half_spread_bps
  + volatility_impact_bps
  + participation_penalty
  + gap_risk_penalty
  + halt_risk_penalty
```

Use historical quote/trade data where possible. For thin names, paper fills are almost useless unless you replay actual bid/ask and volume.

## 6. Risk Management Layer

### Position Sizing

Early Phase 1:

- fixed fractional risk per trade: 10 to 25 bps of equity at risk;
- hard max position: 2% to 5% equity per single name;
- max sector exposure: 10% to 20%;
- max correlated event exposure: e.g. no 5 biotech FDA bets at once.

After evidence:

- volatility targeting:

```text
target_dollar_position = equity * target_vol_contribution / asset_vol
```

- Kelly only as a reference:

```text
kelly_fraction ~= edge / variance
actual_fraction = 0.10 to 0.25 * kelly_fraction
```

Never full Kelly in this system. Your parameter estimates are too noisy.

### Kill Switches

Hard stops:

- max daily realized+unrealized loss;
- max peak-to-trough drawdown;
- max open positions;
- max gross exposure;
- max single ticker exposure;
- max unfilled/canceled order rate;
- max LLM spend/day;
- max source outage duration;
- broker account equity mismatch;
- duplicate order detector.

### LLM Circuit Breaker

Trip if:

- schema invalid rate > threshold;
- hallucination checker fails;
- evidence citations missing;
- prompt/output costs spike;
- model changes version unexpectedly;
- same event yields contradictory classifications;
- LLM confidence diverges from deterministic classifier by too much.

When tripped:

- no LLM-based trading;
- deterministic strategies only;
- alert the maintainer.

### Flash Crash or Halt

Rules:

- subscribe to halt/status source if available;
- if symbol halted, freeze new orders and mark position "manual review";
- if market-wide circuit breaker, cancel pending orders except protective exits if allowed;
- if spread widens above threshold, do not market out unless hard kill condition;
- alert phone immediately.

### Options as Insurance

Protective options can cap risk, but they are not free:

- spreads are wider;
- IV is elevated around news;
- contracts decay;
- liquidity can vanish.

Use options for binary biotech/FDA and squeeze strategies, not as a blanket hedge for every equity trade. Stops are not guaranteed in gaps; options define risk better but cost premium.

## 7. Backtesting Methodology

### Point-in-Time News Database

Required columns:

```text
event_id
source
source_item_id
canonical_url
content_hash
published_at
first_seen_at
ingested_at
source_updated_at
entities_json
event_type
classification_version
raw_artifact_path
```

Golden rule:

- strategy code can only see rows where `first_seen_at <= decision_time`.

### Walk-Forward Setup

Example:

```text
2019-2021 train taxonomy/features
2022 validation and thresholds
2023 locked test
2024 forward research test
2025-2026 paper/live shadow
```

Better:

- rolling walk-forward by quarter;
- purged/embargoed splits around overlapping event windows;
- final untouched lockbox period.

### Costs and Slippage

Include:

- commissions/regulatory fees;
- bid/ask spread;
- market impact;
- latency from signal time to executable quote;
- missed fills;
- borrow costs if short;
- options spread/IV crush;
- overnight gap;
- halt risk.

### Why Most News + Sentiment Backtests Are Bad

Common failures:

- use article publish time but scraped article days later;
- use today's ticker universe historically;
- train sentiment model on future-labeled returns;
- ignore duplicate articles and syndication;
- use adjusted prices incorrectly around splits/dividends;
- assume fills at close/next open without spread;
- test hundreds of variants and report the best;
- omit delisted names;
- ignore transaction costs;
- confuse classification accuracy with tradable edge.

### Believable Sharpe

For a solo retail news strategy after costs:

```text
Sharpe < 0.5       probably not worth trading
0.8 to 1.2         plausible if robust and capacity-limited
1.2 to 1.8         good, inspect for bias
2.0+               suspicious unless very low capacity or very short sample
3.0+               assume overfit until proven live
```

Use Deflated Sharpe and multiple-testing corrections. Bailey and Lopez de Prado's Deflated Sharpe Ratio explicitly corrects for selection bias, backtest overfitting, and non-normality. McLean and Pontiff found stock-return predictors declined out-of-sample and post-publication, a reminder that public alpha decays.

## 8. Build Sequence

Assume 20 hours/week solo.

### Weeks 1-2: Data Spine

Goal:

- deterministic event ingestion and storage.

Build:

- Postgres schema;
- raw artifact store;
- Redis Streams;
- SEC/Fed/Alpaca/Yahoo/Finnhub collectors;
- deterministic event IDs;
- source freshness checks;
- basic alerting.

Exit criteria:

- 7 days of events captured without duplicates;
- every event has raw evidence and `first_seen_at`.

### Weeks 3-4: Ticker Resolver + Event Taxonomy

Build:

- CIK/ticker/company master;
- ticker resolver with confidence;
- event taxonomy;
- FinBERT sentiment;
- stale-news rejection;
- first dashboards.

Exit criteria:

- manual audit of 200 events;
- ticker precision >95% on traded events;
- recall tracked but not optimized at expense of false trades.

### Weeks 5-6: Backtesting Harness

Build:

- event-window returns;
- transaction cost/slippage model;
- walk-forward split;
- two strategies only: PEAD/guidance and 8-K drift.

Exit criteria:

- net-of-cost event study report;
- no LLM yet unless used only for labeling historical events with locked prompts.

### Weeks 7-8: RAG + LLM Enrichment

Build:

- SEC filing chunker;
- pgvector;
- LLM extraction JSON schemas;
- evidence citation validator;
- LLM cost tracker.

Exit criteria:

- LLM improves event classification precision on a blind manually reviewed set;
- if not, keep LLM out of trading and use it for research summaries only.

### Weeks 9-10: Paper Trading

Build:

- Alpaca paper execution;
- risk engine;
- fill reconciliation;
- daily reports;
- phone alerts;
- paper/live config separation.

Exit criteria:

- no duplicate orders;
- no stale trades;
- simulated fills reconciled to market quotes;
- strategy decisions reproducible from stored evidence.

### Week 11: Robustness and Failure Injection

Test:

- source outage;
- LLM outage;
- Redis restart;
- Postgres restart;
- Alpaca timeout;
- duplicate source item;
- bad ticker map;
- halted symbol.

Exit criteria:

- all fail closed or alert-only.

### Week 12: Edge Gate

Run:

- locked out-of-sample report;
- paper forward results;
- cost model;
- manual audit.

Decision:

- continue Phase 1 only if at least one strategy has positive net expectancy and credible OOS statistics.
- otherwise pivot to Phase 2 SaaS/research dashboard or stop.

### MVP That Proves The Thesis

MVP is not autonomous trading.

MVP:

- event database;
- ticker resolver;
- FinBERT + event classifier;
- 8-K and earnings/guidance event windows;
- honest backtest with costs;
- paper alerts.

If that cannot show edge, adding LLM agents will probably make it more expensive, not more profitable.

## 9. Edge Detection Framework

### Statistical Gates

For each strategy:

- net alpha t-stat > 2.0 minimum; >2.5 preferred after costs;
- Deflated Sharpe Ratio confidence > 95%;
- White Reality Check or Hansen SPA when comparing many variants;
- bootstrap confidence interval for mean trade return excludes zero;
- probability of backtest overfitting (PBO) < 10% if using combinatorial cross-validation;
- stable performance across time, sectors, liquidity buckets.

### Minimum Sample Size

Rules of thumb:

```text
intraday/news alerts          300 to 1,000 trades preferred
daily event drift             200+ trades minimum
rare FDA/M&A events           50 to 100 events, but treat as weak evidence
single-name strategy          not enough unless repeated across regimes
```

If the strategy only has 30 historical trades, it is a story, not a system.

### Out-of-Sample Protocol

1. Freeze features and code.
2. Freeze strategy universe.
3. Freeze thresholds.
4. Run on lockbox period once.
5. Record every failed variant in `research_trials`.
6. Do not "just tweak one thing" after seeing lockbox results.

Use a trial ledger:

```text
trial_id
hypothesis
code_version
data_version
parameters
in_sample_result
oos_result
accepted/rejected
notes
```

### Paper Trading Duration

Minimum:

- 3 months for strategies with daily signals;
- 6 months for lower-frequency events;
- at least 100 paper signals before sizing up, unless the signal is rare and you accept high uncertainty.

### Red Flags

- great backtest, no live alerts;
- edge concentrated in one month/year;
- edge disappears after adding spread;
- performance from one ticker;
- many parameters;
- high Sharpe but low number of trades;
- trades rely on same-day close price not available at decision time;
- LLM explanations sound good but do not improve blind labels;
- paper fills much better than real quotes.

### Kill Criterion

At week 12, pause Phase 1 if:

- no strategy has positive net OOS expectancy after costs;
- DSR/Reality Check rejects significance;
- paper trading shows worse fill/slippage than modeled;
- ticker/event audit error rate >5% on traded signals;
- expected monthly alpha on realistic capital does not exceed system cost by 3x.

At 6 months, pivot to SaaS or stop if:

- no strategy has 200+ trades or a credible rare-event study;
- no paper strategy tracks backtest within expected confidence intervals;
- live tiny-capital test loses money for explainable structural reasons, not random variance;
- you keep adding data sources instead of improving one validated edge.

## 10. Failure Modes

### Silent Losses

1. Duplicate/stale news trades.

Monitoring:

- duplicate hash rate;
- event age at trade;
- source lag histogram.

Alert:

- any trade from item older than strategy max age.

2. Ticker resolver mistakes.

Monitoring:

- confidence distribution;
- manual audit queue;
- entity ambiguity rate.

Alert:

- traded event with confidence < threshold.

3. Slippage exceeds model.

Monitoring:

- expected vs actual fill;
- spread at decision;
- participation rate;
- missed-fill rate.

Alert:

- average slippage > model by 2x over 20 trades.

4. Source/API drift.

Monitoring:

- schema validation failures;
- per-source count anomaly;
- fetch errors;
- source freshness.

Alert:

- source silent for longer than expected.

5. Regime decay.

Monitoring:

- rolling Sharpe;
- rolling hit rate;
- drawdown vs expected;
- per-event-type degradation.

Alert:

- strategy falls below kill threshold for N trades/days.

### Dramatic Blowups

1. Runaway duplicate orders.

Prevention:

- idempotency key;
- max orders/minute;
- open-order reconciliation;
- broker-side position cap.

Recovery:

- kill switch;
- cancel all open orders;
- flatten only after manual review unless exposure is unsafe.

2. Halted/crashing small-cap position.

Prevention:

- liquidity filters;
- halt status checks;
- no market orders in thin names;
- defined-risk options for binary events.

Recovery:

- freeze strategy;
- alert;
- reprice after reopen;
- no averaging down.

3. LLM hallucinated catalyst triggers trade.

Prevention:

- evidence validator;
- deterministic event fields;
- LLM cannot trade directly.

Recovery:

- disable LLM strategy;
- mark event invalid;
- review prompt/model version;
- add regression test.

## 11. SaaS Fallback Plan

Most sellable components:

- real-time event feed;
- ticker/entity mapping;
- SEC filing summaries;
- watchlist alerts;
- high-conviction event dashboard;
- RAG over filings;
- "why did this stock move?" explainer;
- paper signal tracker.

Minimum additions:

- auth;
- billing;
- tenant-aware configs;
- Postgres RLS or strict app-layer tenant filters;
- rate limiting;
- email/SMS notification preferences;
- legal disclaimers;
- audit logs;
- cancellation/refund flow.

Competition:

- Benzinga Pro: news/squawk/scanners.
- TrendSpider: scanning, backtesting, bots, AI tools; public pricing shows substantial monthly plans plus data fees.
- Trade Ideas: AI scanning/day-trader workflow.
- Unusual Whales: options flow/social-style dashboards, commonly discussed around roughly tens of dollars/month.

Realistic ARR:

```text
side project with no distribution:      $0 to $25k ARR
focused niche product:                  $50k to $250k ARR
strong marketing/community/trust:        $250k to $1M ARR
>$1M ARR:                                hard, requires distribution and credibility
```

Retail traders often say they want fully automated bots, but they usually buy tools that give confidence, alerts, explanations, and community. Fully automated trading SaaS creates trust, compliance, support, and performance-proof problems.

## 12. Honest Reality Check

### What Percentage Find Genuine News Edge?

There is no clean public statistic for "solo retail developers who find durable systematic news alpha." My skeptical estimate:

```text
find backtest alpha:                 30% to 60%
find honest OOS paper alpha:          5% to 15%
find durable live net alpha:          1% to 5%
scale it beyond personal capital:     <1% to 2%
```

Strong dev skills help you avoid garbage infrastructure and bias. They do not create alpha by themselves.

### Public/Semi-Public Systems

Worked or partly worked:

- PEAD and earnings drift have decades of academic evidence, though the easy version is crowded.
- Insider purchase signals have academic evidence, but the effect is slower and filter-sensitive.
- Merger arbitrage has long-lived returns, but it is professionalized and has crash/tail risk.

Failed or likely weak:

- generic news sentiment on mega-cap headlines;
- Twitter/Reddit sentiment without bot/noise controls;
- LLM-generated trade calls with no point-in-time validation;
- backtests using current constituents or stale article timestamps;
- options-flow tailing without knowing buyer/seller/hedge context.

### Expected Outcome for You

Assuming 20 hrs/week, strong dev skills, and discipline:

```text
(a) find edge and trade it profitably solo:              5% to 15%
(b) no durable edge, but useful SaaS/research pivot:     15% to 30%
(c) no edge and SaaS does not take off:                  55% to 80%
```

These are not meant to discourage you. They are meant to keep the build honest.

### Minimum Capital

If monthly fixed cost is:

```text
$200/month  -> $2,400/year
$500/month  -> $6,000/year
$1,000/month -> $12,000/year
```

Then capital needed just to make fixed costs reasonable:

```text
$10k capital:  $200/month is 24% annual hurdle
$25k capital:  $200/month is 9.6%; $500/month is 24%
$50k capital:  $500/month is 12%
$100k capital: $500/month is 6%; $1,000/month is 12%
```

Practical conclusion:

- keep costs under $200/month until paper edge is strong;
- $50k+ is where a lean system can maybe justify paid data;
- options strategies can use less capital but pay with spreads, IV, and tail risk.

## Recommended Stack

Phase 1 stack:

```text
Python 3.12
Postgres + pgvector + optional TimescaleDB
Redis Streams
DuckDB + Parquet for research exports
Alpaca Trading + Algo Trader Plus when live
FinBERT local
OpenAI GPT-5.4-mini/nano or Claude Sonnet for selected enrichment
ntfy or Discord for alerts
Streamlit/Dash/FastAPI dashboard only after edge tests
```

Do not start with:

- Kubernetes;
- Kafka;
- multi-user auth;
- paid premium news feeds;
- autonomous options execution;
- dozens of strategies.

Start with:

- 8-K drift;
- earnings/guidance drift;
- deterministic event database;
- point-in-time backtest.

## Source Anchors

- Alpaca market data plan docs: Basic free vs Algo Trader Plus $99/month, IEX/SIP/OPRA coverage and rate limits: https://docs.alpaca.markets/v1.3/docs/about-market-data-api
- Alpaca options overview: buying power checks and options behavior: https://docs.alpaca.markets/us/docs/options-trading-overview
- Alpaca options commissions support note: https://alpaca.markets/support/what-are-the-commission-fees-per-option-contract
- Alpaca brokerage fee schedule, revised 2026-04-01: https://files.alpaca.markets/disclosures/BrokFeeSched.pdf
- Alpaca automated trading risk disclosure: https://files.alpaca.markets/disclosures/library/RisksAutoTrading.pdf
- Alpaca OMS performance blog: https://alpaca.markets/blog/alpaca-launches-next-gen-order-management-system/
- Polygon/Massive public stock pricing: https://polygon.io/pricing
- OpenAI API pricing: https://developers.openai.com/api/docs/pricing
- Anthropic API pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Pinecone pricing/free tier: https://www.pinecone.io/pricing/
- SEC EDGAR fair access: https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- Investor.gov PDT transition note: https://www.investor.gov/introduction-investing/investing-basics/glossary/pattern-day-trader
- SEC Form 8-K guide: https://www.secfilingguide.com/filings/8k
- Redis Streams docs: https://redis.io/docs/latest/develop/data-types/streams/
- Postgres NOTIFY docs: https://www.postgresql.org/docs/15/sql-notify.html
- pgvector repo/docs: https://github.com/pgvector/pgvector
- Timescale hypertables docs: https://docs.timescale.com/use-timescale/latest/hypertables/
- DuckDB Parquet docs: https://duckdb.org/docs/current/data/parquet/overview.html
- Postgres Row Level Security docs: https://www.postgresql.org/docs/17/ddl-rowsecurity.html
- Nasdaq co-location latency page: https://www.nasdaq.com/solutions/nasdaq-co-location
- FinBERT paper: https://arxiv.org/abs/1908.10063
- ProsusAI FinBERT repo: https://github.com/ProsusAI/finBERT
- PEAD reference summary: https://www.gsb.stanford.edu/faculty-research/working-papers/earnings-releases-anomalies-behavior-security-returns
- McLean and Pontiff anomaly decay summary: https://colab.ws/articles/10.1111/jofi.12365
- Deflated Sharpe Ratio paper mirror: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- Probability of backtest overfitting summary: https://core.ac.uk/display/24041876
- Insider trading returns NBER paper: https://www.nber.org/papers/w6913
- FDA CRL event study example: https://papers.ssrn.com/sol3/Delivery.cfm/6027774.pdf?abstractid=6027774
- Merger arbitrage risk reference: https://www.sciencedirect.com/science/article/pii/S0929119907000181
