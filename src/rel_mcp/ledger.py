"""Relationship ledger — the CRM the client doesn't have.

SQLite, no ORM, no framework. Six tables, one migration table, all query
paths are explicit functions in this module — nothing else in the code
opens the database directly. Every function that mutates or reads takes
`now` as an injected parameter; there is no wall-clock read in this
module for the same reason there is none in `calendar.py` — brief
outputs must be reproducible from row state alone.

## The one rule the schema enforces by name

`agreed_terms` carries `confirmed_by_owner`. **A row with
`confirmed_by_owner = 0` must never be surfaced to the reader as fact.**
The query function that returns terms tags each one with the flag so
the render layer has to make a deliberate choice — no silent promotion
from "the model heard it in email" to "the owner agreed to it".

## Migrations

`MIGRATIONS` is an ordered list of `(version, sql)` pairs. `connect()`
runs `PRAGMA user_version` and applies any migration whose version is
greater than the current one, in order, in a single transaction each.
Re-running is a no-op. Downgrades are not supported — write a forward
migration instead.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

CommitmentSide = Literal["us", "them"]
CommitmentStatus = Literal["open", "done", "cancelled"]
TranscriptSource = Literal["munsit", "elevenlabs", "manual"]
BotRequestStatus = Literal["requested", "completed", "failed"]


# ─── Models returned to callers ──────────────────────────────────────


class Party(BaseModel):
    id: int
    name: str
    domain: str
    note: str = ""


class Person(BaseModel):
    id: int
    party_id: int
    name: str
    email: str
    role: str = ""


class MeetingRow(BaseModel):
    id: int
    calendar_id: str
    party_id: int | None
    meeting_date: datetime
    title: str
    attendees: list[str] = Field(default_factory=list)


class Commitment(BaseModel):
    id: int
    party_id: int
    side: CommitmentSide
    text: str
    due_date: datetime | None = None
    status: CommitmentStatus
    meeting_id: int | None = None
    delegated_to: str | None = None


class AgreedTerm(BaseModel):
    id: int
    party_id: int
    kind: str
    value: str
    agreed_date: datetime
    source: str = ""
    confirmed_by_owner: bool


class TeamMember(BaseModel):
    id: int
    name: str
    role: str = ""


class ContactEvent(BaseModel):
    id: int
    party_id: int
    kind: str
    contact_date: datetime
    reference: str = ""


class MeetingTranscript(BaseModel):
    id: int
    meeting_id: int
    transcript_text: str
    source: TranscriptSource
    transcribed_at: datetime
    credits_consumed: int | None = None


# ─── Migrations ──────────────────────────────────────────────────────

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE parties (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL,
            domain       TEXT    NOT NULL UNIQUE,
            note         TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL
        );

        CREATE TABLE people (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id     INTEGER NOT NULL REFERENCES parties(id),
            name         TEXT    NOT NULL,
            email        TEXT    NOT NULL UNIQUE,
            role         TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL
        );

        CREATE TABLE meetings (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            calendar_id   TEXT    NOT NULL UNIQUE,
            party_id      INTEGER          REFERENCES parties(id),
            meeting_date  TEXT    NOT NULL,
            title         TEXT    NOT NULL,
            attendees     TEXT    NOT NULL DEFAULT '[]',
            created_at    TEXT    NOT NULL
        );

        CREATE TABLE commitments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id     INTEGER NOT NULL REFERENCES parties(id),
            side         TEXT    NOT NULL CHECK(side IN ('us','them')),
            text         TEXT    NOT NULL,
            due_date     TEXT,
            status       TEXT    NOT NULL DEFAULT 'open'
                                 CHECK(status IN ('open','done','cancelled')),
            meeting_id   INTEGER          REFERENCES meetings(id),
            created_at   TEXT    NOT NULL,
            updated_at   TEXT    NOT NULL
        );

        CREATE TABLE agreed_terms (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id             INTEGER NOT NULL REFERENCES parties(id),
            kind                 TEXT    NOT NULL,
            value                TEXT    NOT NULL,
            agreed_date          TEXT    NOT NULL,
            source               TEXT    NOT NULL DEFAULT '',
            confirmed_by_owner   INTEGER NOT NULL DEFAULT 0,
            created_at           TEXT    NOT NULL
        );

        CREATE TABLE contacts_log (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id       INTEGER NOT NULL REFERENCES parties(id),
            kind           TEXT    NOT NULL,
            contact_date   TEXT    NOT NULL,
            reference      TEXT    NOT NULL DEFAULT '',
            created_at     TEXT    NOT NULL
        );

        CREATE INDEX ix_people_party      ON people(party_id);
        CREATE INDEX ix_meetings_party    ON meetings(party_id);
        CREATE INDEX ix_commitments_party ON commitments(party_id, status);
        CREATE INDEX ix_terms_party       ON agreed_terms(party_id);
        CREATE INDEX ix_contacts_party    ON contacts_log(party_id, contact_date);
        """,
    ),
    (
        2,
        # v2: anti-duplicate table for scheduled briefs. The 15-minute
        # cron pulse re-queries the same meeting-window several times;
        # without this table the same brief would land on Telegram five
        # times. `meeting_id` is the Google Calendar event id, and it's
        # PRIMARY KEY so a second insert for the same meeting fails
        # loudly — the caller checks `has_brief_been_sent` first.
        """
        CREATE TABLE sent_briefs (
            meeting_id   TEXT    PRIMARY KEY,
            sent_at      TEXT    NOT NULL
        );
        """,
    ),
    (
        3,
        # v3: raw transcripts (P21), once a real bot + transcription
        # engine produces one. Storage only — no automatic extraction of
        # commitments or terms from the text here. That's deliberately a
        # separate later step: it needs the same scrutiny as the
        # confirmed_by_owner rule on agreed_terms, and folding it into
        # ingestion would smuggle unconfirmed facts in as a side effect
        # of storage.
        """
        CREATE TABLE meeting_transcripts (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id         INTEGER NOT NULL REFERENCES meetings(id),
            transcript_text    TEXT    NOT NULL,
            source             TEXT    NOT NULL
                                       CHECK(source IN ('munsit','elevenlabs','manual')),
            transcribed_at     TEXT    NOT NULL,
            credits_consumed   INTEGER,
            created_at         TEXT    NOT NULL
        );

        CREATE INDEX ix_transcripts_meeting ON meeting_transcripts(meeting_id);
        """,
    ),
    (
        4,
        # v4: anti-duplicate table for bot dispatch (P21), mirroring
        # sent_briefs exactly — same reason: a 15-minute cron pulse
        # re-querying the same meeting-window must not send a second
        # bot to a meeting it already sent one to. Unlike sent_briefs,
        # this needs a row id to update later (bot_id/status arrive
        # after the initial request), so meeting_id is UNIQUE rather
        # than the primary key itself. The caller checks
        # has_bot_been_requested before mark_bot_requested, same
        # calling convention as has_brief_been_sent.
        """
        CREATE TABLE sent_bots (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id     TEXT    NOT NULL UNIQUE,
            bot_id         TEXT,
            requested_at   TEXT    NOT NULL,
            status         TEXT    NOT NULL DEFAULT 'requested'
                                   CHECK(status IN ('requested','completed','failed')),
            updated_at     TEXT    NOT NULL
        );
        """,
    ),
    (
        5,
        # v5: anti-duplicate table for the daily overdue-commitment chase
        # (P17), same shape and reason as sent_briefs/sent_bots — a cron
        # that pulses more than once a day must not send the digest
        # twice. The key here is the calendar date itself rather than a
        # meeting_id, since a chase isn't tied to any one meeting.
        """
        CREATE TABLE chase_sent_log (
            chase_date   TEXT PRIMARY KEY,
            sent_at      TEXT NOT NULL
        );
        """,
    ),
    (
        6,
        # v6: a local team roster for delegation (P14/delegation.py).
        # sim-agent has its own `employee_links` table, but that's a
        # different concept entirely (Telegram id <-> company user id,
        # for gating outbound notifications) living in a different
        # database — README.dev.md's "Boundary from sim-agent" forbids
        # this profile from reading the other's storage, so this is a
        # genuinely separate, simple roster, not a shortcut around that
        # boundary.
        """
        CREATE TABLE team_members (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL UNIQUE,
            role         TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL
        );
        """,
    ),
    (
        7,
        # v7: delegation.py records who a commitment was handed to
        # directly on the commitment row — a nullable column rather than
        # a separate table, since a commitment has at most one current
        # delegate and the history of past delegations isn't tracked yet
        # (same "store the current fact, not the log" scope as every
        # other single-value column on this table).
        """
        ALTER TABLE commitments ADD COLUMN delegated_to TEXT;
        """,
    ),
]


