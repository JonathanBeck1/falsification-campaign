# 2026-05-19 First Free Event Report

## Context

Jonathan does not want to buy a paid Alpaca market-data subscription before the system proves it can collect useful evidence. That is the right call for the MVP.

We kept the local `.env` in paper mode and added a free Yahoo Finance chart fallback for event-window research bars. Alpaca remains available through `--data-provider alpaca`, but `research-events` now defaults to `--data-provider yahoo`.

## Run

Event ingestion:

```bash
trader-daily fetch-events
```

Counts:

```text
yahoo_finance | other | 15
```

Event-window report:

```bash
trader-daily research-events \
  --benchmark SPY \
  --source yahoo_finance \
  --event-type other \
  --output output/reports/yahoo-spy-first-run.md
```

Run metadata:

```text
events: 15
bars: 79
source: yahoo_finance
event_type: other
minutes: 5
data_provider: yahoo
```

## Result

The report ran without Alpaca credentials and produced forward-return rows for the available horizons.

Current sample is too small and too broad to infer edge. The only event class was `other`, which is not specific enough to trade. This is useful as a pipeline proof, not a signal proof.

## Decision

Do not buy paid Alpaca data yet.

Next work should focus on:

- More event collection runs.
- Better classification so Yahoo Finance headlines do not all collapse into `other`.
- Point-in-time and stale-news controls before treating any backtest result as meaningful.

The system should keep using free historical bars for MVP research until a narrower event class shows enough promise to justify paid data.
