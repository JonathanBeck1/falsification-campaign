# CEF Discount-Capture — REAL Survival Backtest

Replaces the bounded estimate in `research/cef_survival_estimate.md` with an
actual realized backtest: buy the fund the trading day after Saba's SC 13D,
hold to the **resolution date** (resolved funds) or a ~2yr cap (ongoing funds),
measure realized return minus the broad-CEF benchmark (PCEF) over the matched
window = discount-capture excess. Pre-registered in
`research/cef_survival_backtest_preregistration.md`.

**Data status.** Tiingo key **present** — delisted (resolved) funds were fetched from Tiingo.

## Coverage

- Campaigns: 82
- Priced (entered & exited): 81
- Resolved campaigns total: 33; resolved-but-UNPRICED: 1
- Resolved AND priced (the upside actually measured): 32

## Realized excess (target minus PCEF over the matched hold)

| basket | N | mean excess | median excess | mean excess ann. | median hold (yr) | % positive | t-stat |
|---|---|---|---|---|---|---|---|
| untilted | 81 | +0.1053 | +0.0092 | +0.0437 | 1.99 | 51.9% | +2.45 |
| tilted (muni + fast-sponsor) | 47 | +0.0542 | -0.0925 | +0.0170 | 2.00 | 31.9% | +0.96 |

## Pre-registered gate (tilt edge)

**FAIL**

- PASS: priced N=81 (need >= 20)
- FAIL: tilted excess mean=+0.0542 t=+0.96 (need >0 & |t|>=2.0)
- FAIL: tilt beats untilted — tilted mean=+0.0542 vs untilted mean=+0.1053

## Per-campaign realized returns

