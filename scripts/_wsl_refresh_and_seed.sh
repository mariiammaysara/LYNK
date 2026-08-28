#!/bin/bash
# Set PROFILE_NAME env var to override the default Hermes profile name
# Refreshes the WSL clone with the latest Windows-side source, then
# seeds the ledger and shows the agent's answer about a synthetic party.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
PROFILE_NAME="${PROFILE_NAME:-meeting-agent}"

WIN=/mnt/c/Users/ahmed/meetings-agent
WSL=/home/ahmed/meetings-agent

# Refresh source files (don't touch .venv, var/, or .env).
rsync -a --delete \
    --exclude '.venv' \
    --exclude 'var/' \
    --exclude '.env' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude '.ruff_cache' \
    --exclude '.mypy_cache' \
    --exclude '.git' \
    $WIN/src/ $WSL/src/
rsync -a --delete $WIN/scripts/ $WSL/scripts/
cp $WIN/pyproject.toml $WIN/uv.lock $WSL/
cp $WIN/hermes/system_prompt.md /home/ahmed/.hermes/profiles/"$PROFILE_NAME"/SOUL.md

# Clear the ledger to trigger fresh migrations, then seed.
rm -f $WSL/var/state.db
cd $WSL
uv sync 2>&1 | tail -2
echo
uv run python scripts/seed_ledger.py
