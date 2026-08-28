"""Verify Google auth end-to-end without touching any mail or calendar data.

Runs the OAuth flow once, then makes exactly two calls: the Gmail user
profile API (to prove the connected account) and the Calendar list API
(to prove read scope actually landed). If the connected email doesn't
match `OWNER_EMAIL`, the script exits with a loud warning — this catches
the "signed in as the wrong Google account by mistake" case, which is
easy to do on a browser with multiple accounts logged in.
"""

from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from googleapiclient.discovery import build

from rel_mcp.audit import append_audit
from rel_mcp.config import get_settings
from rel_mcp.errors import GoogleAuthError, RelError
from rel_mcp.google.auth import get_credentials


def main() -> int:
    try:
        settings = get_settings()
        creds = get_credentials(settings)
    except GoogleAuthError as exc:
        print(f"[FAIL] google auth: {exc}", file=sys.stderr)
        return 2
    except RelError as exc:
        print(f"[FAIL] config: {exc}", file=sys.stderr)
        return 2

    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    calendar = build("calendar", "v3", credentials=creds, cache_discovery=False)

    profile = gmail.users().getProfile(userId="me").execute()
    connected_email = str(profile.get("emailAddress", "")).lower()

    cal_list = calendar.calendarList().list(maxResults=250).execute()
    calendars_visible = len(cal_list.get("items", []))

    print(f"connected as: {connected_email}")
    print(f"calendars visible: {calendars_visible}")

    append_audit(
        settings.audit_log_path,
        action="google_check",
        summary=f"connected as {connected_email}, {calendars_visible} calendars",
        payload={"email": connected_email, "calendars": calendars_visible},
    )

    if connected_email != settings.owner_email:
        print(
            f"[WARN] connected account ({connected_email}) does not match "
            f"OWNER_EMAIL ({settings.owner_email}). Either sign in with the "
            "right account, or update OWNER_EMAIL in .env.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
