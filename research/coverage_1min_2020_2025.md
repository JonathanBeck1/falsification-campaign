# 1-min option quote coverage, SPY 2020-2025 (day-level ledger)

Two-pass scan of ThetaData 1-min NBBO availability:
pass 1 = nearest weekly expiration, ATM ±1 strike;
pass 2 (on every pass-1 miss) = third-Friday monthly, ATM ±1 strike, throttled.
A day is MISSING only if both passes fail. Tick-level (ivl=0) is blocked on
the Value tier, so 1-min aggregates are the floor of what we can see.
Script: `scripts/scan_1min_coverage.py` + monthly recheck pass.

| year | trading days | OK | missing | coverage |
|---|---:|---:|---:|---:|
| 2020 | 253 | 253 | 0 | 100.0% |
| 2021 | 252 | 175 | 77 | 69.4% |
| 2022 | 251 | 169 | 82 | 67.3% |
| 2023 | 250 | 250 | 0 | 100.0% |
| 2024 | 252 | 252 | 0 | 100.0% |
| 2025 | 249 | 249 | 0 | 100.0% |

## Interpretation

All 159 missing days fall inside **2021-01-04 → 2022-08-19**. Outside that
span coverage is 100%. Within it, ~38% of trading days have NO 1-min option
quotes at our access level (vendor-side; SPY and QQQ fail identical dates;
EOD data unaffected). This includes most of the 2022 bear leg.

Consequences for the VRP suite (brain/29 Phase 4):
1. Clean regimes: 2020 COVID crash, 2023-2025. Degraded: 2021 calm-bull and
   2022 bear (~2/3 of days).
2. The backtest engine must tolerate open positions crossing MISSING_VENDOR
   days (no mark available -> carry last mark, flag the trade).
3. Every per-regime result must report day-coverage %.
4. If 2021-2022 results look interesting, the upgrade question (Standard/Pro
   tier or another vendor) gets revisited with this exact missing-day list.

## Missing days (159)

- 20210104
- 20210107
- 20210115
- 20210201
- 20210202
- 20210208
- 20210209
- 20210210
- 20210212
- 20210216
- 20210222
- 20210223
- 20210303
- 20210308
- 20210312
- 20210315
- 20210415
- 20210423
- 20210428
- 20210430
- 20210503
- 20210510
- 20210514
- 20210520
- 20210525
- 20210526
- 20210528
- 20210608
- 20210610
- 20210617
- 20210621
- 20210623
- 20210629
- 20210701
- 20210702
- 20210706
- 20210709
- 20210712
- 20210714
- 20210715
- 20210716
- 20210719
- 20210720
- 20210723
- 20210728
- 20210730
- 20210809
- 20210827
- 20210831
- 20210915
- 20210917
- 20210921
- 20210922
- 20210924
- 20210927
- 20210929
- 20210930
- 20211004
- 20211008
- 20211011
- 20211013
- 20211015
- 20211018
- 20211021
- 20211025
- 20211026
- 20211028
- 20211102
- 20211115
- 20211124
- 20211201
- 20211208
- 20211213
- 20211214
- 20211220
- 20211227
- 20211231
- 20220105
- 20220107
- 20220110
- 20220112
- 20220119
- 20220121
- 20220124
- 20220125
- 20220126
- 20220131
- 20220201
- 20220202
- 20220203
- 20220204
- 20220209
- 20220211
- 20220215
- 20220217
- 20220218
- 20220222
- 20220223
- 20220225
- 20220228
- 20220301
- 20220303
- 20220304
- 20220308
- 20220317
- 20220323
- 20220325
- 20220411
- 20220414
- 20220419
- 20220425
- 20220427
- 20220428
- 20220429
- 20220504
- 20220506
- 20220509
- 20220510
- 20220513
- 20220516
- 20220518
- 20220519
- 20220520
- 20220531
- 20220603
- 20220606
- 20220607
- 20220608
- 20220609
- 20220610
- 20220613
- 20220614
- 20220617
- 20220621
- 20220622
- 20220624
- 20220627
- 20220628
- 20220630
- 20220701
- 20220705
- 20220707
- 20220711
- 20220712
- 20220714
- 20220720
- 20220722
- 20220725
- 20220727
- 20220729
- 20220803
- 20220804
- 20220805
- 20220808
- 20220809
- 20220810
- 20220811
- 20220817
- 20220819
