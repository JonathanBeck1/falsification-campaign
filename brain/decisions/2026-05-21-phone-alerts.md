# Phone Alert Routing

## Decision

Add a disabled-by-default notification router that supports Discord and ntfy phone alerts, then wire research-cycle completion into that router.

## Why

The pipeline needs operator alerts for long-running research loops, source failures, and future paper-trading readiness. This should not require paid services, should not leak secrets into the repo, and should remain silent during local tests unless explicitly enabled.

## Implementation

- Moved shared notifier protocol and `NullNotifier` into `trader.notify.base`.
- Added `MultiNotifier` and `build_notifier` in `trader.notify.router`.
- Kept `trader.notify.discord.build_notifier` as a compatibility import path.
- Added `NtfyNotifier` using raw `httpx.post` with `Title`, `Priority`, and optional bearer-token headers.
- Added config:
  - `TRADER_ALERTS_ENABLED=false`
  - `NTFY_TOPIC`
  - `NTFY_SERVER_URL`
  - `NTFY_TOKEN`
- Added `notify-test` CLI for route validation.
- Added optional notifier injection to `run_research_cycle`.
- Research-cycle success/failure notifications include run id, candidate count or error, and manifest path.

## Safety Boundaries

- Alerts are disabled unless `TRADER_ALERTS_ENABLED=true`.
- Tests use monkeypatched notifiers/transports only.
- No secrets were added.
- No live trading or broker execution behavior changed.

## Verification

- Focused notifier, CLI, and research-cycle tests passed.
- Full PR verification was run before opening the stacked PR.
