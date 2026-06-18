# Pre-Registration: Stablecoin Depeg Mean-Reversion (T34)

> Status: pre-registered design, written **before** computing any results.
> The hypothesis, sample, windows, split, gate, and kill criteria are fixed
> here so a favorable specification cannot be selected after the fact.
>
> Standard campaign template (see `brain/34_master_test_registry.md` and the
> universal gate in `brain/30_campaign_findings.md`). The single most important
> design decision in this test is the **deliberate inclusion of dead
> stablecoins (UST/USTC)** so the strategy's catastrophic tail is in the sample.

## 0. The whole point of this test (read first)

This is a textbook **survivorship / picking-up-pennies-in-front-of-a-steamroller**
trap. "Buy a stablecoin when it falls below $0.98, hold for the re-peg" looks
great if you only test stablecoins that *survived* (USDC dipped to ~$0.88 in
Mar 2023 and recovered; DAI, USDP, TUSD all re-pegged). But the strategy's true
return distribution is dominated by the rare case where the depeg is a **death
spiral**: TerraUST (UST) fell from $1.00 to ~$0 in May 2022, a ~$18B implosion.
A "buy below $0.98" rule fires on UST on the way to zero and loses ~100%.

The honest test therefore **must** include the corpses. The pre-registered
headline comparison is **mean forward return WITH dead coins vs WITHOUT** — if
including the deaths flips a positive survivor-only mean to negative (or makes
the tail dominate), the strategy is a survivorship artifact and is killed.

## 1. Hypothesis (one sentence, directional, falsifiable)

Buying a major USD stablecoin when its daily close first falls below $0.98 and
holding to a fixed horizon earns a positive **after-cost** mean forward return,
**and that positivity survives the inclusion of stablecoins that died** (did not
re-peg).

## 2. Mechanism — why would this be inefficient?

Candidate mechanism: a stablecoin depeg is usually a transient liquidity/panic
event (redemption-gate fear, a reserve-bank scare like USDC↔SVB), and the
fundamental redemption peg at $1 reasserts via arbitrage. Panicked holders sell
below intrinsic value; patient capital that can hold to recovery collects the
re-peg. The friction stopping arbitrage is *uncertainty about solvency* — you
cannot tell ex-ante whether this depeg re-pegs (USDC) or is terminal (UST).

**Why it should NOT survive:** the very uncertainty that creates the discount is
the reason the strategy is short-volatility / negatively-skewed — many small
re-peg wins funded by rare total losses. Conditional on a depeg, you are
implicitly *short a credit/solvency option*. Efficient pricing of that option
means the discount compensates for the death probability, leaving ~0 edge.

**Honest prior:** **null-to-negative once corpses are included.** Strong prior
that this is a survivorship artifact: survivor-only will look positive; the
full sample (with UST) will be dragged toward / below zero by a handful of
catastrophic events. Likely an **N-too-small / tail-dominated** verdict rather
than a clean t-stat.

## 3. Data + provenance

- **Universe (fixed, pre-specified list):** major USD stablecoins traded as
  USDT-quoted spot pairs on Binance, **explicitly including dead ones**:
  - `USTUSDT` (TerraUST — **DEAD**, the steamroller; archive ends 2022-05)
  - `USTCUSDT` (Terra Classic USD — post-collapse rebrand, never re-pegged)
  - `USDCUSDT` (survived Mar-2023 SVB depeg to ~$0.88)
  - `DAIUSDT` (survived)
  - `BUSDUSDT` (wind-down, but re-pegged; archive ends 2023-12)
  - `TUSDUSDT` (survived; multiple minor depegs)
  - `USDPUSDT` (Pax USD, survived)
  - `FDUSDUSDT` (survived; Feb-2025 minor depeg)
  - `SUSDUSDT`, `GUSDUSDT`, `USDDUSDT` (algorithmic, Tron) — **include any that
    the archive serves**; document coverage. USDD is algorithmic and has
    depegged hard, so it is a wanted tail contributor.

  The list is fixed here BEFORE running. Coverage (which actually have spot
  klines) is documented in the results; **UST inclusion is mandatory and
  verified present** (`data/spot/monthly/klines/USTUSDT/1d/` serves
  2021-12..2022-05, the collapse window).

- **Quote-asset caveat (provenance):** prices are quoted in USDT, itself a
  stablecoin. USDT held ~$1.00 across all event windows here, so USDT-quoted
  price ≈ USD price. USDT's own minor wobbles (e.g. ~$0.95 on 2022-05-12) are a
  documented limitation, not a fatal one — and if anything they understate the
  USD depeg depth. We do NOT use USDT itself as a tradeable cohort member.

- **Source:** Binance public archive `data.binance.vision`, **spot** monthly
  daily klines (`data/spot/monthly/klines/<SYM>/1d/`). No API key, no geoblock.
  This archive is **append-only and never purges delisted symbols** — that is
  the whole reason it can hold UST's corpse. Reuses the existing pure
  parse core in `src/trader/catalysts/crypto_data.py`.

