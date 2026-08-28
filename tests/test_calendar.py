"""Calendar reader — all classification and filtering rules covered on
fixtures, no network. Each test names one concrete rule from the module
docstring."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rel_mcp.google.calendar import _to_meetings

OWNER = "owner@acme.example"
INTERNAL = "cfo@acme.example"
EXTERNAL = "partner@vendor.example"


def _event(
    *,
    event_id: str = "e1",
    summary: str = "Meeting",
    start: str = "2026-01-15T10:00:00+03:00",
    end: str = "2026-01-15T11:00:00+03:00",
    attendees: list[dict[str, Any]] | None = None,
    status: str = "confirmed",
    description: str = "",
    hangout: str | None = None,
) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        "status": status,
        "description": description,
    }
    if attendees is not None:
        ev["attendees"] = attendees
    if hangout is not None:
        ev["hangoutLink"] = hangout
    return ev


def test_external_meeting_is_flagged() -> None:
    events = [_event(attendees=[{"email": EXTERNAL, "responseStatus": "accepted"}])]
    meetings = _to_meetings(events, owner_email=OWNER)
    assert len(meetings) == 1
    assert meetings[0].is_external is True


def test_internal_only_meeting_is_not_flagged() -> None:
    events = [_event(attendees=[{"email": INTERNAL, "responseStatus": "accepted"}])]
    meetings = _to_meetings(events, owner_email=OWNER)
    assert len(meetings) == 1
    assert meetings[0].is_external is False


def test_mixed_meeting_is_external() -> None:
    events = [
        _event(
            attendees=[
                {"email": INTERNAL, "responseStatus": "accepted"},
                {"email": EXTERNAL, "responseStatus": "accepted"},
            ]
        )
    ]
    assert _to_meetings(events, owner_email=OWNER)[0].is_external is True


def test_cancelled_event_is_dropped() -> None:
    events = [_event(status="cancelled", attendees=[{"email": EXTERNAL}])]
    assert _to_meetings(events, owner_email=OWNER) == []


def test_owner_declined_drops_the_meeting() -> None:
    events = [
        _event(
            attendees=[
                {"email": OWNER, "responseStatus": "declined"},
                {"email": EXTERNAL, "responseStatus": "accepted"},
            ]
        )
    ]
    assert _to_meetings(events, owner_email=OWNER) == []


def test_declined_non_owner_is_filtered_from_attendees() -> None:
    events = [
        _event(
            attendees=[
                {"email": EXTERNAL, "responseStatus": "accepted"},
                {"email": "declined@vendor.example", "responseStatus": "declined"},
            ]
        )
    ]
    meetings = _to_meetings(events, owner_email=OWNER)
    assert len(meetings) == 1
    assert [a.email for a in meetings[0].attendees] == [EXTERNAL]


def test_owner_is_excluded_from_attendee_list() -> None:
    events = [
        _event(
            attendees=[
                {"email": OWNER, "responseStatus": "accepted"},
                {"email": EXTERNAL, "responseStatus": "accepted"},
            ]
        )
    ]
    attendees = _to_meetings(events, owner_email=OWNER)[0].attendees
    assert OWNER not in [a.email for a in attendees]


def test_all_day_event_is_dropped() -> None:
    # All-day events have `date` not `dateTime`; they are day markers,
    # not meetings, and the brief pipeline explicitly skips them.
    ev = {
        "id": "e1",
        "summary": "OOO",
        "start": {"date": "2026-01-15"},
        "end": {"date": "2026-01-16"},
        "status": "confirmed",
        "attendees": [{"email": EXTERNAL, "responseStatus": "accepted"}],
    }
    assert _to_meetings([ev], owner_email=OWNER) == []


def test_non_riyadh_timezone_normalizes_to_utc() -> None:
    events = [
        _event(
            start="2026-01-15T09:00:00-05:00",  # 14:00 UTC
            end="2026-01-15T10:00:00-05:00",  # 15:00 UTC
            attendees=[{"email": EXTERNAL}],
        )
    ]
    meeting = _to_meetings(events, owner_email=OWNER)[0]
    assert meeting.start_utc == datetime(2026, 1, 15, 14, 0, tzinfo=UTC)
    assert meeting.end_utc == datetime(2026, 1, 15, 15, 0, tzinfo=UTC)
    assert meeting.start_utc.tzinfo is UTC


def test_meetings_are_sorted_by_start_time() -> None:
    events = [
        _event(event_id="late", start="2026-01-15T14:00:00+03:00", end="2026-01-15T15:00:00+03:00"),
        _event(
            event_id="early",
            start="2026-01-15T09:00:00+03:00",
            end="2026-01-15T10:00:00+03:00",
        ),
    ]
    meetings = _to_meetings(events, owner_email=OWNER)
    assert [m.id for m in meetings] == ["early", "late"]


def test_meet_link_from_hangout_link() -> None:
    events = [_event(hangout="https://meet.google.com/abc-defg-hij")]
    assert _to_meetings(events, owner_email=OWNER)[0].meet_link == "https://meet.google.com/abc-defg-hij"


def test_meet_link_from_conference_data() -> None:
    ev = _event()
    ev["conferenceData"] = {
        "entryPoints": [
            {"entryPointType": "phone", "uri": "tel:+1234"},
            {"entryPointType": "video", "uri": "https://meet.google.com/xyz"},
        ]
    }
    assert _to_meetings([ev], owner_email=OWNER)[0].meet_link == "https://meet.google.com/xyz"


def test_meet_link_from_zoom_conference_data() -> None:
    # Zoom added via Google Calendar's conferencing add-on uses the same
    # generic conferenceData.entryPoints shape as Meet — just a
    # different conferenceSolution and a zoom.us URI. No special-casing
    # needed; this documents that the existing generic lookup covers it.
    ev = _event()
    ev["conferenceData"] = {
        "conferenceSolution": {"name": "Zoom Meeting"},
        "entryPoints": [
            {"entryPointType": "phone", "uri": "tel:+1234"},
            {
                "entryPointType": "video",
                "uri": "https://zoom.us/j/1234567890?pwd=abc123",
                "label": "zoom.us/j/1234567890",
            },
        ],
    }
    assert (
        _to_meetings([ev], owner_email=OWNER)[0].meet_link
        == "https://zoom.us/j/1234567890?pwd=abc123"
    )


def test_no_meet_link_when_absent() -> None:
    # No hangoutLink, no conferenceData — a real, common case (a plain
    # in-person or phone meeting). None is correct, not an error.
    events = [_event()]
    assert _to_meetings(events, owner_email=OWNER)[0].meet_link is None


def test_no_attendees_means_not_external() -> None:
    events = [_event(attendees=[])]
    assert _to_meetings(events, owner_email=OWNER)[0].is_external is False


def test_owner_email_case_insensitive() -> None:
    events = [
        _event(
            attendees=[
                {"email": OWNER.upper(), "responseStatus": "declined"},
                {"email": EXTERNAL, "responseStatus": "accepted"},
            ]
        )
    ]
    assert _to_meetings(events, owner_email=OWNER) == []
