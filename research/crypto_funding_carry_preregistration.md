# Pre-Registration: Perp Funding-Rate Carry, cross-sectional alt tail (T29)

> Status: pre-registered design, written **before** collecting or inspecting
> results. Hypothesis, sample, windows, split, gate, and kill criteria are fixed
> here so a favorable specification cannot be selected after the fact. Standard
> campaign template (universal gate in `brain/30_campaign_findings.md`;
> data-construction warning in `brain/33_data_acquisition_strategy.md`).

## 1. Hypothesis (one sentence, directional, falsifiable)

A delta-neutral funding-carry book that, each day, shorts the perps paying the
most positive funding and harvests that funding earns a **positive after-cost
return that is NOT explained by long crypto price drift**, and the **alt tail
pays more** than the majors.

## 2. Mechanism — why would this be inefficient?

Perpetual-futures funding is the cash flow that tethers perp price to spot:
when longs crowd the trade, funding goes positive and **longs pay shorts**. The
structural claim (brain/33): retail crowds *directional longs* in the small-cap
alt tail, so funding is persistently positive there; the arbitrageur who shorts
the perp and (notionally) holds spot delta-neutral collects that funding. It
persists because the offsetting capital is inventory-/counterparty-/borrow-
constrained on illiquid alts — you cannot freely borrow and short a微 token, and
exchange/custody risk on the alt tail keeps arb capital away.

**Honest prior: small-to-null, survivorship-fragile.** Published crypto-carry
results are notorious for two lies — (a) survivorship (dead tokens that paid huge
funding right before going to zero are dropped), and (b) fee optimism (crypto
taker fees ~5–10 bps/side are *large* and funding is only ~1 bp/8h on average).
Funding has been a known retail topic since ~2021, so any clean edge has had time
to compress. Prior leans KILL.

## 3. Data + provenance

