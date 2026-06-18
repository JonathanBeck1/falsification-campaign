# External Trading Repo Research: Patterns to Borrow, Things to Skip

Date: 2026-05-20
Status: research notes; informs upcoming PRs but doesn't change code yet.
Owner: the maintainer (via Claude Code).

We surveyed three external trading repos to find patterns worth borrowing
into our `<your-handle>/trader` codebase. The goal was IDEAS, not code
adoption — our rules-first / LLM-as-text-decoder architecture
(`brain/10`, `brain/20`, `brain/21`) is incompatible with the multi-agent
debate designs most of these repos use. But individual prompts, schemas,
and edge-case handlers ARE worth borrowing.

## TL;DR

- **TradingAgents (Tauric)** — Apache 2.0, safe. Three patterns worth borrowing:
  pre-fetched XML-tagged sentiment prompt (no tool-calling), append-only
  two-phase memory log, alpha-vs-SPY reflection.
- **live-trade-bench (UIUC)** — **PolyForm Noncommercial 1.0.0. Skip.**
  License forecloses commercial use, and the metrics are weaker than
  what we'd build ourselves. Do not adopt any code.
- **AlpacaTradingAgent (huygiatrng)** — Apache 2.0, safe. Two patterns
  worth borrowing: TradeIntent Pydantic schema with live-position
  drift check, and yfinance fallback on Alpaca data errors. Two things
  to explicitly NOT copy: stops-as-advisory-only, and their hand-rolled
  market-hours calendar.

## License verdicts

| Repo | License | Verdict | Reason |
|---|---|---|---|
| TradingAgents | Apache 2.0 | ✅ Safe | No commercial restriction |
| live-trade-bench | PolyForm Noncommercial 1.0.0 | ❌ Skip | Explicitly non-commercial; needs paid license for any production use |
| AlpacaTradingAgent | Apache 2.0 | ✅ Safe | Inherits from upstream |

Even for Apache 2.0 work we'll copy patterns, not files, and keep
attribution where we lift any non-trivial code block.

## Patterns worth borrowing

### 1. Pre-fetched, XML-tagged evidence injection (from TradingAgents Sentiment Analyst)

**What it is**: instead of giving the LLM tool-calling access to "fetch news
about $TICKER", the orchestrator pre-fetches Yahoo News + StockTwits + Reddit
and injects each as a labeled XML block in the user message:

```
<start_of_yahoo_news>
...headline 1
...headline 2
<end_of_yahoo_news>

<start_of_stocktwits>
...
<end_of_stocktwits>
```

The single LLM call processes everything in one pass. No tool round-trips,
no agentic loops.

**Why it's the right pattern for us**: the TradingAgents header comment
explicitly notes the prior tool-calling version hallucinated Reddit content
under prompt pressure. Pre-fetching + injection is exactly the boundary
`brain/20` argued for: the LLM doesn't navigate, it just reads.

**Where it slots into our code**: this is the same pattern as PR #24's
event enricher prompts. When we wire the SentimentMomentumBrain or
ThesisEngine to ever use an LLM (we currently don't — both are
deterministic), the prompt should pre-inject evidence in this tagged form.

**Bonus**: their Sentiment Analyst prompt also embeds an 8-point "best
practices" guide directly in the system prompt:
- Read Bullish/Bearish ratio as a leading signal
- Flag 90/10 splits as over-extension risk
- Look for cross-source divergences (Reddit bullish, StockTwits bearish = real ambiguity)
- Weight Reddit by upvote engagement
- Distinguish opinion from event
- Identify recurring narrative themes
- Be honest about data-source gaps
- Treat past sentiment as non-predictive

This is the kind of structured domain prompting we should add to PR #24's
enricher prompts when it lands.

### 2. Append-only two-phase memory log (from TradingAgents `memory.py`)

