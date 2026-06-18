# Project North Star

## What We Are Building

Trader is a data-first trading intelligence system.

The core idea is simple: markets move on information, and most trading systems underweight messy real-world events. This project is designed to ingest fast external information, convert it into structured evidence, test whether it has predictive value, and only then connect validated signals to trading execution.

## The Project

The first target is a research and execution system for liquid instruments like SPY and QQQ, with options as the eventual edge layer. The system should ingest financial news, social data, SEC filings, market data, options data, and sentiment/event signals.

## Non-Negotiables

- Evidence first, trades second.
- Every signal must be traceable to raw source material.
- Backtesting and paper trading come before live trading.
- LLMs can analyze, summarize, classify, and debate. They do not get unchecked order authority.
- Scraping should be reliable, polite, logged, and maintainable.
- Secrets, cookies, browser profiles, local outputs, and raw private data do not go into git.

## What Good Looks Like

A future signal should be explainable like this:

```text
At 09:42:16 ET, source X published event Y about ticker Z.
The event was classified as supply-chain negative with confidence 0.82.
Historically, similar events caused a median 45-minute downside move under these volatility conditions.
The current market context passes risk gates A, B, and C.
The system entered a paper trade with defined max loss and logged the full evidence chain.
```

That is the standard.

