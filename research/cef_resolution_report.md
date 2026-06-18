# Saba CEF Activist Campaigns — Resolution Outcomes & 13D-Time Predictors

**Question.** For each of Saba Capital's 82 closed-end-fund (CEF) SC 13D campaigns,
did the fund **RESOLVE** — liquidate, merge, open-end, or run a large tender at NAV
(the terminal events that close the discount and pay an activist) — or did it
**fizzle / stay ongoing**? What is the resolution *rate*, and which features
**observable at 13D time** predict resolution?

**Method.** Event list = `output/catalysts/saba_cef_campaigns.csv` (82 initial SC 13D
filings, the campaign starts). For each subject CIK we pull the fund's full EDGAR
filing history via edgartools and apply a **pure, unit-tested classifier**
(`src/trader/catalysts/cef_resolution.py :: classify_resolution`) to the filings
filed **strictly after** the 13D date, plus a yfinance delisting flag. Labels are
assigned on hard filing evidence only; the rate is therefore a **lower bound**.

**Resolution signal taxonomy** (strongest first):

| Form | Meaning | Strength |
|---|---|---|
| **N-8F** | Application to deregister under the '40 Act — fund has *completed* liquidation/merger and ceases to exist | gold standard |
| **25 / 25-NSE** | Exchange delisting notice — fund delists when it liquidates/merges | strong |
| **N-14 8C / 425 / DEFM14A** | Merger registration / merger proxy — fund merged into another fund | strong |
| **SC TO-I** | Issuer self-tender — counted as resolution **only** when corroborated by no remaining price data (bare SC TO-I = managed-distribution noise) | weak alone |
| **N-23C-2** | Notice to redeem securities — fires *semiannually* to redeem term-preferred shares; pure **noise**, ignored | n/a |

A target with **no yfinance price data** is treated as delisted (resolution) even
when no specific form is matched — delisting is itself a terminal signal.

---

## 1. Headline result

- **N = 82 campaigns. Resolved = 33. Resolution rate = 40.2%.**
- This is a **lower bound**: it counts only completed/announced terminal events
  visible in free filings. Some "ongoing" funds have live proxy fights or pending
  proposals not yet reflected in an N-8F / Form 25 / merger registration.

**Outcome distribution**

| Outcome | N | Trigger forms |
|---|---|---|
| delisted (Form 25 / no price data) | 19 | 25-NSE |
| deregistered (N-8F) | 7 | N-8F |
| merger (N-14 8C / 425) | 6 | 425×4, N-14 8C×2 |
| tender (corroborated SC TO-I) | 1 | SC TO-I (BIGZ) |
| **resolved subtotal** | **33** | |
| ongoing / fizzle | 49 | — |

**Time-to-resolution** (33 resolved, days from 13D to first terminal filing):
**median ≈ 714 days (~2.0 yr), mean ≈ 789 d, range 208–1,472 d.** Saba CEF
campaigns are **slow**: even winners take ~2 years from 13D to the terminal form.
This matters for any tradeable signal — the catalyst is a multi-quarter hold, not
an event-window pop.

---

## 2. Features observable at 13D time vs resolution

### Strongest separator: muni vs equity/alternative

| Class | Resolved | Rate |
|---|---|---|
| **Municipal bond funds** | 20/37 | **54%** |
| Equity / alternative funds | 13/45 | 29% |

This is the cleanest split and it **survives the age confound**: within the
largest single cohort (2023 filings, n=45), muni = **15/25 (60%)** vs equity =
**5/20 (25%)**. Mechanism is plausible — Saba's muni campaigns target sponsor
"families" (BlackRock, Nuveen, MFS, Eaton Vance) that resolve via **fund mergers
into sister funds or open-ending**, a cleaner path than agitating a standalone
equity fund.

### Sponsor family (name-derived, t0-observable)

| Sponsor | Resolved | Rate |
|---|---|---|
| Tortoise | 3/3 | 100% |
| ClearBridge | 3/3 | 100% |
| MFS | 3/3 | 100% |
| Pioneer | 3/3 | 100% |
| Eaton Vance | 2/3 | 67% |
| BlackRock | 7/11 | 64% |
| Nuveen | 3/10 | 30% |
| abrdn | 1/5 | 20% |
| BNY Mellon | 1/5 | 20% |
| Invesco | **0/5** | **0%** |