| ticker | entry | exit | hold (d) | target | bench | excess | resolved | note |
|---|---|---|---|---|---|---|---|---|
| ASA | 2023-10-16 | 2025-10-10 | 725 | +2.4922 | +0.3986 | +2.0936 | no | censored-cap |
| BNY | 2023-10-02 | 2026-02-09 | 861 | +2.2372 | +0.4594 | +1.7778 | yes | resolved |
| NDP | 2022-01-11 | 2024-12-20 | 1074 | +1.0363 | +0.0412 | +0.9951 | yes | resolved |
| TTP | 2023-03-22 | 2024-12-20 | 639 | +1.1676 | +0.2692 | +0.8984 | yes | resolved |
| NTG | 2023-03-22 | 2024-12-20 | 639 | +0.9762 | +0.2692 | +0.7070 | yes | resolved |
| CTR | 2022-09-27 | 2024-09-06 | 710 | +0.8810 | +0.3109 | +0.5701 | yes | resolved |
| EMO | 2022-09-27 | 2024-01-26 | 486 | +0.6585 | +0.1879 | +0.4706 | yes | resolved |
| SRV | 2023-03-03 | 2025-02-28 | 728 | +0.6863 | +0.2372 | +0.4491 | no | censored-cap |
| CEM | 2022-10-10 | 2024-09-06 | 697 | +0.6774 | +0.3012 | +0.3762 | yes | resolved |
| ECAT | 2022-11-02 | 2024-10-31 | 729 | +0.6369 | +0.2822 | +0.3547 | no | censored-cap |
| HIE | 2022-01-06 | 2024-11-20 | 1049 | +0.4025 | +0.0497 | +0.3528 | yes | resolved |
| AGD | 2024-07-26 | 2026-06-08 | 682 | +0.5679 | +0.2303 | +0.3376 | no | censored-cap |
| DMA | 2023-08-23 | 2025-08-21 | 729 | +0.6556 | +0.3237 | +0.3319 | no | censored-cap |
| AOD | 2024-08-05 | 2026-06-08 | 672 | +0.6009 | +0.2694 | +0.3316 | no | censored-cap |
| HQL | 2024-01-02 | 2025-12-26 | 724 | +0.6260 | +0.3103 | +0.3157 | no | censored-cap |
| NBXG | 2024-01-08 | 2026-01-02 | 725 | +0.6030 | +0.2960 | +0.3070 | no | censored-cap |
| BSTZ | 2024-02-06 | 2026-02-04 | 729 | +0.5975 | +0.2918 | +0.3057 | no | censored-cap |
| GF | 2024-09-10 | 2026-06-08 | 636 | +0.4654 | +0.1969 | +0.2686 | no | censored-cap |
| ADX | 2023-09-05 | 2025-08-29 | 724 | +0.5848 | +0.3316 | +0.2532 | no | censored-cap |
| NFJ | 2024-06-17 | 2026-06-08 | 721 | +0.4488 | +0.2552 | +0.1936 | no | censored-cap |
| HQH | 2024-03-18 | 2026-03-13 | 725 | +0.4128 | +0.2193 | +0.1934 | no | censored-cap |
| JRI | 2023-08-15 | 2025-08-13 | 729 | +0.4978 | +0.3208 | +0.1770 | no | censored-cap |
| NMAI | 2022-10-04 | 2024-10-02 | 729 | +0.4773 | +0.3014 | +0.1759 | no | censored-cap |
| GLO | 2024-08-09 | 2026-06-08 | 668 | +0.4041 | +0.2362 | +0.1679 | no | censored-cap |
| IDE | 2023-05-09 | 2025-05-07 | 729 | +0.4059 | +0.2579 | +0.1480 | no | censored-cap |
| GLV | 2024-09-04 | 2026-06-08 | 642 | +0.3434 | +0.1981 | +0.1452 | no | censored-cap |
| ASGI | 2024-01-17 | 2025-04-17 | 456 | +0.2051 | +0.1034 | +0.1017 | yes | resolved |
| NAZ | 2024-05-20 | 2026-05-15 | 725 | +0.3552 | +0.2555 | +0.0997 | no | censored-cap |
| PGZ | 2023-10-04 | 2025-10-02 | 729 | +0.5211 | +0.4242 | +0.0969 | no | censored-cap |
| NPFD | 2024-01-19 | 2026-01-16 | 728 | +0.4079 | +0.3185 | +0.0893 | no | censored-cap |
| LGI | 2024-03-19 | 2026-03-18 | 729 | +0.3126 | +0.2255 | +0.0871 | no | censored-cap |
| MFD | 2024-02-29 | 2024-09-20 | 204 | +0.1876 | +0.1071 | +0.0804 | yes | resolved |
| MEGI | 2023-12-04 | 2025-11-28 | 725 | +0.4085 | +0.3397 | +0.0688 | no | censored-cap |
| KSM | 2023-02-21 | 2024-11-13 | 631 | +0.2865 | +0.2215 | +0.0649 | yes | resolved |
| FGB | 2024-04-30 | 2025-06-27 | 423 | +0.2502 | +0.1993 | +0.0509 | yes | resolved |
| NPCT | 2023-03-28 | 2025-03-26 | 729 | +0.3362 | +0.2870 | +0.0492 | no | censored-cap |
| IGA | 2023-11-02 | 2025-10-31 | 729 | +0.4568 | +0.4099 | +0.0470 | no | censored-cap |
| VTN | 2023-10-19 | 2025-10-17 | 729 | +0.4693 | +0.4277 | +0.0417 | no | censored-cap |
| HYB | 2023-11-15 | 2025-02-11 | 454 | +0.3187 | +0.2803 | +0.0384 | yes | resolved |
| BCAT | 2023-03-29 | 2025-03-27 | 729 | +0.3158 | +0.2777 | +0.0381 | no | censored-cap |
| DMF | 2023-11-02 | 2025-06-18 | 594 | +0.3198 | +0.3106 | +0.0092 | yes | resolved |
| NOM | 2024-04-05 | 2026-04-24 | 749 | +0.2734 | +0.2723 | +0.0011 | yes | resolved |
| MPA | 2023-01-31 | 2023-09-08 | 220 | -0.0391 | -0.0383 | -0.0008 | yes | resolved |
| DHF | 2023-12-11 | 2025-12-05 | 725 | +0.3407 | +0.3441 | -0.0034 | no | censored-cap |
| NAC | 2023-10-13 | 2025-10-10 | 728 | +0.3659 | +0.3970 | -0.0311 | no | censored-cap |
| CPZ | 2024-03-19 | 2026-03-18 | 729 | +0.1845 | +0.2255 | -0.0410 | no | censored-cap |
| CXE | 2023-07-20 | 2026-06-08 | 1054 | +0.3555 | +0.3967 | -0.0411 | yes | resolved |
| VGM | 2024-04-29 | 2026-04-24 | 725 | +0.2382 | +0.2956 | -0.0574 | no | censored-cap |
| BIGZ | 2023-03-17 | 2024-07-22 | 493 | +0.1607 | +0.2183 | -0.0576 | yes | resolved |
| CMU | 2023-04-11 | 2026-06-08 | 1154 | +0.3782 | +0.4502 | -0.0720 | yes | resolved |
| CXH | 2023-07-25 | 2026-06-08 | 1049 | +0.3117 | +0.3960 | -0.0843 | yes | resolved |
| VKQ | 2024-04-29 | 2026-04-24 | 725 | +0.2077 | +0.2956 | -0.0879 | no | censored-cap |
| NMT | 2024-01-05 | 2026-01-02 | 728 | +0.2165 | +0.3090 | -0.0925 | no | censored-cap |
| KTF | 2023-11-14 | 2025-11-12 | 729 | +0.2836 | +0.3790 | -0.0953 | no | censored-cap |
| SABA | 2022-06-08 | 2024-06-06 | 729 | +0.0040 | +0.1039 | -0.0999 | no | censored-cap |
| FMN | 2023-04-19 | 2025-04-17 | 729 | +0.0681 | +0.1777 | -0.1096 | no | censored-cap |
| MIO | 2024-01-08 | 2025-08-22 | 592 | +0.1459 | +0.2585 | -0.1126 | yes | resolved |
| SBI | 2023-01-31 | 2025-01-29 | 729 | +0.0849 | +0.2064 | -0.1215 | no | censored-cap |
| DMB | 2024-06-13 | 2026-06-08 | 725 | +0.1289 | +0.2525 | -0.1236 | no | censored-cap |
| VMO | 2024-01-25 | 2026-01-23 | 729 | +0.1772 | +0.3024 | -0.1251 | no | censored-cap |
| LEO | 2024-06-13 | 2026-06-08 | 725 | +0.1257 | +0.2525 | -0.1269 | no | censored-cap |
| BMEZ | 2023-05-30 | 2025-05-23 | 724 | +0.1374 | +0.2759 | -0.1385 | no | censored-cap |
| CEV | 2023-11-07 | 2025-11-05 | 729 | +0.2481 | +0.3892 | -0.1411 | no | censored-cap |
| EVM | 2023-08-03 | 2025-10-24 | 813 | +0.1951 | +0.3421 | -0.1469 | yes | resolved |
| MHI | 2024-01-08 | 2025-08-22 | 592 | +0.1115 | +0.2585 | -0.1470 | yes | resolved |
| ENX | 2022-12-13 | 2025-10-24 | 1046 | +0.2268 | +0.3777 | -0.1509 | yes | resolved |
| NXJ | 2023-04-11 | 2026-04-24 | 1109 | +0.2746 | +0.4331 | -0.1585 | yes | resolved |
| NBH | 2023-11-21 | 2025-11-19 | 729 | +0.1674 | +0.3268 | -0.1595 | no | censored-cap |
| GRX | 2024-07-11 | 2026-06-08 | 697 | +0.0520 | +0.2208 | -0.1688 | no | censored-cap |
| NQP | 2023-03-23 | 2026-04-24 | 1128 | +0.2977 | +0.4679 | -0.1701 | yes | resolved |
| VPV | 2023-05-16 | 2025-05-14 | 729 | +0.1229 | +0.2943 | -0.1714 | no | censored-cap |
| BHV | 2023-11-21 | 2025-06-09 | 566 | +0.0903 | +0.2617 | -0.1715 | yes | resolved |
| DSM | 2024-01-02 | 2025-12-26 | 724 | +0.1377 | +0.3103 | -0.1725 | no | censored-cap |
| TEAF | 2023-03-22 | 2025-11-07 | 961 | +0.2334 | +0.4087 | -0.1753 | yes | resolved |
| MHN | 2023-10-26 | 2026-02-06 | 834 | +0.3359 | +0.5203 | -0.1843 | yes | resolved |
| AFB | 2023-09-22 | 2025-09-19 | 728 | +0.1997 | +0.3858 | -0.1861 | no | censored-cap |
| MYN | 2023-11-21 | 2025-06-09 | 566 | +0.0728 | +0.2617 | -0.1890 | yes | resolved |
| PEO | 2023-08-14 | 2025-08-08 | 725 | +0.0916 | +0.3001 | -0.2085 | no | censored-cap |
| BFZ | 2023-03-07 | 2026-02-06 | 1067 | +0.1670 | +0.3846 | -0.2175 | yes | resolved |
| IIF | 2024-08-15 | 2026-06-08 | 662 | -0.0623 | +0.2135 | -0.2758 | no | censored-cap |
| VFL | 2022-02-16 | 2025-12-11 | 1394 | -0.0643 | +0.2541 | -0.3184 | yes | resolved |
| MAV | 2023-11-07 | 2023-11-07 | 0 | n/a | n/a | n/a | yes | no-price-data |

## Honest caveats

- **NAV-free, so this is excess OVER the CEF market, not absolute return.** PCEF
  nets out CEF beta and broad discount moves; a held basket also earns the asset
  class return on top.
- **Delisting-price coverage is the whole ballgame.** Without a Tiingo key the
  resolved winners are missing and the result is biased low. WITH a key, Tiingo's
  last marks may predate the actual liquidation/merger cash-out, so realized
  upside is a conservative read of the terminal NAV payoff (we cannot see the
  final liquidation value, only the last traded price).
- **Ongoing funds are right-censored.** Their hold is capped at the max-hold; many
  2024 'ongoing' names are still cooking and may resolve later, so the untilted
  basket understates the eventual resolution rate.
- **Thin per-sponsor cells.** The tilt leans on n=3-5 sponsor cohorts; treat the
  tilt vs untilted gap as directional, not a tight estimate.
- **Frictions not deducted here.** CEFs trade with wide spreads (~1% round-trip);
  subtract that from any mean before sizing. A multi-quarter convex hold, never
  life-changing.

*Generated by `scripts/run_cef_survival.py`. Pure backtest logic is unit-tested in
`tests/financial/test_cef_survival_backtest.py`; the Tiingo client in
`tests/financial/test_tiingo.py`.*
