# Decision: Initial Repo Structure

Date: 2026-05-18

## Context

The project began as a trading intelligence platform. A new GitHub repo was created for the work.

## Decision

Use a clean Python package layout with:

- `brain/` for long-lived project context
- `src/trader/` for source code
- `src/trader/adapters/` for source-specific scrapers/connectors
- separate placeholders for ingestion, normalization, storage, signals, backtesting, and execution
- `research/` for repo/vendor/source research
- `output/` gitignored for generated local artifacts

## Consequences

This makes room for the trading platform with a clean, extensible layout. It also prevents browser profiles, cookies, virtual environments, and raw generated data from contaminating git history.

