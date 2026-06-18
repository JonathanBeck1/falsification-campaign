# Insider-Buy Clusters as a Forward-Return Signal — Event Study Result

Pre-registration: `research/insider_cluster_preregistration.md`.
Market-adjusted CAR = stock return minus SPY (beta=1), summed over the
trading-day window from the event date (the LAST buy in the cluster).

## Run metadata
- Form-4 scan: first 1 calendar day(s)/month, 2020-01-01 .. 2020-06-30
- Scanned filing-days: 6
- Cluster def: >= K distinct insiders within 30 calendar days; K_primary=2, K_strict=3
- Benchmark: SPY | OOS split: event year <= 2021 (early) vs > (late)
- Placebo: random non-cluster dates for the same names (seed=12345)

## Sample accounting (count the dropouts honestly)
- Open-market purchases (code P) collected: 969
- K>=2 clusters detected: 26  (distinct issuers: 26)
- K>=3 clusters detected: 9
- K>=2 events with full [0,+252] price window (study N): 12
  - dropped, no yfinance price (delisted/unmatched ticker): 14
  - dropped, short/incomplete forward window: 0
- Placebo events built: 12  (no placebo slot: 0)
- OOS early (<= 2021): 12  | OOS late: 0
- K>=3 study N: 2 (no price: 7, short: 0)

> yfinance purges delisted tickers, so the `no price` count is a real,
> survivorship-biased dropout: the survivors that remain are tilted UP.

## Market-adjusted CAR vs SPY — K>=2 clusters (REAL)
| window | n | mean % | median % | % pos | t-stat |
|---|---|---|---|---|---|
| CAR +1m [0,+21] | 12 | +9.21 | +4.58 | 50% | +1.45 |
| CAR +3m [0,+63] (PRIMARY) | 12 | +11.80 | +1.58 | 50% | +1.25 |
| CAR +6m [0,+126] | 12 | +26.58 | -0.43 | 50% | +1.65 |
| CAR +12m [0,+252] | 12 | +58.71 | +18.41 | 75% | +2.82 |

## Placebo (random non-cluster dates, same names)
| window | n | mean % | median % | % pos | t-stat |
|---|---|---|---|---|---|
| CAR +1m [0,+21] | 12 | -7.71 | -10.22 | 33% | -1.78 |
| CAR +3m [0,+63] (PRIMARY) | 12 | -9.41 | -8.31 | 42% | -1.65 |
| CAR +6m [0,+126] | 12 | +10.67 | +1.70 | 50% | +0.80 |
| CAR +12m [0,+252] | 12 | +47.04 | +18.07 | 67% | +2.11 |

## OOS early (<= 2021)
| window | n | mean % | median % | % pos | t-stat |
|---|---|---|---|---|---|
| CAR +1m [0,+21] | 12 | +9.21 | +4.58 | 50% | +1.45 |
| CAR +3m [0,+63] (PRIMARY) | 12 | +11.80 | +1.58 | 50% | +1.25 |
| CAR +6m [0,+126] | 12 | +26.58 | -0.43 | 50% | +1.65 |
| CAR +12m [0,+252] | 12 | +58.71 | +18.41 | 75% | +2.82 |

## OOS late (> 2021)
| window | n | mean % | median % | % pos | t-stat |
|---|---|---|---|---|---|
| CAR +1m [0,+21] | 0 | +nan | +nan | nan% | +0.00 |
| CAR +3m [0,+63] (PRIMARY) | 0 | +nan | +nan | nan% | +0.00 |
| CAR +6m [0,+126] | 0 | +nan | +nan | nan% | +0.00 |
| CAR +12m [0,+252] | 0 | +nan | +nan | nan% | +0.00 |

## Robustness: K>=3 clusters (stricter conviction)
| window | n | mean % | median % | % pos | t-stat |
|---|---|---|---|---|---|
| CAR +1m [0,+21] | 2 | -8.85 | -8.85 | 0% | -25.31 |
| CAR +3m [0,+63] (PRIMARY) | 2 | -10.78 | -10.78 | 0% | -8.43 |
| CAR +6m [0,+126] | 2 | -14.81 | -14.81 | 0% | -2.98 |
| CAR +12m [0,+252] | 2 | -5.60 | -5.60 | 0% | -1.12 |

## Pre-registered gate verdict

### FAIL (idea killed / null)

- FAIL: N=12 (need >= 30)
- FAIL: primary car_0_p63 mean=+0.1180 t=+1.25 (need >0 & |t|>=2.0)
- PASS: beats placebo — real car_0_p63 mean=+0.1180 vs placebo mean=-0.0941 (need real greater)
- FAIL: OOS sign stable — early=+0.1180 late=+nan (need same sign)

## How to read this

Primary horizon is `car_0_p63` (~3 months). A real, tradeable cluster
signal needs: N>=30, a positive primary CAR with |t|>=2, that BEATS the
same-names placebo, and keeps its sign across the OOS split. Anything
less is consistent with the honest prior: the cluster-buy effect is the
best-documented insider signal but is old, public, and likely decayed.
Even a nominal 'pass' here would still owe a cluster-robust standard
error (events on correlated small-caps are not independent) before any
capital — we did NOT correct for cross-sectional correlation.

