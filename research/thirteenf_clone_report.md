# 13F Institutional Cloning (filing-date) — Event Study Result

Pre-registration: `research/thirteenf_clone_preregistration.md`.
Market-adjusted CAR = stock return minus SPY (beta=1), summed over the
trading-day window from the FILING date (the only ex-ante-tradeable
timing). The 45-day disclosure lag is the structural reason this is
expected to fail after cost.

## Run metadata
- Managers (frozen, n=12): Berkshire Hathaway (Buffett), Pershing Square (Ackman), Third Point (Loeb), Greenlight Capital (Einhorn), Appaloosa (Tepper), Baupost Group (Klarman), Icahn Capital (Icahn), Lone Pine Capital, Scion Asset Mgmt (Burry), Pershing Square Holdings, Tiger Global Management, Viking Global Investors
- Filing-date span: 2015-01-01 .. 2024-06-30
- De-minimis position filter: $5,000,000
- Benchmark: SPY | OOS split: filing year <= 2020 (early) vs > (late)
- Friction: 10 bps round-trip, subtracted per event
- Placebo: random non-event dates for the same names (seed=12345)
- Mean filing lag (filing_date - report_period): 47.0 days

## Sample accounting (count the dropouts honestly)
- 13F-HR filings kept: 398
- Clone events (NEW positions, deduped by ticker+date): 8142 across 2967 distinct names
- Events with full [0,+252] price window (study N): 6002
  - dropped, no yfinance price (delisted/unmatched ticker): 2108
  - dropped, short/incomplete forward window: 32
- Placebo events built: 6019 (no placebo slot: 15)
- OOS early (<= 2020): 3083 | OOS late: 2919

> yfinance purges delisted tickers, so `no price` is a real,
> survivorship-biased dropout: the survivors that remain are tilted UP,
> which biases the test TOWARD the clone hypothesis. A kill is conservative.

## Market-adjusted CAR vs SPY — clone events, GROSS
| window | n | mean % | median % | % pos | t-stat |
|---|---|---|---|---|---|
| CAR +1m [0,+21] | 6002 | -0.24 | -0.11 | 49% | -1.46 |
| CAR +3m [0,+63] (PRIMARY) | 6002 | -0.46 | +0.16 | 51% | -1.72 |
| CAR +6m [0,+126] | 6002 | -0.76 | +0.00 | 50% | -2.03 |
| CAR +12m [0,+252] | 6002 | -0.84 | +0.05 | 50% | -1.54 |

## After-cost (10 bps round-trip) — the ranked view
| window | n | mean % | median % | % pos | t-stat |
|---|---|---|---|---|---|
| CAR +1m [0,+21] | 6002 | -0.34 | -0.21 | 49% | -2.07 |
| CAR +3m [0,+63] (PRIMARY) | 6002 | -0.56 | +0.06 | 50% | -2.09 |
| CAR +6m [0,+126] | 6002 | -0.86 | -0.10 | 50% | -2.30 |
| CAR +12m [0,+252] | 6002 | -0.94 | -0.05 | 50% | -1.72 |

## Placebo (random non-event dates, same names, after-cost)
| window | n | mean % | median % | % pos | t-stat |
|---|---|---|---|---|---|
| CAR +1m [0,+21] | 6019 | +0.04 | +0.04 | 50% | +0.22 |
| CAR +3m [0,+63] (PRIMARY) | 6019 | +0.33 | +0.13 | 50% | +1.19 |
| CAR +6m [0,+126] | 6019 | +0.68 | -0.10 | 50% | +1.66 |
| CAR +12m [0,+252] | 6019 | +0.25 | -0.09 | 50% | +0.46 |

## OOS early (filing year <= 2020, after-cost)
| window | n | mean % | median % | % pos | t-stat |
|---|---|---|---|---|---|
| CAR +1m [0,+21] | 3083 | +0.45 | +0.57 | 53% | +2.11 |
| CAR +3m [0,+63] (PRIMARY) | 3083 | +1.32 | +1.09 | 54% | +3.97 |
| CAR +6m [0,+126] | 3083 | +2.34 | +1.46 | 53% | +4.93 |
| CAR +12m [0,+252] | 3083 | +4.03 | +2.95 | 54% | +5.82 |

## OOS late (filing year > 2020, after-cost)
| window | n | mean % | median % | % pos | t-stat |
|---|---|---|---|---|---|
| CAR +1m [0,+21] | 2919 | -1.17 | -1.23 | 44% | -4.61 |
| CAR +3m [0,+63] (PRIMARY) | 2919 | -2.54 | -1.23 | 47% | -6.07 |
| CAR +6m [0,+126] | 2919 | -4.24 | -1.68 | 46% | -7.32 |
| CAR +12m [0,+252] | 2919 | -6.18 | -4.08 | 45% | -7.42 |

## Too-good tripwire / top-5 contributor inspection (PRIMARY, gross)
- Top-5 events contribute -30% of the summed primary CAR.
  - CD (Third Point (Loeb)) filed 2020-11-13: +183.6%
  - CVNA (Tiger Global Management) filed 2023-05-15: +166.4%
  - NVAX (Tiger Global Management) filed 2024-02-14: +162.1%
  - CD (Lone Pine Capital) filed 2020-11-16: +161.1%
  - CBI (Berkshire Hathaway (Buffett)) filed 2015-11-16: +146.8%

## Pre-registered gate verdict

### FAIL (idea killed / null)

- PASS: N=6002 (need >= 30)
- FAIL: primary car_0_p63 after-cost mean=-0.0056 t=-2.09 (need >0 & |t|>=2.0)
- FAIL: beats placebo — real car_0_p63 mean=-0.0056 vs placebo mean=+0.0033 (need real greater)
- FAIL: OOS sign stable — early=+0.0132 late=-0.0254 (need same sign)

## How to read this

Primary horizon is `car_0_p63` (~3 months). A real, tradeable clone
signal needs: N>=30, a positive AFTER-COST primary CAR with |t|>=2, that
BEATS the same-names placebo, and keeps its sign across the OOS split.
The honest prior was null-to-negative: 13F's 45-day disclosure lag means
the filing-date follower trades on ~1.5-month-stale information, exactly
the window where any informed-trading edge would already be impounded.

