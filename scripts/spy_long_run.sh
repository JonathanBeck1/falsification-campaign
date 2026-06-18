#!/usr/bin/env bash
# SPY super-long run: wait for ThetaData, grind the SPY options backfill to 100%,
# export it to the parquet lake, then refresh studies. Resumable, idempotent,
# single-instance. Safe to run persistently (e.g. via launchd).
#
# Launch detached yourself with:
#     caffeinate -s nohup scripts/spy_long_run.sh >/dev/null 2>&1 &
# (Claude launches it in the background, and the launchd agent runs it on login.)
#
# Watch progress:  tail -f output/spy_long_run.log   — or the dashboard's
# "🗄️ Data Coverage" view.

set -u
MAIN="/ABSOLUTE/PATH/TO/trades"
WT="/ABSOLUTE/PATH/TO/trader-catalyst"
LAKE="$HOME/trader-lake-fast"      # internal lake the engine reads (outside the SSD DB dir)
export TRADER_SEC_USER_AGENT="catalyst-research you@example.com"
PY="$WT/.venv/bin/python"
LOG="$WT/output/spy_long_run.log"
LOCK="$WT/output/spy_long_run.lock"
mkdir -p "$WT/output"
exec >> "$LOG" 2>&1

# --- single instance ---------------------------------------------------------
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "[$(date)] already running (pid $(cat "$LOCK")); exiting."; exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

echo; echo "================ SPY LONG RUN started $(date) (pid $$) ================"
theta_up() { (echo > /dev/tcp/127.0.0.1/25510) >/dev/null 2>&1; }
spy_pct() { "$PY" - <<'PY'
import json
from pathlib import Path
p = Path("/ABSOLUTE/PATH/TO/trader-catalyst/output/catalysts/data_coverage.json")
try:
    print(json.loads(p.read_text())["tickers"].get("SPY", {}).get("pct_of_reference", 0))
except Exception:
    print(0)
PY
}

# --- Phase 1: wait for ThetaData (poll up to 48h) ----------------------------
waited=0
until theta_up; do
  [ $((waited % 1800)) -eq 0 ] && echo "[$(date +%H:%M)] waiting for ThetaData Terminal on 127.0.0.1:25510 ..."
  sleep 60; waited=$((waited + 60))
  [ "$waited" -ge 172800 ] && { echo "[$(date)] ThetaData not up in 48h; exiting."; exit 1; }
done
[ -d "/Volumes/Express 1M2" ] || { echo "[$(date)] external drive not mounted; abort."; exit 1; }
echo "[$(date)] ThetaData reachable + drive mounted — beginning SPY backfill."

# --- Phase 2: grind SPY backfill to completion (retry loop) ------------------
for pass in $(seq 1 80); do
  echo "[$(date)] --- SPY backfill pass $pass (current $(spy_pct)% ) ---"
  ( cd "$MAIN" && "$MAIN/.venv/bin/python" -m trader.cli options-backfill-thetadata-quotes \
      --ticker SPY --start 2020-01-02 --end 2026-06-06 ) || echo "[backfill pass exited $?]"
  "$PY" "$WT/scripts/refresh_coverage.py"
  pct=$(spy_pct)
  echo "[$(date)] SPY now ${pct}%"
  awk "BEGIN{exit !($pct >= 99)}" && { echo "[$(date)] SPY backfill COMPLETE."; break; }
  if ! theta_up; then echo "[$(date)] ThetaData dropped — waiting to resume..."; until theta_up; do sleep 60; done; fi
done

# --- Phase 3: export SPY to the parquet lake ---------------------------------
echo "[$(date)] exporting SPY -> $LAKE"
( cd "$MAIN" && "$MAIN/.venv/bin/python" -m trader.cli options-export-parquet-lake \
    --ticker SPY --out "$LAKE" ) || echo "[export exited $?]"

# --- Phase 4: refresh studies + verify + final coverage ----------------------
( cd "$WT" && "$PY" -u scripts/run_cef_study.py ) || echo "[cef study exited $?]"
if [ -n "${TIINGO_API_KEY:-}" ]; then
  ( cd "$WT" && "$PY" -u scripts/run_cef_survival.py ) || echo "[cef survival exited $?]"
fi
( cd "$WT" && "$PY" -m pytest \
    tests/financial/test_cef_study.py tests/financial/test_cef_resolution.py \
    tests/financial/test_cef_survival_backtest.py tests/financial/test_tiingo.py \
    tests/financial/test_lockup_study.py tests/financial/test_ipo_universe.py \
    tests/financial/test_ipo_lockup.py tests/financial/test_spac_arb.py \
    tests/financial/test_insider_clusters.py tests/financial/test_index_rebalance.py -q ) \
    || echo "[tests exited $?]"
"$PY" "$WT/scripts/refresh_coverage.py"

echo "================ SPY LONG RUN finished $(date) — SPY at $(spy_pct)% ================"
