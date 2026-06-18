# Replay Report and Data Coverage

Date: 2026-05-21

## Decision

Add two operator-facing read-only reports:

- `trader-daily data-status`
- `trader-daily replay-report`

The immediate problem is not strategy complexity. The immediate problem is
visibility: we need to know what data exists locally before claiming edge or
adding more models.

## Scope

`data-status` inventories the local SQLite database:

- historical daily bar coverage by ticker;
- normalized news event coverage by source and event type;
- source fetch health;
- research run count;
- paper intent count.

`replay-report` reads existing historical replay output:

- full-window leaderboard;
- optional train/test split;
- estimated transaction-cost drag from filled notional;
- embedded data coverage section;
- explicit caveat that the report is not proof of edge.

## Important Limitation

This does not create historical news data. The current news adapters collect
recent/live-ish events. Historical price replay proves price/macro plumbing for
the six deterministic replay-safe brains, not event-driven alpha.

## Next Data Work

Collect data in this order:

1. Broader free daily price history through `backfill-prices`.
2. Scheduled live event collection into `news_events`.
3. SEC filing history for selected tickers.
4. Point-in-time event outcome studies.
5. Paid market/news/options data only after free data shows a reason to spend.
