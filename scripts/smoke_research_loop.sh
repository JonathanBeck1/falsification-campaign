#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKE_ROOT="${SMOKE_ROOT:-/tmp/trader-smoke}"
PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/.venv/bin/python}"
export PYTHONPATH="$REPO_ROOT/src"

if [[ ! -x "$PYTHON_BIN" ]]; then
  FALLBACK_PYTHON="$HOME/trader-catalyst/.venv/bin/python"
  if [[ -x "$FALLBACK_PYTHON" ]]; then
    PYTHON_BIN="$FALLBACK_PYTHON"
  else
    echo "Python executable not found. Set PYTHON_BIN or create .venv." >&2
    exit 1
  fi
fi

rm -rf "$SMOKE_ROOT"
mkdir -p "$SMOKE_ROOT/data" "$SMOKE_ROOT/output/reports"
cd "$SMOKE_ROOT"

"$PYTHON_BIN" -m trader.cli seed-events --demo --limit 6
"$PYTHON_BIN" -m trader.cli enrichment-status --source demo_news
"$PYTHON_BIN" -m trader.cli enrich-events --source demo_news --limit 6 --mock-llm
"$PYTHON_BIN" -m trader.cli enrichment-status --source demo_news
"$PYTHON_BIN" -m trader.cli score-events --source demo_news --limit 6 --output output/reports/smoke-candidates.md
"$PYTHON_BIN" -m trader.cli review-events --source demo_news --only enriched --output output/reports/smoke-review.md
"$PYTHON_BIN" -m trader.cli similar-events \
  --event-id evt_demo_aapl_guidance \
  --as-of 2026-05-20T14:00:00+00:00 \
  --k 3 \
  --min-candidates 1 \
  --output output/reports/smoke-similar-events.md
"$PYTHON_BIN" -m trader.cli candidate-context \
  --source demo_news \
  --as-of 2026-05-20T14:00:00+00:00 \
  --candidate-limit 6 \
  --hits-per-candidate 2 \
  --min-candidates 1 \
  --output output/reports/smoke-candidate-context.md
"$PYTHON_BIN" -m trader.cli stage-paper-intents --source demo_news --min-score 30 --limit 6 --last-price 450
"$PYTHON_BIN" -m trader.cli simulate-paper-intents --last-price 450
"$PYTHON_BIN" -m trader.cli outcome-backtest \
  --benchmark SPY \
  --source demo_news \
  --group-by event_type,sentiment,urgency \
  --horizons 5m,15m,1h,1d \
  --output output/reports/smoke-outcomes.md
"$PYTHON_BIN" -m trader.cli outcome-review \
  --outcome-report output/reports/smoke-outcomes.md \
  --output output/reports/smoke-outcome-review.md
"$PYTHON_BIN" -m trader.cli edge-report \
  --outcome-report output/reports/smoke-outcomes.md \
  --output output/reports/smoke-edge-report.md \
  --min-n 10 \
  --cost-bps 2
"$PYTHON_BIN" -m trader.cli research-cycle \
  --skip-fetch \
  --mock-llm \
  --source demo_news \
  --benchmark SPY \
  --horizons 5m,15m \
  --candidate-context \
  --as-of 2026-05-20T14:00:00+00:00 \
  --min-candidates 1 \
  --reports-dir output/reports/cycle

echo "Smoke research loop passed."
echo "Reports written under: $SMOKE_ROOT/output/reports"
