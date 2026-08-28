"""Bot-dispatch decisions and cycle — deterministic timing, orchestrated send.

Two layers in this module:

`should_send_bot(meeting, now)` is a pure function of its inputs, no
network, no clock read of its own — same shape as `brief.py`. It answers
exactly one question: "is this the moment to send a Meeting BaaS bot to
this meeting?"

`run_meeting_bot_cycle(...)` is the orchestration layer built on top of
it: for a list of meetings, it checks timing, checks the `sent_bots`
dedup table, and calls `meetingbaas_client.send_bot` for whichever
meetings are actually due. Unlike `should_send_bot`, this layer does
touch the network and the ledger — that's its entire job, mirroring the
P10 cron worker (`scripts/pre_meeting_brief.py`) but for bot dispatch
instead of brief delivery.

## The three conditions `should_send_bot` checks, all required

1. **Timing** — the same 45–75 minute pre-meeting window P10 uses for
   briefs. A 15-minute cron pulse combined with a 30-minute window gives
   two chances to catch a meeting, absorbing one missed pulse.
2. **External** — `meeting.is_external`, computed once in `calendar.py`
   and never re-judged here.
3. **Has a link** — `meeting.meet_link` must be set. A bot sent
   without a URL to join has nothing to do; `should_send_bot` returns
   `False` rather than the caller discovering that at send time.

## What `run_meeting_bot_cycle` deliberately does NOT do

It sends the bot and returns — it does not wait for the recording. A
meeting can run for an hour; blocking the cron process for that long
would stop it from doing anything else (including sending bots to other
meetings that become due in the meantime). Retrieving and transcribing
the finished recording is a separate, later step: a pulse that finds
`sent_bots` rows with `status = "requested"` and calls
`wait_for_recording` or `get_recording_url` on each — not built here.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from rel_mcp.errors import MeetingBotError
from rel_mcp.google.calendar import Meeting
from rel_mcp.ledger import has_bot_been_requested, mark_bot_requested, update_bot_status
from rel_mcp.transcripts.meetingbaas_client import send_bot

# Same window P10 uses for briefs (see scripts/pre_meeting_brief.py) —
# kept as its own constants here rather than imported from a script,
# since a script is not a library dependency and the two decisions
# (send a brief vs. send a bot) are conceptually separate even though
# they currently share the same numbers.
SEND_BOT_WINDOW_MIN_LOWER = 45
SEND_BOT_WINDOW_MIN_UPPER = 75


def should_send_bot(meeting: Meeting, now: datetime) -> bool:
    """True iff a Meeting BaaS bot should be sent to `meeting` right now."""
    if not meeting.is_external:
        return False

    if not meeting.meet_link:
        return False

    window_lower = now + timedelta(minutes=SEND_BOT_WINDOW_MIN_LOWER)
    window_upper = now + timedelta(minutes=SEND_BOT_WINDOW_MIN_UPPER)
    return window_lower <= meeting.start_utc <= window_upper


def run_meeting_bot_cycle(
    ledger: sqlite3.Connection,
    meetings: list[Meeting],
    now: datetime,
    meetingbaas_api_key: str,
    elevenlabs_api_key: str,
    webhook_url: str | None = None,
    *,
    audit_log_path: Path,
    dry_run: bool = True,
) -> list[str]:
    """Send a Meeting BaaS bot to every due meeting in `meetings`.

    For each meeting, in order: skip if `should_send_bot` says it's not
    time yet; skip if `has_bot_been_requested` says one was already
    requested (dedup — a re-firing cron pulse must not double-send);
    otherwise mark the request, call `send_bot`, and record the outcome
    (`bot_id` + `status="requested"` on success, `status="failed"` on
    failure). A failure sending one bot is recorded and does NOT stop
    the cycle — the next meeting still gets its chance.

    Returns one human-readable Arabic status line per meeting considered
    (not just the ones a bot was sent to), so a caller — a cron script or
    a manual dry-run — can log or print exactly what happened.

    `dry_run=True` (the default, matching `Settings.dry_run`'s own safe
    default) still evaluates timing and dedup, but makes no ledger write
    and no network call — every meeting that would get a bot is reported
    as such without actually requesting one. Pass `dry_run=False` only
    once you're ready to actually dispatch (Meeting BaaS bots cost real
    money per minute).

    `elevenlabs_api_key` is accepted for signature symmetry with the
    eventual recording-retrieval step but is not used here — dispatching
    a bot never transcribes anything; see the module docstring for why
    that's a separate step.
    """
    del elevenlabs_api_key  # reserved for the retrieval step, see docstring

    results: list[str] = []

    for meeting in meetings:
        if not should_send_bot(meeting, now):
            results.append(f"تخطي: {meeting.title} — خارج نافذة الإرسال")
            continue

        if has_bot_been_requested(ledger, meeting.id):
            results.append(f"تخطي: {meeting.title} — بوت اتطلب قبل كده")
            continue

        if dry_run:
            results.append(f"[dry-run] هيتبعت بوت لـ: {meeting.title}")
            continue

        try:
            request_id = mark_bot_requested(ledger, meeting_id=meeting.id, now=now)
        except sqlite3.IntegrityError:
            # has_bot_been_requested above raced with another writer
            # (e.g. an overlapping cron pulse) between its check and
            # this insert — the UNIQUE constraint on meeting_id caught
            # it. Treat it the same as the ordinary dedup skip above
            # rather than letting the whole cycle crash.
            results.append(f"تخطي: {meeting.title} — بوت اتطلب فى نفس اللحظة (تعارض)")
            continue

        # should_send_bot already guaranteed meet_link is set — this
        # assert only narrows the type for mypy, not a runtime check of
        # something that can actually happen at this point.
        assert meeting.meet_link is not None

        try:
            session = send_bot(
                meeting.meet_link,
                meetingbaas_api_key,
                webhook_url=webhook_url,
                audit_log_path=audit_log_path,
                now=now,
            )
        except MeetingBotError as exc:
            update_bot_status(
                ledger, request_id=request_id, bot_id=None, status="failed", now=now
            )
            results.append(f"فشل الإرسال: {meeting.title} — {exc}")
            continue

        update_bot_status(
            ledger,
            request_id=request_id,
            bot_id=session.bot_id,
            status="requested",
            now=now,
        )
        results.append(f"بوت اتبعت بنجاح: {meeting.title} — bot_id={session.bot_id}")

    return results