**What it is**: every trade decision writes a Markdown block to a single
file (`trading_memory.md`) at decision time with a `pending` tag. Later,
when the outcome is known, a second pass rewrites the same block with:
- Realized return
- Alpha vs SPY (or regional benchmark)
- An LLM-authored REFLECTION section ("the catalyst played out as
  expected; the surprise was the duration")

Atomic temp-file + rename writes. HTML-comment delimiters between entries.
Optional rotation cap.

**Why it's worth borrowing**: this is the closed-loop learning we proposed
in `brain/19` (memory retrieval from Park et al.) but never implemented.
The two-phase pattern is concrete and small enough to copy. Past entries
get injected into future prompts as same-ticker history (n=5) plus
cross-ticker lessons (n=3).

**Where it slots into our code**: future PR — `brain/24_trade_memory.md`.
After the ThesisEngine emits a decision and we have a paper-trade outcome,
write the reflection. Build on top of our existing `decisions` and
`brain_equity_curve` SQLite tables; the Markdown file is a flat human-
readable mirror of the same data.

### 3. Alpha-vs-benchmark reflection (from TradingAgents)

**What it is**: every reflection block computes realized return AND alpha
vs SPY (the benchmark). The agent's "did I add value" question is answered
against passive long, not zero.

**Why we need it**: we already have a `BuyAndHoldBrain` as the implicit
benchmark, but no automatic comparison of brain returns vs benchmark in
our reflection or dashboard. Easy add when we wire the memory log.

### 4. TradeIntent Pydantic schema + drift check (from AlpacaTradingAgent)

**What it is**: a structured object that carries everything needed for
execution:

```python
class TradeIntent(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL", "HOLD"]
    qty: float | None
    stop_price: float | None
    take_profit: float | None
    required_controls: list[str]   # e.g. ["pdt_safe", "market_open"]
    warnings: list[str]
```

At execution time, `execute_trade_intent()` validates the intent against
the **live** broker position (not the stale snapshot the brain saw). If
the intent was for "buy 100 shares" but the broker says we already own
150 shares (maybe an earlier order filled differently than expected), the
execution refuses or downsizes.

**Why we need it**: our current flow is `Decision -> RiskGate.review() ->
broker.submit()`. The RiskGate sizes based on `AccountState` passed in
from the runner — which is a snapshot computed at the start of the run.
If anything has changed between snapshot and submit (rare but possible),
we don't catch it.

**Where it slots into our code**: a small refactor on `src/trader/execution/`.
Add a `TradeIntent` dataclass that the brain emits; the `AlpacaBroker`
re-checks position state before submit. The PDT check + halt check (next
section) belong on this boundary too.

### 5. yfinance data-fetch fallback on Alpaca errors (from AlpacaTradingAgent)

**What it is**: if Alpaca returns a subscription error, rate-limit, or
permission error during data fetch, transparently fall back to yfinance
for the same query. They use this because their default Alpaca data
plan has limits the free tier doesn't make obvious.

**Why we need it**: our `fetch_intraday_bars` in
`src/trader/adapters/alpaca/market.py` uses `StockHistoricalDataClient`
on the free Alpaca tier (IEX feed, delayed). If we ever hit a rate limit
or temporary outage, we have no fallback — the research run dies. We
already use yfinance elsewhere (`adapters/yahoo/market.py`), so this is a
small wiring change, not a new dependency.

**Where it slots into our code**: small PR. Add a wrapper that tries
Alpaca first, catches specific exception classes, and routes to
`fetch_yahoo_intraday_bars` on failure with a structured log.

### 6. `(is_open, reason_string)` tuple return for market hours (from AlpacaTradingAgent)

**What it is**: instead of a bool, the market-hours helper returns
`(is_open, reason)` so callers can log *why* a trade was skipped:

- `(False, "closed: weekend")`
- `(False, "closed: 9:25 AM ET (open at 9:30)")`
- `(False, "closed: early-close holiday at 1:00 PM ET")`
- `(True, "open")`

**Why we need it**: our `AlpacaBroker.market_is_open()` returns just
`bool`. When a brain is skipped, our log says "market closed" with no
detail. Trivial improvement.

## Things to explicitly NOT copy

### Stops/targets as advisory-only (AlpacaTradingAgent)

Their `TradeIntent` includes `stop_price` and `take_profit` fields, but
their `execute_trade_intent()` only RECORDS these — it never places a
bracket OCO order at the broker. The protective_order_status is literally
`"advisory_only"`.

**Why this is wrong**: a stop-loss that isn't at the broker is a stop-loss
that doesn't fire when your laptop loses internet. We should either place
real bracket orders (Alpaca supports `OrderClass.BRACKET`) or remove the
field entirely. Copying their pattern as-is gives the appearance of
protection without the substance.

### Hand-rolled market-hours calendar (AlpacaTradingAgent)

They embed a holiday table through 2027 with no early-close handling
(Black Friday, Christmas Eve, day-after-Thanksgiving). NYSE-only. No
extended-hours support.

**Why this is wrong**: a maintained calendar library handles early
closes, half-days, and all major US exchanges. Don't roll our own.

When we need market-hours logic beyond what `AlpacaBroker.market_is_open()`
gives us, use `exchange-calendars` — already declared in our
`pyproject.toml` under the `trading` extra.

> Note (per Codex review 2026-05-20): an earlier draft of this section
> recommended `pandas_market_calendars` as a "transitive dependency
> through alpaca-py." That was unverified and wrong — our
> `pyproject.toml` declares `exchange-calendars`, not
> `pandas_market_calendars`. If a future PR determines
> `pandas_market_calendars` has capabilities `exchange-calendars` lacks,
> add it as an *explicit* dependency in `pyproject.toml` rather than
> relying on a transitive import.

### Multi-agent debate architecture (TradingAgents)

Their Bull/Bear Researcher + Aggressive/Conservative/Neutral Risk debate
nodes are clever but explicitly forbidden by `brain/10` and `brain/20`.
A debate is just multiple LLM calls voting; the "agentic" framing
disguises that none of them are auditable as a deterministic rule.

We already rejected this in the ADR. Mentioning here only so it doesn't
get re-proposed.

### live-trade-bench in any form

PolyForm Noncommercial 1.0.0 forecloses any production use. Even the
data fetchers (`news_fetcher.py`, `reddit_fetcher.py`, `stock_fetcher.py`)
are governed by the same license. If we want similar functionality,
re-implement from scratch.

## Gap analysis: our Alpaca/execution stack vs theirs

Comparing our current code against
AlpacaTradingAgent's `alpaca_utils.py`:

### Gaps in OUR code (theirs handles, we don't)

| Gap | Their approach | Severity for us |
|---|---|---|
| **Position drift check** | `execute_trade_intent()` validates intent vs live broker position before submit | Medium — rare but real |
| **yfinance data fallback** | Catches Alpaca subscription/rate-limit errors, routes to yfinance | Low — only matters on outages |
| **Detailed market-hours reason** | `(is_open, reason)` tuple | Low — observability nicety |
| **Crypto sizing via notional** | Uses `notional=` for crypto, `qty=` for stocks | Not applicable — we trade SPY/QQQ only |
| **Position state FSM** | Explicit `{LONG, SHORT, NEUTRAL} × actions` matrix | Not applicable — we're long-only on broad-index ETFs |

### Gaps in THEIR code (we handle, they don't)

| Gap | Our approach | Their state |
|---|---|---|
| **Kill switch** | `RiskGate.kill_switch_path` check on every cycle | Missing |
| **Daily-loss circuit breaker** | `RiskGate.max_daily_loss_pct` halts trading after threshold | Missing |
| **LLM cost cap** | `RiskGate.max_llm_cost_per_day_usd` + preventive gate (PR #26) | Missing |
| **PDT awareness** | `RiskGate.is_pdt_account` blocks day-trades under $25K | Missing |
| **Cash clipping** | RiskGate downsizes orders when cash insufficient | Partial (they raise on submit failure) |

### Gaps both architectures have

These are real exposure both architectures share. Worth a follow-up PR:

| Gap | What's needed |
|---|---|
| **Partial fill handling** | `submit()` returns immediately; no polling for status; partial fills aren't detected. Need a fill watcher or post-submit reconciliation. |
| **Order rejection catch** | `submit_order` exceptions propagate raw. Need explicit catch for `APIError` and a structured rejection event. |
| **Halted-ticker detection** | `market_is_open()` checks market hours; doesn't check `asset.tradable` per-ticker, doesn't catch LULD halts during the day. |
| **Stale-quote check** | We use snapshot `last_price` without comparing against current bid/ask spread. A wide spread = stale market or halted ticker. |
| **Buying-power vs cash** | We check `acct.cash`; Alpaca's `buying_power` differs on margin accounts (we're cash-only paper today, so this is hypothetical until live). |
| **Position reconciliation** | We never compare Alpaca's `positions()` to our SimBroker SQLite state. They can drift. |
| **Broker-side protective orders** | Neither of us places real bracket/OCO orders. Stops "in code" are not stops. |

## Recommended next actions

Ordered by value, smallest first:

1. **`market_is_open()` returns `(bool, reason)`** — 1-hour change in
   `src/trader/execution/broker.py`. Logs become clearer immediately.

2. **yfinance fallback on Alpaca data errors** — half-day change to
   `src/trader/adapters/alpaca/market.py` (and the intraday path). Wraps
   the `client.get_stock_bars` call in a try/except for specific Alpaca
   errors and falls through to `fetch_yahoo_intraday_bars`.

3. **Order rejection + partial fill handling** — day-or-two PR. Add
   `submit_with_status_watch()` that polls until the order is filled,
   cancelled, or times out, and emits structured events for each state
   transition. Surface partial fills as a distinct event class.

4. **Pre-fetched XML-tagged prompt pattern** for the event enricher
   (PR #24) once it merges. Doesn't change code today; just informs the
   prompt design when we iterate on it.

5. **Append-only two-phase memory log** — bigger PR (`brain/24` doc
   first, then implementation). After we have a few weeks of paper
   trades to reflect on, the memory log becomes the input for refining
   the THESIS_TABLE.

6. **Halted-ticker detection** — wait until we go live. Paper trading
   doesn't expose halts the same way live does. This becomes important
   only when real money is involved.

## What this is NOT

- Not a recommendation to fork or add any of these repos as deps. All
  patterns get re-implemented in our codebase with attribution.
- Not approval to adopt multi-agent debate architectures. ADR brain/20
  still stands.
- Not a backtest. The patterns above are pre-validated only insofar as
  the upstream projects exist and run; whether they improve OUR returns
  is empirical.

## Closing note

The most valuable single output of this research: the **noncommercial
license on live-trade-bench**. That was the one repo I was most likely to
recommend adopting (for our missing backtest harness, per `brain/22`
roadmap). It's foreclosed. We will need to build our own evaluation
harness from scratch. That'll be `brain/23_event_study_backtester.md`
implementation work, sized appropriately.

The other valuable output: TradingAgents' **XML-tagged evidence injection
pattern** is a clean fit for our boundary discipline. When PR #24 merges
and we start refining the enricher prompts, that's the pattern to copy.