# ─── Connection and migration runner ─────────────────────────────────


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open the DB, apply any pending migrations, yield the connection.

    Rows come back as `sqlite3.Row` so callers can `row["column"]`
    instead of positional indexing. FKs are enforced — a naked SQLite
    connection has them off by default.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _run_migrations(conn)
        yield conn
    finally:
        conn.close()


def _run_migrations(conn: sqlite3.Connection) -> None:
    # `executescript` manages its own transaction and commits on success;
    # in autocommit mode (`isolation_level=None`) that's the right shape.
    # `user_version` is bumped only after the script succeeds, so a
    # failed partial migration is retried on the next open.
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        conn.executescript(sql)
        conn.execute(f"PRAGMA user_version = {version}")


# ─── Writers ─────────────────────────────────────────────────────────


def upsert_party(
    conn: sqlite3.Connection, *, name: str, domain: str, now: datetime, note: str = ""
) -> Party:
    """Insert or fetch by domain — the domain is the natural key."""
    domain = domain.lower().strip()
    row = conn.execute("SELECT * FROM parties WHERE domain = ?", (domain,)).fetchone()
    if row:
        return _party_from_row(row)
    cur = conn.execute(
        "INSERT INTO parties(name, domain, note, created_at) VALUES(?,?,?,?)",
        (name, domain, note, _iso(now)),
    )
    return Party(id=int(cur.lastrowid or 0), name=name, domain=domain, note=note)


