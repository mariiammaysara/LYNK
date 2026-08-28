#!/bin/bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

cp /mnt/c/Users/ahmed/meetings-agent/.env.example ~/meetings-agent/
cd ~/meetings-agent
uv sync 2>&1 | tail -5
echo "---"
uv run python -c "import rel_mcp; print('rel_mcp version', rel_mcp.__version__)"
