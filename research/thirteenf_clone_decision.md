# Decision: 13F Institutional Cloning (T45)

Pre-registration: `research/thirteenf_clone_preregistration.md`. Falsify-first.

## Verdict

### ❌ KILL — filing-date 13F cloning is null-to-negative after cost; the 45-day disclosure lag is the binding constraint, exactly as pre-registered.

Cloning the NEW positions of 12 famous managers, entered on the **filing date**
(the only ex-ante-tradeable timing), earns a *negative* market-adjusted CAR.
After cost it is significantly negative, it is *beaten by its own placebo*, and
its sign *flips* across the OOS split. Three of four gate lines fail.

## Numbers (after-cost, PRIMARY window `car_0_p63` ≈ 3 months)

| metric | value |
|---|---|
| N (usable) | 6,002 clone events (8,142 raw, deduped; 2,108 dropped no-price, 32 short window) |
| gross mean | −0.46% (t=−1.72) |
| after-cost mean | **−0.56%** |
| t-stat (after-cost) | **−2.09** |
| IS mean (filing yr ≤ 2020) | +1.32% (t=+3.97) |
| OOS mean (filing yr > 2020) | **−2.54% (t=−6.07)** — sign flip |
| placebo mean (same names, random dates) | +0.33% (t=+1.19) — *higher than real* |
| mean filing lag (filing_date − report_period) | **47.0 days** |

12 managers (Berkshire, Pershing Square, Third Point, Greenlight, Appaloosa,
Baupost, Icahn, Lone Pine, Scion, Pershing Square Holdings, Tiger Global, Viking),
398 13F-HR filings, filing dates 2015-01-01 .. 2024-06-30. Friction 10 bps
round-trip. Benchmark SPY (beta=1).

## Gate result (each line PASS/FAIL)

- **PASS**: N=6,002 (need ≥ 30).
- **FAIL**: after-cost primary mean=−0.56%, t=−2.09 (need > 0 & |t| ≥ 2 — the
  mean is significantly the WRONG sign).
- **FAIL**: does NOT beat placebo — real primary mean −0.56% vs placebo +0.33%
  (same names on random non-event dates earn MORE than the clone dates).
- **FAIL**: OOS sign flip — IS +1.32% → OOS −2.54% (effect inverts post-2020).
- Too-good tripwire: not triggered (mean is negative); top-5 contributors are
  +30% of the *negative* summed CAR (i.e. a few big winners only soften the loss,
  they don't drive a fake positive). Note CD shows a ~+184% outlier — a stale/
  delisted-ticker collision in yfinance, flagged and immaterial to a kill.

## Artifact class (if killed)

**Decayed effect / in-noise, with the structural cause identified.** The clone
("best ideas" / follow-smart-money) anomaly was historically real at the
*trade date*; by the *disclosure date* it is gone. The mechanism is exactly the
pre-registered killer: 13F is filed a mean of **47 days after quarter-end**, so
the filing-date follower trades on ~1.5-month-stale information — the entire
window in which any informed-trading edge would already be impounded. The
in-sample 2015-20 positive (+1.32%) is the residual of that decayed effect plus
a mega-cap/growth-beta tailwind; it **inverts to −2.54% out-of-sample
(2021-24)** when the regime turned, and the same-names placebo (+0.33%) shows
even the in-sample residual is name-level drift, not a clone signal. This sits
alongside brain/30's *pooled-baseline / composition* family: the cohort inherits
the managers' high-beta book, not skill a follower can harvest at T+47 days.

## Honest verdict (2–4 sentences)

Buying the new positions famous managers disclose, on the day you can actually
learn about them, loses money after cost (−0.56%, t=−2.09 at 3 months) and is
out-earned by trading the very same names on random dates. The apparent
in-sample edge is a decayed, regime-dependent artifact that flips sign post-2020,
and the 47-day mean disclosure lag is the demonstrated reason. This KILL does
**not** prove the managers lack skill, nor that the *quarter-end* (trade-date)
clone is dead — only that the 45-day 13F disclosure lag destroys the
retail-tradeable, filing-date version, precisely as hypothesized.

## Files

- `src/trader/catalysts/thirteenf_clone.py` — pure core (NEW-position diff,
  filing-date clone events, market-adjusted CAR, aggregation + gate)
- `tests/financial/test_thirteenf_clone.py` — 22 network-free unit tests
- `scripts/run_thirteenf_clone_study.py` — end-to-end EDGAR + yfinance runner
- `research/thirteenf_clone_preregistration.md` — pre-registered design
- `research/thirteenf_clone_report.md` — full run report (tables + gate)
- `data/thirteenf_clone_results.txt` — raw run output
- `output/catalysts/thirteenf_filings.csv`, `thirteenf_clone_events.csv` — intermediates

## Registry status update line (paste into brain/34)

`- ✅ **T45** 13F institutional cloning (filing-date) — *KILL: cloning 12 famous managers' NEW positions from the FILING date earns after-cost −0.56% at 3m (t=−2.09, wrong sign), LOSES to same-name placebo (+0.33%), and OOS sign-flips (IS +1.32%/t=3.97 → OOS −2.54%/t=−6.07). Mean filing lag 47.0 days = the structural killer: by disclosure the info is ~1.5mo stale. N=6,002, 2015-24. Decayed effect; trade-date version untested.*`