def upsert_team_member(
    conn: sqlite3.Connection, *, name: str, role: str, now: datetime
) -> TeamMember:
    """Insert or fetch by name — the same "natural key, idempotent insert"
    shape as `upsert_party`."""
    row = conn.execute("SELECT * FROM team_members WHERE name = ?", (name,)).fetchone()
    if row:
        return _team_member_from_row(row)
    cur = conn.execute(
        "INSERT INTO team_members(name, role, created_at) VALUES(?,?,?)",
        (name, role, _iso(now)),
    )
    return TeamMember(id=int(cur.lastrowid or 0), name=name, role=role)


def upsert_person(
    conn: sqlite3.Connection,
    *,
    party_id: int,
    name: str,
    email: str,
    role: str = "",
    now: datetime,
) -> Person:
    email = email.lower().strip()
    row = conn.execute("SELECT * FROM people WHERE email = ?", (email,)).fetchone()
    if row:
        return _person_from_row(row)
    cur = conn.execute(
        "INSERT INTO people(party_id, name, email, role, created_at) VALUES(?,?,?,?,?)",
        (party_id, name, email, role, _iso(now)),
    )
    return Person(id=int(cur.lastrowid or 0), party_id=party_id, name=name, email=email, role=role)


def record_meeting(
    conn: sqlite3.Connection,
    *,
    calendar_id: str,
    party_id: int | None,
    meeting_date: datetime,
    title: str,
    attendees: list[str],
    now: datetime,
) -> MeetingRow:
    row = conn.execute(
        "SELECT * FROM meetings WHERE calendar_id = ?", (calendar_id,)
    ).fetchone()
    if row:
        return _meeting_from_row(row)
    cur = conn.execute(
        "INSERT INTO meetings(calendar_id, party_id, meeting_date, title, attendees, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (calendar_id, party_id, _iso(meeting_date), title, json.dumps(attendees), _iso(now)),
    )
    return MeetingRow(
        id=int(cur.lastrowid or 0),
        calendar_id=calendar_id,
        party_id=party_id,
        meeting_date=meeting_date,
        title=title,
        attendees=list(attendees),
    )


