#!/usr/bin/env bash
# Persistent nightly scheduler: runs overnight_run.sh every NIGHTLY_INTERVAL hours
# (default 24h, fires at NIGHTLY_HOUR local time, default 02:30).
#
# Co-exists with spy_long_run.sh: the SPY backfill phase is automatically skipped
# when the long-run is active. Single-instance, logged, continue-on-error.
#
# Launch (survives the session; relaunch after reboot):
#     caffeinate -s nohup scripts/nightly_loop.sh >/dev/null 2>&1 &
#
# Run-now-and-then-loop (skips the first sleep):
#     RUN_NOW=1 caffeinate -s nohup scripts/nightly_loop.sh >/dev/null 2>&1 &
#
# Watch:  tail -f output/nightly_loop.log
# Stop:   pkill -f nightly_loop.sh && rm -f output/nightly_loop.lock

set -u
WT="/ABSOLUTE/PATH/TO/trader-catalyst"
LOG="$WT/output/nightly_loop.log"
LOCK="$WT/output/nightly_loop.lock"
NIGHTLY_HOUR="${NIGHTLY_HOUR:-2}"      # 02:00 local
NIGHTLY_MIN="${NIGHTLY_MIN:-30}"       # :30 -> fires 02:30
RUN_NOW="${RUN_NOW:-0}"
mkdir -p "$WT/output"
exec >> "$LOG" 2>&1

# --- single instance ---------------------------------------------------------
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "[$(date)] already running (pid $(cat "$LOCK")); exiting."; exit 0
fi
echo $$ > "$LOCK"; trap 'rm -f "$LOCK"' EXIT

echo; echo "================ NIGHTLY LOOP started $(date) (pid $$) ================"
echo "schedule: every day at ${NIGHTLY_HOUR}:$(printf %02d "$NIGHTLY_MIN") local"

seconds_until_next_fire() {
  python3 - <<PY
from datetime import datetime, time, timedelta
now = datetime.now()
target = now.replace(hour=${NIGHTLY_HOUR}, minute=${NIGHTLY_MIN}, second=0, microsecond=0)
if target <= now:
    target += timedelta(days=1)
print(int((target - now).total_seconds()))
PY
}

first=1
while true; do
  if [ "$RUN_NOW" = "1" ] && [ "$first" = "1" ]; then
    echo "[$(date)] RUN_NOW=1 — firing the first pass immediately."
  else
    secs=$(seconds_until_next_fire)
    echo "[$(date)] sleeping ${secs}s until next fire ($(date -v+${secs}S '+%Y-%m-%d %H:%M:%S'))"
    sleep "$secs" || true
  fi
  first=0
  echo; echo "================ FIRE $(date) ================"
  bash "$WT/scripts/overnight_run.sh" || echo "[overnight_run exited $?]"
  echo "================ FIRE done $(date) ================"
done
