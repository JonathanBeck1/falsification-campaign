# Pre-Registration: Crypto Time-Series Momentum / Trend-Following (T33)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypothesis, sample, windows, split, gate, and kill criteria are
> fixed here so a favorable specification cannot be selected after the fact.
>
> Standard campaign template (see `brain/34_master_test_registry.md` and the
> universal gate in `brain/30_campaign_findings.md`). Reuses the survivorship-
> aware Binance foundation `src/trader/catalysts/crypto_data.py` (built for T29).

## 1. Hypothesis (one sentence, directional, falsifiable)

A time-series momentum rule on crypto perps — long an asset when its trailing
N-day return is > 0, flat otherwise, applied per-asset and equal-weighted across
the survivorship-aware universe — earns a **positive after-cost risk-adjusted
return whose Sharpe EXCEEDS buy-and-hold** (BTC and equal-weight universe) over
2020–2025.

## 2. Mechanism — why would this be inefficient?

Behavioral trend persistence in a retail-heavy, 24/7, low-institutional-
arbitrage market: under-reaction to information and herding/FOMO inflows push
prices in the same direction for weeks, so trailing return predicts next-period
return. The forced/uninformed counterparty is the late retail entrant; the
friction that could let it persist is the absence of a deep, low-cost arbitrage
community early in crypto's history (vs equities/FX where TSMOM has largely
decayed and is heavily mined).

**Honest prior: small-to-null, leaning to "just beta-timing".** Crypto trend-
following is one of the most-mined retail strategies on earth. The base rate
from this campaign is 19 tests / 19 kills. The single most likely failure mode
is NOT a fee wipeout but **the strategy merely capturing the 2020–2021 bull run
with lower drawdown** — i.e. beta-timing / exposure management, not alpha. That
is the same lesson as the sell-in-May kill: lower drawdown at a lower Sharpe is
not an edge. Prior probability of a real risk-adjusted edge: **low (~10–15%)**.

## 3. Data + provenance

- **Universe (fixed):** every USDT perp with a funding/kline dump in the Binance
  `data.binance.vision` archive, sampled by an **evenly-strided** alphabetical
  slice (NOT a recency/liquidity filter — does not reintroduce survivorship). The
  universe **RETAINS delisted symbols** (the archive is append-only and never
  purges dead perps; T29 verified ~23% are delisted). Equal-weight across all
  names with a live price on each day.
- **Source:** `data.binance.vision` (Binance public S3 archive, no API key, not
  geoblocked) via `src/trader/catalysts/crypto_data.py`. Daily klines (`1d`).
- **Construction & staleness:** daily close-to-close returns from real exchange
  closes. A delisted token's collapse is realized by its actual final closes (no
  forward-fill past delisting). No adjustment needed (perps, no dividends/splits).
- **Date list:** every UTC trading day a symbol has a real kline; knowable
  ex-ante (the bar exists at its own close).
- **Sample span:** **IS 2020-01-01 .. 2022-12-31** · **OOS 2023-01-01 .. 2025-12-31.**
  (IS deliberately contains the 2020–21 bull AND the 2022 bear so the IS half
  alone cannot be "all bull".)

## 4. Strategy & control definition

- **Signal (per asset, fixed):** trailing N-day simple return
  `r_trail(t) = close(t-1)/close(t-1-N) - 1`, computed through **t-1** only.
  Two **pre-registered lookbacks, fixed in advance, NOT mined: N ∈ {30, 90}.**
- **Position (long-flat PRIMARY):** `pos(t) = 1 if r_trail(t) > 0 else 0`.
  Equal-weight across all names with a position; daily rebalance.
