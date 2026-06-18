#!/usr/bin/env bash
# Start the ThetaData Terminal if it isn't already serving on 25510. Idempotent.
set -u
JAVA="/opt/homebrew/opt/openjdk/bin/java"
DIR="$HOME/ThetaTerminal"
if curl -s -o /dev/null --max-time 5 "http://127.0.0.1:25510/v2/system/mdds/status"; then
  echo "ThetaData already serving on 25510."; exit 0
fi
cd "$DIR" || { echo "no $DIR"; exit 1; }
nohup "$JAVA" -jar ThetaTerminal.jar --creds-file "$DIR/creds.txt" >> "$DIR/terminal.log" 2>&1 &
echo "ThetaData launched (pid $!); waiting for REST..."
curl -s --retry 25 --retry-connrefused --retry-delay 3 --max-time 5 -o /dev/null \
  -w "ThetaData REST HTTP %{http_code}\n" "http://127.0.0.1:25510/v2/system/mdds/status"
