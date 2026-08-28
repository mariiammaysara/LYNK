"""Print the brief for a specific calendar meeting — exactly as it would
be delivered — without sending it anywhere.

The brief pipeline is deterministic (see `brief.py` docstring), so the
output here is character-for-character identical to what a scheduled
brief would put on Telegram. Use this for two things:

1. **Preview a brief before delivery.** Given a real meeting_id from
   the calendar, see what the agent will show its owner.
2. **See a brief with synthetic data.** Run `scripts/seed_ledger.py`
   first to populate the ledger, then pass any meeting_id that has
   an attendee from `alofoq-tech.example` or `najd-consulting.example`
   (the two synthetic domains). The brief will be rich instead of
   the empty "first meeting" placeholder.

USAGE:  uv run python scripts/dry_run_brief.py <meeting_id>
   or:  uv run python scripts/dry_run_brief.py --any
        (picks the first upcoming external meeting)
"""

from __future__ import annotations

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from rel_mcp import server as srv


async def _run(meeting_id: str | None) -> int:
    if meeting_id is None:
        up = await srv.list_upcoming_meetings(within_hours=72)
        if not up["ok"] or not up.get("meetings"):
            print("(مافيش اجتماعات فى الـ ٧٢ ساعة الجاية — مافيش حاجة أعرض عليها brief)")
            return 1
        first = up["meetings"][0]
        meeting_id = first["id"]
        print(f"# picked meeting: {first['title']} ({first['starts_at_local']})")
        print()

    result = await srv.get_meeting_brief(meeting_id=meeting_id)
    if not result["ok"]:
        print(f"[FAIL] {result['human_summary']}")
        if result.get("detail"):
            print(f"       {result['detail']}")
        return 2

    print("=== brief (as it would be sent to Telegram) ===")
    print(result["human_summary"])
    print("=== end brief ===")
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    arg = sys.argv[1]
    meeting_id = None if arg == "--any" else arg
    return asyncio.run(_run(meeting_id))


if __name__ == "__main__":
    sys.exit(main())