Sponsor matters a lot at the extremes. **Invesco (0/5) and abrdn/BNY Mellon (20%)
are persistent foot-draggers**; Tortoise/ClearBridge/MFS/Pioneer cleaned up fast.
Caveat: most per-sponsor cells are n=3–5, so these are suggestive, not
statistically tight, and partly entangled with filing-date age and muni/equity mix.

### Escalation proxy — # of SC 13D/A amendments (POST-HOC, not t0-known)

| Group | Resolved |
|---|---|
| ≤ 8 amendments | 15/46 (33%) |
| > 8 amendments | 18/36 (50%) |

Resolved campaigns carry **more** amendments (resolved median 11 vs ongoing 7).
This is mechanically circular — a resolving campaign accrues more 13D/A traffic on
its way to the finish — and the count is **not observable at 13D time**. It is a
*progress thermometer*, not a *selection feature*. Do not use it for entry timing.

### Term funds — too few to call

Only 4 name-"Term" funds (TEAF, BMEZ, MEGI, BSTZ); 1/4 resolved. No signal.
(Target-term funds have a built-in NAV liquidation date, which should *help*
resolution, but the sample is too small here.)

### The age confound (read this before trusting any rate)

| Filing year | N | Resolved | Rate |
|---|---|---|---|
| 2022 | 10 | 7 | 70% |
| 2023 | 45 | 20 | 44% |
| 2024 | 27 | 6 | 22% |

Older campaigns have had more time to reach a terminal filing, so the cross-section
rate is **right-censored**: 2024 campaigns are not "fizzles," they are mostly still
cooking. The true long-run resolution rate is **above 40%** — many 2024 "ongoing"
funds will resolve later. Any backtest must use **filing-cohort / survival**
framing, not a flat cross-sectional rate.

---

## 3. Per-campaign labels (resolved first, then by date)

