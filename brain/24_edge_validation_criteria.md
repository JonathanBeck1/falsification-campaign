# Edge Validation Criteria

This project does not trade because a model sounded confident. It trades only after an event class passes a research gate.

## Minimum Gate For Candidate Edge

- Minimum sample size: 30 events per bucket/horizon.
- Minimum net mean return: +5 bps after assumed transaction costs.
- Minimum t-stat: 2.0.
- Minimum hit rate: 55%.
- Must pass an out-of-sample or walk-forward split before paper deployment.
- Must survive a transaction cost sensitivity check.

## Default Costs

- SPY/QQQ research-only default: 2 bps round trip.
- Thin single-name research default: 10 bps round trip.
- Options research default: not enabled until options data and slippage model exist.

## Kill Criteria

Stop pursuing a bucket when any of these remain true after 100+ observations:

- Net mean return is negative after costs.
- t-stat remains below 1.5.
- Results depend on one or two outlier events.
- Signal disappears when using observed_at instead of published_at.
- Signal only works before realistic latency and slippage are applied.

## Deployment Ladder

1. Research-only report.
2. Mock enrichment sanity check.
3. Real LLM enrichment review on small batch.
4. Paper intent staging.
5. SimBroker fills.
6. Alpaca paper execution behind explicit paper-only command.
7. Live trading remains disabled until a separate human-approved runbook exists.
