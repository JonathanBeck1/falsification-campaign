# Paper Intent Readiness

## Decision

Add a research-only paper trade intent layer between scored event candidates and any future execution path.

## Why

The system needs an auditable decision surface before live or paper broker wiring. High-scoring news candidates should become explicit, persisted trade plans that pass deterministic risk review and can be simulated locally. This creates a reviewable paper trail without submitting Alpaca orders.

## Implementation

- Added `paper_trade_intents` with candidate score, proposed action, risk result, final action/qty, simulation id, status, and source event context.
- Added `PaperTradeIntent`.
- Added candidate-to-intent conversion:
  - bullish candidates stage `BUY`
  - bearish candidates stage `SELL`
  - neutral and low-score candidates are ignored
  - targets are clamped to `[0, 1]`
- Added `risk_review_intent` using the existing `RiskGate`.
- Added CLI commands:
  - `stage-paper-intents`
  - `simulate-paper-intents`
- `simulate-paper-intents` uses `SimBroker` only and refuses to run when `TRADER_LIVE=true`.
- Added `PAPER DESK` to the Streamlit terminal with staged, risk-blocked, skipped, and simulated intent visibility.

## Safety Boundaries

- No Alpaca orders are submitted.
- No live trading behavior changed.
- Paper simulation is local SQLite plus `SimBroker`.
- The terminal module is visibility-only.

## Verification

- Focused paper-intent, CLI, and dashboard tests passed.
- Streamlit smoke check rendered `PAPER DESK` after demo seeding and staging.
- Full PR verification was run before opening the stacked PR.
