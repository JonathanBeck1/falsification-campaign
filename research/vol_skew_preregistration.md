# Pre-Registration: Single-name 25-delta skew dynamics (T25)

> Status: pre-registered design, written **before** computing or inspecting any
> results. Hypothesis, sample, windows, split, gate, and kill criteria are fixed
> here so a favorable specification cannot be selected after the fact.
>
> Universal gate: `brain/30_campaign_findings.md`. Foundation reused:
> `src/trader/catalysts/vol_surface_data.py` (`risk_reversal_25d`, `atm_iv`,
> `compute_implied_vols`, `load_option_quotes`). Slug: `vol_skew`.

## 0. Universe (fixed, explicit)

The 24 fully-collected single names in the EOD option lake (2022–2026, ~1115
trade-days each):

```
ADBE AMAT AMD AVGO BKNG COST CSCO GOOG GOOGL HON INTU ISRG LIN LRCX
META MU NFLX PEP QCOM REGN TMUS TSLA TXN VRTX
```

Plus the two indices **QQQ, SPY** used ONLY as the pooled/market control (NOT as
cohort members; the test is single-name). **AAPL, AMZN, NVDA are EXCLUDED** —
still being collected, not fully populated.

## 1. Hypothesis (two framings; PRIMARY declared)

Define **skew(i,t) = IV(25Δ put) − IV(25Δ call)** for name *i* on day *t* at the
~30-day tenor (`risk_reversal_25d`, target_days=30, target_delta=0.25). Positive
skew = downside vol richer than upside = the normal equity crash-fear shape.

- **(a) Skew as a SIGNAL** — the cross-sectional level (and, separately, the
  20-day change) of `skew(i,t)` predicts name *i*'s subsequent ~21-trading-day
  forward stock return. Direction tested: high put-skew names = elevated
  crash-fear → could be either an oversold-bounce *positive* predictor or a
  realized-downside *negative* predictor; we test the sign, do not assume it.
- **(b) Skew PREMIUM** — systematically **selling the 25Δ put and delta-hedging**
  (short crash insurance) earns a positive after-cost premium for bearing crash
  risk.

**PRIMARY = (a), the SIGNAL framing, level-based, long–short decile.** Reason:
the signal test is a clean cross-sectional predictive claim that does not require
a full options execution/margin model, so its gate is the least ambiguous; the
premium framing (b) is the SECONDARY confirmatory leg and is where the KEY
control (skew premium = short-vol + short-delta beta in disguise) lives.

## 2. Mechanism — why might this be inefficient?

Crash-insurance demand: institutional hedgers and structured-product desks are
chronic net buyers of downside (25Δ) puts, pushing put IV above call IV. The
counterparty (the put seller) is compensated for bearing crash risk — a *risk
premium*, not necessarily alpha. For the SIGNAL framing, the behavioral story is
that skew over/under-reacts to crash fear, so its level/change carries
information about subsequent returns that the spot market is slow to price. The
friction that could let it persist: shorting crash insurance has a fat left tail
(2022, regime selloffs) that deters arbitrage capital.

**Honest prior: NULL → small.** T03 already tested 25Δ skew as a QQQ option
feature and found *no edge*. The campaign's one mechanistically-real vol premium
(crypto VRP, T32) was decaying and a proxy; the equity VRP (T19) was mechanism-
null (corr ≈ 0.01). Strong prior that any "skew premium" here is short-vol +
short-delta beta, not a distinct skew alpha. We expect a KILL and design to catch
the disguise.

## 3. Data + provenance

- **Universe (fixed):** the 24 names in §0; QQQ/SPY market control only.
- **Source:** owned EOD option-chain parquet lake
  `$TRADER_EOD_LAKE_ROOT/` (ThetaData,
  collect-then-own). Underlying spot joined from yfinance daily close (lake's
  `underlying_close` is NULL across the lake — documented in `vol_surface_data`).
- **Construction & staleness:** option price = mid=(bid+ask)/2; two-sided quotes
  only; IV via the audited Black–Scholes solver; r=4% flat, q=0 (skew is an IV
  *difference* at the same date → rate/div differenced out). Skew is computed
  causally from day-*t* EOD quotes; forward return uses spot strictly AFTER *t*.
  Sampling cadence: **weekly (every 5th trade-day per name)** to reduce
  overlap-induced autocorrelation in the 21-day forward return; the panel is
  built once and frozen.
- **Forward return:** name *i* spot close-to-close from t0 to t0+21 trading days,
  from yfinance (the same source `vol_surface_data` already uses).
- **Sample span:** lake 2022-01-03 .. 2026-06-12. **IS = 2022-01 .. 2024-03**
  (early ~½), **OOS = 2024-04 .. 2026-06** (late ~½). Split fixed by calendar
  midpoint, declared before results.

## 4. Cohort & control definition

