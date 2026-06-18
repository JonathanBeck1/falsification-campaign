# Decision: Earnings-Announcement Premium (T43)

Pre-registration: `research/earnings_premium_preregistration.md`. Falsify-first.
Raw run: `data/earnings_premium_results.txt` · `research/earnings_premium_report.md`.

## Verdict

### ❌ KILL — announcement premium is real but tiny, fails after-cost |t|, and has DECAYED to zero out-of-sample; what remains is compensated jump-risk variance, not alpha.

## Numbers (after-cost, PRIMARY window car_m1_p1, market-adjusted)

| metric | value |
|---|---|
| N (usable events) | **2156** (49 tickers, 0 dropped) |
| gross mean abnormal return | **+0.344%** |
| after-cost mean (10 bps/event) | **+0.244%** |
| after-cost t-stat | **+1.85** (need ≥ 2.0 → FAIL) |
| median | +0.182% |
| win rate | 51.8% |
| premium net of same-stock baseline | **+0.303%**, Welch t = **+2.17** |
| IS (2015–2020) after-cost mean (t) | **+0.459%** (t = **+2.76**), n=1176 |
| OOS (2021–2025) after-cost mean (t) | **−0.014%** (t = **−0.07**), n=980 |
| placebo (non-earnings) mean (t) | **+0.041%** (t = −1.27) — null ✓ |
| jump-risk corr( \|CAR\|, window vol ) | **+0.734** |
| event-window Sharpe | +0.056 |

## Gate result (each line PASS/FAIL)

- **PASS**: N = 2156 (need ≥ 30).
- **FAIL**: after-cost announcement mean = +0.244%, t = **+1.85** (need > 0 **and |t| ≥ 2.0**).
- **FAIL**: OOS sign stability — IS = +0.459% (n=1176) vs **OOS = −0.014%** (n=980); the premium **flipped to ~zero** out-of-sample.
- **PASS**: placebo non-earnings windows null (mean +0.041%, |t| = 1.27 < 2.0).
- **PASS**: premium survives same-stock baseline subtraction (+0.303%, t=+2.17).
- Too-good tripwire: not triggered (Sharpe 0.06, win 51.8%, median ≈ mean). Top-5
  contributors (AMD +36.5%, AVGO +34.4%, ORCL +29.6%, CRM +29.6%, TSLA +25.9%)
  are real single-day earnings jumps; mean ex-top-5 = +0.272% vs +0.344% full —
  the effect is **not** driven by a handful of events (broad-based but small).

## Artifact class (if killed)

**Decayed effect / compensated risk premium** (brain/30: "the mechanism was real
historically but no longer survives"), with a **jump-risk-variance** overlay.
This is NOT one of the seven contamination artifacts — the data are clean (0/2156
dropped), the placebo is null, and the premium survives the same-stock baseline,
so the historical IS premium (+0.46%, t=2.76) is a *genuine* announcement effect.
It simply (a) does not clear the after-cost |t|≥2 bar on the full sample, (b) has
**decayed to zero in 2021–2025**, and (c) tracks event-window volatility
(corr +0.73) — i.e. it is **compensation for bearing the scheduled jump, not
exploitable alpha**.

## Honest verdict (2–4 sentences)

The earnings-announcement premium is *real but uninvestable here*: across 2,156
mega/large-cap earnings events 2015–2025, holding through the print earned a
gross +0.34% market-adjusted abnormal return that is genuinely an announcement
effect (placebo ~0, survives same-stock baseline at t=2.17) — but it is only
+0.24% after a conservative 10 bps cost, with t=1.85 below the |t|≥2 bar, and it
**collapsed from +0.46% (t=2.76) in 2015–2020 to −0.01% (t=−0.07) in 2021–2025**.
The +0.73 correlation between the realized premium and event-window volatility
confirms what little premium existed was **compensation for jump risk, not
alpha**. This kill does NOT prove the premium is dead in the neglected small-cap
names where it historically lived — this universe is liquid mega/large-cap,
exactly where it should be most arbed away, and we cannot test the neglected tail
cleanly on free data.

## Coverage / data honesty note

yfinance `get_earnings_dates(limit=100)` was **far more reliable than feared**:
every one of the 49 fixed-universe tickers returned ≥20 dated earnings events in
2015–2025 (44 typical), for **2,156 total events with 0 dropped** for incomplete
or glitched windows. BMO/AMC was inferred from the timestamp hour (≥13:00 ET →
AMC, market reacts next session; missing time → AMC). Caveat: a small number of
yfinance dates can be off by one session or be a restated/duplicate date — the
[-1,+1] window absorbs a 1-day slip and same-date duplicates are deduped, but a
few mis-timed events are possible. **This test did NOT suffer from thin/unreliable
earnings dates** — the sample is well-powered; the kill is on the economics, not
the data.

## Files

- `src/trader/catalysts/earnings_premium.py` — pure core (abnormal returns,
  BMO/AMC t0, event/placebo CARs, jump-risk corr, gate)
- `tests/financial/test_earnings_premium.py` — 25 network-free tests
- `scripts/run_earnings_premium_study.py` — end-to-end runner (yfinance)
- `research/earnings_premium_preregistration.md` — pre-reg (written before results)
- `research/earnings_premium_report.md` · `data/earnings_premium_results.txt` — raw output
- `output/catalysts/earnings_premium_study.json` — machine-readable result

## Registry status update line (paste into brain/34)

`- ❌ **T43** Earnings-announcement premium — *real but KILLED: gross +0.34% / after-cost +0.24% (t=1.85, <2); IS +0.46% (t=2.76) → OOS −0.01% (t=−0.07) decay; corr(premium, window-vol)=+0.73 → compensated jump-risk variance, not alpha; N=2156, placebo null. Scoped to liquid mega/large-cap.*`
