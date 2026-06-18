#!/usr/bin/env bash
# News catalog loop: keeps running until the catalog is done or the budget is hit.
#
# Launch detached:
#   caffeinate -s nohup scripts/news_catalog_loop.sh >/dev/null 2>&1 &
# Watch:
#   tail -f output/news_catalog_loop.log
# Stop:
#   pkill -f news_catalog_loop.sh && rm -f output/news_catalog_loop.lock
#
# Self-healing: if the python runner exits (api error, transient), the loop
# sleeps 30s and restarts. Single-instance lock prevents duplicates.
# Hard budget: $30 default (override with CATALOG_BUDGET_USD).

set -u
WT="/ABSOLUTE/PATH/TO/trader-catalyst"
MAIN="/ABSOLUTE/PATH/TO/trades"
ENV_FILE="$MAIN/.env"
PY="$WT/.venv/bin/python"
LOG="$WT/output/news_catalog_loop.log"
LOCK="$WT/output/news_catalog_loop.lock"
BUDGET="${CATALOG_BUDGET_USD:-0}"      # 0 = unlimited under Codex sub
MODEL="${CATALOG_MODEL:-gpt-5.5}"      # Codex backend; no API key needed
mkdir -p "$WT/output"
exec >> "$LOG" 2>&1

# Single-instance lock
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "[$(date)] already running (pid $(cat "$LOCK")); exiting."; exit 0
fi
echo $$ > "$LOCK"; trap 'rm -f "$LOCK"' EXIT

echo; echo "================ NEWS CATALOG LOOP started $(date) (pid $$) ================"
echo "budget USD: $BUDGET   model: $MODEL"

# run_news_catalog.py loads its own env from $ENV_FILE directly (more robust than
# shell sourcing — handles spaces and special chars in values cleanly).
echo "[$(date)] env source: $ENV_FILE  (python loads it directly)"

attempt=1
max_attempts=200
while [ "$attempt" -le "$max_attempts" ]; do
  echo; echo "[$(date)] --- iteration $attempt ---"
  if cd "$WT" && "$PY" -u scripts/run_news_catalog.py --budget-usd "$BUDGET" --model "$MODEL"; then
    echo "[$(date)] runner exited cleanly (budget/cap or all events done)."
    # If exit code 0 AND no events left, we're done.
    pending=$("$PY" -c "
import sys; sys.path.insert(0, '$WT/src')
from trader.catalog.build import detect_events, load_catalog, already_classified
from pathlib import Path
events = detect_events()
catalog = load_catalog(Path('$WT/output/catalysts/news_catalog.parquet'))
print(sum(1 for e in events if not already_classified(catalog, e.ticker, e.date)))
" 2>/dev/null || echo 999)
    echo "[$(date)] pending events remaining: $pending"
    if [ "$pending" = "0" ]; then
      echo "[$(date)] CATALOG COMPLETE."
      break
    fi
    echo "[$(date)] budget likely reached; sleeping 60s in case it lifts (it won't unless env changes)"
    sleep 60
  else
    echo "[$(date)] runner failed (exit $?); sleeping 30s before retry"
    sleep 30
  fi
  attempt=$((attempt + 1))
done

echo "================ NEWS CATALOG LOOP finished $(date) ================"
