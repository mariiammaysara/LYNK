"""Calendar reader — deterministic, timezone-injected, cancellation-aware.

Everything the brief pipeline needs to know about "the CEO's next hour"
comes out of this module. Three things it does that a naive Calendar API
call doesn't:

1. **External classification lives here, in code.** A meeting is external
   iff at least one non-owner attendee has an email whose domain differs
   from the owner's. This is never a judgement call the model makes at
   brief time — it is a property of the row, computable offline.

2. **Cancelled events and declined-by-owner events are dropped.** Google
   returns both; both mean "this is not happening" and both would
   otherwise inflate the brief queue.

3. **`now` is injected.** No module in the read path calls the system
   clock. That's what makes the calendar-side tests deterministic and
   what will keep the brief scheduler reproducible under DST or
   day-boundary edge cases.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from pydantic import BaseModel, Field


class Attendee(BaseModel):
    """One attendee row on a meeting."""

    email: str
    name: str | None = None
    response: str = "needsAction"


class Meeting(BaseModel):
    """A single scheduled meeting, as we care about it downstream.

    Times are always UTC — the surrounding timezone (`Asia/Riyadh`) is
    applied only at render time, in one place, never here.
    """

    id: str
    title: str
    start_utc: datetime
    end_utc: datetime
    attendees: list[Attendee] = Field(default_factory=list)
    description: str = ""
    meet_link: str | None = None
    is_external: bool


# ─── Public API ──────────────────────────────────────────────────────


def upcoming_meetings(
    creds: Credentials,
    *,
    now: datetime,
    owner_email: str,
    within_hours: int = 48,
) -> list[Meeting]:
    """Meetings that start in the window `(now, now + within_hours]`.

    Ordered by start time. Cancelled events and events the owner declined
    are omitted; declined attendees are omitted from the attendee list.
    """
    end = now + timedelta(hours=within_hours)
    events = _list_events(creds, time_min=now, time_max=end)
    return _to_meetings(events, owner_email=owner_email)


def just_ended(
    creds: Credentials,
    *,
    now: datetime,
    owner_email: str,
    lookback_minutes: int = 30,
) -> list[Meeting]:
    """Meetings that ended in the window `[now - lookback_minutes, now)`.

    Used by the post-meeting confirmation tap (later phase) — the same
    filter and classification rules as `upcoming_meetings`.
    """
    start = now - timedelta(minutes=lookback_minutes)
    events = _list_events(creds, time_min=start, time_max=now)
    return [m for m in _to_meetings(events, owner_email=owner_email) if m.end_utc <= now]


# ─── Internals ───────────────────────────────────────────────────────


def _list_events(
    creds: Credentials,
    *,
    time_min: datetime,
    time_max: datetime,
) -> list[dict[str, Any]]:
    """One primary-calendar page, sorted, singleEvents expanded."""
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    resp = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=_rfc3339(time_min),
            timeMax=_rfc3339(time_max),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        )
        .execute()
    )
    items = resp.get("items", [])
    return list(items) if isinstance(items, list) else []


def _to_meetings(events: list[dict[str, Any]], *, owner_email: str) -> list[Meeting]:
    owner_domain = _domain_of(owner_email)
    out: list[Meeting] = []

    for event in events:
        if event.get("status") == "cancelled":
            continue

        # Drop the entire event if the owner declined it; keep the
        # meeting but filter *other* declined attendees out of its list.
        raw_attendees = event.get("attendees") or []
        if _owner_declined(raw_attendees, owner_email):
            continue

        start_utc = _parse_boundary(event.get("start"))
        end_utc = _parse_boundary(event.get("end"))
        if start_utc is None or end_utc is None:
            # All-day events (or malformed rows) have `date` not
            # `dateTime` — we deliberately do not surface them; the brief
            # pipeline is about scheduled meetings, not day markers.
            continue

        attendees = [
            Attendee(
                email=(a.get("email") or "").lower(),
                name=a.get("displayName"),
                response=a.get("responseStatus", "needsAction"),
            )
            for a in raw_attendees
            if (a.get("email") or "").lower() != owner_email.lower()
            and a.get("responseStatus") != "declined"
        ]

        is_external = any(_domain_of(a.email) != owner_domain for a in attendees)

        out.append(
            Meeting(
                id=str(event["id"]),
                title=str(event.get("summary") or ""),
                start_utc=start_utc,
                end_utc=end_utc,
                attendees=attendees,
                description=str(event.get("description") or ""),
                meet_link=_meet_link(event),
                is_external=is_external,
            )
        )

    out.sort(key=lambda m: m.start_utc)
    return out


def _owner_declined(attendees: list[dict[str, Any]], owner_email: str) -> bool:
    owner_email_lower = owner_email.lower()
    for a in attendees:
        email = (a.get("email") or "").lower()
        if email == owner_email_lower and a.get("responseStatus") == "declined":
            return True
    return False


def _parse_boundary(boundary: dict[str, Any] | None) -> datetime | None:
    if not boundary:
        return None
    dt_str = boundary.get("dateTime")
    if not isinstance(dt_str, str):
        return None
    # Google returns RFC3339 with a `Z` or `+HH:MM` suffix. Python 3.11+
    # `fromisoformat` accepts both, but the trailing `Z` needs replacing.
    normalized = dt_str.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed.astimezone(UTC)


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _domain_of(email: str) -> str:
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[1].lower()


def _meet_link(event: dict[str, Any]) -> str | None:
    link = event.get("hangoutLink")
    if isinstance(link, str) and link:
        return link
    conf = event.get("conferenceData") or {}
    for entry in conf.get("entryPoints") or []:
        if entry.get("entryPointType") == "video":
            uri = entry.get("uri")
            if isinstance(uri, str):
                return uri
    return None
