"""Call every rel_mcp tool in order, print the human_summary for each.

This is the fastest way to prove the whole pipeline — auth, calendar,
ledger, brief render — works on this machine without spinning up
Hermes. If this script fails, no wiring above it will save you.
"""

from __future__ import annotations

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from rel_mcp import server as srv


async def _run() -> int:
    print("─── get_health ───")
    health = await srv.get_health()
    print(health["human_summary"])
    print(f"  google_ok={health['google_ok']}")
    print(f"  kill_switch_active={health['kill_switch_active']}")
    print(f"  last_audit: {health['last_audit_line'][:120]}")
    if not health["google_ok"]:
        print("[FAIL] google connection broken — fix it before running the rest.")
        return 2

    print("\n─── list_upcoming_meetings(within_hours=48) ───")
    up = await srv.list_upcoming_meetings(within_hours=48)
    print(up["human_summary"])
    for m in up.get("meetings", [])[:5]:
        mark = "خارجى" if m["is_external"] else "داخلى"
        print(f"  [{mark}] {m['starts_at_local']}  {m['title']}  (id={m['id']})")

    print("\n─── list_open_commitments ───")
    commits = await srv.list_open_commitments()
    print(commits["human_summary"])

    first_meeting = next(iter(up.get("meetings", [])), None)
    if first_meeting is None:
        print("\n(مافيش اجتماعات فى الكالندر عشان أختبر get_meeting_brief)")
        return 0

    print(f"\n─── get_meeting_brief({first_meeting['id']}) ───")
    brief = await srv.get_meeting_brief(meeting_id=first_meeting["id"])
    if brief["ok"]:
        print(brief["human_summary"])
    else:
        print(f"[FAIL] {brief['human_summary']}: {brief.get('detail', '')}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