- **SIGNAL (PRIMARY):** each weekly cross-section, rank names by `skew(i,t)`;
  **long the bottom decile (lowest put-skew), short the top decile (highest put-
  skew)** — sign-agnostic: we report the realized sign and judge by |t|. With 24
  names a "decile" is the top/bottom ~⅓ (8 names each side; pre-registered as
  tertiles given N=24, NOT deciles — fixed here). Abnormal return = name fwd ret
  − equal-weight universe fwd ret (cross-sectional demean), so the long–short is
  market-neutral by construction.
- **Change variant (SECONDARY):** same construction on Δ20-day skew.
- **Control / baseline:** (i) the equal-weight universe forward return (pooled
  baseline; the long–short already nets it out); (ii) **placebo** = shuffle the
  skew→name assignment within each date 200× and re-rank (composition-matched
  permutation); claim requires perm p<0.05. (iii) up/down symmetry: does sorting
  on +skew and −skew give symmetric P&L (real signal) or same-sign (drift)?
- **PREMIUM (SECONDARY) + KEY control:** short 25Δ put, daily delta-hedged proxy
  P&L per name (collect put theta/premium, pay realized downside). KEY control —
  regress the premium P&L on (short ATM-straddle vol P&L) and (−1×name beta·
  market ret); the *residual* alpha is the only claimable skew premium. If the
  premium is fully explained (residual |t|<2), it is short-vol+short-delta beta
  in disguise → not a distinct edge.

## 5. Measurement window + LOOK-AHEAD statement

- **Windows:** PRIMARY = `fwd_ret_0_p21` (t0→t0+21 trading days). t0 = the first
  trading day STRICTLY AFTER the EOD snapshot date *t* (skew is known at *t*'s
  close; we can only act at *t+1* open / *t+1* close — we use *t+1* close to
  *t+21* close, i.e. no same-bar leak).
- **Look-ahead audit:** the cohort/sort is defined entirely by `skew(i,t)`
  computed from day-*t* EOD option quotes; the forward return measurement window
  begins at *t+1* and uses only spot at/after *t+1*. No element of the return
  window overlaps the snapshot that defines membership. Skew itself uses only
  same-day quotes (no future expiration data). The IS/OOS calendar split is
  ex-ante.

## 6. Friction model

- **Round-trip cost (SIGNAL):** single-name equity round trip ~**10 bps** (5 bps
  each side; conservative for these liquid mega/large-caps). Charged once per
  rebalance per leg of the long–short. We also stress at **2× (20 bps)**.
- **Round-trip cost (PREMIUM):** option round trip is far costlier; we charge a
  **vega/vol-point friction** consistent with the T32 VRP convention plus the
  delta-hedge stock cost. The premium claim must survive 2× cost.
- After-cost expectancy is the ONLY ranked metric. No pre-cost ranking anywhere.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** usable cross-sections (weekly dates with ≥ ~12 names having a
      valid skew). With ~225 weekly dates × ~24 names this is easily met; the
      binding N for the t-stat is the number of weekly long–short observations.
- [ ] **After-cost expectancy** correct-signed with **|t| ≥ 2.0** on the PRIMARY
      (`fwd_ret_0_p21`, level-sorted tertile long–short), Newey–West / clustered
      where overlap remains.
- [ ] **OOS sign stability** — IS and OOS halves same sign, both N ≥ 10.
- [ ] **Pooled baseline** — long–short already nets the universe; explicitly
      report universe mean and the up/down symmetry check.
- [ ] **Matched-control / placebo** — within-date skew-shuffle permutation shows
      ~0; claim requires perm p<0.05 AND net |t| ≥ 2.
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from mean
      auto-triggers placebo + top-5 contributor inspection before any write-up.
- [ ] **TAIL (mandatory for any short-crash-insurance leg)** — report worst
      single-period P&L, max drawdown, and drop-worst robustness. A premium
      claim that hinges on excluding the 2022 selloff is rejected.
- [ ] **KEY control (premium)** — premium residual after short-vol + short-delta
      beta must keep |t| ≥ 2, else the "premium" is disguised beta → KILL.
- [ ] **Data provenance** — documented in §3.

No alternative window may replace the PRIMARY if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill if ANY holds:

- After-cost PRIMARY |t| < 2, OR after-cost expectancy wrong-signed/≤0 for the
  declared long–short.
- N < 30 usable weekly cross-sections.
- OOS sign flip (effect decayed / regime-dependent).
- Placebo absorbs the effect (perm p ≥ 0.05 or net |t| < 2).
- Fewer than 5 names/dates drive the result (drop top contributors → vanishes).
- **Premium framing:** residual alpha after the short-vol + short-delta beta
  control has |t| < 2 (it was beta in disguise), OR the verdict hinges on
  excluding the worst drawdown month.

## 9. Limitations

A kill does NOT prove skew carries no information at finer cadence (intraday,
0DTE), under a different tenor/delta, or in a conditioned subset (earnings,
high-VIX). It tests the unconditioned weekly cross-sectional level/change of the
30-day 25Δ skew across 24 liquid large-caps, EOD, after realistic cost. The 24-
name universe is small for a cross-section (tertiles of 8), so the cross-
sectional t-stat has limited power; we report it honestly. yfinance spot is the
underlying-of-record (lake `underlying_close` is NULL) — a documented dependency.
