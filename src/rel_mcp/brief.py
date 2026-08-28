"""Brief composer — deterministic, offline, testable.

## What this module is (and is not)

The `Brief` returned by `build_brief` is a pure function of its inputs:
a `Meeting` from the calendar reader, a ledger connection, a list of
`Thread` objects from the Gmail reader, and `now`. No network calls, no
model calls, no wall-clock reads. The same inputs give the same brief.

Everything the model does later is _phrasing_, not composition. Which
facts belong in the brief is decided here, in code. Which words render
them is `render.py`. Neither of those is left to the model to invent.

## The one behavioral rule that changes over time

**Empty sections get dropped, not filled with prose.** A brief for a
brand-new counterparty legitimately has no last-contact line, no open
commitments, no agreed terms — and the render skips those sections
rather than writing "no previous history yet". A single flag line at
the end explains that the ledger is empty; that's the honest surface.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from rel_mcp.google.calendar import Meeting
from rel_mcp.google.gmail import Thread
from rel_mcp.ledger import (
    agreed_terms,
    get_transcript,
    last_contact,
    open_commitments,
    party_for_domain,
    recent_meetings,
)

# ─── Brief model ─────────────────────────────────────────────────────


class LastContactRef(BaseModel):
    kind: str
    days_ago: int
    reference: str = ""


class OpenCommitmentRef(BaseModel):
    text: str
    days_to_due: int | None = None  # negative = overdue; None = no due date
    overdue: bool = False


class TermFact(BaseModel):
    kind: str
    value: str
    confirmed: bool


class ThreadRef(BaseModel):
    subject: str
    days_ago: int


class Brief(BaseModel):
    # Header
    meeting_title: str
    starts_at_local_iso: str  # already tz-shifted by caller for rendering
    is_external: bool
    party_name: str | None = None
    attendee_names: list[str] = Field(default_factory=list)

    # Body sections — any may be empty; render skips empty ones
    last_contact: LastContactRef | None = None
    our_open: list[OpenCommitmentRef] = Field(default_factory=list)
    their_open: list[OpenCommitmentRef] = Field(default_factory=list)
    terms: list[TermFact] = Field(default_factory=list)
    threads: list[ThreadRef] = Field(default_factory=list)

    # Guidance
    suggested_questions: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)

    # True iff a previous meeting with this party has a stored
    # transcript (P21). Existence only — never the text itself; that's
    # not yet considered ready for direct display in a brief.
    has_recent_transcript: bool = False


# ─── Public API ──────────────────────────────────────────────────────


def build_brief(
    *,
    meeting: Meeting,
    ledger: sqlite3.Connection,
    threads: list[Thread],
    now: datetime,
    starts_at_local_iso: str,
    max_threads: int = 3,
) -> Brief:
    """Compose a brief from the given inputs. Deterministic and offline.

    `starts_at_local_iso` is passed in pre-formatted because the timezone
    lives in `Settings`, not here — this module stays free of any
    configuration read.
    """
    external_attendees = [a for a in meeting.attendees if "@" in a.email]
    attendee_names = [a.name or a.email for a in external_attendees]

    party = _resolve_party(ledger, external_attendees)

    if party is None:
        # No ledger row exists for this counterparty yet — the honest
        # brief says so and offers only calendar + thread context.
        thread_refs = _top_threads(threads, now, max_threads)
        return Brief(
            meeting_title=meeting.title,
            starts_at_local_iso=starts_at_local_iso,
            is_external=meeting.is_external,
            party_name=None,
            attendee_names=attendee_names,
            threads=thread_refs,
            suggested_questions=_new_party_questions(),
            flags=["new_party"],
        )

    our_open = _commitments_by_side(ledger, party.id, side="us", now=now)
    their_open = _commitments_by_side(ledger, party.id, side="them", now=now)
    terms = [
        TermFact(kind=t.kind, value=t.value, confirmed=t.confirmed_by_owner)
        for t in agreed_terms(ledger, party.id)
    ]
    last = _last_contact_ref(ledger, party.id, now)
    thread_refs = _top_threads(threads, now, max_threads)

    flags = _compose_flags(our_open, their_open, terms)
    questions = _questions_from(our_open, their_open, terms)
    has_transcript = _has_recent_transcript(ledger, party.id)

    return Brief(
        meeting_title=meeting.title,
        starts_at_local_iso=starts_at_local_iso,
        is_external=meeting.is_external,
        party_name=party.name,
        attendee_names=attendee_names,
        last_contact=last,
        our_open=our_open,
        their_open=their_open,
        terms=terms,
        threads=thread_refs,
        suggested_questions=questions,
        flags=flags,
        has_recent_transcript=has_transcript,
    )


# ─── Internals ───────────────────────────────────────────────────────


def _resolve_party(ledger: sqlite3.Connection, attendees: list[Any]) -> Any:
    """First external attendee whose domain is in the ledger wins."""
    for a in attendees:
        domain = a.email.split("@", 1)[1].lower() if "@" in a.email else ""
        if not domain:
            continue
        party = party_for_domain(ledger, domain)
        if party is not None:
            return party
    return None


def _commitments_by_side(
    ledger: sqlite3.Connection,
    party_id: int,
    *,
    side: str,
    now: datetime,
) -> list[OpenCommitmentRef]:
    all_open = open_commitments(ledger, party_id)
    picked = [c for c in all_open if c.side == side]
    refs: list[OpenCommitmentRef] = []
    for c in picked:
        if c.due_date is None:
            refs.append(OpenCommitmentRef(text=c.text, days_to_due=None, overdue=False))
            continue
        days = (c.due_date.date() - now.date()).days
        refs.append(
            OpenCommitmentRef(
                text=c.text,
                days_to_due=days,
                overdue=days < 0,
            )
        )
    return refs


def _last_contact_ref(
    ledger: sqlite3.Connection, party_id: int, now: datetime
) -> LastContactRef | None:
    event = last_contact(ledger, party_id)
    if event is None:
        return None
    days = (now.date() - event.contact_date.date()).days
    return LastContactRef(kind=event.kind, days_ago=max(days, 0), reference=event.reference)


def _top_threads(threads: list[Thread], now: datetime, limit: int) -> list[ThreadRef]:
    sorted_threads = sorted(threads, key=lambda t: t.last_message_at, reverse=True)
    refs: list[ThreadRef] = []
    for t in sorted_threads[:limit]:
        days = (now.date() - t.last_message_at.date()).days
        refs.append(ThreadRef(subject=t.subject or "(بدون عنوان)", days_ago=max(days, 0)))
    return refs


def _compose_flags(
    our_open: list[OpenCommitmentRef],
    their_open: list[OpenCommitmentRef],
    terms: list[TermFact],
) -> list[str]:
    flags: list[str] = []
    if any(c.overdue for c in our_open + their_open):
        flags.append("has_overdue")
    if any(not t.confirmed for t in terms):
        flags.append("unconfirmed_terms")
    return flags


def _questions_from(
    our_open: list[OpenCommitmentRef],
    their_open: list[OpenCommitmentRef],
    terms: list[TermFact],
) -> list[str]:
    """Questions derived from data — never invented, always tied to a row.

    Kept short and specific; the render layer prefixes them with a bullet.
    """
    qs: list[str] = []
    for c in their_open:
        if c.overdue:
            qs.append(f"موقف «{c.text}» — متأخر من متى؟")
        else:
            qs.append(f"متى «{c.text}»؟")
    for t in terms:
        if not t.confirmed:
            qs.append(f"تأكيد {t.kind}: {t.value}")
    # Our own overdue commitments deserve a reminder note too, phrased
    # as a self-question so it reads as prep, not as blame.
    for c in our_open:
        if c.overdue:
            qs.append(f"«{c.text}» — لسه علينا، حالته إيه؟")
    return qs


def _has_recent_transcript(ledger: sqlite3.Connection, party_id: int) -> bool:
    """True iff any of the party's recorded meetings has a stored transcript."""
    return any(
        get_transcript(ledger, m.id) is not None for m in recent_meetings(ledger, party_id)
    )


def _new_party_questions() -> list[str]:
    # For a brand-new counterparty the ledger has nothing to draw on —
    # a static three-item prompt is better than fabricating "questions
    # about their commitments" out of nothing.
    return [
        "الجهة والدور — تعارف مختصر",
        "الهدف من الاجتماع من وجهة نظرهم",
        "الخطوة الجاية بعد الاجتماع",
    ]
