# Alpaca Market Data Plan

## Role In The System

Alpaca should be the first execution and market-data integration.

The system should use Alpaca for:

- paper trading
- account state
- order submission
- positions
- fills
- market snapshots
- historical bars where plan coverage is sufficient

## Open Questions To Verify

- Which SDK is best for 2026 usage?
- What options data is included in the planned paid tier?
- What options execution permissions are available?
- What are websocket limits?
- What are historical data limits?
- Does the plan include OPRA data, and under what conditions?

## First Integration Boundary

The first Alpaca module should not know about LLMs or web scraping.

It should expose boring operations:

```text
get_clock()
get_account()
get_positions()
get_latest_quote(symbol)
get_bars(symbol, timeframe, start, end)
submit_paper_order(order_intent)
cancel_order(order_id)
```

## Risk Gates Before Any Order

- market is open
- instrument is allowlisted
- max daily loss not exceeded
- position size under cap
- no duplicate active signal
- spread/liquidity acceptable
- paper mode by default

## First Milestone

Place a paper trade from a manually created signal record, not from a live scraper. This tests execution plumbing without pretending the signal engine is ready.

