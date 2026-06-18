# 2026-05-19 Yahoo Event Classification

## Context

The first free event report proved the plumbing worked, but all Yahoo Finance headlines were classified as `other`. That made the report impossible to use for strategy research.

## Change

Add Yahoo-specific, deterministic keyword classification for common broad-market headline patterns:

- Fed/FOMC/Powell/rate language -> `fed_commentary`
- Inflation/jobs/payroll/GDP language -> `macro_surprise`
- Earnings/results/revenue/profit language -> `earnings_surprise`
- Analyst upgrade/downgrade language -> analyst event types
- Options/short-squeeze/momentum language -> `unusual_social_velocity`

These are intentionally conservative rules. They are auditable and easy to replace with a better finance NLP model later.

## Result

After rerunning event ingestion with the improved normalizer, Yahoo events split into:

```text
yahoo_finance | earnings_surprise        | 4
yahoo_finance | fed_commentary           | 1
yahoo_finance | other                    | 8
yahoo_finance | unusual_social_velocity  | 1
```

The classified SPY event-window report ran with Yahoo bars and produced per-event-type rows.

## Decision

This is an improvement for research organization, not evidence of alpha.

Next work should collect more events over time and add point-in-time/stale-news controls before treating report stats as signal evidence.
