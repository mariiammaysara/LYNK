#!/bin/bash
# Set PROFILE_NAME env var to override the default Hermes profile name
# Interactive chat with the agent profile — bypasses Telegram
# so we can prove the model+tools+SOUL loop works end-to-end without
# fighting the Telegram-in-WSL connection issue. Runs the same model
# (Haiku 4.5 via OpenRouter), same SOUL.md, same MCP server (rel_mcp).
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
PROFILE_NAME="${PROFILE_NAME:-meeting-agent}"
exec hermes -p "$PROFILE_NAME" chat
