# Trading Intelligence Plan

## Thesis

News and event data can create tradeable edge when it is faster, cleaner, or better classified than what the market has immediately priced in.

The project should not assume this edge exists. It should build the machinery to test it.

## Phase 1: Evidence Pipeline

Build the source adapters and raw evidence store:

- RSS/feed discovery
- GNews discovery
- trafilatura/newspaper extraction
- Apify X ingestion
- SEC EDGAR downloader
- Alpaca market data
- optional Polygon market/options/news data

Success means we can reconstruct exactly what the system knew at a specific timestamp.

## Phase 2: Event Normalization

Turn raw text into structured events:

- ticker candidates
- company/entity names
- event category
- sentiment
- urgency
- source credibility
- timestamps
- evidence snippets
- confidence

This is where FinBERT, VADER, LLM classification, and custom rules can work together.

## Phase 3: Research

Measure whether events predict returns or volatility:

- event windows: 5m, 15m, 30m, 1h, 1d
- SPY/QQQ reaction
- single-name reaction
- options IV/skew reaction
- false-positive rate
- source latency

Research should produce boring, numeric answers before any live trading.

## Phase 4: Paper Trading

Convert only validated signals into Alpaca paper trades.

The paper engine should log:

- source evidence
- signal snapshot
- market snapshot
- order intent
- risk gate result
- order result
- exit reason

## Phase 5: Live Trading

Live trading is only justified after paper trading shows stable edge and drawdown behavior.

Live mode must include:

- max daily loss
- max position size
- max open trades
- instrument allowlist
- no-trade windows
- kill switch
- complete logs