- **Construction & staleness:** daily close, UTC. No adjustment needed
  (stablecoins don't split). The dead-coin signal is intrinsic: the price series
  simply stops (UST) — we do NOT rely on any external delisting feed.

- **Sample span:** 2018-01 .. 2026-05 (full archive). IS = events with t0
  **before 2023-01-01**; OOS = t0 **on/after 2023-01-01**.

## 4. Cohort & event definition

- **Event (depeg):** for a symbol, the first daily close `< 0.98` after the
  price has been `>= 0.995` (re-armed). I.e. a fresh break below the threshold.
  After an event fires, the symbol is **disarmed** until its close recovers to
  `>= 0.995` again — so a single multi-day depeg counts as ONE event, not one
  per day below peg. This prevents one slow death from manufacturing dozens of
  overlapping "events".
- **t0:** the close date of the first sub-$0.98 print. Entry fill = that day's
  close (price already below peg; this is the actionable signal close).
- **No control universe of "non-events":** the placebo (§7) is a random-date
  pseudo-depeg drawn from the SAME symbols' non-event days, measuring the same
  forward windows. This isolates the depeg signal from each coin's baseline
  drift toward $1.

## 5. Measurement window + LOOK-AHEAD statement

- **Forward windows (calendar days from t0, inclusive of t0 close as entry):**
  - `ret_to_peg`: forward return if/when close first reaches `>= 0.995` within
    a 30-day cap; if never within 30d, the position is marked at the **day-30
    close** (or the LAST available close if the series ends first — this is how
    UST's death enters as a near-total loss). **PRIMARY = `ret_30d` below.**
  - `ret_7d`, `ret_30d`: forward return entry→close at t0+7 / t0+30 calendar
    days (or last available close if the series terminates earlier — terminal
    death is realized, NOT dropped).
  - **PRIMARY window: `ret_30d`** (fixed-horizon hold; the honest one because it
    forces realization of deaths rather than waiting indefinitely for a re-peg
    that never comes).
- **Terminal-death rule (critical):** if a symbol's price series ENDS while the
  position is open (UST archive stops 2022-05-13 at ~$0.18), the position is
  marked to the **last available close** as the realized exit. This books UST's
  ~80% loss instead of silently dropping the worst event. Stated explicitly to
  forbid the survivorship escape hatch.
- **Look-ahead audit:** the event is defined purely by the close on/before t0
  (price `< 0.98`). All forward windows start AT t0's close (entry) and measure
  strictly forward. No future information defines membership. The death is
  detected by the series terminating in the forward window — which is exactly
  what a real holder would experience in real time; no peeking.

## 6. Friction model

- **Round-trip cost:** 20 bps (0.20%) per round trip — Binance spot taker ~10
  bps/side plus stablecoin slippage in a panic. Stated conservatively; depeg
  conditions widen spreads, so 20 bps is a floor. Sensitivity at 40 bps reported.
- **Application:** subtract once per round trip from gross forward return.
  After-cost mean is the ONLY ranked metric.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** usable depeg events across the universe. *(Honest note: very
      likely FAILS — depegs of major stablecoins are rare. A small-N verdict is
      an acceptable and expected outcome; we report N honestly rather than
      manufacturing events by lowering the threshold post-hoc.)*
- [ ] **After-cost mean (PRIMARY `ret_30d`) WITH dead coins** positive with
      **|t| ≥ 2.0**.
- [ ] **Survivorship check (the headline):** after-cost mean WITH vs WITHOUT
      dead coins (UST/USTC and any terminal coin). If excluding the corpses is
      what makes the mean positive, the strategy is a survivorship artifact →
      KILL regardless of the survivor-only t-stat.
- [ ] **Tail/skew report:** full loss distribution — min, p5, median, mean, max,
      skew, and the single worst event's contribution. Short-vol signature
      (median > mean, fat left tail) is itself disqualifying evidence.
- [ ] **OOS sign stability** — IS (pre-2023) and OOS (2023+) same sign. *(May be
      unreportable if either half has N<10 — state honestly.)*
- [ ] **Placebo** — random non-event entry dates on the same symbols show ~0
      forward return; the depeg signal must beat its own baseline drift.
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from
      mean auto-triggers placebo + top-contributor inspection. *(A high win rate
      here is EXPECTED and is itself the red flag — short-vol strategies win
      often and lose huge.)*
- [ ] **Data provenance** — source, construction, staleness, USDT-quote caveat
      documented (§3).

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY (`ret_30d`, WITH dead coins) mean ≤ 0, OR |t| < 2.
- **Including the dead coins flips the survivor-only positive mean to ≤ 0** (the
  survivorship-artifact verdict — the expected outcome).
- Tail dominates: removing the single worst event flips the sign, OR median ≫
  mean with a fat left tail (short-vol signature).
- N < 30 usable events → cannot claim a statistical edge; verdict is
  "N-too-small / tail-dominated, not claimable" (a KILL for *claiming an edge*,
  honestly reported as such).
- Placebo absorbs the effect, OR OOS sign flips.

## 9. Limitations

- **USDT-quote denomination:** prices are in USDT, not pure USD; documented in
  §3. Mitigant: USDT ≈ $1 across windows; bias if any is to *understate* depeg
  depth (conservative for the survivor side, makes the test if anything *kinder*
  to the hypothesis).
- **Daily bars only:** intraday depeg lows (USDC ~$0.88) are deeper than the
  daily close (~$0.985); using daily close *understates* both the entry discount
  and the intraday recovery. A daily-close test is conservative on entry timing.
- **Small universe:** ~8-11 stablecoins, rare events → low N is intrinsic and
  expected. A kill here does NOT prove no stablecoin re-peg trade exists at
  finer (intraday, on-chain) resolution or with active solvency screening — it
  proves the **naive daily "buy any depeg" rule is a survivorship trap** once
  the deaths are honestly included.
- **No solvency filter:** the hypothesis under test is deliberately the *naive*
  rule (buy ANY depeg). The whole point is to show that the naive rule's tail is
  fatal; a smarter solvency-screened variant is out of scope.
