# Decision: Cash-Merger Arbitrage Spread (T40)

Pre-registration: `research/merger_arb_preregistration.md`. Falsify-first.
Live run: `research/merger_arb_report.md` (2026-06-17).

## Verdict

### DATA_WALL — the spread cannot be measured on free data because the deals that pay it delist and are purged.

This is an honest infrastructure outcome (like T39), NOT an edge claim and NOT a
KILL of the merger-arb hypothesis itself. The pre-registered DATA_WALL gate
(§8: "fewer than 15 completed deals priceable") fired on the live census.

## The census (the actual finding)

| outcome | priceable on yfinance | purge rate |
|---|---|---|
| completed (target delisted on close) | **2 / 24** | **92%** |
| broken (target kept trading) | 2 / 8 | 75% |
| total | 4 / 32 | 88% |

And the 2 "priceable completed" names are **false positives** on inspection: ULTI
returns a 42-row delisting stub (its return was dropped as a glitch), and MMI
returns a reused/wrong ticker (entry $42.74 vs an $11–$22 deal, "held" 1652 days).
The true completed-deal purge rate is effectively **~100%**. Likewise the 2
"priceable broken" names are corrupted — SPLS shows an entry dated 2026-01-16
(Staples relisted-entity ticker reuse); only NXPI (Qualcomm walked away in 2018,
so it kept trading) is a genuine survivor, and it shows the realized **−11.8%
annualized** break loss.

## Numbers (where anything was priceable)

| metric | value |
|---|---|
| N priceable (usable returns) | 3 |
| pooled after-cost annual excess over T-bill | **−16.20%** |
| pooled t (vs 0) | −7.32 |
| completed-only | n=1, −17.72% (the stub) |
| broken-only | n=2, −15.44% |
| IS (<=2019) / OOS (>2019) | −15.44% (n=2) / −17.72% (n=1) |
| placebo (random-date pseudo-deals) | n=10, +4.50%, t=+0.27 (null — behaved) |

Every priceable return is **negative**: the only deals the free source lets you
price are the ones that broke and craterd. Measuring an edge on that sample would
report the *opposite* of merger arb.

## Gate result (each line)

- **DATA_WALL: completed-deal targets priceable = 2/24 (need >= 15); purge 92%.**
  Gate halts here by pre-registered precedence — the edge gate is not reached.
- (not evaluated) N>=30, after-cost |t|>=2, OOS sign stability, placebo.
- Placebo was still computed and behaved (t=+0.27, null), confirming the harness
  manufactures no signal.

## Artifact class

**Inverse / data-source survivorship.** Not one of the 7 brain/30 classes in the
usual direction (those are about *finding* a fake edge); this is the dual — a
**measurement wall**. yfinance retains a ticker only if it is still actively
trading under that symbol today, which is *anti-correlated* with the event we
need to measure: a completed cash merger delists the target. So the population
that captures the arb spread (completed deals) is exactly the population the free
price source deletes, while broken deals (which the strategy must bear as the
loss tail) are over-represented. Any "edge" computed on free data here would be a
**composition/survivorship artifact** pointing the wrong way.

## Honest verdict (2–4 sentences)

Cash-merger arb cannot be tested on EDGAR + yfinance because the spread is
captured by deals that complete, and completed-deal targets delist and are purged
from yfinance (24/24 completed targets effectively unpriceable; only broken
survivors like NXPI remain, all showing losses). The placebo behaved (null), and
the EDGAR announce-filing anchoring worked (962–1782 merger-filing hits around
each announce date), so the harness is sound — the wall is purely the price
source. This DATA_WALL does **not** prove merger arb has no edge; it proves the
hypothesis needs a delisted-retaining price source (Tiingo/CRSP — Tiingo's client
already exists in this repo but no key is provisioned and it is outside the
EDGAR+yfinance free-data scope) to be tested honestly. Given the literature
(Mitchell-Pulvino: most of the gross spread is eaten by the break tail + costs)
and 19 prior campaign kills, the prior remains null/marginal.

## What a kill does NOT prove

The wall does not establish whether the after-break-tail, after-cost annualized
spread beats T-bills — that question is unanswerable on free data here and is the
right thing to revisit only if a delisted-retaining source is funded.

## Files

- `src/trader/catalysts/merger_arb.py` — pure core: fixed curated event list
  (24 completed + 8 broken), per-deal annualized after-cost excess-return math,
  outcome-stratified census, pre-registered gate with DATA_WALL precedence.
- `tests/financial/test_merger_arb.py` — 22 network-free tests (return math,
  broken-deal-does-not-assume-deal-price, census purge rates, gate DATA_WALL /
  KILL / SURVIVES branches).
- `scripts/run_merger_arb_study.py` — thin live runner (yfinance prices + EDGAR
  announce-filing anchoring + census + placebo + gate).
- `research/merger_arb_report.md`, `data/merger_arb_results.txt`,
  `output/catalysts/merger_arb_study.json` — raw run output.

## Registry status update line (paste into brain/34)

`- ✅ **T40** Cash-merger arb spread — *DATA_WALL: completed-deal targets delist on close and yfinance purges them — 2/24 completed priceable (92%+ purge, true ~100%; the 2 are delisting stubs/ticker reuse), vs broken survivors (NXPI −11.8% ann) that yfinance RETAINS = inverse survivorship. Spread is captured by completed deals → unmeasurable on free EDGAR+yfinance. Placebo null (t=+0.27), EDGAR anchoring worked. Needs Tiingo/CRSP (delisted-retaining); not in free scope.*`
