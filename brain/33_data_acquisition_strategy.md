# Brain 33 — Data Acquisition Strategy: where the next data dollar goes

Date: 2026-06-14
Status: reference. Synthesizes a research sweep of untested-edge data territory,
given the 19-kill campaign and a solo-hobbyist budget (tens of $/mo, not
thousands; compute free on owned hardware).

## Framing

The 19 kills exhausted *liquid, public, daily-frequency, US-large-cap* data —
the most-arbitraged corner of finance. Unexploited territory for a hobbyist
clusters in three places:
1. Intraday microstructure of instruments partly owned but not fully exploited
   (single-name options; the incoming 0DTE backfill).
2. 24/7 / fragmented / younger markets where retail dominates and institutions
   are capacity/mandate-constrained (crypto derivatives, prediction markets).
3. Structural-flow datasets where the edge is a mechanism, not a pattern
   (borrow fees, ETF roll/flow, dispersion).

Critical nuance: killing *index* condor VRP (mechanism null) does NOT kill the
variance-risk-premium or single-name effects — it kills the **index-level,
daily-frequency expression**. The same mechanisms can survive at the
single-name, intraday, or cross-sectional-correlation level where capacity is
far smaller.

## Top 3 directions (ranked by plausibility × accessibility)

1. **Single-name equity options vol surfaces + dispersion** (~20–50 names via
   the EXISTING ThetaData pipeline, ~$50/mo). Untested corner: dispersion /
   correlation premium (index IV systematically rich vs constituents) — a
   DIFFERENT mechanism than the killed index VRP, structurally capacity-limited
   because harvesting it is execution-expensive. Reuses the adapter, lake-sync,
   marking/metrics tests already built. **Biggest failure risk: execution cost
   eats the thin (1–2 vol-pt) edge; fill-model optimism would manufacture a
   fake edge.** Universe must be anchored to historical index membership, not
   today's liquidity (survivorship).

2. **Crypto perpetual funding-rate carry, cross-sectional across the alt long
   tail** ($0 data; Binance/Bybit/OKX/CoinGlass free APIs; 24/7 = runs while
   you sleep). Mechanism: retail crowds directional longs → persistent positive
   funding a delta-neutral harvester collects; alt tail pays more because arb
   capital is inventory/counterparty constrained. **Biggest failure risk:
   survivorship — dead tokens vanish from exchange APIs; without a delisting log
   built FIRST, the backtest shows gorgeous carry that is pure survivor-
   conditioning (the small/illiquid-equity kill, transplanted).**

3. **The incoming 0DTE / 0–3 DTE QQQ backfill → intraday dealer-gamma-
   conditioned reversion** ($0 marginal, own NBBO, intraday frequency BELOW the
   daily level proven picked-clean). **Biggest failure risk: most-watched new
   frontier; edge compressing in real time and NO capacity limit protecting it —
   may be arriving late to a closing window.**

## Trap list (exciting but arbitraged or data-quality mirages) — DO NOT BUY

- **Congressional-trade trackers** (Quiver/Unusual Whales/NANC ETF) — most-
  publicized "signal" in retail finance, lagged ≤45d, the "edge" is mega-cap-
  tech beta (already-killed universe).
- **"Unusual options flow" / "dark pool prints"** ($50–150/mo) — delayed,
  venue-incomplete, can't distinguish hedge from directional. Compute flow
  yourself from owned NBBO instead.
- **Reddit/WSB sentiment, Google Trends** — heavily mined since 2021, reflexive,
  survivorship/look-ahead minefield.
- **SEC filings-text NLP** — same family as the already-killed news-catalyst /
  PEAD work; clean-PIT version is exactly where naive studies cheat.
- **Broad Form-4 insider** — known/weak; only microcaps survive, colliding with
  the killed small/illiquid universe.

## Cross-cutting warning

Every NEW universe (crypto tokens, single-name underlyings, futures) reintro-
duces survivorship + point-in-time risk — the failure mode behind several of
the 19 kills. The pre-registration discipline defends the *test*; the
**data-construction step** (delisting logs, historical index membership,
continuous-contract roll) is where look-ahead sneaks in BEFORE the test runs.
Budget more effort for clean universe construction than for strategy logic.

## Honorable mentions (lower priority)

Equity borrow fees / short interest (IBKR free files, but must log daily going
forward — no cheap clean backfill); commodity/rates futures term structure
(Norgate ~$30–60/mo, continuous-contract construction is a data-quality trap);
crypto options / Deribit DVOL (self-log free); prediction markets (free, but
the winnable sub-markets are thin and the liquid ones are a bot playground).
