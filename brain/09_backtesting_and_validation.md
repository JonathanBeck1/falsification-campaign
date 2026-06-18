# Backtesting And Validation

## Purpose

Backtesting is where ideas go to earn the right to exist.

No signal should reach live execution because it feels smart. It needs evidence.

## Event Window Tests

For each event type, measure forward returns and volatility after:

- 1 minute
- 5 minutes
- 15 minutes
- 30 minutes
- 1 hour
- market close
- next open
- next close

## Metrics

- hit rate
- average return
- median return
- distribution tails
- max adverse excursion
- max favorable excursion
- drawdown
- Sharpe-like risk metric
- slippage sensitivity
- spread sensitivity
- latency sensitivity

## Options-Specific Checks

Before options execution, test:

- IV change after event
- bid/ask spread
- chain liquidity
- delta exposure
- theta decay
- implied move vs realized move
- exit timing

## Common Traps

- using revised timestamps instead of first-seen timestamps
- survivorship bias
- ignoring duplicated syndicated articles
- ignoring bid/ask spread
- pretending market orders fill at mid
- fitting event categories to past winners
- letting an LLM produce non-reproducible labels without storing prompts and versions

## First Validation Target

Build one small event-window study before any automated trading:

```text
news event -> mapped SPY/QQQ exposure -> 15m/1h return distribution
```

