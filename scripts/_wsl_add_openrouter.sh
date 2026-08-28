#!/bin/bash
# Set PROFILE_NAME env var to override the default Hermes profile name
# Temporary helper — reads OPENROUTER_API_KEY from secrets.txt and registers
# it with Hermes. Delete after the agent profile is bootstrapped.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
PROFILE_NAME="${PROFILE_NAME:-meeting-agent}"

SECRETS=/mnt/c/Users/ahmed/meetings-agent/secrets.txt
KEY=$(grep '^OPENROUTER_API_KEY=' "$SECRETS" | head -1 | cut -d= -f2- | tr -d '\r\n')

if [ -z "$KEY" ]; then
    echo "ERROR: OPENROUTER_API_KEY not found in $SECRETS" >&2
    exit 1
fi

echo "key len: ${#KEY}"
hermes auth add openrouter --type api-key --label "${PROFILE_NAME}-dev" --api-key "$KEY"
