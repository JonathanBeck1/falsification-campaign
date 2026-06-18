# Additional Data Sources to Consider

Date: 2026-05-20
Status: proposal. Doc-only. Ranked by impact for SPY/QQQ news-driven trading.
Owner: a collaborator (via Claude Code).

This is a catalogue of free and low-cost public data we don't have wired
yet, ordered by how much I expect each to actually help our specific
use case (deterministic-rules-first, news-driven, SPY/QQQ shares only).

The goal is not "ingest everything." The goal is "wire the smallest set
that materially improves our thesis confidence and macro regime
overlay." Most of these matter not because they predict direction
directly, but because they make the existing thesis taxonomy more
calibrated.

## Speed amendment (correction to brain/21)

Before listing data, an amendment. brain/21 said "we can't beat speed."
That's too pessimistic. There are three speed tiers:

| Tier | Latency | Players |
|---|---|---|
| HFT | microseconds | Co-located prop firms, market makers |
| Machine-fast | 1-30 seconds | Us, quant retail tools, broker algos |
| Human-fast | 5-30 minutes | Retail traders reading headlines |

HFT eats the first-touch. We won't reach that tier. But there's a real
gap between HFT's first-millisecond reaction and retail's 5-30 minute
reaction — and that's where we sit. In that gap, machine-fast beats
human-fast.

To compress our latency toward the low end of "machine-fast" we should:

1. **Use WebSocket / SSE feeds where available** — but be careful about
   which providers actually offer free streaming. As of 2026-05, the
   honest picture is:

   | Provider | Streaming for news | Tier | Latency improvement vs polling |
   |---|---|---|---|
   | Alpaca News | SSE / WebSocket available | Free tier | ~10-30s |
   | Finnhub News | WebSocket available | **News Premium (paid)** | n/a until we pay |
   | Yahoo Finance | None published | Free tier | Polling only |
   | SEC EDGAR | Atom polling only | Free tier | Polling only |
   | Fed RSS | RSS polling only | Free tier | Polling only |

   So the only free-tier streaming upgrade today is Alpaca News. Finnhub
   streaming is gated behind a paid News Premium plan and should not be
   in the free-tier latency budget. Wiring Alpaca SSE on its own
   compresses our Alpaca-source latency to ~1-3s; everything else
   remains polling at whatever cadence the cron + adapter allow
   (10-60s realistic). Plan accordingly: the "machine-fast tier" we
   actually achieve on free tier is closer to **10-30s for most
   sources, 1-3s for Alpaca-sourced news only**.

