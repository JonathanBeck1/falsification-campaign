# Decision: Crypto Time-Series Momentum / Trend-Following (T33)

Pre-registration: `research/crypto_momentum_preregistration.md`. Falsify-first.
Run live on the free Binance `data.binance.vision` archive (survivorship-aware,
delisted retained) — 2026-06-14.

## Verdict

### ❌ KILL — levered/timed BETA, not alpha: momentum Sharpe (0.79) is BELOW buy-and-hold BTC (0.99), and a random-timing placebo with matched exposure earns ~91% of the strategy's return.

## Numbers (after-cost, PRIMARY = N=90 long-flat)

| metric | value |
|---|---|
| N (days, >=5 names) | 1,212 (panel 2,192 days x 110 symbols, 2020–2025) |
| gross mean/day | +0.2323% (ann +84.8%, Sharpe 0.84) |
| after-cost mean/day | +0.2187% (ann +79.8%, Sharpe **0.788**) |
| after-cost t-stat | **+1.79** (need ≥ 2 — FAIL) |
| fee drag | −4.97%/yr (avg turnover 0.21 on active days) |
| IS mean (t) 2020–22 | +0.2407%/day (t=1.15), Sharpe 0.76 |
| OOS mean (t) 2023–25 | +0.2012%/day (t=1.41), Sharpe 0.83 |
| placebo (random timing) | +0.1995%/day, Sharpe 0.68, t=1.61 |

### The exposure / beta-timing control (THE KEY TEST)

| book | ann return | Sharpe | max drawdown |
|---|---|---|---|
| **Momentum N=90 (net)** | +79.8% | **0.788** | −93.4% |
| Buy-and-hold BTC | +61.3% | **0.989** | −76.7% |
| Buy-and-hold EW universe | +61.5% | 0.701 | −87.0% |

Momentum does **not** beat both buy-and-hold Sharpes — it loses to BTC on
risk-adjusted return AND has a worse drawdown. Higher raw return at a lower
Sharpe and deeper drawdown is levered/timed beta, not alpha.

## Gate result (each line PASS/FAIL)

- PASS: N=1,212 days (need ≥ 30).
- **FAIL: after-cost mean=+0.2187%/day, t=+1.79 (need >0 & |t|≥2).**
- PASS: OOS sign stable (IS +0.24%/day, OOS +0.20%/day, both +).
- **FAIL: EXPOSURE CONTROL — momentum Sharpe 0.788 < B&H BTC 0.989 (and barely
  above the EW universe 0.701). Beta-timing, not alpha.**
- PASS (and damning): placebo (random entry/exit, matched exposure) earns
  +72.8%/yr, Sharpe 0.68, t=1.61 — ~91% of the strategy's return with NO real
  trend timing. t<2 so it "passes" the |t|<2 bar, but the near-equality to the
  real book is the smoking gun.
- too-good tripwire: not tripped (Sharpe 0.79, win 52.3%).

Two of the seven gate conditions fail; either is a KILL on its own.

## Artifact class (if killed)

**Beta-timing / exposure (the sell-in-May exposure trap), confirmed by a
matched-exposure placebo.** Not one of the seven artifact classes per se — this
is the "real mechanism historically but no risk-adjusted edge vs the benchmark"
bucket the pre-reg explicitly flagged. The strategy IS long crypto most of the
time during a structural bull market; the trailing-return filter mostly just
controls *how much* of the time you're exposed. A random-timing book with the
same average exposure captures almost all of the return.

## Honest verdict (2–4 sentences)

Crypto daily time-series momentum produces a big headline return (+80%/yr after
cost) but at a Sharpe (0.79) that is *worse* than simply holding BTC (0.99) and
with a deeper drawdown (−93% vs −77%). A placebo that randomises entry/exit
timing while holding average exposure fixed earns ~91% of the same return, which
proves the "edge" is exposure to a rising market, not the trend rule's timing.
The primary spec also fails the after-cost |t|≥2 bar (t=1.79). This kill does
NOT prove no trend signal of any horizon/frequency/asset works — only that this
pre-registered daily long-flat rule, after honest crypto taker fees, is levered
beta dressed up as alpha.

### Note on the tempting non-primary cells

N=30 long-short shows Sharpe 1.02 (t=2.49) and N=30 long-flat Sharpe 1.01. These
are NOT claimable: they are not the pre-registered PRIMARY (N=90 long-flat), the
pre-reg forbids substituting a faster lookback after seeing results, and the same
exposure/placebo logic applies (the N=90 placebo already earns Sharpe 0.68 with
zero real timing). Reporting them only to be transparent that a miner *would* have
fished one out — which is exactly why the lookback and variant were fixed in
advance. Crypto trend-following is heavily mined; this is what the mining looks
like up close.

## Files

- `src/trader/catalysts/crypto_momentum.py` — pure TSMOM core + B&H exposure
  control + gate
- `tests/financial/test_crypto_momentum.py` — 9 network-free unit tests (lag /
  no look-ahead, long-flat vs flat, turnover cost, gross−cost reconciliation,
  deterministic exposure-preserving placebo, B&H benchmarks)
- `scripts/run_crypto_momentum_study.py` — end-to-end runner (free archive)
- `data/crypto_momentum_results.txt` — raw run output
- `research/crypto_momentum_preregistration.md` — pre-registration

## Registry status update line (paste into brain/34)

`- ❌ **T33** Crypto time-series momentum / trend-following — *KILL: levered/timed BETA, not alpha. N=90 long-flat net +79.8%/yr but Sharpe 0.79 < buy-and-hold BTC 0.99 (and worse −93% drawdown vs −77%); random-timing placebo with matched exposure earns +72.8%/yr (~91% of the return, Sharpe 0.68) — the rule mostly times exposure, not trend. Primary after-cost t=1.79<2. OOS sign-stable but that's just persistent bull beta. N=30 cells (Sharpe ~1.0) tempting but non-primary/forbidden by pre-reg.*`
