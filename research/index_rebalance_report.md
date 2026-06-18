# The S&P 500 index-rebalance effect — Event Study Result

Pre-registration: `research/index_rebalance_preregistration.md` (written and the
glitch guard added *before* the final run). Falsify-first. **A clean null is a win.**

Market-adjusted CAR = stock daily return − SPY daily return (beta=1), summed in
event time around the membership-change **effective** date (t0 = first trading day
on/after it).

## Data source and reliability

- **Event list:** `fja05680/sp500` GitHub repo, *"S&P 500 Historical Components &
  Changes (Updated).csv"* — daily-ish **full constituent snapshots**, 1996→
  2026-06-02 (2,712 snapshots). We **diff consecutive snapshots** into add/delete
  events (`changes_from_snapshots`, pure + unit-tested). Cross-checked against the
  repo's independent `sp500_changes_since_2019.csv` event file — they agree on
  essentially every 2019 change. **Reliability: good for the fact and effective
  date of each change.**
- **The dates are EFFECTIVE dates, not ANNOUNCEMENT dates** (S&P announces ~1 week
  prior). This is the headline data wall: we cannot cleanly isolate the
  announcement pop. We place a `[-5,-1]` window to *try* to catch the
  announcement-driven run-up; everything else is post-effective. This handicaps us
  toward finding *no* effect, which makes a null robust but a null on the
  announcement pop itself **untested**.
- **Prices:** yfinance, auto-adjusted closes; SPY as market proxy.
- **Glitch guard:** events with any single-day |abnormal return| > 75% are dropped
  as data glitches (split/near-zero prints). This caught exactly one addition
  (CBE, 2011, a +65,000% spike) that otherwise turned the additions mean into a
  nonsensical +234%.

## Sample accounting (count, don't hide)

| set | events 2010-2025 | usable | dropped |
|---|---|---|---|
| ADDITIONS | 350 | **277** | 73 (no/short data + 1 glitch) |
| DELETIONS | 346 | **66** | **280 (81% purged)** |

**The deletion side is crippled by survivorship.** 81% of deletions are gone from
yfinance — the bulk are M&A casualties (the deleted firm was acquired; only the
acquirer's ticker survives, e.g. DWDP, LLL, RHT, TWTR, ATVI, SIVB). The 66
survivors are overwhelmingly *relegation* deletions (firms that shrank but kept
trading). **We do not draw conclusions from the deletion CARs.** Additions are
alive by construction and essentially complete.

## Additions — market-adjusted CAR (the headline, N=277)

| window | mean | median | %pos | t-stat |
|---|---|---|---|---|
| `[-5,-1]` pre-effective run-up | +0.32% | -0.58% | 47% | +0.83 |
| `[-1,+1]` the change | -0.19% | -0.10% | 49% | -0.71 |
| `[0,+5]` | -0.44% | -0.28% | 48% | -1.40 |
| **`[0,+21]` PRIMARY** | **-0.71%** | -0.55% | 45% | **-1.29** |

The hypothesis was a **positive** post-effective CAR. The data show a small
**negative** drift, not statistically distinguishable from zero. The classic
"index-addition pop" is **absent at the effective date** in 2010-2025: median %pos
sits below 50% in every forward window. If anything, additions slightly
*underperform* SPY in the month after inclusion — consistent with a mild reversal
of any pre-effective buying pressure.

## Deletions — CAR (N=66, survivor-biased, NOT interpreted)

| window | mean | median | %pos | t-stat |
|---|---|---|---|---|
| `[0,+5]` | +1.61% | +0.81% | 56% | +1.35 |
| `[0,+21]` PRIMARY | +2.09% | +2.68% | 62% | +1.17 |

Hypothesis was **negative**. The survivors drift mildly **positive** (a relegated
small-cap that survives often bounces), but with 81% of the true deletion universe
missing this is a **selection artifact, not evidence**. Reported for completeness;
excluded from the verdict.

## The decay test (additions, primary `[0,+21]`)

| sub-sample | N | mean | t-stat |
|---|---|---|---|
| EARLY 2010-2017 | 121 | -0.41% | -0.57 |
| RECENT 2018-2025 | 156 | -0.94% | -1.18 |

There is **no positive effect in either era to decay from.** Both sub-samples are
null/slightly-negative. The literature's "strong pre-2000, gone post-2010" story
is consistent with this: by 2010 the effect was already arbitraged away, so within
2010-2025 there is nothing left to fade. (The recent half is marginally *more*
negative, but neither is significant — do not read a trend into noise.)

## Pre-registered gate verdict

### ❌ FAIL — idea killed / null result

- PASS: N=277 (need ≥ 30)
- **FAIL: signal — `car_0_p21` mean=-0.0071 t=-1.29 (need >0 & |t|≥2.0)**
- PASS: OOS sign stable — early=-0.0041 late=-0.0094 (same sign, but both null)

## Honest verdict

**The S&P 500 index-rebalance effect is not tradable in 2010-2025 on this design,
and there is no detectable decay because there is no effect to decay from.**
Additions earn a small, insignificant *negative* market-adjusted CAR over the
month after the effective date — the opposite of the 1980s-90s pop, fully
consistent with the prior that the effect has been anticipated and front-run for
two decades (Greenwood, Bennett, Patel). This is a **clean falsification**, the
sixth idea this repo has killed.

### Caveats / what this does NOT prove

1. **Effective-date timing, not announcement.** Our source gives effective dates;
   S&P announces ~1 week earlier. A real *announcement-day* pop (and its
   front-running by arbitrageurs in the days before effective) could exist and be
   largely complete before our `[-5,-1]` window even opens. The `[-5,-1]` mean is
   ~0, which is *suggestive* that the run-up is also gone, but we cannot make the
   strong claim without true announcement timestamps (a paid data wall:
   S&P press releases / Bloomberg INDX). **The announcement-window effect is
   UNTESTED here, not disproven.**
2. **Deletion side is unusable** due to 81% yfinance survivorship purge. A proper
   deletion study needs a survivorship-free price source (CRSP).
3. **Beta=1 market adjustment** (house convention). Newly-added S&P names skew
   large-cap/low-beta, so this is unlikely to manufacture a false negative.
4. **No transaction costs / index-fund mechanics modeled** — irrelevant given the
   raw signal is already null.

## Files

- `src/trader/catalysts/index_rebalance.py` — snapshot-diff parser + pure CAR/gate
- `tests/financial/test_index_rebalance.py` — 20 network-free tests
- `scripts/run_index_rebalance_study.py` — end-to-end runner
- `data/index_rebalance_results.txt` — raw run output (this report's numbers)
