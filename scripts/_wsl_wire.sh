#!/bin/bash
# Set PROFILE_NAME env var to override the default Hermes profile name
# Copies credentials.json + token.json to WSL clone (so paths in Hermes
# config.yaml don't need to reach through /mnt/c), and rewrites the
# Hermes config to point at the WSL clone.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
PROFILE_NAME="${PROFILE_NAME:-meeting-agent}"

WSL_REPO=/home/ahmed/meetings-agent
WIN_REPO=/mnt/c/Users/ahmed/meetings-agent
SECRETS=$WIN_REPO/secrets.txt
CONFIG=/home/ahmed/.hermes/profiles/"$PROFILE_NAME"/config.yaml

# Move Google identity into WSL clone so the MCP subprocess reads from
# its own tree (no mount-crossing on every call).
mkdir -p $WSL_REPO/var
cp $WIN_REPO/credentials.json $WSL_REPO/credentials.json
if [ -f $WIN_REPO/var/token.json ]; then
    cp $WIN_REPO/var/token.json $WSL_REPO/var/token.json
    echo "token.json copied"
else
    echo "no token.json — will need OAuth re-run"
fi

TG_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$SECRETS" | head -1 | cut -d= -f2- | tr -d '\r\n')

cat > "$CONFIG" <<YAML
model:
  provider: openrouter
  name: anthropic/claude-haiku-4.5

timezone: Asia/Riyadh

gateway:
  telegram:
    bot_token: ${TG_TOKEN}
    home_channel: "1277050535"

mcp_servers:
  rel:
    command: /home/ahmed/.local/bin/uv
    args:
      - "--directory"
      - "/home/ahmed/meetings-agent"
      - "run"
      - "python"
      - "-m"
      - "rel_mcp.server"
    trust: untrusted
    env:
      ENVIRONMENT: local
      DRY_RUN: "true"
      GOOGLE_CREDENTIALS_PATH: /home/ahmed/meetings-agent/credentials.json
      GOOGLE_TOKEN_PATH: /home/ahmed/meetings-agent/var/token.json
      AUDIT_LOG_PATH: /home/ahmed/meetings-agent/var/audit.jsonl
      STATE_DB_PATH: /home/ahmed/meetings-agent/var/state.db
      TIMEZONE: Asia/Riyadh
      OWNER_EMAIL: mariammaysara.ai@gmail.com
      KILL_SWITCH_PATH: /home/ahmed/meetings-agent/var/STOP
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

echo "config rewritten"

cp /mnt/c/Users/ahmed/meetings-agent/hermes/system_prompt.md \
   /home/ahmed/.hermes/profiles/"$PROFILE_NAME"/SOUL.md
echo "SOUL.md refreshed"

echo
echo "== mcp_selftest from WSL =="
cd $WSL_REPO
uv run python scripts/mcp_selftest.py 2>&1 | head -15
