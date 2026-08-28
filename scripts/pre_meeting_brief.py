"""The cron worker for the pre-meeting brief.

Called from Hermes cron every 15 minutes on the server. For each
external meeting starting in the next 45–75 minutes, builds the brief
via the MCP tool pipeline and either prints it (`--dry-run`) or sends
it to Telegram (`--send`, wired on the server).

The anti-duplicate guard is a table in the ledger (`sent_briefs`); a
meeting id present there is skipped, so a 15-minute pulse re-entering
the same window does not re-fire the same brief.

USAGE (local, dry-run only):
    uv run python scripts/pre_meeting_brief.py --dry-run

USAGE (on the server, once Telegram is available — added in P10):
    uv run python scripts/pre_meeting_brief.py --send
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from rel_mcp import server as srv
from rel_mcp.config import get_settings
from rel_mcp.ledger import connect, has_brief_been_sent, mark_brief_sent

# Fire briefs for meetings starting between BRIEF_WINDOW_MIN_LOWER and
# BRIEF_WINDOW_MIN_UPPER minutes from now. A 15-minute cron pulse
# combined with a 30-minute window means each meeting has two chances
# to be picked up, absorbing one missed pulse without doubling delivery.
BRIEF_WINDOW_MIN_LOWER = 45
BRIEF_WINDOW_MIN_UPPER = 75


async def _run(dry_run: bool) -> int:
    settings = get_settings()
    now = datetime.now(UTC)
    window_lower = now + timedelta(minutes=BRIEF_WINDOW_MIN_LOWER)
    window_upper = now + timedelta(minutes=BRIEF_WINDOW_MIN_UPPER)

    up = await srv.list_upcoming_meetings(within_hours=2)
    if not up["ok"]:
        print(f"[fail] {up['human_summary']}: {up.get('detail','')}")
        return 2

    candidates: list[dict[str, str]] = []
    for m in up.get("meetings", []):
        if not m["is_external"]:
            continue
        start_utc = datetime.fromisoformat(m["starts_at_utc"])
        if window_lower <= start_utc <= window_upper:
            candidates.append(m)

    if not candidates:
        lower = BRIEF_WINDOW_MIN_LOWER
        upper = BRIEF_WINDOW_MIN_UPPER
        print(f"[ok] no external meetings in the {lower}–{upper} min window")
        return 0

    with connect(settings.state_db_path) as ledger:
        for m in candidates:
            if has_brief_been_sent(ledger, m["id"]):
                print(f"[skip] {m['id']} — brief already delivered")
                continue

            brief = await srv.get_meeting_brief_for_cron(meeting_id=m["id"])
            if not brief["ok"]:
                print(f"[fail-brief] {m['id']}: {brief['human_summary']}")
                continue

            text = brief["human_summary"]
            print(f"=== brief for {m['id']} — {m['starts_at_local']} — {m['title']} ===")
            print(text)
            print()

            if dry_run:
                print(f"[dry-run] would send {len(text)} chars to Telegram; not marking as sent")
            else:
                # TODO(P10 on server): call the Telegram send here.
                # The Hermes cron will handle delivery via its own
                # send_message tool; this script only prepares the payload.
                mark_brief_sent(ledger, meeting_id=m["id"], now=now)
                print(f"[sent] {m['id']}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="print briefs, do not mark as sent"
    )
    parser.add_argument(
        "--send", action="store_true", help="record as sent (delivery is Hermes cron)"
    )
    args = parser.parse_args()
    if args.dry_run == args.send:
        parser.error("pass exactly one of --dry-run or --send")
    return asyncio.run(_run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
