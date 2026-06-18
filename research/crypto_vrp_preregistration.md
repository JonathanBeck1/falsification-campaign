# Pre-Registration: Crypto Volatility Risk Premium (T32)

> Status: pre-registered design, written **before** computing any spread,
> return, t-stat, or tail metric. The IV source, short-vol construction,
> friction, IS/OOS split, gate, and KILL criteria are fixed here so a favorable
> specification cannot be selected after the fact. Standard campaign template
> (`brain/34_master_test_registry.md`, universal gate in
> `brain/30_campaign_findings.md`). This is the **crypto analog** of the equity
> VRP kill (`brain/decisions/2026-06-13-vrp-qqq-in-sample-kill.md`); the lessons
> from that kill (mechanism null, tail risk) are built into the gate below.

## 1. Hypothesis (one sentence, directional, falsifiable)

Crypto 30-day implied volatility (Deribit DVOL for BTC and ETH) systematically
exceeds subsequent 30-day realized volatility — a positive crypto Volatility
Risk Premium (IV − RV > 0) — and a short-vol position that sells this premium
earns a **positive after-cost return with |t| ≥ 2 that survives its catastrophic
left tail**.

## 2. Mechanism — why would this be inefficient?

Structural insurance demand: option *buyers* (retail, miners hedging, levered
longs buying downside protection, structured-product desks) systematically
overpay for convexity, so sellers of vol earn a premium for warehousing tail
risk. This is the *same* economic VRP mechanism as equities (SPX/QQQ), but in a
**younger, retail-heavy, less-arbitraged** market: crypto options liquidity is
thin, dealer balance sheets are small, and there is no deep institutional
vol-selling complex compressing the premium — so the premium *could* be larger
and more persistent than in equity index options.

The counterparty paying the premium: net option buyers (protection-seekers and
lottery-ticket longs). The friction stopping it being arbed away: warehousing
crypto vol requires posting margin against genuinely unbounded gap risk (no
circuit breakers, 24/7, exchange/oracle failure), so capital is scarce and the
premium persists as compensation for ruin risk — **not** a free lunch.

**Honest prior: null → marginal.** The equity VRP (a stronger, more-studied,
more-liquid version) was just KILLED at the mechanism level on QQQ in-sample
(IV-RV↔pnl Pearson = 0.01, expectancy −$5.96/t, t=−0.55). The mechanism-null
finding there is partly underlying-agnostic. The crypto-specific *hope* is that
the less-arbitraged market preserves a premium equities have competed away — but
the dominant prior, post-equity-kill, is that any apparent crypto VRP return is
short-gamma beta plus a fat left tail, not a harvestable spread. **The crypto
tail is worse**: a single 2021-05 / 2022-05 (LUNA) / 2022-11 (FTX) vol spike can
wipe years of premium, so the honest verdict hinges on the tail, not the mean.

## 3. Data + provenance

- **Instruments (fixed):** BTC and ETH (the only two DVOL currencies). No
  post-hoc currency selection.
