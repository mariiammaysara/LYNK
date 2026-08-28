#!/bin/bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/meetings-agent
uv run python scripts/mcp_selftest.py 2>&1
