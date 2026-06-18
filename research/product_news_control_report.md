# product_news__up — matched-control test

Design: per-event baseline = mean CAR[+1,+21] over all eligible control days
for the SAME ticker in the SAME calendar year (excluding ±5 trading days
around any catalog event for that ticker). Permutation: 2,000 placebo cohorts
with identical (ticker, year) composition. Seed=7, pre-registered gates:
net |t|>=2 AND permutation p<0.05.

- Events: **48**
- Raw cohort CAR[+1,+21]: **+9.26%**
- Matched (ticker, year) baseline: **+9.12%**
- **Net drift: +0.14% (t=+0.07)** — FAIL
- Permutation p-value: **0.4730** (placebo mean +9.17%, 95th pct +11.70%) — FAIL

## Verdict: **KILLED**

## Classifier-leak probe (diagnostic)

- high confidence: N=15, raw +12.69%, net +1.14%
- med/low confidence: N=33, raw +7.70%, net -0.31%

## Ticker composition

- TSLA: 23
- NVDA: 9
- GOOGL: 6
- AAPL: 4
- MSFT: 2
- AVGO: 2
- META: 1
- AMZN: 1

## Per-event detail

| ticker | date | conf | event CAR % | ctrl mean % | net % |
|---|---|---|---:|---:|---:|
| TSLA | 2023-01-17 | medium | +47.27 | +5.00 | +42.27 |
| NVDA | 2023-01-09 | medium | +30.81 | +4.41 | +26.40 |
| TSLA | 2020-03-19 | medium | +42.09 | +16.18 | +25.91 |
| TSLA | 2020-11-17 | high | +38.47 | +16.18 | +22.28 |
| TSLA | 2020-04-03 | medium | +36.27 | +16.18 | +20.09 |
| TSLA | 2020-11-18 | high | +33.43 | +16.18 | +17.25 |
| TSLA | 2020-08-13 | high | +31.69 | +16.18 | +15.51 |
| TSLA | 2020-06-30 | high | +30.26 | +16.18 | +14.08 |
| TSLA | 2020-12-14 | medium | +25.45 | +16.18 | +9.27 |
| TSLA | 2020-08-12 | high | +24.86 | +16.18 | +8.68 |
| TSLA | 2020-08-17 | medium | +24.27 | +16.18 | +8.09 |
| TSLA | 2020-12-17 | medium | +24.14 | +16.18 | +7.96 |
| AAPL | 2024-06-11 | high | +6.42 | -1.08 | +7.50 |
| GOOGL | 2024-12-10 | high | +6.68 | +0.38 | +6.30 |
| NVDA | 2025-05-13 | low | +8.44 | +2.34 | +6.10 |
| AMZN | 2023-04-13 | medium | +8.29 | +2.49 | +5.80 |
| TSLA | 2020-12-03 | medium | +21.18 | +16.18 | +5.00 |
| TSLA | 2020-08-20 | medium | +20.52 | +16.18 | +4.34 |
| TSLA | 2020-11-23 | high | +19.87 | +16.18 | +3.69 |
| GOOGL | 2023-05-10 | medium | +5.18 | +2.31 | +2.87 |
| TSLA | 2020-07-02 | high | +18.37 | +16.18 | +2.19 |
| NVDA | 2025-05-14 | low | +3.43 | +2.34 | +1.09 |
| TSLA | 2020-11-24 | high | +17.11 | +16.18 | +0.93 |
| META | 2023-03-14 | medium | +7.26 | +6.46 | +0.80 |
| GOOGL | 2024-12-11 | medium | +1.08 | +0.38 | +0.70 |
| GOOGL | 2023-05-11 | medium | +0.94 | +2.31 | -1.37 |
| MSFT | 2023-02-07 | medium | +0.36 | +2.20 | -1.84 |
| AVGO | 2021-03-15 | medium | -1.48 | +1.50 | -2.98 |
| MSFT | 2020-08-03 | medium | -1.71 | +1.32 | -3.03 |
| GOOGL | 2023-12-07 | medium | -0.78 | +2.31 | -3.08 |
| NVDA | 2024-06-05 | medium | +1.43 | +7.75 | -6.32 |
| TSLA | 2022-03-22 | medium | +5.19 | +11.95 | -6.76 |
| AAPL | 2020-12-15 | medium | -2.32 | +4.71 | -7.03 |
| NVDA | 2025-01-22 | medium | -5.29 | +2.34 | -7.64 |
| TSLA | 2020-08-26 | medium | +6.18 | +16.18 | -10.00 |
| GOOGL | 2023-02-07 | medium | -9.00 | +2.31 | -11.31 |
| NVDA | 2021-06-28 | medium | -4.63 | +6.94 | -11.56 |
| AAPL | 2020-10-12 | high | -6.86 | +4.71 | -11.57 |
| TSLA | 2020-09-14 | medium | +4.26 | +16.18 | -11.93 |
| AAPL | 2020-08-21 | high | -7.39 | +4.71 | -12.10 |
| NVDA | 2021-04-12 | high | -6.18 | +6.94 | -13.12 |
| TSLA | 2020-09-15 | low | +1.49 | +16.18 | -14.69 |
| AVGO | 2025-09-10 | medium | -9.64 | +5.75 | -15.39 |
| NVDA | 2025-01-03 | medium | -13.76 | +2.34 | -16.11 |
| NVDA | 2021-04-15 | medium | -12.20 | +6.94 | -19.14 |
| TSLA | 2020-08-31 | high | -5.33 | +16.18 | -21.51 |
| TSLA | 2022-03-28 | high | -11.00 | +11.95 | -22.95 |
| TSLA | 2020-10-01 | medium | -10.54 | +16.18 | -26.72 |
