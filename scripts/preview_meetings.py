"""Print the next 48 hours of meetings as a plain Arabic table.

Reads the real calendar. External meetings are marked; internal-only
ones are annotated so it's obvious the classification ran. This is the
first time you see the agent's view of the calendar in one place.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

# Windows consoles default to cp1252 and choke on Arabic. Force UTF-8
# on stdout/stderr before the first print — the cost on POSIX terminals
# is zero (they're already UTF-8).
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from rel_mcp.config import get_settings
from rel_mcp.errors import RelError
from rel_mcp.google.auth import get_credentials
from rel_mcp.google.calendar import upcoming_meetings


def main() -> int:
    try:
        settings = get_settings()
        creds = get_credentials(settings)
    except RelError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    now = datetime.now(UTC)
    meetings = upcoming_meetings(
        creds,
        now=now,
        owner_email=settings.owner_email,
        within_hours=48,
    )

    if not meetings:
        print("مافيش اجتماعات فى الـ ٤٨ ساعة الجاية.")
        print("لو الكالندر مفروض فيه حاجة، اتأكدى إنك بتشوفى نفس الحساب فى Google Calendar.")
        return 0

    tz = ZoneInfo(settings.timezone)
    print(f"عدد الاجتماعات فى الـ ٤٨ ساعة الجاية: {len(meetings)}")
    print(f"التوقيت: {settings.timezone}")
    print("─" * 78)

    for m in meetings:
        local = m.start_utc.astimezone(tz)
        mark = "خارجى" if m.is_external else "داخلى"
        attendees = ", ".join(a.email for a in m.attendees) or "—"
        print(f"[{mark}] {local.strftime('%Y-%m-%d %H:%M')}  {m.title}")
        print(f"        الحضور: {attendees}")
        if m.meet_link:
            print(f"        رابط: {m.meet_link}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