| Ticker | Name | 13D date | Sponsor | Class | Outcome | Trigger | Res. date | Days |
|---|---|---|---|---|---|---|---|---|
| HIE | Miller/Howard High Income Equity Fun | 2022-01-05 | Miller/Howard | eq/alt | **deregistered** | N-8F | 2026-01-16 | 1472 |
| NDP | TORTOISE ENERGY INDEPENDENCE FUND, I | 2022-01-10 | Tortoise | eq/alt | **delisted** | 25-NSE | 2024-12-23 | 1078 |
| VFL | Delaware Investments National Munici | 2022-02-15 | Delaware | muni | **merger** | 425 | 2025-12-11 | 1395 |
| CTR | ClearBridge MLP & Midstream Total Re | 2022-09-26 | ClearBridge | eq/alt | **deregistered** | N-8F | 2024-09-09 | 714 |
| EMO | ClearBridge Energy Midstream Opportu | 2022-09-26 | ClearBridge | eq/alt | **merger** | N-14 8C | 2024-01-26 | 487 |
| CEM | ClearBridge MLP & Midstream Fund Inc | 2022-10-07 | ClearBridge | eq/alt | **deregistered** | N-8F | 2024-09-09 | 703 |
| ENX | EATON VANCE NEW YORK MUNICIPAL BOND  | 2022-12-12 | Eaton Vance | muni | **delisted** | 25-NSE | 2025-10-27 | 1050 |
| MPA | BLACKROCK MUNIYIELD PENNSYLVANIA QUA | 2023-01-30 | BlackRock | muni | **merger** | 425 | 2023-09-08 | 221 |
| KSM | DWS STRATEGIC MUNICIPAL INCOME TRUST | 2023-02-17 | DWS | muni | **deregistered** | N-8F | 2025-05-28 | 831 |
| BFZ | BLACKROCK CALIFORNIA MUNICIPAL INCOM | 2023-03-06 | BlackRock | muni | **delisted** | 25-NSE | 2026-02-09 | 1071 |
| BIGZ | BlackRock Innovation & Growth Trust | 2023-03-16 | BlackRock | eq/alt | **tender** | SC TO-I | 2024-07-22 | 494 |
| NTG | Tortoise Midstream Energy Fund, Inc. | 2023-03-21 | Tortoise | eq/alt | **delisted** | 25-NSE | 2024-12-23 | 643 |
| TEAF | ECOFIN SUSTAINABLE & SOCIAL IMPACT T | 2023-03-21 | Ecofin | eq/alt | **delisted** | 25-NSE | 2025-11-10 | 965 |
| TTP | TORTOISE PIPELINE & ENERGY FUND, INC | 2023-03-21 | Tortoise | eq/alt | **delisted** | 25-NSE | 2024-12-23 | 643 |
| NQP | NUVEEN PENNSYLVANIA QUALITY MUNICIPA | 2023-03-22 | Nuveen | muni | **delisted** | 25-NSE | 2026-04-27 | 1132 |
| CMU | MFS HIGH YIELD MUNICIPAL TRUST | 2023-04-10 | MFS | muni | **delisted** | 25-NSE | 2026-06-08 | 1155 |
| NXJ | NUVEEN NEW JERSEY QUALITY MUNICIPAL  | 2023-04-10 | Nuveen | muni | **delisted** | 25-NSE | 2026-04-27 | 1113 |
| CXE | MFS HIGH INCOME MUNICIPAL TRUST | 2023-07-19 | MFS | muni | **delisted** | 25-NSE | 2026-06-08 | 1055 |
| CXH | MFS INVESTMENT GRADE MUNICIPAL TRUST | 2023-07-24 | MFS | muni | **delisted** | 25-NSE | 2026-06-08 | 1050 |
| EVM | EATON VANCE CALIFORNIA MUNICIPAL BON | 2023-08-02 | Eaton Vance | muni | **delisted** | 25-NSE | 2025-10-27 | 817 |
| BNY | BLACKROCK NEW YORK MUNICIPAL INCOME  | 2023-09-29 | BlackRock | muni | **delisted** | 25-NSE | 2026-02-09 | 864 |
| MHN | BLACKROCK MUNIHOLDINGS NEW YORK QUAL | 2023-10-25 | BlackRock | muni | **delisted** | 25-NSE | 2026-02-09 | 838 |
| DMF | BNY MELLON MUNICIPAL INCOME, INC. | 2023-11-01 | BNY Mellon | muni | **deregistered** | N-8F | 2025-10-10 | 709 |
| MAV | PIONEER MUNICIPAL HIGH INCOME ADVANT | 2023-11-07 | Pioneer | muni | **delisted** | 25-NSE | 2025-08-27 | 659 |
| HYB | NEW AMERICA HIGH INCOME FUND INC | 2023-11-14 | New America | eq/alt | **deregistered** | N-8F | 2025-09-12 | 668 |
| BHV | BLACKROCK VIRGINIA MUNICIPAL BOND TR | 2023-11-20 | BlackRock | muni | **merger** | 425 | 2025-06-09 | 567 |
| MYN | BLACKROCK MUNIYIELD NEW YORK QUALITY | 2023-11-20 | BlackRock | muni | **merger** | 425 | 2025-06-09 | 567 |
| MHI | PIONEER MUNICIPAL HIGH INCOME FUND,  | 2024-01-05 | Pioneer | muni | **delisted** | 25-NSE | 2025-08-27 | 600 |
| MIO | Pioneer Municipal High Income Opport | 2024-01-05 | Pioneer | muni | **delisted** | 25-NSE | 2025-08-27 | 600 |
| ASGI | abrdn Global Infrastructure Income F | 2024-01-16 | abrdn | eq/alt | **merger** | N-14 8C | 2025-04-18 | 458 |
| MFD | MACQUARIE/FIRST TRUST GLOBAL INFRAST | 2024-02-28 | First Trust | eq/alt | **delisted** | 25-NSE | 2024-09-23 | 208 |
| NOM | NUVEEN MISSOURI QUALITY MUNICIPAL IN | 2024-04-04 | Nuveen | muni | **delisted** | 25-NSE | 2026-04-27 | 753 |
| FGB | FIRST TRUST SPECIALTY FINANCE & FINA | 2024-04-29 | First Trust | eq/alt | **deregistered** | N-8F | 2025-08-04 | 462 |
| SABA | TEMPLETON GLOBAL INCOME FUND | 2022-06-07 | Templeton | eq/alt | **ongoing** | — | — | — |
| NMAI | Nuveen Multi-Asset Income Fund | 2022-10-03 | Nuveen | eq/alt | **ongoing** | — | — | — |
| ECAT | BlackRock ESG Capital Allocation Tru | 2022-11-01 | BlackRock | eq/alt | **ongoing** | — | — | — |
| SBI | WESTERN ASSET INTERMEDIATE MUNI FUND | 2023-01-30 | Western Asset | muni | **ongoing** | — | — | — |
| SRV | CUSHING MLP & INFRASTRUCTURE TOTAL R | 2023-03-02 | Cushing | eq/alt | **ongoing** | — | — | — |
| NPCT | Nuveen Core Plus Impact Fund | 2023-03-27 | Nuveen | eq/alt | **ongoing** | — | — | — |
| BCAT | BlackRock Capital Allocation Trust | 2023-03-28 | BlackRock | eq/alt | **ongoing** | — | — | — |
| FMN | Federated Hermes Premier Municipal I | 2023-04-18 | Federated Hermes | muni | **ongoing** | — | — | — |
| IDE | Voya Infrastructure, Industrials & M | 2023-05-08 | Voya | eq/alt | **ongoing** | — | — | — |
| VPV | Invesco Pennsylvania Value Municipal | 2023-05-15 | Invesco | muni | **ongoing** | — | — | — |
| BMEZ | BlackRock Health Sciences Term Trust | 2023-05-26 | BlackRock | eq/alt | **ongoing** | — | — | — |
| PEO | ADAMS NATURAL RESOURCES FUND, INC. | 2023-08-11 | Adams | eq/alt | **ongoing** | — | — | — |
| JRI | Nuveen Real Asset Income & Growth Fu | 2023-08-14 | Nuveen | eq/alt | **ongoing** | — | — | — |
| DMA | Destra Multi-Alternative Fund | 2023-08-22 | Destra | eq/alt | **ongoing** | — | — | — |
| ADX | ADAMS DIVERSIFIED EQUITY FUND, INC. | 2023-09-01 | Adams | eq/alt | **ongoing** | — | — | — |
| AFB | ALLIANCEBERNSTEIN NATIONAL MUNICIPAL | 2023-09-21 | AllianceBernstein | muni | **ongoing** | — | — | — |
| PGZ | Principal Real Estate Income Fund | 2023-10-03 | Principal | eq/alt | **ongoing** | — | — | — |
| NAC | Nuveen California Quality Municipal  | 2023-10-12 | Nuveen | muni | **ongoing** | — | — | — |
| ASA | ASA Gold & Precious Metals Ltd | 2023-10-13 | Other | eq/alt | **ongoing** | — | — | — |
| VTN | Invesco Trust for Investment Grade N | 2023-10-18 | Invesco | muni | **ongoing** | — | — | — |
| IGA | Voya Global Advantage & Premium Oppo | 2023-11-01 | Voya | eq/alt | **ongoing** | — | — | — |
| CEV | EATON VANCE CALIFORNIA MUNICIPAL INC | 2023-11-06 | Eaton Vance | muni | **ongoing** | — | — | — |
| KTF | DWS MUNICIPAL INCOME TRUST | 2023-11-13 | DWS | muni | **ongoing** | — | — | — |
| NBH | NEUBERGER BERMAN MUNICIPAL FUND INC. | 2023-11-20 | Neuberger Berman | muni | **ongoing** | — | — | — |
| MEGI | MainStay CBRE Global Infrastructure  | 2023-12-01 | MainStay | eq/alt | **ongoing** | — | — | — |
| DHF | BNY MELLON HIGH YIELD STRATEGIES FUN | 2023-12-08 | BNY Mellon | eq/alt | **ongoing** | — | — | — |
| DSM | BNY MELLON STRATEGIC MUNICIPAL BOND  | 2023-12-29 | BNY Mellon | muni | **ongoing** | — | — | — |
| HQL | abrdn Life Sciences Investors | 2023-12-29 | abrdn | eq/alt | **ongoing** | — | — | — |
| NMT | NUVEEN MASSACHUSETTS QUALITY MUNICIP | 2024-01-04 | Nuveen | muni | **ongoing** | — | — | — |
| NBXG | Neuberger Berman Next Generation Con | 2024-01-05 | Neuberger Berman | eq/alt | **ongoing** | — | — | — |
| NPFD | Nuveen Variable Rate Preferred & Inc | 2024-01-18 | Nuveen | eq/alt | **ongoing** | — | — | — |
| VMO | Invesco Municipal Opportunity Trust | 2024-01-24 | Invesco | muni | **ongoing** | — | — | — |
| BSTZ | BlackRock Science & Technology Term  | 2024-02-05 | BlackRock | eq/alt | **ongoing** | — | — | — |
| HQH | abrdn Healthcare Investors | 2024-03-15 | abrdn | eq/alt | **ongoing** | — | — | — |
| CPZ | Calamos Long/Short Equity & Dynamic  | 2024-03-18 | Calamos | eq/alt | **ongoing** | — | — | — |
| LGI | LAZARD GLOBAL TOTAL RETURN & INCOME  | 2024-03-18 | Lazard | eq/alt | **ongoing** | — | — | — |
| VGM | Invesco Trust for Investment Grade M | 2024-04-26 | Invesco | muni | **ongoing** | — | — | — |
| VKQ | Invesco Municipal Trust | 2024-04-26 | Invesco | muni | **ongoing** | — | — | — |
| NAZ | NUVEEN ARIZONA QUALITY MUNICIPAL INC | 2024-05-17 | Nuveen | muni | **ongoing** | — | — | — |
| DMB | BNY Mellon Municipal Bond Infrastruc | 2024-06-12 | BNY Mellon | muni | **ongoing** | — | — | — |
| LEO | BNY MELLON STRATEGIC MUNICIPALS, INC | 2024-06-12 | BNY Mellon | muni | **ongoing** | — | — | — |
| NFJ | Virtus Dividend, Interest & Premium  | 2024-06-14 | Virtus | eq/alt | **ongoing** | — | — | — |
| GRX | Gabelli Healthcare & WellnessRx Trus | 2024-07-10 | Gabelli | eq/alt | **ongoing** | — | — | — |
| AGD | abrdn Global Dynamic Dividend Fund | 2024-07-25 | abrdn | eq/alt | **ongoing** | — | — | — |
| AOD | abrdn Total Dynamic Dividend Fund | 2024-08-02 | abrdn | eq/alt | **ongoing** | — | — | — |
| GLO | Clough Global Opportunities Fund | 2024-08-08 | Clough | eq/alt | **ongoing** | — | — | — |
| IIF | MORGAN STANLEY INDIA INVESTMENT FUND | 2024-08-14 | Morgan Stanley | eq/alt | **ongoing** | — | — | — |
| GLV | Clough Global Dividend & Income Fund | 2024-09-03 | Clough | eq/alt | **ongoing** | — | — | — |
| GF | NEW GERMANY FUND INC | 2024-09-09 | New Germany | eq/alt | **ongoing** | — | — | — |

