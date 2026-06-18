# Decision: Day-of-Week & Pre-Holiday Effects (T50)

Pre-registration: `research/day_of_week_preregistration.md`. Falsify-first.
Universal gate: `brain/30_campaign_findings.md`.

## Verdict

### ❌ KILL (both effects) — Monday effect absent & sign-reversed; pre-holiday drift in-noise and cost-eaten

A two-hypothesis family run end-to-end on **8,287** SPY daily close-to-close
returns (1993-02 → 2025-12, yfinance auto-adjusted). **Neither** the Monday
effect nor the pre-holiday drift survives the pre-registered gate. Both abnormal
returns sit **inside** their Monte-Carlo placebo null bands, both fail |t|≥2, and
the headline anomaly (Monday) has the **wrong sign** — Mondays are the
*positive* side of the week now, not negative.

## Numbers (PRIMARY contrasts; gross AND after-cost)

### (a) Monday effect — hypothesised NEGATIVE

| metric | value |
|---|---|
| N (Monday returns) | 1,558 |
| Monday mean (gross) | **+0.0535%/day** (sign WRONG — expected negative) |
| Monday mean (after 2bps) | +0.0335%/day |
| baseline (Tue–Fri) mean | +0.0457%/day |
| abnormal (gross) | +0.0078%/day, Welch \|t\|=0.22 |
| abnormal (after-cost) | −0.0122%/day |
| cohort one-sample t | +1.64 |
| IS mean (early half) | +0.0424% (t=+0.83, N=782) |
| OOS mean (late half) | +0.0646% (t=+1.59, N=776) — same sign, positive |
| placebo abnormal mean / 95th-pct \|t\| | +0.000004 / **1.97** (real \|t\|=0.22) |

Weekday table (gross / after-cost mean, one-sample t vs 0): Mon +0.054%/+0.034%
(t=1.64) · Tue +0.072%/+0.052% (t=2.55) · Wed +0.059%/+0.039% (t=2.13) · Thu
+0.016%/−0.004% (t=0.56) · Fri +0.035%/+0.015% (t=1.28). The textbook "worst day"
(Monday) is **not** the worst — Thursday is — and no weekday is significantly
negative.

### (b) Pre-holiday drift — hypothesised POSITIVE

| metric | value |
|---|---|
| N (pre-holiday days) | 296 |
| pre-holiday mean (gross) | **+0.0985%/day** (right sign) |
| pre-holiday mean (after 2bps) | +0.0785%/day |
| baseline (non-pre-holiday) mean | +0.0453%/day |
| abnormal (gross) | +0.0533%/day, Welch \|t\|=**0.93** |
| abnormal (after-cost) | +0.0333%/day |
| cohort one-sample t | +1.77 (fails ≥2) |
| IS mean (early half) | +0.0779% (t=+0.85, N=144) |
| OOS mean (late half) | +0.1181% (t=+1.81, N=152) — same sign, positive |
| placebo abnormal mean / 95th-pct \|t\| | −0.0000 / **1.94** (real \|t\|=0.93) |

## Gate result (each line PASS/FAIL)

**Monday:**
- PASS: N=1,558 (need ≥ 30)
- **FAIL**: after-cost signal — net mean +0.000335 (wanted NEGATIVE), abnormal |t|=0.22 (need right sign & |t|≥2)
- PASS: OOS sign stable — IS +0.000424 / OOS +0.000646 (same sign, both N≥10)
- **FAIL**: placebo — real abnormal |t|=0.22 vs placebo 95th-pct |t|=1.97 (need real > placebo)
- too-good tripwire: not triggered

**Pre-holiday:**
- PASS: N=296 (need ≥ 30)
- **FAIL**: after-cost signal — net mean +0.000785 (right sign) but abnormal |t|=0.93 (need |t|≥2)
- PASS: OOS sign stable — IS +0.000779 / OOS +0.001181 (same sign, both N≥10)
- **FAIL**: placebo — real abnormal |t|=0.93 vs placebo 95th-pct |t|=1.94 (need real > placebo)
- too-good tripwire: not triggered

Both placebos behave exactly as designed (abnormal mean ≈ 0 across 5,000 random
draws), confirming the harness isn't manufacturing significance.

## Artifact class (brain/30)

- **Monday effect: decayed → reversed.** The mechanism (weekend settlement carry,
  T+3 era) was real historically but the effect has not merely vanished — over
  1993-2025 Monday's mean is *positive*. This is the textbook "anomaly that
  reversed after publication / settlement reform" and lands squarely in
  **"decayed effect / in-noise"** (the converse of artifact #2): the bps are
  there but they have the wrong sign and are inside placebo noise.
- **Pre-holiday drift: friction-scale noise (artifact class #2).** A real-looking
  +5.3 bps gross pre-holiday premium, but at Welch |t|=0.93 it is **inside the
  placebo band** — i.e. statistically indistinguishable from drawing 296 random
  days — and a daily-traded rule pays the 2 bps round trip that eats most of it.
  Even taking it at face value it never clears |t|≥2. "Real-but-uncapturable /
  cost-eaten," which for a tradable claim is a KILL.

## Honest verdict (skeptical read)

Exactly the textbook outcome the pre-reg predicted. **The Monday effect is not
just dead — it has reversed sign**: across the full 1993-2025 SPY history Mondays
return a modest +5.4 bps/day, and Monday isn't even the weakest weekday. The
pre-holiday drift *looks* alive at the gross level (+9.9 bps on pre-holiday days
vs +4.5 bps baseline) and its OOS half is actually stronger than IS, which is why
a naive screen would flag it — but its abnormal |t| is 0.93, **below** the
placebo 95th percentile, so it is statistically indistinguishable from noise, and
a strategy that must trade around ~9 pre-holiday days a year pays the daily round
trip that already shaves a third off the gross number. Neither effect provides a
capturable, statistically-supported edge after the universal gate. This does NOT
prove these anomalies never existed (the pre-2000 literature is real); it shows
that on liquid SPY, post-publication, they are noise after costs — consistent
with the campaign's standing conclusion (brain/30).

## Deviations from pre-registration

- **Holiday calendar:** `pandas_market_calendars` is not installed in this venv,
  so — as the pre-reg §3 anticipated — the **primary calendar-gap definition**
  (a holiday = a non-weekend weekday absent from SPY's own trading index) was
  used. This is exact for SPY's actual sessions and fully ex-ante (no look-ahead;
  uses only which days the market was open). 296 pre-holiday days were flagged
  over the sample — consistent with ~9/yr standard NYSE closures. The hardcoded
  standard-NYSE cross-check list described in the pre-reg was therefore not
  needed and is not separately reported.
- **IS/OOS split:** chronological 50/50 by trading-day count (mid = 1993–~2009 vs
  ~2009–2025), as registered.
- No other deviations. Friction (2 bps), gates, placebo (5,000 draws), and kill
  criteria are exactly as pre-registered.

## Files

- `research/day_of_week_preregistration.md` — pre-registered design (written first)
- `src/trader/catalysts/day_of_week.py` — pure core + per-effect gate
- `tests/financial/test_day_of_week.py` — 16 network-free tests
- `scripts/run_day_of_week_study.py` — end-to-end runner (yfinance)
- `data/day_of_week_results.txt` — raw run output

## Registry status update line (for the main thread to paste into brain/34)

`- ✅ **T50** Day-of-week & pre-holiday effects — *KILL: Monday effect reversed sign (+5.4bps, |t|=0.22, in placebo noise); pre-holiday drift +5.3bps gross but |t|=0.93 < placebo band, cost-eaten. Both decayed/in-noise after costs.*`