- **Secondary (reported, not the claim):** long-short `pos = sign(r_trail)`.
- **Daily book return:** `mean_i[ pos_i(t) · ret_i(t) ] − turnover · cost`.
- **THE KEY CONTROL (exposure / beta-timing):** compute the Sharpe of:
  (a) the momentum book, (b) **buy-and-hold BTC**, (c) **buy-and-hold the equal-
  weight universe**. The claim REQUIRES momentum Sharpe to exceed BOTH B&H
  Sharpes. If momentum just captures the bull run with less drawdown at a Sharpe
  ≤ B&H, that is beta-timing/exposure, **NOT alpha** — and is a KILL.
- **PRIMARY lookback for the gate: N = 90** (the slower, less-traded, less-fee-
  sensitive horizon; chosen ex-ante, not after seeing results). N = 30 is
  reported and must not be substituted if N = 90 fails.

## 5. Measurement window + LOOK-AHEAD statement

- **Window:** daily after-cost book returns over the full span; PRIMARY metric is
  the **after-cost annualized Sharpe** of the N=90 long-flat book vs the two B&H
  Sharpes.
- **Look-ahead audit:** the signal `r_trail(t)` uses closes only through `t-1`;
  the position taken at `t` earns `ret_i(t)` (the t-1→t close return). Selection
  information strictly precedes the return it earns. The lag is enforced in code
  (`.shift(1)`) and pinned by a unit test. No future close enters the signal.

## 6. Friction model

- **Round-trip cost:** **12 bps** = ~6 bps/side crypto taker × 2, applied to the
  fraction of the book that **changes position** each day (turnover). Trend rules
  trade often → fees are LARGE and modeled honestly on every flip. A 2× stress
  (24 bps) is reported.
- **Application:** subtract per-day `turnover · cost` from the gross book; the
  after-cost Sharpe / mean is the ONLY ranked metric.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** usable days with a non-empty basket (trivially met; real bar is
      the multi-year daily series).
- [ ] **After-cost expectancy** positive with **|t| ≥ 2.0** on the PRIMARY (N=90,
      long-flat) daily book.
- [ ] **OOS sign stability** — IS and OOS after-cost mean same sign (positive),
      both halves N ≥ 30 days.
- [ ] **EXPOSURE / BETA-TIMING CONTROL (the key one):** momentum after-cost
      **Sharpe > buy-and-hold BTC Sharpe AND > buy-and-hold equal-weight-universe
      Sharpe**, on the SAME span. Failing this = beta-timing, not alpha = KILL.
- [ ] **Placebo** — random entry/exit timing (signal shuffled / random position
      with matched exposure) shows after-cost |t| < 2 (~0).
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from mean
      auto-triggers a placebo run + top-contributor inspection before any write-up.
- [ ] **Data provenance** — source, construction, staleness documented (§3).

No alternative lookback (N=30) may replace the PRIMARY (N=90) if the primary
gate fails.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY (N=90) |t| < 2, OR after-cost expectancy ≤ 0.
- **Momentum after-cost Sharpe ≤ EITHER buy-and-hold Sharpe** (BTC or EW
  universe) — the effect is beta-timing/exposure, not alpha. THIS IS THE
  HEADLINE KILL CONDITION.
- OOS after-cost sign flip (effect decayed / regime-dependent).
- Placebo (random timing) reproduces the result (|t| ≥ 2): the "edge" is just
  exposure to a rising market, not the timing rule.
- After-cost return is positive only because of fees being understated (effect
  vanishes / flips sign at the 2× cost stress while B&H is unaffected).

## 9. Limitations

- Daily-bar resolution only; intraday trend variants and faster rebalances are
  NOT tested — a kill here does not prove higher-frequency trend is dead.
- Equal-weight EW universe is a coarse "market" proxy; BTC B&H is the cleaner
  beta benchmark and is the binding control.
- Long-flat ignores borrow/short-funding nuance of the long-short variant; the
  claim rests on long-flat, the realistically tradeable retail version.
- A kill proves "this pre-registered daily TSMOM rule, after honest crypto fees,
  does not beat buy-and-hold risk-adjusted" — NOT that no trend signal of any
  spec/horizon/asset could ever work.
