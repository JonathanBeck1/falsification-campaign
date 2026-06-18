# `trader` — Strategic Alignment Briefing

**Date:** 2026-05-23
**Authors:** the maintainer (project lead) + strategic review with Claude
**Audience:** a collaborator and the collaborator's coding agent (Claude Code / Codex)
**Purpose:** Single source of truth on what the project is, what it isn't, and what to build next. Read this before opening another PR.

---

## 1. The headline decision

**`trader` is pivoting from an equity-news-driven trading intelligence platform to a strictly-options project, focused on harvesting the volatility risk premium on SPY/QQQ via defined-risk iron condors.**

Most of the existing code — the 19-variant equity-strategy horse-race, the news adapters feeding equity signals, the equity-execution path — is dead weight for the new project. The methodology hardening done in the last 24 hours (PRs #93, #94, #95) transfers cleanly. The strategic and infrastructure direction does not.

This pivot was discussed and agreed on 2026-05-23 between the maintainer and Claude. The collaborator needs to ratify or push back before more code lands.

---

## 2. The strategic frame

`trader` is no longer a product attempt. It is a personal R&D project with two terminal outcomes:

- **Outcome A — Edge found.** Backtest passes a pre-registered out-of-sample test. The maintainer trades the strategy privately at small size. No SaaS, no open-source, no public writeup. Disclosure destroys the edge — we don't disclose.
- **Outcome B — No edge.** OOS test fails. We publish the negative result like KALSHI-edge (or freeze the repo and use it as portfolio material for quant roles). We do NOT pivot to SaaS to compete with OpenBB or Fincept — they have the audience, contributors, and data-source breadth. Entering that market from behind, after a strategy fails, is the worst possible entry condition.

There is no Outcome C (SaaS fallback). The `brain/13` document's SaaS pivot is removed from the plan.

---

## 3. Why options, and why specifically this slice

### Why options at all

News-driven equity signals (SEC 8-Ks, Fed RSS, FRED macro) on SPY/QQQ are public information sources that institutional money parses milliseconds after publication with dedicated NLP pipelines. The literature is consistent: retail systematic strategies built on parsing public news against efficient liquid markets do not produce sustained edge. KALSHI-edge's -$16.40 / 1,115 bets / -0.47 BSS result is consistent with this, not an outlier. We should expect the same outcome from the existing equity-news track.

Options markets are different. They price *uncertainty*, and retail traders systematically overpay for it (lottery tickets, protection puts, etc.). The flipside — selling that overpriced uncertainty in a disciplined, hedged way — captures the **volatility risk premium (VRP)**: implied vol consistently exceeds realized vol over long horizons, and the gap persists because the demand side (people wanting protection or upside) structurally exceeds the supply side (people willing to underwrite tail risk). It is one of the most-documented persistent retail-accessible edges in finance.

### The specific slice we picked

**Defined-risk short volatility on SPY (with optional QQQ extension), via iron condors at 30-45 days to expiration, 16-delta short strikes.**

The one-sentence hypothesis (this is the hypothesis to write into `brain/26` Q1):

> "Selling 30-45 DTE iron condors on SPY at strikes ~1 standard deviation OTM (~16-delta), with a VIX-regime filter that disables entry when VIX is in the top decile of its trailing 252-day distribution, a 50% profit-take rule, a 2x-credit stop-loss rule, and a 21-DTE time-exit rule, produces positive risk-adjusted returns over a 5+ year backtest after realistic per-contract commissions and slippage."

### Why this specific structure, not others

- **Iron condors** are defined-risk both sides. Selling naked puts or strangles is what blows up retail accounts (Feb 2018, March 2020). Defined-risk caps the disaster scenario at the strike width.
- **30-45 DTE** is the empirical sweet spot for VRP harvest — long enough to collect meaningful theta, short enough to avoid gamma risk.
- **16-delta** is the conventional "one standard deviation OTM" choice. Gives ~84% theoretical win rate at expiration.
- **VIX regime filter** disables the strategy when implied vol is in the top decile. This is when tail events compound; staying out preserves capital.
- **50% profit / 2x stop / 21 DTE time exit** is the TastyTrade convention. Well-validated for VRP harvest specifically.
- **SPY (and QQQ)** because liquidity is excellent, bid/ask spreads are tight, options approval at E*Trade is manageable at Tier 3 (spreads).

### What we rejected

- **Vol-risk-premium via naked short puts** — same edge but tail-risk catastrophic for retail.
- **Earnings IV crush on single names** — real edge but single-name options have worse slippage and don't match the maintainer's SPY/QQQ background.
- **Skew/term-structure trades** — too sophisticated for the first hypothesis test.
- **Gamma scalping / delta-hedged vol trading** — requires intraday execution; E*Trade API and rate limits make this impractical.
- **Directional options trading** — the maintainer's prior approach. Weak evidence of persistence; "made decent money" over a period is consistent with variance during a bull market, not persistent edge.

---

## 4. Realistic numbers (so we agree on what success looks like)

The historical envelope for well-executed retail VRP harvest is:
- Annual returns net of costs: **8-15%** on capital at risk
- Sharpe ratio (deflated, net of selection bias): **0.8 – 1.3**
- Win rate (with 50% profit rule): **80-88%**
- Average win:loss ratio: **1:2 to 1:3** (small frequent wins, larger but capped losses)
- Drawdowns in tail-event years: **20-50%** (Feb 2018: -20% in a week for many VRP strategies; March 2020: -30 to -50%)
- Backtest-to-live degradation: **20-40%** typical, driven by retail-broker slippage

**A passing OOS test means deflated Sharpe ≥ 0.8 net of realistic slippage and commissions, with the worst single trade equal to (not exceeding) the stop-loss level.** A backtest showing Sharpe ≥ 2.0 indicates a bug — almost certainly survivorship bias, look-ahead, or wrong slippage assumptions.

**Win rate alone is the wrong metric.** Expectancy per trade (avg win × win rate − avg loss × loss rate, net of fees) is the only number that matters. Healthy expectancy for a 5-wide SPY iron condor is roughly $5-8 per contract per attempt net of $5-10 commissions and slippage.

---

## 5. Execution constraints (what we can actually do)

**Broker:** E*Trade Power E*Trade. E*Trade has a developer API (developer.etrade.com), OAuth-based, bureaucratic to enroll. It works for execution but is dated compared to IBKR or tastytrade. We accept this constraint because that's where the account is.

**E*Trade API gives real-time options data only. NO historical chains.** This is a hard constraint: we cannot backtest from E*Trade data. We need a separate historical-options-chain provider.

**Recommended data sources for the backtest:**
- **Polygon options** (~$99/month) — best price-quality tradeoff for SPY specifically
- **ORATS** (~$99/month) — better IV term structure data, more institutional
- **CBOE DataShop** — institutional pricing, top quality

Decision required from the maintainer + the collaborator: which data source. Without this picked, the chain-ingestion adapter can't be built.

**Options approval tier at E*Trade:** Tier 3 (vertical spreads) is sufficient for iron condors. Tier 4 (naked) is not needed and we don't go there.

**Account size implications:** Iron condors with $5-wide spreads at 16-delta produce ~$1.00 credit and ~$400 max loss per contract. Sizing at 1-2% of account per trade implies meaningful minimum capital — strategy is capital-efficient at $25K+ accounts. Below that, per-trade granularity is rough.

---

## 6. Build plan for the options track

### What transfers from the existing build (keep, don't rebuild)

- **PR #93** — `brain/25_horse_race_protocol.md` and `brain/26_alignment_2026Q2.md` skeletons. The hypothesis section in brain/26 needs to be replaced with the options hypothesis above.
- **PR #94** — Deflated Sharpe column. Hypothesis-agnostic. Keeps as-is.
- **PR #95** — Locked OOS filter + `leaderboard-oos` CLI. Hypothesis-agnostic. Keeps as-is.
- The Streamlit dashboard scaffolding (deprioritize the equity-strategy tabs; we'll add an options-specific view later if useful)
- The point-in-time event-storage discipline and SQLite schema (transfers cleanly to options data)
- The risk-gate architecture (`RiskGate.max_position_pct`, `SizingPolicy`) — extends naturally to options sizing
- The pre-registration culture in `brain/` docs (the entire methodology rigor)

### What's dead weight (stop investing in)

- The 19-variant equity-strategy matrix in `signals/variants.py` (ClassicalBrain, VIXRegime equity sizing, MacroEvent equity entry, EarningsTone, HybridBrain on equities, SentimentMomentum) — all of these are equity strategies. Don't delete them yet (they may inform a regime feature later), but don't invest more in them.
- The news adapters (Alpaca News, Finnhub, Yahoo News) — these were feeding the equity-news hypothesis we're abandoning.
- The events backfill plan (Fed RSS, SEC EDGAR 8-K backfills, FRED macro releases as event triggers) — these were inputs to equity strategies. VIX as a regime feature comes from price data, not from these sources.
- The horse-race "leaderboard" interpretation as a strategy-selection tool — we have one strategy, not 19.

### What needs to be built (new infrastructure for options)

| Component | Est. effort | Notes |
|---|---|---|
| Historical options chain adapter | 1-2 days | Once the maintainer picks Polygon vs ORATS vs CBOE |
| Options chain storage schema (SQLite) | half-day | Schema: expiration, strike, type, bid, ask, mark, IV, delta, gamma, theta, vega, OI, volume, ts |
| Greeks computation utilities | half-day | `py_vollib` if vendor doesn't provide Greeks; vendor data preferred |
| IV surface storage / query layer | half-day | For the VIX regime filter and for IV-rank features |
| **Options-aware backtest engine** | **3-5 days** | The biggest piece. Walks dates, builds positions, applies exits, tracks P&L with realistic slippage |
| Iron condor strategy "brain" | 1-2 days | Entry rule, exit rules, sizing |
| VIX regime feature (extension) | half-day | Read VIX, compute 252d percentile, gate entry |
| E*Trade execution adapter | 3-5 days | OAuth flow, options orders, position queries — only after backtest passes |

Total estimate: ~2-3 weeks of focused work to land the backtest infrastructure and run the OOS test. E*Trade execution adapter is deferred until backtest passes.

---

## 7. The phased plan (replaces the previous build plan)

### Phase 0 — Alignment (this week)

- The maintainer and the collaborator both sign off on this document.
- `brain/26_alignment_2026Q2.md` (in PR #93) is updated with the options hypothesis from Section 3, default thresholds (deflated Sharpe ≥ 0.8, hit rate ≥ 80%, sample size ≥ 30 trades in OOS window, $0.05-0.10/contract slippage, $0.65/contract commission), off-ramp choice (the maintainer picks).
- `brain/25_horse_race_protocol.md` either gets revised to be a single-strategy OOS protocol (no horse-race), OR is closed and replaced with a single-strategy pre-registration doc.
- PR triage of the existing 10-PR stack (#82–92): most likely **DEFER** or **CLOSE** all of them under the new direction. The collaborator to comment on each.

### Phase 1 — Options data infrastructure (1 week)

- Pick data vendor (Polygon options recommended).
- Build chain ingest adapter, storage schema, Greeks computation, IV surface storage.
- Backfill historical SPY chains for the selection window (e.g. 2018-01-01 through today minus 90 days) and the locked OOS window (last 90 days).

### Phase 2 — Backtest engine and strategy (1-2 weeks)

- Build the options-aware backtest engine.
- Implement the iron condor strategy brain per Section 3 hypothesis.
- Run the strategy on the selection window only. Compute composite metrics including deflated Sharpe (PR #94 already provides this).

### Phase 3 — The decision (1 day)

- Run `trader leaderboard-oos --variant iron_condor_spy --since <oos_cutoff>` exactly once (PR #95 already provides this).
- Compare OOS metrics to brain/26 thresholds.
- Write `brain/28_decision_2026Q3.md` with PASS or FAIL.

### Phase 4a — If pass: private deployment

- Paper trade via SimBroker for 60 days at full pre-declared sizing.
- If paper Sharpe ≈ OOS Sharpe (within 1 SE), build the E*Trade execution adapter.
- Live at small size only after that.

### Phase 4b — If fail: off-ramp

- Execute the off-ramp the maintainer picked in brain/26 Q4.
- No SaaS pivot.

---

## 8. Open decisions still gating the next code

1. **Collaborator: do you agree with this pivot?** If you push back, that's the conversation to have before any more PRs land.
2. **Options data vendor.** Polygon options (recommended), ORATS, or CBOE DataShop. Subscription cost is real but it's the only path to a clean backtest.
3. **Disposition of the 10 open PRs.** Defer or close each? The collaborator to review.
4. **Off-ramp choice in brain/26 Q4.** The maintainer to pick: (a) personal small-size trading on marginal pass, (b) negative-result writeup, (c) walk away entirely.

Everything else has reasonable defaults that can be applied without further decisions.

---

## 9. Cross-agent coordination notes (for the collaborator's agent specifically)

If you (the collaborator's agent) have been working on equity-news infrastructure — events backfill, ensemble brain, decisions CLI, dashboard polish — **stop and re-read this document.** The equity-news track is being deprecated. Do not open new PRs against `signals/`, news adapters, or the 19-variant matrix until the collaborator has triaged the existing stack.

The methodology PRs (#93, #94, #95) are sound under the new direction. Do not redo them.

When you resume, the next work is options data infrastructure (Section 6). The single largest piece is the options-aware backtest engine — that should be the highest-priority new ticket.

If you find a contradiction between this document and any prior `brain/` doc (especially `brain/00_project_north_star.md`, `brain/13_financial_pipeline_proposal.md`, or `brain/24_edge_validation_criteria.md`), this document overrides. The collaborator and the maintainer can update the older docs to reflect the new direction in a separate cleanup PR.

---

## 10. What this is, and what it isn't

This is: a pre-registered, methodology-rigorous attempt to harvest a documented structural edge (the volatility risk premium) using a defined-risk options strategy on a market the maintainer knows (SPY), with an explicit decision protocol and an honest expectation of what success and failure look like.

This is not: a trading bot that finds alpha automatically. A SaaS product. A general-purpose options research platform. A competitor to OpenBB. A finance terminal. A magic system that beats the market without a specific edge.

If the experiment passes, the maintainer trades it. If it fails, we publish the result honestly and move on. Either way, the project ends with a clear answer, not another six months of feature-building in case the next adapter is the magic one.

That clarity is the actual deliverable.
