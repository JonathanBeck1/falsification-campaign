# Pre-Registration: Event Returns by SEC 8-K Item Type

> Status: pre-registered design, written **before** collecting or inspecting
> study results.
>
> Item definitions, cohorts, windows, controls, and pass criteria are fixed
> before the EDGAR filing sample is downloaded.

## Why this exists

Form 8-K disclosures are tagged, forced corporate disclosures. Item numbers
identify the subject of the filing, allowing a direct test of whether some
public disclosure types carry persistent information while others are routine.

The study compares post-filing market-adjusted returns across four common item
types instead of treating every 8-K as homogeneous.

## Honest prior

- **Item 2.02, Results of Operations:** overlaps the PEAD mechanism, so some
  post-announcement drift is plausible.
- **Item 5.02, officer or director changes:** usually muted after disclosure;
  the prediction is no reliable post-filing return.
- **Item 1.01, material agreements:** heterogeneous, but the prior mean is
  positive because signed commercial or financing agreements often resolve
  uncertainty.
- **Item 7.01, Regulation FD disclosure:** broad and frequently routine; this is
  the noise-control cohort.

## Sample

- **Universe (fixed, 30 symbols):** AAPL, MSFT, NVDA, AMZN, META, GOOGL, GOOG,
  TSLA, BRK-B (skip because EDGAR ticker mapping is unreliable), JPM, V, MA,
  UNH, LLY, JNJ, XOM, WMT, HD, PG, COST, AVGO, ORCL, ADBE, CRM, NFLX, AMD,
  INTC, QCOM, CSCO, PEP.
- **Filing window:** **2020-01-01 through 2024-12-31**.
- **Filings:** SEC EDGAR Form 8-K filings fetched with `edgartools`.
- **Prices:** adjusted daily stock closes from `yfinance`.
- **Benchmark:** SPY adjusted daily close.
- **t0:** first stock trading day on or after the filing date.

Filing text that cannot be retrieved or classified is skipped and counted.

## Method

For each filing, classify every header matching:

`Item <digit>.<two digits>`

Compute beta=1 market-adjusted CARs over `[0,+5]` and `[0,+21]`.

Group events by Item 1.01, 2.02, 5.02, and 7.01.

A filing containing `{1.01, 2.02}` contributes to both cohorts, so item groups
are not mutually exclusive.

For each cohort report N, mean, median, and t-statistic versus zero. The primary
comparison is a Welch-style t-statistic for the Item 2.02 minus Item 7.01
`car_0_p21` difference.

## Pre-registered gate

ALL conditions must hold:

- Item 2.02 mean `car_0_p21` differs from Item 7.01, with absolute t-statistic
  on the difference **at least 2.0**.
- Item 1.01 mean `car_0_p21` is positive with t-statistic **at least 2.0**.
- Item 5.02 mean `car_0_p21` is muted, with **absolute t-statistic below 2.0**.

The 2020-2022 and 2023-2024 halves are reported as an out-of-sample sign check.

## Kill criteria

Kill the item-type signal if any condition holds:

- There is no significant separation between the item-type cohorts.
- Fewer than five outlier filings drive a cohort result.
- Primary signs flip between the early and out-of-sample halves.
- Results depend on unreported filing or ticker retrieval errors.

## Limitations

- One filing can enter multiple item cohorts, so simple between-group t-stats
  ignore dependence from overlapping observations.
- Full text can repeat item numbers in tables of contents or exhibits.
- Filing dates do not encode the exact public timestamp.
- Beta=1 SPY adjustment does not remove sector-specific returns.