def add_commitment(
    conn: sqlite3.Connection,
    *,
    party_id: int,
    side: CommitmentSide,
    text: str,
    due_date: datetime | None,
    meeting_id: int | None,
    now: datetime,
) -> Commitment:
    cur = conn.execute(
        "INSERT INTO commitments"
        "(party_id, side, text, due_date, status, meeting_id, created_at, updated_at)"
        " VALUES(?,?,?,?,'open',?,?,?)",
        (party_id, side, text, _iso(due_date), meeting_id, _iso(now), _iso(now)),
    )
    return Commitment(
        id=int(cur.lastrowid or 0),
        party_id=party_id,
        side=side,
        text=text,
        due_date=due_date,
        status="open",
        meeting_id=meeting_id,
    )


def set_commitment_status(
    conn: sqlite3.Connection,
    *,
    commitment_id: int,
    status: CommitmentStatus,
    now: datetime,
) -> None:
    conn.execute(
        "UPDATE commitments SET status = ?, updated_at = ? WHERE id = ?",
        (status, _iso(now), commitment_id),
    )


def add_agreed_term(
    conn: sqlite3.Connection,
    *,
    party_id: int,
    kind: str,
    value: str,
    agreed_date: datetime,
    source: str,
    confirmed_by_owner: bool,
    now: datetime,
) -> AgreedTerm:
    cur = conn.execute(
        "INSERT INTO agreed_terms"
        "(party_id, kind, value, agreed_date, source, confirmed_by_owner, created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (
            party_id,
            kind,
            value,
            _iso(agreed_date),
            source,
            1 if confirmed_by_owner else 0,
            _iso(now),
        ),
    )
    return AgreedTerm(
        id=int(cur.lastrowid or 0),
        party_id=party_id,
        kind=kind,
        value=value,
        agreed_date=agreed_date,
        source=source,
        confirmed_by_owner=confirmed_by_owner,
    )


def log_contact(
    conn: sqlite3.Connection,
    *,
    party_id: int,
    kind: str,
    contact_date: datetime,
    reference: str,
    now: datetime,
) -> ContactEvent:
    cur = conn.execute(
        "INSERT INTO contacts_log(party_id, kind, contact_date, reference, created_at)"
        " VALUES(?,?,?,?,?)",
        (party_id, kind, _iso(contact_date), reference, _iso(now)),
    )
    return ContactEvent(
        id=int(cur.lastrowid or 0),
        party_id=party_id,
        kind=kind,
        contact_date=contact_date,
        reference=reference,
    )


def store_transcript(
    conn: sqlite3.Connection,
    *,
    meeting_id: int,
    transcript_text: str,
    source: TranscriptSource,
    now: datetime,
    credits_consumed: int | None = None,
) -> None:
    """Store a transcript against `meeting_id`. Pure storage — no parsing,
    no extraction. See the v3 migration comment for why that's deferred.
    """
    conn.execute(
        "INSERT INTO meeting_transcripts"
        "(meeting_id, transcript_text, source, transcribed_at, credits_consumed, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (meeting_id, transcript_text, source, _iso(now), credits_consumed, _iso(now)),
    )


# ─── Sent-brief anti-duplicate ───────────────────────────────────────


def has_brief_been_sent(conn: sqlite3.Connection, meeting_id: str) -> bool:
    """True iff a scheduled brief for this meeting_id already went out.

    Called by the cron job before it queues a delivery, so a 15-minute
    pulse re-firing over the same 45–75-min window does not send the
    same brief five times.
    """
    row = conn.execute(
        "SELECT 1 FROM sent_briefs WHERE meeting_id = ?", (meeting_id,)
    ).fetchone()
    return row is not None


