#!/bin/bash
# Set PROFILE_NAME env var to override the default Hermes profile name
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
PROFILE_NAME="${PROFILE_NAME:-meeting-agent}"

echo "== stopping any prior gateway =="
pkill -f "hermes.*${PROFILE_NAME}.*gateway.*run" 2>&1 || true
sleep 1

echo
echo "== starting gateway (nohup) =="
nohup hermes -p "$PROFILE_NAME" gateway run > ~/"$PROFILE_NAME"-gateway.log 2>&1 &
disown
sleep 5
PID=$(pgrep -f "hermes.*${PROFILE_NAME}.*gateway.*run" | head -1)
echo "PID $PID"

echo
echo "== tail of log =="
tail -20 ~/"$PROFILE_NAME"-gateway.log 2>/dev/null || echo "no log yet"

echo
echo "== gateway status =="
hermes -p "$PROFILE_NAME" gateway status 2>&1 || true
