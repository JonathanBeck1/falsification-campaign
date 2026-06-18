#!/usr/bin/env bash
# Install / remove the persistent SPY long-run launchd agent (user-level).
#
#   scripts/install_launchd.sh install     # load it (runs now + on every login)
#   scripts/install_launchd.sh uninstall   # stop and remove it
#   scripts/install_launchd.sh status      # is it loaded / running?
#
# The agent runs scripts/spy_long_run.sh under caffeinate. The script waits for
# the ThetaData Terminal, grinds the SPY backfill to 100%, exports to the lake,
# and refreshes studies. KeepAlive restarts it only on failure (a clean finish
# does NOT loop). Single-instance lock prevents duplicates.

set -eu
LABEL="com.trader.spy-long-run"
SRC="/ABSOLUTE/PATH/TO/trader-catalyst/scripts/${LABEL}.plist"
DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"

case "${1:-status}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents"
    cp "$SRC" "$DEST"
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$DEST"
    launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
    echo "installed + started: $LABEL"
    echo "watch: tail -f /ABSOLUTE/PATH/TO/trader-catalyst/output/spy_long_run.log"
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$DEST"
    echo "removed: $LABEL"
    ;;
  status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      echo "$LABEL is LOADED"; launchctl print "$DOMAIN/$LABEL" | grep -E "state =|pid =" || true
    else
      echo "$LABEL is not loaded"
    fi
    ;;
  *) echo "usage: $0 {install|uninstall|status}"; exit 2 ;;
esac
