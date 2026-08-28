"""Dry-run the bot-dispatch orchestrator against the real calendar.

Mirrors `dry_run_brief.py` (which previews the P10 brief pipeline) but
for the P21 orchestrator: fetches real upcoming meetings, then runs
`run_meeting_bot_cycle(..., dry_run=True)` over them and prints one
Arabic status line per meeting considered. No network call to Meeting
BaaS is made and nothing is written to the ledger — timing (45-75 min
window) and dedup (`sent_bots`) are still evaluated for real.

USAGE:  uv run python scripts/dry_run_orchestrator.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from rel_mcp.config import get_settings
from rel_mcp.google.auth import get_credentials
from rel_mcp.google.calendar import upcoming_meetings
from rel_mcp.ledger import connect
from rel_mcp.orchestrator import run_meeting_bot_cycle


def main() -> int:
    settings = get_settings()
    now = datetime.now(UTC)

    creds = get_credentials(settings)
    meetings = upcoming_meetings(
        creds, now=now, owner_email=settings.owner_email, within_hours=6
    )

    if not meetings:
        print("(مافيش اجتماعات فى الـ ٦ ساعات الجاية)")
        return 1

    with connect(settings.state_db_path) as ledger:
        results = run_meeting_bot_cycle(
            ledger,
            meetings,
            now,
            settings.require_meetingbaas_api_key(),
            settings.require_elevenlabs_api_key(),
            audit_log_path=settings.audit_log_path,
            dry_run=True,
        )

    print("=== orchestrator dry-run ===")
    for line in results:
        print(line)
    print("=== end ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
