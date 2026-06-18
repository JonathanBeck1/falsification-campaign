# Event Outcome Backtester V1

Date: 2026-05-20

Status: accepted

## Decision

v1 uses Yahoo bars and `observed_at` by default.

## Why

- Avoids requiring Alpaca paid market data for the first calibration pass.
- Supports honest point-in-time-ish event outcome research by anchoring outcomes
  to when the event was observed.
- Separates empirical research artifacts from live trading systems.

## Boundaries

- Research-only.
- No orders.
- No signal proof.
- Yahoo bars are a free fallback, not production execution data.
- Reports need enough samples before any edge claims.

## Next Calibration Questions

- Which event classes should be calibrated first?
- Which horizons should be treated as primary versus diagnostic?
- What sample size and `min_sample` thresholds are required before reporting an
  apparent edge?
- How should transaction costs and slippage be modeled?
- What paid data trigger should move this workflow beyond Yahoo fallback bars?
