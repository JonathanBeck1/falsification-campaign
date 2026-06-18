# Decision: FOMC Pre-Announcement Drift (T47)

Pre-registration: `research/fomc_drift_preregistration.md`. Falsify-first.
**A clean decay finding is a win.**

The pre-FOMC return is SPY's close-to-close return on the trading day **before**
each scheduled FOMC announcement (the session entirely before the 2pm-ET
statement). Abnormal = cohort pre-FOMC mean − pooled non-event baseline mean.

## Verdict

### ❌ KILL — the famous pre-FOMC drift is real in-sample but DECAYED and in-noise out of sample; it dies at every gate after N.

## Run metadata

- SPY (yfinance, auto-adjusted): 2,915 bars, 2014-06-02 .. 2025-12-31.
- Scheduled FOMC events 2015-2025: **87** (88 minus the cancelled Mar-2020
  meeting), **87 usable, 0 dropped**.
- Non-event baseline: **2,305** trading days (>3 trading days from any event).
- Placebo: 5,000 random pseudo-event draws, seed 42.

## Numbers (pre_fomc = PRIMARY, close-to-close)

| metric | value |
|---|---|
| N (usable) | 87 |
| cohort pre_fomc mean (gross) | **+0.116%** |
| non-event baseline mean | +0.065% |
| abnormal (gross) | +0.051% |
| after-cost mean (2 bps) | +0.096% |
| after-cost abnormal | +0.031% |
| pre_fomc t-stat | **+1.35** |
| %positive | 52% |
| IS 2015-2020 mean (t) | **+0.217% (t=+2.08), 62% pos** |
| OOS 2021-2025 mean (t) | **−0.003% (t=−0.02), 40% pos** |
| placebo abnormal mean | +0.000002 (≈0) |
| placebo 95th-pct \|t\| | **2.33** (> real \|t\|=1.35) |

(The announcement-day return — D itself — is +0.115%, t=+0.99: no reaction edge
either. Reported, not part of the claim.)

## Gate result

- **PASS: N=87** (need ≥ 30).
- **FAIL: after-cost signal** — pre_fomc net mean +0.096%, **t=+1.35** (need >0 &
  |t| ≥ 2.0). Below the bar even on the full sample, before any split.
- **FAIL: OOS sign stable** — IS=+0.217% (t=+2.08) but OOS=**−0.003%** (t=−0.02).
  The in-sample drift **vanishes and flips sign** out of sample; %positive falls
  from 62% to 40%. Textbook decay.
- **FAIL: placebo** — the real |t|=1.35 is **smaller** than the placebo
  95th-percentile |t|=2.33. A random non-event day, matched for count, produces a
  *larger* apparent "drift" 5% of the time than the real FOMC days do. The
  pre-FOMC days are statistically indistinguishable from random days. The placebo
  abnormal mean is +0.000002 — exactly the ~0 the design predicted.

## Artifact class

**Decayed effect / in-noise.** The mechanism was real historically (Lucca–Moench
documented it 1994-2011 with a t-stat well above 2), but the effect no longer
survives: (a) the full-sample t is already only 1.35, (b) the entire signal lives
in the IS half and is gone post-2020, and (c) it sits *inside* the placebo null
band. This is the cleanest possible illustration of an **anomaly that survives a
naive in-sample test but dies to OOS + a matched placebo** — the IS-only result
(t=2.08) is exactly the kind of number that would be written down as "an edge" by
a study that stopped at the in-sample mean.

## Honest verdict

The pre-FOMC announcement drift was genuinely present in SPY through 2020
(+0.22%/event, t=2.08, 62% up-days — consistent with the published anomaly), but
it has **decayed to nothing since the effect became widely known**: 2021-2025
shows −0.003%/event, fewer than half the days up, and a t of essentially zero.
Pooled, the effect (t=1.35) is weaker than what random non-event days throw off
(placebo 95th-pct |t|=2.33), and a 2 bps round trip leaves only +0.031% abnormal
with no statistical support. **T47 is a KILL.** This does *not* disprove that the
anomaly existed — it confirms it decayed exactly as the post-2015 literature
predicted, and that the surviving in-sample residual cannot be distinguished from
noise after the campaign's standard gate.

### Caveats / what this does NOT prove

1. **Daily resolution**, not the intraday 2pm-to-2pm window of Lucca–Moench. The
   D−1 close-to-close bar is the cleanest daily proxy and is unambiguously
   pre-announcement, but a true intraday replication (using the existing 1-min
   tooling) is a separate test that could recover a sharper IS effect — it would
   not change the OOS-decay or placebo verdicts.
2. **SPY only, N=87** — limited power; wide CIs are expected. The point estimate
   is small *and* OOS-unstable *and* placebo-dominated, so low power is not the
   story; even a generous read fails two independent gates.
3. **Cancelled Mar-2020 meeting excluded** (emergency Mar-15 action; no tradable
   pre-FOMC day). Including a placeholder would only add COVID-crash noise and
   cannot rescue a null.

## Files

- `src/trader/catalysts/fomc_drift.py` — pure pre-FOMC / baseline / abnormal / gate
- `tests/financial/test_fomc_drift.py` — 19 network-free tests
- `scripts/run_fomc_drift_study.py` — end-to-end runner (hardcoded Fed-calendar dates)
- `data/fomc_drift_results.txt` — raw run output (this report's numbers)

## Registry status update line (brain/34)

`- ✅ **T47** FOMC pre-announcement drift (Lucca–Moench) — *KILL (decayed: IS t=2.08 → OOS t=−0.02; pooled t=1.35 inside placebo band)*.`