def mark_brief_sent(conn: sqlite3.Connection, *, meeting_id: str, now: datetime) -> None:
    """Record that the brief for `meeting_id` was delivered at `now`.

    Idempotent: a second call for the same meeting_id is a no-op
    (`INSERT OR IGNORE`), so a caller that crashes between delivery and
    marking, then retries, does not double-record.
    """
    conn.execute(
        "INSERT OR IGNORE INTO sent_briefs(meeting_id, sent_at) VALUES(?,?)",
        (meeting_id, _iso(now)),
    )


# ─── Sent-bot anti-duplicate (P21) ────────────────────────────────────


def has_bot_been_requested(conn: sqlite3.Connection, meeting_id: str) -> bool:
    """True iff a Meeting BaaS bot was already requested for this meeting_id.

    Called by the orchestrator before it dispatches a bot, mirroring
    `has_brief_been_sent` — a re-firing cron pulse must not send a
    second bot to a meeting it already sent one to.
    """
    row = conn.execute(
        "SELECT 1 FROM sent_bots WHERE meeting_id = ?", (meeting_id,)
    ).fetchone()
    return row is not None


def mark_bot_requested(conn: sqlite3.Connection, *, meeting_id: str, now: datetime) -> int:
    """Record that a bot was requested for `meeting_id`; return the row id.

    The caller checks `has_bot_been_requested` first — unlike
    `mark_brief_sent`, this is not `INSERT OR IGNORE`: `meeting_id` is
    UNIQUE, so a second call for the same meeting fails loudly rather
    than silently returning a stale id. The returned row id is used
    later by `update_bot_status` once `bot_id` and a final status are
    known.
    """
    cur = conn.execute(
        "INSERT INTO sent_bots(meeting_id, requested_at, status, updated_at)"
        " VALUES(?,?,'requested',?)",
        (meeting_id, _iso(now), _iso(now)),
    )
    return int(cur.lastrowid or 0)


def update_bot_status(
    conn: sqlite3.Connection,
    *,
    request_id: int,
    bot_id: str | None,
    status: BotRequestStatus,
    now: datetime,
) -> None:
    """Update the `sent_bots` row `request_id` with `bot_id` and `status`."""
    conn.execute(
        "UPDATE sent_bots SET bot_id = ?, status = ?, updated_at = ? WHERE id = ?",
        (bot_id, status, _iso(now), request_id),
    )


# ─── Daily chase anti-duplicate (P17) ──────────────────────────────────


def has_chase_been_sent_today(conn: sqlite3.Connection, now: datetime) -> bool:
    """True iff the overdue-commitment chase already went out for `now`'s
    calendar date. Mirrors `has_brief_been_sent`."""
    row = conn.execute(
        "SELECT 1 FROM chase_sent_log WHERE chase_date = ?", (now.date().isoformat(),)
    ).fetchone()
    return row is not None


def mark_chase_sent(conn: sqlite3.Connection, *, now: datetime) -> None:
    """Record that the chase for `now`'s calendar date was sent.

    Idempotent (`INSERT OR IGNORE`), same rationale as `mark_brief_sent`:
    a caller that crashes between building the message and marking it
    sent, then retries, must not double-record.
    """
    conn.execute(
        "INSERT OR IGNORE INTO chase_sent_log(chase_date, sent_at) VALUES(?,?)",
        (now.date().isoformat(), _iso(now)),
    )


# ─── Readers ─────────────────────────────────────────────────────────


def party_for_domain(conn: sqlite3.Connection, domain: str) -> Party | None:
    row = conn.execute("SELECT * FROM parties WHERE domain = ?", (domain.lower(),)).fetchone()
    return _party_from_row(row) if row else None


def list_team_members(conn: sqlite3.Connection) -> list[TeamMember]:
    """Every team member on record, alphabetical by name."""
    rows = conn.execute("SELECT * FROM team_members ORDER BY name").fetchall()
    return [_team_member_from_row(r) for r in rows]


