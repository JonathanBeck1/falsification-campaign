# Decision: <STRATEGY NAME> (Txx)

Pre-registration: `research/<...>_preregistration.md`. Falsify-first.

## Verdict

### <✅ SURVIVES / ❌ KILL / ⚠️ MARGINAL> — <one-line summary>

## Numbers (after-cost, PRIMARY window)

| metric | value |
|---|---|
| N (usable) | <n> |
| gross mean | <+/-x.xx%> |
| after-cost mean | <+/-x.xx%> |
| t-stat | <+/-x.xx> |
| IS mean (t) | <...> |
| OOS mean (t) | <...> |
| placebo mean (t) | <~0 expected> |

## Gate result (each line PASS/FAIL)

- <PASS/FAIL: N=... (need ≥ 30)>
- <PASS/FAIL: after-cost signal mean=... t=... (need >0 & |t|≥2)>
- <PASS/FAIL: OOS sign stable IS=... OOS=...>
- <PASS/FAIL: placebo/matched-control null>
- <too-good tripwire: triggered? / n/a>

## Artifact class (if killed)

<Which of the 7 (brain/30): look-ahead leakage · friction-scale noise · data
glitch · derived/fake data · pooled-baseline contamination · composition effect ·
classifier hindsight leak. Or "decayed effect / in-noise" if the mechanism was
real historically but no longer survives.>

## Honest verdict (2–4 sentences)

<What the data show, why, and what this kill does NOT prove.>

## Files

- `src/trader/.../<module>.py` — pure core + gate
- `tests/financial/test_<...>.py` — N network-free tests
- `scripts/run_<...>.py` — end-to-end runner
- `data/<...>_results.txt` — raw run output

## Registry status update line (paste into brain/34)

`- ✅ **Txx** <name> — *<VERDICT (one phrase)>*.`