---

## 4. Honest verdict

**Can resolution be reliably determined from free filings?** **Yes, on the upside.**
N-8F, Form 25/25-NSE, and merger registrations (N-14 8C / 425) are unambiguous
machine-readable terminal events; combined with the yfinance delisting flag they
give a high-precision "this fund resolved" label. The classifier deliberately
**under-counts** (bare SC TO-I and DEF 14A are not trusted), so 40.2% is a floor.
What we **cannot** cleanly read from free filings is the *quality* of a tender
(fraction of shares / price vs NAV) or live-but-unfiled proxy outcomes — those need
proxy-text parsing or a NAV feed.

**Is a tradeable selection signal plausible?** **Weakly plausible, with caveats.**
- The muni-vs-equity split (54% vs 29%, surviving the age confound) and the sponsor
  spread (Invesco 0/5 … Tortoise/MFS/Pioneer 3/3) are **real, t0-observable
  separators**. A selector that overweights **muni funds at fast-resolving sponsors**
  and avoids Invesco/abrdn/BNY Mellon would have raised the hit rate meaningfully.
- **But** the per-sponsor cells are tiny (n=3–5) and confounded with age and asset
  class, so the sponsor effect is a hypothesis, not an established edge.
- The dominant practical wall is **time**: median ~2 years to a terminal filing.
  This is a patient, discount-capture hold, not an event trade — and the
  cross-section is heavily right-censored, so the rate and feature strengths must be
  re-estimated in a **survival / cohort** frame before sizing anything.

**Bottom line.** Resolution *labels* are reliable from free filings. Predictive
*features* exist (muni + sponsor) and are directionally strong, but the samples are
thin and time-censored — promising enough to justify a survival-model follow-up,
**not** strong enough to deploy as a standalone selection signal yet.

---

*Generated by `src/trader/catalysts/cef_resolution.py`. Classifier logic is pure
and unit-tested in `tests/financial/test_cef_resolution.py` (17 tests).
Live data: EDGAR filing histories via edgartools + yfinance delisting flags,
collected 2026-06-08.*