def open_commitments(conn: sqlite3.Connection, party_id: int) -> list[Commitment]:
    """All commitments with status = 'open', ordered by due date (nulls last)."""
    rows = conn.execute(
        "SELECT * FROM commitments"
        " WHERE party_id = ? AND status = 'open'"
        " ORDER BY due_date IS NULL, due_date ASC, id ASC",
        (party_id,),
    ).fetchall()
    return [_commitment_from_row(r) for r in rows]


def agreed_terms(conn: sqlite3.Connection, party_id: int) -> list[AgreedTerm]:
    """All terms for a party — each carries its own `confirmed_by_owner`.

    Callers MUST NOT drop the flag; the render layer decides how to
    surface a `confirmed_by_owner = False` term (typically as "غير مؤكد"),
    but it never becomes an unqualified fact.
    """
    rows = conn.execute(
        "SELECT * FROM agreed_terms WHERE party_id = ? ORDER BY agreed_date DESC",
        (party_id,),
    ).fetchall()
    return [_term_from_row(r) for r in rows]


def last_contact(conn: sqlite3.Connection, party_id: int) -> ContactEvent | None:
    row = conn.execute(
        "SELECT * FROM contacts_log WHERE party_id = ? ORDER BY contact_date DESC LIMIT 1",
        (party_id,),
    ).fetchone()
    return _contact_from_row(row) if row else None


def recent_meetings(conn: sqlite3.Connection, party_id: int, limit: int = 5) -> list[MeetingRow]:
    rows = conn.execute(
        "SELECT * FROM meetings WHERE party_id = ? ORDER BY meeting_date DESC LIMIT ?",
        (party_id, limit),
    ).fetchall()
    return [_meeting_from_row(r) for r in rows]


def get_transcript(conn: sqlite3.Connection, meeting_id: int) -> str | None:
    """The most recent transcript text stored for `meeting_id`, or `None`."""
    row = conn.execute(
        "SELECT transcript_text FROM meeting_transcripts"
        " WHERE meeting_id = ? ORDER BY transcribed_at DESC LIMIT 1",
        (meeting_id,),
    ).fetchone()
    return row["transcript_text"] if row else None


# ─── Row → model helpers ─────────────────────────────────────────────


def _party_from_row(row: sqlite3.Row) -> Party:
    return Party(id=row["id"], name=row["name"], domain=row["domain"], note=row["note"] or "")


def _team_member_from_row(row: sqlite3.Row) -> TeamMember:
    return TeamMember(id=row["id"], name=row["name"], role=row["role"] or "")


def _person_from_row(row: sqlite3.Row) -> Person:
    return Person(
        id=row["id"],
        party_id=row["party_id"],
        name=row["name"],
        email=row["email"],
        role=row["role"] or "",
    )


def _meeting_from_row(row: sqlite3.Row) -> MeetingRow:
    return MeetingRow(
        id=row["id"],
        calendar_id=row["calendar_id"],
        party_id=row["party_id"],
        meeting_date=_parse_iso(row["meeting_date"]),
        title=row["title"],
        attendees=json.loads(row["attendees"] or "[]"),
    )


def _commitment_from_row(row: sqlite3.Row) -> Commitment:
    return Commitment(
        id=row["id"],
        party_id=row["party_id"],
        side=row["side"],
        text=row["text"],
        due_date=_parse_iso(row["due_date"]) if row["due_date"] else None,
        status=row["status"],
        meeting_id=row["meeting_id"],
        delegated_to=row["delegated_to"],
    )


def _term_from_row(row: sqlite3.Row) -> AgreedTerm:
    return AgreedTerm(
        id=row["id"],
        party_id=row["party_id"],
        kind=row["kind"],
        value=row["value"],
        agreed_date=_parse_iso(row["agreed_date"]),
        source=row["source"] or "",
        confirmed_by_owner=bool(row["confirmed_by_owner"]),
    )


def _contact_from_row(row: sqlite3.Row) -> ContactEvent:
    return ContactEvent(
        id=row["id"],
        party_id=row["party_id"],
        kind=row["kind"],
        contact_date=_parse_iso(row["contact_date"]),
        reference=row["reference"] or "",
    )


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat()


def _parse_iso(s: str | Any) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)
