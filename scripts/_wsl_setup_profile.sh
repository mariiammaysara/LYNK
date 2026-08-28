#!/bin/bash
# Set PROFILE_NAME env var to override the default Hermes profile name
# Bootstraps the agent's Hermes profile in WSL. Idempotent —
# safe to re-run. Delete after the profile is stable in production.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
PROFILE_NAME="${PROFILE_NAME:-meeting-agent}"

echo "== auth list =="
hermes auth list

echo
echo "== profile create $PROFILE_NAME =="
if hermes profile list 2>/dev/null | grep -q "$PROFILE_NAME"; then
    echo "already exists — skipping create"
else
    hermes profile create "$PROFILE_NAME" \
        --description "ذكاء الاجتماعات والعلاقات — briefs قبل الاجتماعات الخارجية"
fi

echo
echo "== profile list =="
hermes profile list