- **Universe (fixed, survivorship-aware):** every USDⓈ-M (USDT-margined) perp
  that has a funding-rate dump in Binance's public archive `data.binance.vision`
  — **LIVE *and* DELISTED**. The archive is append-only and never purges dead
  symbols (verified: SRMUSDT funding 2020-09..2024-07, BTSUSDT ..2024-08, vs
  BTCUSDT ..current). The delisted flag = "last funding month lags the archive
  frontier by > 2 months". This is the survivorship correction the equity
  small/illiquid kill (#10) and brain/33 demand. Majors = {BTC, ETH, BNB}; the
  **alt tail = everything else**.
- **Source:** `data.binance.vision` monthly dumps (no auth, no key, no geoblock).
  funding = `.../futures/um/monthly/fundingRate/<SYM>/`; price =
  `.../futures/um/monthly/klines/<SYM>/1d/`. Built via
  `src/trader/catalysts/crypto_data.py` (pure parse core + injectable HTTP seam,
  unit-tested network-free).
- **Construction & staleness:** funding is the realized per-interval rate (3×/day,
  8h intervals → summed to a daily funding yield). Price is the perp daily close
  (UTC). A symbol contributes only on days within its own listing span (a
  delisted token contributes funding *and* its terminal price collapse — no
  forward-fill past its last bar; its delisting is a realized event, not a gap).
- **Carry construction (fixed):** each UTC day *t*, rank symbols by **trailing**
  funding (mean per-interval funding over the prior 7 days, computed with data
  available *as of the close of t-1*). Form an equal-weight **short-perp** book
  on the top-funding decile (positive funding → short collects it). Daily book
  P&L = (funding collected on day *t*) − (perp price return on the short leg on
  day *t*) − (rebalance turnover cost). Delta-neutral idealization: the long-spot
  leg is assumed to exactly offset the short-perp **price** delta, so the price
  term that survives is the basis/slippage, NOT spot beta. We make this explicit
  and ALSO report the non-neutral decomposition (see §5 control).
- **Sample span:** IS **2020-01-01 .. 2022-12-31** · OOS **2023-01-01 ..
  2025-12-31**. (Binance UM funding starts 2020-01 for BTC; most alts onboard
  later — each symbol enters on its own first bar.)

## 4. Cohort & control definition

- **Cohort (treated):** the daily top-funding-decile short-perp carry book, over
  the survivorship-aware universe (delisted included).
- **Controls / baselines (three, all pre-registered):**
  1. **Survivor-only re-run** — same logic restricted to symbols still live at the
     frontier. The *gap* between cohort and survivor-only is the survivorship-bias
     magnitude (expected: survivor-only looks BETTER, because it drops the tokens
     that died after paying funding).
  2. **Price-drift decomposition (THE critical control, brain/33):** decompose the
     book return into **funding-collected** vs **perp-price-PnL**. A "carry" that
     is really just being short a falling alt market (or long a rising one) is not
     edge. Edge requires the *funding* component to dominate and the price
     component to be ~0 under the delta-neutral idealization.
  3. **Random-decile placebo:** rank-shuffle the funding signal (pick the carry
     basket at random each day, same size, same friction). A real funding edge
     must beat this placebo.
- **Signal:** trailing-7d mean funding, lagged one day (no same-day look-ahead).

## 5. Measurement window + LOOK-AHEAD statement

- **Window:** daily, IS then OOS. PRIMARY metric = **mean daily after-cost book
  return, annualized, with t-stat on the daily series**.
- **Look-ahead audit:** the carry basket on day *t* is selected from funding
  **realized through t-1** (trailing-7d mean lagged 1 day); the P&L is funding +
  price *on day t*. Selection information strictly precedes the measured return.
  Funding intervals are stamped at their settlement time; we only use intervals
  whose `calc_time < t 00:00 UTC` for selection. Delisted tokens are NOT
  hindsight-removed — they sit in the universe until their last real bar, so a
  token that paid funding then crashed contributes the crash.

## 6. Friction model

- **Round-trip cost: 12 bps** = ~6 bps/side Binance taker (alt perp taker ≈
  4–7 bps; we take the pessimistic end) × 2 sides, applied to **turnover** (the
  fraction of the book that changes names on each daily rebalance), NOT to the
  full notional every day. A fully-held name pays nothing on a day it stays in.
- Funding is netted as a cash flow (collected when short into positive funding,
  paid when funding flips negative on a held short). Spot-leg trading cost for the
  delta-neutral hedge is included in the same 6 bps/side (spot taker is similar).
- After-cost annualized return + t is the ONLY ranked metric.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** trading days with ≥ 5 names in the basket (cross-sectional N).
- [ ] **After-cost** mean daily return **> 0 with |t| ≥ 2.0** on the PRIMARY
      (full-sample daily) series.
- [ ] **OOS sign stability** — IS and OOS halves same sign, both with ≥ 30 days.
- [ ] **Survivorship check** — cohort (delisted-included) result is reported
      *alongside* survivor-only; the claim rests on the **delisted-included**
      number. If survivor-only is the only positive one, that is a KILL, not a pass.
- [ ] **Price-drift decomposition** — the **funding** component must be the
      dominant positive driver; if the edge is really perp-price drift (being net
      short a falling market), KILL.
- [ ] **Placebo** — random-decile placebo ≈ 0 (|t| < 2); cohort must beat it.
- [ ] **Too-good tripwire** — annualized Sharpe > 3 or win-rate > 85% auto-triggers
      a top-contributor inspection (which tokens/days drive it) before any write-up.
- [ ] **Data provenance** — source/construction/staleness documented (§3).

No alternative window/decile may replace the PRIMARY if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY |t| < 2, OR after-cost mean ≤ 0.
- OOS sign flip.
- The **price** component (not funding) drives the positive result — it's crypto
  beta, not carry.
- **Survivor-only is positive but delisted-included is not** — the apparent edge
  is pure survivorship conditioning.
- Random-decile placebo is not ~0 (the "edge" is a friction/construction artifact,
  not the funding signal).
- Fewer than 5 tokens drive the result (remove top contributors → it vanishes).

## 9. Limitations

- **Delta-neutral idealization.** We assume the long-spot leg perfectly offsets
  the short-perp price delta intraday. Real execution has basis slippage,
  spot/perp tick mismatch, and rebalance drift the daily model cannot see — so the
  decomposition's "price ≈ 0" is an *idealization*; a real book carries residual
  delta. A KILL here is strong (even the idealized book fails); a PASS would still
  need live-execution validation before sizing.
- **Funding settlement granularity.** We aggregate 8h funding to daily; intraday
  position changes between funding stamps are not modeled.
- **Borrow/shortability of spot.** The mechanism *assumes* you can hold spot to
  hedge; for the deepest alt tail, spot custody/borrow may be infeasible — the
  model does not charge for that, so it is optimistic in the alt tail's favor.
- **What a kill does NOT prove:** it does not prove funding carry is dead on every
  venue/horizon — only that the daily, equal-weight, top-decile Binance-UM
  expression, net of honest taker fees and survivorship, is not a claimable edge.
