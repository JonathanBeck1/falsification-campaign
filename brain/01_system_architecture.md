# System Architecture

## High-Level Flow

```text
source adapters
  -> ingestion jobs
  -> raw evidence store
  -> normalization
  -> entity/ticker mapping
  -> event classification
  -> feature generation
  -> backtesting/research
  -> risk gates
  -> paper execution
  -> live execution
```

## Layers

### Adapters

Adapters know how to talk to one source. Examples:

- RSS feeds
- Google News discovery
- Business/news article extraction
- SEC EDGAR downloads
- Alpaca market data
- Apify X scraper

Adapters should produce raw payloads plus source metadata. They should not decide whether to trade.

### Ingestion

Ingestion runs adapters on schedules or event triggers. It handles retries, rate limits, dedupe, run IDs, and source health.

### Raw Evidence Store

The raw evidence store keeps the original article text, DOM payload, API response, SEC filing, post text, or market snapshot. This makes every downstream decision auditable.

### Normalization

Normalization converts raw source data into stable internal records:

- `Article`
- `SocialPost`
- `Filing`
- `MarketBar`
- `OptionQuote`
- `Event`

### Entity And Ticker Mapping

This layer maps mentions to tickers and instruments. It must handle ambiguity:

- `Apple` as company vs fruit
- `ON` as a ticker vs a word
- `CAT` as Caterpillar vs animal word
- sector/index news that affects SPY/QQQ without naming them

### Signals

Signals are deterministic outputs from evidence and features. An LLM can help classify events, but the signal record should be structured and testable.

### Backtesting

Backtesting proves whether a signal has edge after fees, slippage, spread, execution delay, and realistic risk constraints.

### Execution

Execution should start with Alpaca paper trading. Live trading needs explicit risk gates, kill switches, order limits, and logging.

## First Production Shape

The practical v1 should be a modular Python service with simple local storage first. Do not start with a huge distributed system. Add queues, Postgres, vector search, and dashboards as the system earns them.