- **IV source:** Deribit public REST
  `GET /api/v2/public/get_volatility_index_data`, the **DVOL** index — a
  model-free 30-day forward implied-vol index (Deribit's BTC/ETH analog of VIX),
  in annualized vol points (%). Daily resolution (`resolution=86400`), OHLC; we
  use the **close** of the DVOL index each UTC day.
- **RV source:** realized volatility computed from BTC/ETH **spot daily close**
  via `crypto_data.fetch_kline_history` (Binance `data.binance.vision` archive,
  same survivorship-honest source as T29/T33). RV(t) = annualized stdev of the
  next-N daily log returns (close-to-close), N = 30, scaled by √365 to match
  DVOL's annualized 30-day convention.
- **Construction & staleness:** DVOL close is the realized index level for that
  UTC day (no derived/parity series — provenance is Deribit's own published
  index). Spot RV is a *forward* window: it uses returns strictly **after** the
  IV observation (look-ahead audit in §5). No adjustment, no survivorship issue
  (BTC/ETH are live majors).
- **Event/date list:** every UTC day with both a DVOL close and ≥ N forward
  spot closes. Knowable ex-ante (the IV is observed at t; the trade is opened at
  t; the RV is only used to *score* the premium ex-post, never to select entry).
- **Sample span:** DVOL history begins **2021-03-24** (verified live — the index
  did not exist before; this is the hard data wall). Span 2021-03-24 .. run date
  (~2026-06). **IS = 2021-03-24 .. 2023-12-31** (includes 2021-05 crash, LUNA
  May-2022, FTX Nov-2022 — the tails). **OOS = 2024-01-01 .. run date.**

## 4. Cohort & control definition

- **Spread (the VRP measurement):** for each day t,
  `vrp(t) = DVOL_close(t) − RV_fwd(t, N=30)`, both in annualized vol points.
  Mean spread > 0 is the *existence* claim (necessary, not sufficient).
- **Short-vol proxy return (the tradeable claim):** a daily-rebalanced short
  position in a synthetic 30-day variance/vol exposure, P&L proxied as
  `short_vol_pnl(t) = scale * (IV(t-1)^2 − rv_1d(t)^2) − cost`, i.e. each day the
  short-variance book collects the entry implied variance and pays the realized
  daily variance (the standard variance-swap replication accrual), where
  `rv_1d(t)` is that day's squared log return annualized. This is the honest,
  *path-dependent* short-vol P&L that actually eats the tail — a single huge
  daily move makes `rv_1d^2 ≫ IV^2` and produces a large loss, exactly the
  catastrophe the gate must survive. `scale` normalizes to vega-equivalent units
  (so a 1-vol-point miss is comparable across the IV range).
- **Control / baseline (the mechanism test — THE KEY CONTROL):** Pearson
  correlation between the entry-day **IV−RV spread** and the realized
  short-vol P&L. If the P&L is genuinely *harvesting the premium*, days with a
  bigger ex-post-overpriced IV should pay more → positive correlation. If
  correlation ≈ 0 (the equity-VRP failure mode), the returns are short-gamma
  **beta**, not VRP. Additionally: a long-vol / random-sign placebo book must
  show ~0, and we report buy-and-hold short-vol vs the spread monotonicity by
  spread quartile.
- **t0:** the IV is observed at the close of day t; the short-vol accrual is
  earned over day t+1 (so entry information strictly precedes the P&L day).

## 5. Measurement window + LOOK-AHEAD statement

- **Windows:** PRIMARY = the daily short-vol proxy return series (full sample),
  after cost; the spread series is the supporting *existence* measurement at
  N=30 forward.
- **Look-ahead audit:** The entry signal is IV(t) and IV(t-1), both observed at
  or before the close of day t. The short-vol P&L for day t+1 uses *only* that
  day's realized squared return, which occurs strictly **after** the entry IV.
  The 30-day forward RV used for the IV−RV *spread* statistic is, by
  construction, a *forward* window (returns after t) — it is used **only to score
  the premium ex post**, never to filter or select entry days, so it introduces
  no look-ahead into the tradeable return. Every entry day is taken
  unconditionally; no day is selected using future information.

## 6. Friction model

- **Round-trip cost:** crypto options are expensive to trade. Deribit option
  fees are min(0.0003 BTC, 0.125% of premium) per contract plus wide bid/ask on
  the wings. We model a conservative **2 vol-points** round-trip friction per
  rebalance equivalent on the short-vol proxy (bid/ask + fee + delta-hedge
  slippage), applied as a daily cost drag of `2_vol_pts^2` variance-equivalent
  scaled to the daily accrual. We additionally stress at **2× cost (4 vol-pt)**.
- **Application:** subtract once per round trip from gross; after-cost return is
  the ONLY ranked metric.

## 7. Pre-registered gate (ALL must hold — from brain/30, + crypto-tail addenda)

- [ ] **N ≥ 30** usable days (trivially satisfied; ~1,900 days expected).
- [ ] **After-cost expectancy** of the short-vol proxy positive with
      **|t| ≥ 2.0** on the PRIMARY (daily) series.
- [ ] **OOS sign stability** — IS (2021-03..2023-12) and OOS (2024-01..) same
      sign, both N ≥ 10.
- [ ] **Mechanism (replaces pooled baseline) — MANDATORY, NON-SIGN-ONLY:** the
      Pearson correlation between entry-day IV−RV spread and short-vol P&L must
      be **≥ +0.10 AND** the spread-quartile P&L gradient must be **monotone
      increasing** (Q1 < … < Q4). A sign-only "> 0" pass is explicitly
      INSUFFICIENT (the equity kill's lesson: +0.01 nominally cleared a sign-only
      gate yet the mechanism was null). If correlation < 0.10 or the gradient is
      non-monotone, the "edge" is short-gamma beta, not VRP → KILL.
- [ ] **Placebo** — a long-vol (sign-flipped) book and a random-entry book show
      ~0 / mirror; claim requires the short book's edge not be reproduced by the
      placebo.
- [ ] **TAIL SURVIVAL — MANDATORY (crypto-specific):** report the worst single-
      day loss, the max peak-to-trough drawdown, and the after-cost return with
      the **single worst vol-spike month removed AND retained**. The claim
      requires the after-cost mean to remain **positive with |t| ≥ 2 INCLUDING
      the full tail** (no trimming). If a single spike month flips the verdict,
      the premium does not survive its tail → KILL.
- [ ] **Too-good tripwire** — Sharpe > 3 / win rate > 85% / median ≫ mean
      auto-triggers placebo + top-5 worst-day inspection (short-vol win rate is
      *expected* high with a fat left tail — that asymmetry is itself the
      tripwire, and a high win rate with negative tail-inclusive expectancy is a
      KILL, not a pass).
- [ ] **Data provenance** — DVOL = Deribit published index (§3); RV = Binance
      archive spot closes (§3). Both documented.

No alternative window may replace the PRIMARY if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY (full-sample, tail-inclusive) |t| < 2, OR expectancy ≤ 0.
- Mechanism: |corr(spread, pnl)| < 0.10 OR non-monotone spread-quartile
  gradient (returns are short-gamma beta, not VRP — the equity-kill failure).
- OOS sign flip vs IS.
- Removing the single worst vol-spike month flips the sign / the verdict
  hinges on excluding the tail (premium does not survive its catastrophe).
- Placebo (long-vol/random) reproduces the edge.
- N < 30 (not expected).

## 9. Limitations

- **Hard data wall:** DVOL does not exist before 2021-03-24, so the 2020-03
  COVID crypto crash (a canonical vol spike) is OUT of sample — we cannot test
  the premium across that tail. The IS window still contains 2021-05, LUNA
  (2022-05), and FTX (2022-11), three severe spikes.
- The short-vol P&L is a **variance-swap-replication proxy**, not a backtested
  options book with real Deribit quotes/strikes/margin — it captures the
  vol-selling accrual and the realized-variance tail honestly but abstracts
  away exact strike selection, delta-hedge execution, and margin calls. A KILL
  here kills the *clean variance-premium* claim; it does not prove a hand-tuned,
  conditioned, actively-hedged options book is impossible (that would need its
  own pre-reg and real quote data).
- A KILL does NOT prove crypto IV never exceeds RV (it usually does, in the
  mean) — it proves the *spread is not after-cost harvestable once its tail is
  paid*, which is the only economically meaningful claim.
