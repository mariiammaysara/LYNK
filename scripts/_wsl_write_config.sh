#!/bin/bash
# Set PROFILE_NAME env var to override the default Hermes profile name
# Writes the full config.yaml for the agent profile. Reads OpenRouter key
# and Telegram bot token from secrets.txt. Idempotent — overwrites.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
PROFILE_NAME="${PROFILE_NAME:-meeting-agent}"

SECRETS=/mnt/c/Users/ahmed/meetings-agent/secrets.txt
CONFIG=/home/ahmed/.hermes/profiles/"$PROFILE_NAME"/config.yaml

TG_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$SECRETS" | head -1 | cut -d= -f2- | tr -d '\r\n')

if [ -z "$TG_TOKEN" ]; then
    echo "ERROR: TELEGRAM_BOT_TOKEN missing" >&2
    exit 1
fi

cat > "$CONFIG" <<YAML
# $PROFILE_NAME profile — Hermes gateway config
# Model runs via OpenRouter (auth added separately with 'hermes auth add openrouter').
model:
  provider: openrouter
  name: anthropic/claude-haiku-4.5

# Riyadh timezone. Use the bare 'timezone' key — 'cron.timezone' is
# silently accepted and does nothing (a known Hermes gotcha).
timezone: Asia/Riyadh

# Telegram gateway. home_channel is Mariam's chat id for dev testing;
# swap to the owner's chat id before delivery.
gateway:
  telegram:
    bot_token: ${TG_TOKEN}
    home_channel: "1277050535"

# MCP server — rel_mcp lives on the Windows side, accessed via /mnt/c.
# trust: untrusted is MANDATORY (see README.dev.md decision — Hermes
# otherwise honors the server's own readOnlyHint, collapsing two
# independent gates into one).
mcp_servers:
  rel:
    command: uv
    args:
      - "--directory"
      - "/mnt/c/Users/ahmed/meetings-agent"
      - "run"
      - "python"
      - "-m"
      - "rel_mcp.server"
    trust: untrusted
    env:
      ENVIRONMENT: local
      DRY_RUN: "true"
      GOOGLE_CREDENTIALS_PATH: /mnt/c/Users/ahmed/meetings-agent/credentials.json
      GOOGLE_TOKEN_PATH: /mnt/c/Users/ahmed/meetings-agent/var/token.json
      AUDIT_LOG_PATH: /mnt/c/Users/ahmed/meetings-agent/var/audit.jsonl
      STATE_DB_PATH: /mnt/c/Users/ahmed/meetings-agent/var/state.db
      TIMEZONE: Asia/Riyadh
      OWNER_EMAIL: mariammaysara.ai@gmail.com
      KILL_SWITCH_PATH: /mnt/c/Users/ahmed/meetings-agent/var/STOP
    tools:
      include:
        - list_upcoming_meetings
        - get_meeting_brief
        - get_party_status
        - list_open_commitments
        - get_health
        - stop_agent
        - dispatch_meeting_bots
        - get_meeting_summary
YAML

echo "config written to $CONFIG"
echo
echo "== config check =="
hermes -p "$PROFILE_NAME" config check || true

echo
echo "== copy SOUL.md =="
cp /mnt/c/Users/ahmed/meetings-agent/hermes/system_prompt.md \
   /home/ahmed/.hermes/profiles/"$PROFILE_NAME"/SOUL.md
echo "SOUL.md copied ($(wc -l < /home/ahmed/.hermes/profiles/"$PROFILE_NAME"/SOUL.md) lines)"
