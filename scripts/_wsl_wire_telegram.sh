#!/bin/bash
# Set PROFILE_NAME env var to override the default Hermes profile name
# Writes Telegram env vars into the profile's .env so Hermes actually
# enables the platform. config.yaml alone doesn't switch it on.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
PROFILE_NAME="${PROFILE_NAME:-meeting-agent}"

SECRETS=/mnt/c/Users/ahmed/meetings-agent/secrets.txt
ENV_PATH=$(hermes -p "$PROFILE_NAME" config env-path)
TG_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$SECRETS" | head -1 | cut -d= -f2- | tr -d '\r\n')
CHAT_ID=1277050535

echo "env file: $ENV_PATH"

cat > "$ENV_PATH" <<ENV
# $PROFILE_NAME profile env — Hermes reads these to enable platforms.
TELEGRAM_BOT_TOKEN=$TG_TOKEN
TELEGRAM_ALLOWED_USERS=$CHAT_ID
TELEGRAM_HOME_CHANNEL=$CHAT_ID
TELEGRAM_HOME_CHANNEL_NAME=Mariam (dev)
ENV

chmod 600 "$ENV_PATH"
echo "env file written ($(wc -l < "$ENV_PATH") lines)"

echo
echo "== restart gateway =="
pkill -f "hermes.*${PROFILE_NAME}.*gateway.*run" 2>&1 || true
sleep 1
nohup hermes -p "$PROFILE_NAME" gateway run > ~/"$PROFILE_NAME"-gateway.log 2>&1 &
disown
sleep 4
echo "PID $(pgrep -f "hermes.*${PROFILE_NAME}.*gateway.*run" | head -1)"

echo
echo "== log tail =="
tail -25 ~/"$PROFILE_NAME"-gateway.log 2>&1
