# CEF Discount/NAV Pilot — Phase 5 Go/No-Go Probe

Date: 2026-06-13 · FREE Tiingo tier · 20 funds (10 live + 10 delisted)

Discount = raw price close / raw NAV close - 1, aligned on date. NAV via the NMFQS `X<ticker>X` symbol. Glitch guard (brain/32): |1d price ret|>20% with |1d NAV ret|<2% flagged + excluded from stats.

## Per-fund results

| ticker | status | overlap days | mean disc | latest disc | glitch days | span |
|---|---|---:|---:|---:|---:|---|
| GAM | live | 2820 | -15.7% | -12.0% | 0 | 2015-01-02 → 2026-06-11 |
| GUT | live | 2870 | +60.9% | +100.6% | 0 | 2015-01-02 → 2026-06-12 |
| PEO | live | 2837 | -14.2% | -11.7% | 0 | 2015-01-02 → 2026-06-11 |
| RVT | live | 2870 | -10.9% | -12.7% | 0 | 2015-01-02 → 2026-06-12 |
| USA | live | 2871 | -5.5% | -12.5% | 0 | 2015-01-02 → 2026-06-12 |
| PDI | live | 2810 | +7.8% | +4.2% | 0 | 2015-01-02 → 2026-06-11 |
| PTY | live | 2817 | +18.3% | +2.7% | 0 | 2015-01-02 → 2026-06-11 |
| BST | live | 2847 | -2.9% | -9.7% | 0 | 2015-01-02 → 2026-06-11 |
| UTF | live | 2845 | -4.4% | -3.0% | 0 | 2015-01-02 → 2026-06-11 |
| NEA | live | 2844 | -8.6% | +0.9% | 0 | 2015-01-02 → 2026-06-11 |
| MZF | delisted | 904 | -7.7% | -0.8% | 0 | 2015-01-02 → 2018-08-03 |
| GCH | delisted | 836 | -12.8% | -4.4% | 0 | 2015-01-02 → 2018-04-27 |
| ISL | delisted | 836 | -13.7% | -6.3% | 0 | 2015-01-02 → 2018-04-27 |
| JHA | delisted | 579 | -0.4% | +0.0% | 0 | 2016-02-29 → 2018-11-26 |
| KMM | delisted | 979 | -7.5% | -0.2% | 0 | 2015-01-02 → 2018-11-19 |
| KST | delisted | 979 | -7.5% | -0.2% | 0 | 2015-01-02 → 2018-11-19 |
| EMI (price missing) | delisted | 0 | — | — | 0 | — → — |
| NBD | delisted | 977 | -5.9% | -8.5% | 0 | 2015-01-02 → 2018-11-19 |
| MSP (no overlapping price+NAV days) | delisted | 0 | — | — | 0 | — → — |
| BHL | delisted | 651 | -2.7% | -0.2% | 1 | 2015-01-02 → 2017-08-03 |

## Do live CEFs show a persistent structural discount?

- Median discount across live funds: **-5.0%** (mean **+2.5%**, skewed by premium names — use the median).
- Funds trading at a PREMIUM (mean disc > 0): **3** of 10.

## Resolution capture (THE key pilot output)

For delisted/resolved funds: does the discount narrow toward 0 as the price series ends? Baseline = mean discount in the -250..-60 trading-day band; Final = mean over the last 20 trading days.

| ticker | baseline (-250..-60) | final 20d | narrowed? |
|---|---:|---:|---|
| MZF | -7.7% | -1.1% | yes |
| GCH | -8.5% | -6.2% | yes |
| ISL | -9.9% | -6.8% | yes |
| JHA | -1.4% | -0.3% | yes |
| KMM | -3.2% | -0.4% | yes |
| KST | -3.1% | -0.4% | yes |
| EMI | — | — | — |
| NBD | -5.1% | -7.9% | no |
| MSP | — | — | — |
| BHL | -1.2% | -0.4% | yes |

- Dead funds with both windows populated: **8**; of those, **7** narrowed toward 0.
- Aggregate baseline discount **-5.0%** → final-20d discount **-2.9%**.

## Data-quality verdict

- Funds with usable overlapping price+NAV: **18** of 20.
- Total glitch days flagged across all funds: **1**.
- Funds with NAV missing entirely: **0**.
- Funds with NO usable price (X-stripped ticker REUSED by a different security after delisting, or no price series): **2** (reuse=1, missing=1). This is the identity-collision hazard flagged in brain/32 — the dominant data risk for the full study, concentrated in DEAD funds.

