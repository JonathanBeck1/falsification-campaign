# Pre-Registration: Cross-Exchange Perp Funding Dispersion (T31)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypothesis, sample, windows, split, gate, and kill criteria are
> fixed here so a favorable specification cannot be selected after the fact.
>
> Standard campaign template (`brain/34_master_test_registry.md`; universal gate
> in `brain/30_campaign_findings.md`). T31 is **market-neutral by construction**
> and venue-relative — distinct from T29 (directional funding carry, which
> carried price risk).

## 1. Hypothesis (one sentence, directional, falsifiable)

The **same** perpetual (BTCUSDT, ETHUSDT, and liquid alts) carries **different**
realized funding rates on two venues (Binance vs OKX) at the same 8h funding
timestamp, and a market-neutral position — long the perp on the LOW-funding
venue, short the same perp on the HIGH-funding venue — harvests a positive
**after-cost** funding difference with `|t| ≥ 2`.

## 2. Mechanism — why would this be inefficient?

Each venue computes funding independently from its **own** index price, premium
EMA, interest-rate term, and clamp/cap (Binance clamps majors at ±0.75%/interval
band logic; OKX uses ±0.375% bands with its own premium formula). Because the two
funding formulas read different order books and apply different caps, the realized
8h rate differs venue-to-venue even for an identical contract. A delta-neutral
long-low / short-high book has **no net crypto price exposure** (the two legs are
the same underlying, opposite sign), so it isolates the funding **difference**.

**Why it might persist:** capturing it requires simultaneously holding margined
positions on two venues, paying taker fees on **both** legs each rebalance, and
posting collateral on both — capital- and fee-intensive, with cross-venue
transfer/withdrawal latency. That friction is exactly what could keep a few-bps
dispersion un-arbed.

**Honest prior: NULL.** Cross-venue funding arb is a well-known, capital- and
fee-intensive trade. The decisive question is not "is dispersion nonzero?" (it
trivially is) but "is mean dispersion **larger than the round-trip cost of
running matched positions on two venues**?" Two-venue taker round trip is
~20–40 bps; a BTC dispersion of fractions of a bp per interval will not clear it.
Prior strongly that this is **dead on arrival after costs**.

## 3. Data + provenance

- **Instrument(s) / universe (fixed):** perps listed on **both** Binance USDⓈ-M
  and OKX USDT-SWAP, restricted to the liquid set whose symbol maps cleanly
  (`SYMBOLUSDT` ⇄ `SYMBOL-USDT-SWAP`). Candidate list fixed ex-ante:
  BTC, ETH, SOL, XRP, DOGE, BNB, ADA, AVAX, LINK, LTC, DOT, TRX, BCH, NEAR,
  APT, ARB, OP, MATIC, ATOM, FIL (20 majors/large alts). A symbol enters the
  panel only if BOTH venues return funding over the overlap window.
- **Source:**
  - Binance funding: `data.binance.vision` public archive via
    `src/trader/catalysts/crypto_data.py` (`fetch_funding_history`).
    Survivorship-aware, retains delisted; recent ms/µs epoch fix applied.
  - OKX funding: `https://www.okx.com/api/v5/public/funding-rate-history`
    (free, no auth, public). Paginated via the `after` cursor (returns records
    OLDER than the cursor timestamp).
- **Construction & staleness:** realized per-interval funding (`last_funding_rate`
  on Binance; `realizedRate`/`fundingRate` on OKX), NOT annualized. Both are the
  rate **paid at interval close** — knowable only AT close, so the join is a
  contemporaneous measurement (no forecast). Survivorship: only symbols live on
  BOTH venues over the window (this is a same-window, both-alive intersection —
  the relevant survivorship for a cross-venue book is "both venues list it").
- **Timestamp alignment (load-bearing):** Binance archive timestamps carry
  sub-second offsets (e.g. `00:00:00.005Z`); OKX timestamps are exact. Both
  fund on the 8h grid (00:00 / 08:00 / 16:00 UTC). The join **floors both to
  the funding hour** before matching, else ~60% of rows drop silently.
- **Event/date list:** every matched 8h funding timestamp in the overlap window;
  fully ex-ante (a fixed UTC grid).
- **Sample span (DATA WALL):** OKX public funding history returns only ~283 rows
  (~3 months, 8h cadence) — verified live: oldest available ≈ 2026-03-12,
  newest ≈ run date. Binance has 2020+, but the **overlap** is bounded by OKX to
  roughly **2026-03-12 .. run date**. This is a documented depth wall, NOT a
  modeling choice. IS = first half of the overlap, OOS = second half.

## 4. Cohort & control definition

- **Cohort (treated):** for each matched (symbol, timestamp), the **signed
  funding difference** `d = funding_A − funding_B` where the convention is fixed
  ex-ante: the book is **long on the lower-funding venue, short on the
  higher-funding venue**, so the gross harvest per interval is `|d|` (you always
  receive the high side and pay the low side). The portfolio is the cross-sectional
  mean of `|d|` over the symbols available at that timestamp.
