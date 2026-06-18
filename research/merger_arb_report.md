# T40 — Cash-Merger Arbitrage Study Result

Pre-registration: `research/merger_arb_preregistration.md`.

## Run metadata
- Run at: 2026-06-17T15:38:10.964564+00:00
- Curated events: 32 (24 completed, 8 broken)
- Price source: yfinance (free); EDGAR anchors announce filings
- T-bill control: 4.0%/yr; round-trip cost: 20 bps
- IS = announce year <= 2019, OOS = year > 2019

## PRICE-AVAILABILITY CENSUS (the data-wall test)
- Completed-deal targets priceable on yfinance: 2/24 (purge rate 92%)
- Broken-deal targets priceable on yfinance: 2/8 (purge rate 75%)
- Total priceable: 4/32
  -> yfinance RETAINS broken deals (target kept trading) but PURGES
     completed deals (target delisted on close) = inverse survivorship.

## Per-deal log
- ATVI   2022-01-18 completed deal=$  95.00 | PURGED (no yfinance data) | edgar_hits=962
- TWTR   2022-04-25 completed deal=$  54.20 | PURGED (no yfinance data) | edgar_hits=1714
- MGI    2022-02-15 completed deal=$  11.00 | PURGED (no yfinance data) | edgar_hits=1333
- CTXS   2022-01-31 completed deal=$ 104.00 | PURGED (no yfinance data) | edgar_hits=1100
- NUAN   2021-04-12 completed deal=$  56.00 | PURGED (no yfinance data) | edgar_http_500
- CERN   2021-12-20 completed deal=$  95.00 | PURGED (no yfinance data) | edgar_hits=1069
- CONE   2021-11-15 completed deal=$  90.50 | PURGED (no yfinance data) | edgar_hits=1782
- ULTI   2019-02-04 completed deal=$ 331.50 | priced but return dropped (glitch) | edgar_hits=996
- SGEN   2023-03-13 completed deal=$ 229.00 | PURGED (no yfinance data) | edgar_hits=1164
- HZNP   2022-12-12 completed deal=$ 116.50 | PURGED (no yfinance data) | edgar_hits=1021
- ABMD   2022-11-01 completed deal=$ 380.00 | PURGED (no yfinance data) | edgar_hits=1509
- SAVE   2022-07-28 completed deal=$  33.50 | PURGED (no yfinance data) | edgar_hits=1444
- MIME   2021-12-07 completed deal=$  80.00 | PURGED (no yfinance data) | edgar_hits=1336
- COUP   2022-12-12 completed deal=$  81.00 | PURGED (no yfinance data) | edgar_hits=1021
- CSOD   2021-08-05 completed deal=$  57.50 | PURGED (no yfinance data) | edgar_http_500
- MNTV   2022-03-21 completed deal=$  16.00 | PURGED (no yfinance data) | edgar_hits=1492
- ZEN    2022-06-24 completed deal=$  77.50 | PURGED (no yfinance data) | edgar_hits=1018
- SWCH   2022-05-11 completed deal=$  34.25 | PURGED (no yfinance data) | edgar_hits=1712
- TCDA   2023-12-11 completed deal=$  10.00 | PURGED (no yfinance data) | edgar_http_500
- CDK    2022-04-07 completed deal=$  54.87 | PURGED (no yfinance data) | edgar_hits=1188
- ROVR   2023-11-29 completed deal=$  11.00 | PURGED (no yfinance data) | edgar_hits=988
- FORG   2022-10-11 completed deal=$  23.25 | PURGED (no yfinance data) | edgar_hits=1018
- PNM    2020-10-21 completed deal=$  50.30 | PURGED (no yfinance data) | edgar_hits=1216
- MMI    2021-12-06 completed deal=$  22.00 entry=$  42.74@2021-12-06 term=$  22.00 hold=1652d ann_excess=-17.7% | edgar_hits=1285
- NXPI   2016-10-27 broken    deal=$ 110.00 entry=$  87.59@2016-10-27 term=$  86.93 hold=43d ann_excess=-11.8% | edgar_hits=1518
- TIF    2019-11-25 broken    deal=$ 135.00 | PURGED (no yfinance data) | edgar_http_500
- SPLS   2015-02-04 broken    deal=$  33.50 entry=$  49.88@2026-01-16 term=$  48.97 hold=46d ann_excess=-19.0% | edgar_http_500
- ANTM   2015-07-24 broken    deal=$ 188.00 | PURGED (no yfinance data) | edgar_http_500
- RAD    2017-06-29 broken    deal=$   6.50 | PURGED (no yfinance data) | edgar_http_500
- ALXN   2020-12-12 broken    deal=$  60.00 | PURGED (no yfinance data) | edgar_hits=1362
- CCMP   2021-12-15 broken    deal=$ 192.00 | PURGED (no yfinance data) | edgar_hits=1323
- LM     2020-02-18 broken    deal=$  50.00 | PURGED (no yfinance data) | edgar_hits=1198

## Returns where priceable (annualized after-cost EXCESS over T-bill)
- Pooled (all priceable): n=3 excess=-16.20% t=-7.32 median=-17.72% win=0%
- Completed-only: n=1 excess=-17.72% t=+0.00
- Broken-only:    n=2 excess=-15.44% t=-4.29

## IS / OOS (where priceable)
- IS  (<= 2019): mean excess -15.44% (n=2)
- OOS (>  2019): mean excess -17.72% (n=1)

## Placebo (random-date pseudo-deals on surviving tickers)
- n=10 mean excess=+4.50% t=+0.27

## Pre-registered verdict
### DATA_WALL
- DATA_WALL: completed-deal targets priceable on yfinance = 2/24 (need >= 15); completed purge rate = 92%
-   broken-deal targets priceable = 2/8 (purge 75%) — the free source RETAINS the deals that did NOT pay the spread
