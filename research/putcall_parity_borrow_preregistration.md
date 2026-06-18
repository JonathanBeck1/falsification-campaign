# Pre-Registration: Put-Call Parity / Implied Borrow (T26)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypothesis, sample, windows, split, gate, and kill criteria are
> fixed here so a favorable specification cannot be selected after the fact.
>
> Standard campaign template (`brain/34_master_test_registry.md`, universal gate
> in `brain/30_campaign_findings.md`). Reuses the audited vol-surface foundation
> `src/trader/catalysts/vol_surface_data.py` (lake loader + BS core).

## 1. Hypothesis (one sentence, directional, falsifiable)

Cross-sectionally, single names whose option chains imply a **higher hard-to-
borrow rate** (larger negative put-call-parity deviation, i.e. a depressed
options-implied forward) earn **lower after-cost forward returns** than names
with a near-zero implied borrow — the short-supply / overvaluation signal.

## 2. Mechanism — why would this be inefficient?

A genuine short constraint (hard-to-borrow shares, high borrow fee) is priced
into the option chain: arbitrageurs who would short the stock to enforce
put-call parity cannot, so the implied forward falls below the cost-of-carry
forward and the implied borrow rate rises. The classic result (Ofek-Richardson-
Whitelaw 2004; D'Avolio 2002) is that high-borrow names are over-valued and
subsequently **under-perform** — the borrow fee is the friction that stops the
mispricing being arbed away (you literally cannot get the shares to short).

**Honest prior: NULL for THIS universe.** The effect lives in small-cap,
illiquid, heavily-shorted, hard-to-borrow names. Our fixed universe is 24
**easy-to-borrow mega-caps** (general-collateral, ~0 borrow fee) plus two index
ETFs. Implied borrow should be ≈ 0 (only flat-rate mis-spec + mid-quote noise),
so there should be **no cross-sectional return signal**. The most likely honest
verdict is `DATA_WALL`: the right universe for this effect (HTB small-caps) is
not in the lake. Documenting that cleanly — implied borrow ≈ 0, no dispersion to
sort on — is the result.

## 3. Data + provenance

- **Universe (FIXED, 24 single names + 2 indices):** ADBE AMAT AMD AVGO BKNG
  COST CSCO GOOG GOOGL HON INTU ISRG LIN LRCX META MU NFLX PEP QCOM REGN TMUS
  TSLA TXN VRTX, plus QQQ, SPY. **EXCLUDED on purpose:** AAPL, AMZN, NVDA — still
  being collected (incomplete lake). The 24 single names are fully collected
  2022-2026 (~1115 trade-days each).
- **Source:** owned EOD option-chain parquet lake (ThetaData) at
  `$TRADER_EOD_LAKE_ROOT`, read through the
  audited `vol_surface_data.load_option_quotes` loader. Option price = mid =
  (bid+ask)/2; one-sided / non-positive-mid rows dropped before any computation.
- **Underlying:** lake `underlying_close` is NULL across the entire lake (verified
  2026-06-17); the loader fills spot from the **yfinance daily close** joined by
  date. The implied-borrow quantity is differenced against `S`, so it inherits
  that spot — a small spot error biases the *level* of q\*, but the
  **cross-sectional rank** (the signal) is robust to a common-mode spot error.
- **Forward returns:** stock forward returns from yfinance daily closes
  (`trader.catalysts.prices.fetch_daily`), market-adjusted vs SPY (beta=1).
- **Risk-free rate:** flat 4% continuously compounded (the foundation's
  documented `DEFAULT_RISK_FREE_RATE`); held constant across all names so it is a
  common-mode level shift that differences out of the cross-sectional rank.
- **Sample span:** 2022-01-01 .. 2026-06-13. IS = trade-date year ≤ 2023; OOS =
  year ≥ 2024.

## 4. Cohort & control definition

- **Per-(name, date) implied borrow.** For each trade-date, take matched
  (expiration, strike) call+put pairs that are near-the-money (|K/S − 1| ≤ 0.05)
  and in a clean tenor band (7d ≤ τ ≤ 120d), both legs two-sided. Solve the
  parity relation `C − P = S·e^{−q*·τ} − K·e^{−r·τ}` for the implied carry
  `q* = −ln((C − P + K·e^{−r·τ}) / S) / τ`. The **implied borrow proxy** is
  `b = q* − div_yield`, but since these names are ~0-dividend tech/large-caps we
  report the raw cross-name carry `q*` and net the universe median (a flat-rate
  / spot common-mode absorber). Aggregate to a per-(name, date) robust
  **median q\*** across qualifying pairs (median, not mean — one bad pair must
  not move it; brain/30 class-3 defense).
- **Cohort (treated) = HIGH implied borrow:** on each rebalance date, the names in
  the **top tercile** of cross-sectional implied borrow (`q* − cross-sectional
  median q*` that day).
- **Control = LOW implied borrow:** the **bottom tercile** that same date. The
  signal is the long-low / short-high spread (high-borrow should under-perform).
- **Pooled baseline:** the cross-sectional mean forward return that date (the
  market move) is differenced out by the long-short construction; we also report
  each leg vs the SPY-adjusted universe mean.
- **Abnormal return:** stock forward return − SPY forward return (beta=1).

## 5. Measurement window + LOOK-AHEAD statement

- **Rebalance cadence:** monthly (first available trade-date each calendar
  month), to keep observations independent and turnover realistic.
- **Holding / windows (event time, trading days):** `fwd_21d` (PRIMARY, ~1
  month, matches the rebalance), `fwd_5d`, `fwd_63d` (reported, non-gating).
- **Look-ahead audit:** the implied borrow on date *t* uses **only** option
  quotes observed at the close of *t*. The forward return is measured strictly
  over (*t*, *t*+h] using closes **after** *t*. The sort happens at *t*; no
  future information enters the ranking. The yfinance underlying used for spot is
  the same-day close (knowable at *t*). No survivorship: the universe is fixed
  ex-ante and all 24 names are alive across the whole span.

## 6. Friction model

- **Round-trip cost:** single-name equity ~10 bps round-trip (5 bps each way).
  The long-short spread crosses two names per leg → charge **20 bps per
  rebalance** against the spread (pre-registered).
- **Application:** subtracted once per rebalance from the gross spread; after-cost
  spread expectancy is the ONLY ranked metric. (We are NOT trading the options —
  the option chain only *measures* the borrow; the tradeable leg is the
  cross-sectional equity long-short.)

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** usable rebalance-level spread observations.
- [ ] **After-cost spread** has the predicted sign (low-borrow > high-borrow,
      i.e. positive long-low/short-high spread) with **|t| ≥ 2.0** on `fwd_21d`.
- [ ] **OOS sign stability** — IS (≤2023) and OOS (≥2024) spread same sign, both
      halves N ≥ 10.
- [ ] **Pooled baseline / dispersion precondition** — the cross-sectional implied
      borrow must actually **disperse** (IQR of per-date q\* materially above the
      flat-rate/mid-quote noise floor). If borrow ≈ constant ≈ 0 across names
      there is nothing to sort on → DATA_WALL, not a tradeable null.
- [ ] **Placebo** — a random-sign / shuffled-borrow sort shows ~0 spread; claim
      requires placebo null AND net |t| ≥ 2.
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from mean
      auto-triggers a placebo run + top-contributor inspection before write-up.
- [ ] **Data provenance** — source, construction, staleness documented (§3).

No alternative window may replace `fwd_21d` if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill (or DATA_WALL) if ANY holds:

- After-cost `fwd_21d` spread |t| < 2, OR spread has the wrong sign.
- N < 30 usable rebalance spreads.
- OOS sign flip (effect decayed / regime-dependent).
- Placebo absorbs the effect (net |t| < 2).
- **DATA_WALL:** cross-sectional implied borrow does not disperse beyond the
  noise floor (the universe is all easy-to-borrow → the effect cannot be tested
  here). This is the pre-registered MOST-LIKELY outcome and is reported as a
  clean negative, not forced into a tradeable verdict.

## 9. Limitations

A kill / DATA_WALL here does **not** disprove the Ofek-Richardson-Whitelaw
hard-to-borrow effect — it only documents that our easy-to-borrow mega-cap +
index lake is the **wrong universe** to test it. The real effect requires
small-cap / high-short-interest / hard-to-borrow names with non-trivial borrow
fees, plus a true borrow-fee series and an American-vs-European early-exercise
correction (we use a European parity identity; for these low-dividend names the
early-exercise bias on the put leg is second-order but not zero). We also use a
flat 4% rate and a yfinance same-day close for spot; both are common-mode and
difference out of the cross-sectional rank but bias the absolute q\* level.
