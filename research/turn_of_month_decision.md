# Decision: Turn-of-Month Effect (T48)

Pre-registration: `research/turn_of_month_preregistration.md`. Falsify-first.

## Verdict

### ❌ KILL — directionally right but weak in-sample and decayed to ~zero out of sample; fails after-cost |t| and placebo gates.

## Numbers (full SPY sample 1993-02-01 .. 2025-12-30, N=8,286 daily returns)

| metric | value |
|---|---|
| TOM days (N) | 1,580 |
| ROM days (N) | 6,706 |
| TOM mean daily ret | +0.0745% |
| ROM mean daily ret | +0.0409% |
| **TOM−ROM diff (gross)** | **+0.0336%/day (3.4 bps)** |
| after-cost diff (−0.5 bp/TOM-day) | +0.0286%/day |
| **Welch t (TOM vs ROM)** | **+1.05** |
| IS diff (t) 1993–2009 | +0.0580% (t=+1.21), TOM N=812 |
| OOS diff (t) 2010–2025 | +0.0078% (t=+0.18), TOM N=768 |
| placebo 1000× (mean t / 95th-pct \|t\|) | −0.30 / 1.93 |
| long-TOM/flat-ROM annualized Sharpe (gross) | 0.45 |
| ^GSPC cross-check (1993–2025) | +0.0284%/day, t=+0.89 |

## Gate result (each line PASS/FAIL)

- **PASS**: TOM N — IS=812, OOS=768 (need both ≥ 100).
- **FAIL**: after-cost signal — TOM−ROM net diff=+0.000286, Welch t=+1.05 (need >0 **and |t|≥2.0**).
- **PASS**: OOS sign stable — IS diff=+0.000580, OOS diff=+0.000078 (same sign, both positive).
- **FAIL**: placebo — real |t|=1.05 vs placebo 95th-pct |t|=1.93 (need real > placebo; it isn't).
- too-good tripwire: **not triggered** — Sharpe 0.45, TOM win-rate 54.5%, no outlier month dominates.

Two of four gate lines FAIL → KILL.

## Artifact class (if killed)

**Decayed effect / in-noise.** The mechanism (month-end structural inflows) was
real historically: TOM daily returns are ~1.8× ROM in-sample (+5.8 bps vs the
baseline) with a respectable but sub-threshold t=1.21. By the OOS half (2010–
2025) the difference collapses to +0.8 bps (t=0.18) — economically and
statistically gone. This is the textbook post-publication decay of a famous
seasonal anomaly (Ariel 1987; Lakonishok-Smidt 1988), not any of the seven
construction artifacts. Notably the sign never flipped — it just shrank into the
noise, and even the full-sample |t| (1.05) sits *below* the random-pseudo-window
placebo band (1.93), meaning a randomly placed 4-day window would look about as
"significant" as the true turn-of-month window does.

## Honest verdict (2–4 sentences)

The turn-of-month window does show the expected positive tilt in SPY (+3.4
bps/day gross over the full history, and a meaningfully larger +5.8 bps in the
1993–2009 half), and the `^GSPC` cross-check agrees in sign and magnitude — so
the anomaly is not a phantom. But it never clears our after-cost |t|≥2 bar, it
decays to +0.8 bps (t=0.18) post-2010, and the real t-stat doesn't even beat a
random-window placebo, so there is no claimable, tradeable edge today. This KILL
does **not** prove the effect never existed — it confirms it once did, has
decayed out of sample, and is now indistinguishable from a randomly placed
calendar window on US large-cap index data.

## Files

- `src/trader/catalysts/turn_of_month.py` — pure core: calendar TOM mask
  (no look-ahead), TOM/ROM split + Welch diff, seeded placebo, gate.
- `tests/financial/test_turn_of_month.py` — 18 network-free tests (all pass).
- `scripts/run_turn_of_month_study.py` — end-to-end runner (yfinance, free data).
- `research/turn_of_month_preregistration.md` — pre-registered design.
- `data/turn_of_month_results.txt` — raw run output.
- `output/catalysts/turn_of_month_study.json` — machine-readable results.

## Registry status update line (for the owner of brain/34)

`- ✅ **T48** Turn-of-month effect — *KILL: +3.4 bps/day gross (t=1.05, < placebo 1.93); IS +5.8 bps (t=1.21) → OOS +0.8 bps (t=0.18) — decayed seasonal, in-noise.*`
