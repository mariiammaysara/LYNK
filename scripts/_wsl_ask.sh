#!/bin/bash
# Set PROFILE_NAME env var to override the default Hermes profile name
# One-shot ask against the agent profile. Bypasses Telegram —
# uses hermes -z for a scripted prompt/response.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
PROFILE_NAME="${PROFILE_NAME:-meeting-agent}"

PROMPT="${1:-إيه اجتماعاتى فى الـ ٤٨ ساعة الجاية؟}"
echo "== prompt: $PROMPT =="
echo
timeout 90 hermes -p "$PROFILE_NAME" -z "$PROMPT" 2>&1