2. **Keep the LLM out of the trade-execution path**. Tier-1 deterministic
   short-circuit (PR #26) handles the first reaction in milliseconds.
   LLM enrichment runs async AFTER the position is taken, for audit
   trail and to refine the next thesis.

3. **Pre-stage scheduled events as ALERTS, not as triggers.** A calendar
   tells us *when* CPI is released, not whether it beat or missed.
   Knowing FOMC is at 14:00 ET means we can:
   - Increase polling cadence on news adapters in the 5 minutes before
     and after a known event time
   - Pre-load thesis templates so classification + aggregation latency
     after the actual print is minimal
   - Refuse to take a new position in the last 5 minutes before a known
     macro release (positioning into known volatility, not on a signal)

   **What it explicitly does NOT mean: trade at the scheduled time
   without actual release data.** Any trade decision around a scheduled
   event requires (a) the actual print value, (b) consensus / prior
   expectation, (c) successful parse of both, (d) a freshness check
   that the data is from the current release. If any of those are
   missing, the system stays at baseline — no-trade is the safe
   fallback. This matches brain/10's rule that LLM/automated decisions
   can never execute on partial inputs.

## Tier 1: Free, high impact

These are the data sources I'd wire first. All are public, all are free,
all materially feed into the thesis-engine confidence rating or the
macro regime overlay (the deterministic gates around the LLM-classified
news signal).

### 1. Economic calendar

**What:** Scheduled times of FOMC meetings, CPI, NFP, PCE, GDP, retail
sales, etc. — every event in the macro_release bucket of brain/21.

**Why it matters:** Half of the thesis taxonomy involves scheduled
events. We should KNOW that FOMC is tomorrow at 14:00 ET, so the system
can pre-stage thesis templates, increase polling cadence around the
release window, and refuse new positions in the minutes leading up to
known volatility.

**What this is NOT:** the calendar does not trigger trades on its own.
A calendar entry says *when* CPI is scheduled, not *what the print
was*. Any actual trade decision around a scheduled event requires the
news adapter to capture the release payload, the normalizer/enricher
to extract the surprise direction, AND a freshness check that the data
is from the current release. Missing or stale data → no-trade
fallback, system stays at baseline. This is the same rule brain/10
applies to LLM decisions: never execute on partial inputs.

**Source options:**
- ForexFactory public XML calendar (free, well-structured)
- Investing.com calendar (free with rate-limit dance)
- FRED release schedule (free, official, but only US data)

**Integration cost:** small. One adapter, one nightly cron, a new
`scheduled_events` table. The pre-staging logic (cadence change,
no-new-position window) goes in `runner.py` and gates on calendar
entries that match a configured horizon (e.g., 5 minutes before/after).
Trade execution itself remains gated on the actual release payload
arriving through the existing news pipeline.

### 2. VIX term structure

**What:** VIX9D, VIX, VIX3M, VIX6M — implied volatility at different
horizons. The shape of the curve (contango vs backwardation) is a
regime indicator.

**Why it matters:** brain/21's macro regime overlay currently uses
spot VIX. The term structure tells us if vol is *expected to spike*
(backwardation) or *expected to mean-revert* (contango). The same
spot VIX 20 means very different things depending on the curve shape.

**Source:** Yahoo Finance via `yfinance` (free; tickers are `^VIX9D`,
`^VIX`, `^VIX3M`, `^VIX6M`). We already use yfinance for bars.

**Integration cost:** trivial. Add to the macro snapshot.

### 3. High-yield credit spreads (HYG/LQD ratio)

**What:** Ratio of high-yield bond ETF to investment-grade bond ETF.
Widening = credit stress; narrowing = risk-on.

**Why it matters:** Credit markets often lead equity weakness by 4-24
hours. A widening HY/IG spread when our news signal is bullish is a
"don't trust the bullish signal yet" condition.

**Source:** Yahoo Finance bars for HYG and LQD. We have the
infrastructure.

**Integration cost:** trivial. New helper in macro snapshot.

### 4. Earnings calendar for QQQ megacaps

**What:** Confirmed earnings report dates for the top 10-20 QQQ/SPY
constituents: AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA, etc.

**Why it matters:** brain/21's earnings-season regime bucket needs to
know when megacap earnings happen. Also: position-sizing should be
reduced going into a megacap earnings day if our broad-index position
has significant exposure to that name. NVDA reports tonight after
close → our QQQ position has a known event-risk overlay.

**Source:** Yahoo Finance has next-earnings-date per ticker (free).
Finnhub has earnings calendar endpoint (free tier covers this). NASDAQ
also publishes a calendar.

**Integration cost:** small. Per-ticker fetch nightly; cache.

### 5. Treasury futures / yields real-time

**What:** 2Y, 10Y, 30Y Treasury yields with intraday resolution.
Currently we have FRED daily data, which is end-of-day stale.

**Why it matters:** During rate-sensitive periods, yields move BEFORE
stocks. A spike in 10Y yield during the Fed press conference is the
signal; SPY reaction is the lagging effect. Acting on yields directly
can give us a 1-5 minute head start.

**Source options:**
- Yahoo Finance has `^TNX` (10Y) with intraday updates (free)
- Treasury Direct API (free, official, end-of-day)
- Polygon.io has intraday treasury data (~$30/mo if we ever want real
  tick data)

**Integration cost:** small. Add to macro snapshot via yfinance.

### 6. SEC Form 4 insider trading filings

**What:** Required filings when corporate insiders (executives,
directors, large shareholders) buy or sell their own company's stock.
Public on SEC EDGAR.

**Why it matters:** Insiders selling cluster before bad news; insiders
buying cluster before good news. Documented persistent edge in academic
literature (Lakonishok-Lee 2001, Cohen-Malloy-Pomorski 2012). Effect is
strongest for executives buying (selling has more confounders: tax,
diversification).

**Source:** SEC EDGAR — we already query EDGAR for 8-K filings. Form
4 is the same API. Free.

**Integration cost:** moderate. Need a new normalizer that turns Form 4
filings into an `insider_activity` event type. Aggregated weekly
insider buy/sell ratio per ticker becomes a feature for the
ThesisEngine.

## Tier 2: Free, moderate impact

These are worth wiring once tier 1 is in. Each contributes a smaller
edge but is cheap to add.

### 7. Crypto (BTC / ETH)

**What:** Bitcoin and Ethereum spot prices, intraday.

**Why it matters:** BTC often moves before equities during risk-on/risk-off
flips, especially during US off-hours. A 2 AM BTC drop is a leading
indicator of US equity weakness at open ~30% of the time historically.
Imperfect but free.

**Source:** Coinbase API (free), Binance public API (free), or yfinance
(`BTC-USD`).

### 8. USD/JPY and DXY

**What:** Dollar against yen (safe-haven proxy) and DXY (broad dollar
index).

**Why it matters:** JPY rallies when global risk-off (carry-trade
unwinds). DXY rises on US-specific bullishness or global risk-off
(complicated). Both add signal to the regime overlay.

**Source:** yfinance (`USDJPY=X`, `DX-Y.NYB`). Free.

### 9. Sector ETF relative strength

**What:** Daily relative performance of XLF (financials), XLK (tech),
XLE (energy), XLV (healthcare), XLY (discretionary), XLP (staples),
XLU (utilities), XLI (industrials), XLB (materials), XLRE (real
estate).

**Why it matters:** Regime detection. Defensive sectors (XLP, XLV, XLU)
outperforming during an apparent bull market = late-cycle warning.
Tech (XLK) leading = risk-on. Useful as a confirmation/disconfirmation
signal for our news theses.

**Source:** yfinance. Free.

### 10. News publication velocity

**What:** Count of news items per ticker per hour, normalized against a
trailing baseline.

**Why it matters:** Sudden spike in news volume for a ticker = something
is happening even if no individual headline is decisive. Useful as a
"pay attention" signal.

**Source:** Computed from our existing `news_events` table. No new
adapter needed.

**Integration cost:** trivial. A query and a SQL view.

### 11. Reddit WSB sentiment (controversial)

**What:** Aggregated post sentiment from r/wallstreetbets and r/stocks.

**Why it matters:** Documented signal for retail flow on QQQ-style
names (Atilgan-Bali-Demirtas 2022 found r/WSB sentiment predicts
3-day reversals, especially in high-short-interest stocks). For broad
SPY/QQQ trading, the signal is smaller but non-zero — extreme retail
bullishness has historically marked tops.

**Source:** Pushshift was the canonical source; now restricted. Reddit
official API has rate limits but is free. Some third-party aggregators
(Apewisdom, etc.) re-package this for free with delay.

**Integration cost:** moderate. The hardest part is filtering out
genuine retail sentiment from coordinated pump-and-dump campaigns. A
known-bot filter would be needed.

**Caveat:** brain/21 currently lists "retail forum chatter" in the
IGNORE set. The argument for revisiting that is: at *aggregate* level
(not per-headline), retail sentiment is a measurable contrarian
indicator. Worth a backtest before wiring.

## Tier 3: Free, smaller impact

Worth knowing exist; lower priority.

### 12. AAII Sentiment Survey

Weekly retail bullish/bearish ratio published by American Association
of Individual Investors. Free. Updated Thursdays.

**Use:** Contrarian indicator. Extreme retail bullishness (>50% bulls)
historically precedes corrections; extreme bearishness (>50% bears)
precedes rallies. Weekly cadence means it's a regime flag, not a
trading trigger.

### 13. CBOE Put/Call ratio

Daily total options put-to-call ratio. Free from CBOE.

**Use:** >1.0 = bearish positioning (potentially contrarian-bullish);
<0.6 = bullish positioning (potentially contrarian-bearish). Smaller
effect for broad-index than for single names.

### 14. Polymarket / Kalshi prediction markets

Real-money bets on Fed decisions, election outcomes, recession odds.

**Use:** For known macro events (Fed meetings), Polymarket odds often
update minutes-to-hours before financial press picks up the
implication. A shift in Polymarket Fed-cut odds is a leading indicator.

**Source:** Polymarket has a public API; Kalshi requires an account
but has read-only public market prices.

**Integration cost:** small for read-only. Filter to markets relevant
to our trade theses (Fed decisions, recession odds, election outcomes).

### 15. Google Trends

Search volume for ticker symbols, company names, related terms.

**Use:** Lagging in normal markets; can spike before market hours when
something is breaking. Da-Engelberg-Gao 2011 documented predictive
power, but with weekly cadence in their data — real-time Trends are
noisier.

**Integration cost:** moderate. Free public API; rate limits are tight.

### 16. VIX futures positioning (CFTC COT)

Commitments of Traders report from CFTC. Weekly. Free. Shows net
positioning of large speculators vs commercials in VIX futures.

**Use:** Speculator-long-VIX = expecting volatility; that's a regime
signal. Weekly cadence and Friday-after-close release means it's
slow.

## Tier 4: Mostly noise for SPY/QQQ

Listing for completeness; I would NOT prioritize these.

- **Wikipedia pageviews** — interesting research, small effect
- **Stocktwits sentiment** — too noisy for broad index
- **Single-name social sentiment** (we already filter this out)
- **Crypto altcoin movements** (BTC/ETH are useful; altcoins are noise)
- **Foreign equity indices** during US hours (US leads in our timeframe)

## Mid-cost options (not yet justified)

If we ever decide to pay for data, these are the most-justified spots.
None of these are needed for v1.

| Source | Cost | What it gets us | Worth paying? |
|---|---|---|---|
| Polygon.io | $79/mo | Real-time options flow, dark pool prints | Only if we move to options |
| Bloomberg Terminal | $2400/mo | Everything | No |
| Refinitiv | $1500+/mo | News, fundamentals | No |
| Benzinga Pro | $99/mo | News + analyst notes | Maybe — we already get Benzinga via Alpaca News |
| FlowAlgo | $97/mo | Options flow + dark pool | Only if options |
| Unusual Whales | $30-100/mo | Options flow | Only if options |
| TheTradeXchange | $9/mo | Curated news headlines | Maybe — cheap, focused |

**The honest assessment:** for a shares-only SPY/QQQ news-driven system
running off Alpaca paper trading, **none of the paid sources are
needed.** All real edge is in the tier 1 list above, all of which is
free.

## Recommended implementation order

If we wire tier 1 incrementally, this is the order I'd suggest:

1. **VIX term structure** (~30 min of work, immediate regime signal)
2. **HYG/LQD credit spreads** (~30 min, lead indicator)
3. **Economic calendar** (~2 hours, requires new adapter + table)
4. **Earnings calendar** (~2 hours, similar shape)
5. **Treasury yields intraday** (~1 hour, add to macro snapshot)
6. **SEC Form 4 insider filings** (~half day, new normalizer + event type)

That's roughly one week of part-time work to get all six wired. Each
one is independently testable and improves the calibration of the
thesis engine.

## What I'd actually do next

Before wiring any of these, the prerequisite is **PR #24 merges and we
have a labeled event corpus**. Without enriched events, adding
VIX/credit/calendar features is premature — they're inputs to the
*regime overlay around the thesis engine*, and the thesis engine
doesn't exist yet.

Order:

1. PR #24 merges. Labeled event corpus accumulates over a few days.
2. ThesisEngine implementation (brain/21 + new brain/23 spec).
3. Once ThesisEngine emits theses, THEN tier 1 data sources get wired
   as confidence-modifiers and regime overlays. We'll know exactly
   which ones move the needle because we can backtest with/without.
4. Tier 2 and 3 only if tier 1 doesn't produce clear edge.

## Open question for the maintainer

You mentioned having prior work from a separate project that you plan
to bring in. The most valuable thing that work could contribute is
**empirically validated event-reaction magnitudes** — i.e., the
`expected_magnitude_pct` numbers in brain/21's THESIS_TABLE. Anything
you have on "what did SPY/QQQ actually do 1h/4h/24h after a CPI
surprise of X%" would beat any data source on this list, because it
directly calibrates the existing taxonomy instead of adding new
features.

If your prior work has labeled event outcomes, that's the highest-value
thing you can land. Otherwise we'll build it by accumulating
enrichments + bar data after PR #24 merges.
