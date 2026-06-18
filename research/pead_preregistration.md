# Pre-Registration: Post-Earnings Announcement Drift in Large Caps

> Status: pre-registered design, written **before** collecting or inspecting
> study results.
>
> The hypothesis, sample, windows, split, pass gate, and kill criteria are fixed
> here to prevent retrospective selection of a favorable specification.

## Why this exists

Post-earnings announcement drift (PEAD) is one of the most studied anomalies in
finance. Prices have historically continued moving in the direction of an
earnings surprise for weeks or months after the announcement.

This study asks a narrower, current question:

> Does a simple PEAD signal survive from 2020 through 2025 in highly liquid US
> mid- and mega-cap stocks after controlling for the broad market?

The test uses public earnings dates, adjusted daily prices, and a fixed beta=1
market adjustment. It does not optimize thresholds, holding periods, or ticker
selection after observing returns.

## Honest prior

PEAD is real historically, but it is public, heavily studied, and easier to
trade than many anomalies. Multiple studies find substantial decay in large
capitalization stocks after 2010 as information processing and systematic
trading improved.

Our prior is therefore a **small or null effect** in this liquid universe. A
clean pass is surprising and must be checked for timing and selection errors.

## Data

- **Universe (fixed, 50 names):** NVDA, AVGO, AMD, ORCL, CRM, COST, AAPL, MSFT,
  GOOGL, META, AMZN, TSLA, NFLX, ADBE, INTC, QCOM, MU, AMAT, LRCX, KLAC, JPM,
  BAC, WFC, GS, MS, V, MA, PYPL, AXP, BLK, JNJ, PFE, MRK, LLY, ABBV, UNH,
  CVS, HD, LOW, WMT, TGT, DIS, NKE, MCD, SBUX, KO, PEP, XOM, CVX, BA.
- **Earnings dates:** `yfinance` earnings dates from **2020-01-01 through
  2025-12-31**.
- **Stock prices:** split- and dividend-adjusted daily closes from `yfinance`.
- **Benchmark:** SPY adjusted daily close.
- **Market adjustment:** stock daily return minus SPY daily return, beta=1.
- **t0:** first stock trading day on or after the earnings date.
- Events without the complete `[-1,+63]` trading-day window are dropped and
  counted.

## Cohort split

Cheap historical analyst-consensus surprise data is not reliably available for
the full sample. Instead, the study uses the close-to-close move on day t0 as a
proxy for surprise sign:

`prev_day_reaction = close[t0] / close[t0-1] - 1`

- **Positive cohort:** `prev_day_reaction > 0`.
- **Negative cohort:** `prev_day_reaction < 0`.
- Exact zero reactions are excluded from both cohorts.

The hypothesis is directional continuation: post-event abnormal returns should
remain higher for the positive cohort. CARs use inclusive windows `[-1,+1]`,
`[0,+5]`, `[0,+21]`, and `[0,+63]`; `[0,+21]` is primary.

## Pre-registered gate

ALL conditions must hold:

- At least **200** usable events across both nonzero cohorts.
- Positive-cohort mean `car_0_p21` is greater than negative-cohort mean
  `car_0_p21`.
- The Welch-style t-statistic on that mean difference is **at least 2.0**.
- The positive-minus-negative mean difference has the same positive sign in
  both the 2020-2022 and 2023-2025 sub-samples.

No alternative horizon may replace `[0,+21]` if the primary gate fails.

## Kill criteria

Kill the PEAD bucket if any condition holds:

- The cohort-mean difference at +21 trading days has `|t| < 2`.
- Fewer than 200 usable events survive the fixed data rules.
- Fewer than five outlier events drive the effect: removing the most extreme
  observations eliminates the primary separation.
- The positive-minus-negative difference flips sign out of sample.

## Limitations

- `yfinance` earnings dates have coverage gaps and may omit older events.
- The study has no analyst-consensus surprise measure.
- The sign proxy is partly degenerate with the target: the t0 return determines
  cohort membership and is included in CARs. The genuinely new information is
  the **drift after t0**, not the announcement-day separation.
- Beta=1 is a coarse market control and does not remove sector or factor moves.
- Daily closes cannot resolve whether an announcement occurred before open or
  after close; the fixed t0 convention is applied uniformly.