- **Control / baseline (the decisive one):** the **two-venue round-trip cost**.
  Holding a matched position means taker entry + exit on BOTH venues. The honest
  control is: `mean(|d|) per interval` vs `round_trip_cost`. If the cost line is
  above the dispersion line, the strategy is dead regardless of statistics.
- **Placebo:** **venue-label shuffle** — randomly permute which venue is "A" vs
  "B" per (symbol, timestamp) under a fixed seed. A real persistent dispersion
  with a stable sign should survive a directional read; a placebo that destroys
  the pairing should collapse the **signed** harvest toward 0. (For `|d|` the
  magnitude is sign-invariant, so the placebo targets the *signed* directional
  variant and the round-trip-cost comparison is the primary kill.)
- **Abnormal return / signal:** per-interval `|d|` minus per-interval round-trip
  cost (amortized — see §6). This is the after-cost harvest.

## 5. Measurement window + LOOK-AHEAD statement

- **Windows:** per-interval (8h) after-cost harvest, aggregated to a mean and a
  t-stat over all matched intervals. PRIMARY = pooled after-cost mean per interval.
- **Look-ahead audit:** funding for an interval is realized AT interval close;
  the harvest `|funding_A − funding_B|` for that interval uses only the two rates
  realized at that same close — no future information. Position sizing uses the
  prior interval's available symbol set (no same-interval membership look-ahead).
  Both rates are observable at the close, so the difference is a contemporaneous
  measurement, not a forecast — the trade collects the realized difference.

## 6. Friction model

- **This is the crux.** Cross-venue is fee-heavy: you pay taker fees on BOTH
  venues and hold margin on both.
  - Taker fee per leg: **5 bps** (0.0005) base case; **10 bps** stress case.
  - A matched position has 2 legs (Binance + OKX), each opened AND closed:
    **4 taker fills** per round trip = `4 × leg_fee`.
    Base: 4 × 5 = **20 bps round trip**. Stress: 4 × 10 = **40 bps round trip**.
  - **Amortization:** funding accrues every 8h (3×/day). To compare a per-interval
    harvest against a round-trip cost, the cost is amortized over an assumed
    holding period. We report BOTH:
    1. **Per-interval gross dispersion `mean(|d|)`** vs the **full** 20–40 bps
       round trip (the brutal one-interval-and-out view), AND
    2. The **break-even holding period**: how many 8h intervals you must hold for
       cumulative `Σ|d|` to exceed one 20 bps round trip. If that number is large
       (weeks), price/basis drift and margin risk over that hold dominate.
- **Application:** after-cost expectancy is the ONLY ranked metric. The cost line
  is plotted explicitly against the dispersion line (mandatory honest control).

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** usable matched intervals (overlap window gives ~280 × symbols).
- [ ] **After-cost expectancy** positive with **|t| ≥ 2.0** on the PRIMARY
      (per-interval `mean(|d|) − amortized_cost`).
- [ ] **Dispersion > cost (decisive control):** `mean(|d|)` per interval exceeds
      the round-trip cost amortized over a *reasonable* hold (≤ ~1 week / 21
      intervals). If `mean(|d|)` < full round trip AND break-even hold is long,
      KILL.
- [ ] **OOS sign stability** — IS/OOS halves same sign, both N ≥ 10.
- [ ] **Placebo** — venue-shuffle collapses the *signed* harvest toward 0.
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from mean
      auto-triggers placebo + top-5 contributor inspection.
- [ ] **Data provenance** — source, construction, staleness documented (§3).

No alternative window may replace the PRIMARY if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY |t| < 2, OR after-cost expectancy ≤ 0.
- **`mean(|d|)` per interval < round-trip cost** AND break-even hold > ~1 week
  (dead on arrival after two-venue fees) — the expected outcome.
- N < 30 usable matched intervals.
- OOS sign flip.
- Placebo absorbs the (signed) effect.
- Fewer than 5 symbols / intervals drive the result.

## 9. Limitations

- **OKX depth wall (~3 months):** the overlap window is bounded by OKX's public
  funding-rate-history endpoint (~283 rows). The IS/OOS split is therefore short
  (~6 weeks each). A kill here is robust against costs (the cost wall is
  window-independent), but a *positive* result would need a longer venue-pair
  history (a paid or scraped OKX archive) before being claimable.
- **Bybit geoblocked (HTTP 403 CloudFront) from this environment** — documented
  wall; OKX substituted as venue B.
- We model funding harvest only; we do NOT model collateral funding cost,
  borrow, withdrawal latency, or exchange counterparty risk — all of which make
  the real trade WORSE, so omitting them biases the test toward the strategy.
  A kill stands a fortiori.
- A kill proves the *unconditioned* cross-venue dispersion harvest is dead after
  two-venue taker fees on this venue pair / window; it does not test event-driven
  dispersion spikes (e.g. one venue's cap binding during a squeeze).
