"""Ledger — schema is created idempotently, and every read/write path
gives back the shape the brief pipeline expects. Every test uses a
temp file DB; `connect()` is a context manager so nothing leaks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rel_mcp.ledger import (
    add_agreed_term,
    add_commitment,
    agreed_terms,
    connect,
    get_transcript,
    has_bot_been_requested,
    has_brief_been_sent,
    last_contact,
    log_contact,
    mark_bot_requested,
    mark_brief_sent,
    open_commitments,
    party_for_domain,
    recent_meetings,
    record_meeting,
    set_commitment_status,
    store_transcript,
    update_bot_status,
    upsert_party,
    upsert_person,
)

T0 = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    with connect(db):
        pass
    with connect(db):
        pass  # must not raise


def test_migrations_create_all_tables(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    with connect(db) as conn:
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {
        "parties",
        "people",
        "meetings",
        "commitments",
        "agreed_terms",
        "contacts_log",
        "sent_bots",
    }.issubset(tables)


def test_upsert_party_is_idempotent_by_domain(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        a = upsert_party(conn, name="Vendor A", domain="vendor.example", now=T0)
        b = upsert_party(conn, name="Vendor A", domain="VENDOR.EXAMPLE", now=T0)
        assert a.id == b.id


def test_party_for_domain_case_insensitive(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        upsert_party(conn, name="X", domain="vendor.example", now=T0)
        found = party_for_domain(conn, "VENDOR.EXAMPLE")
        assert found is not None and found.domain == "vendor.example"


def test_open_commitments_returns_only_open_ordered_by_due(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        p = upsert_party(conn, name="V", domain="v.example", now=T0)
        far = add_commitment(
            conn,
            party_id=p.id,
            side="them",
            text="deliver spec",
            due_date=T0 + timedelta(days=10),
            meeting_id=None,
            now=T0,
        )
        near = add_commitment(
            conn,
            party_id=p.id,
            side="us",
            text="send draft",
            due_date=T0 + timedelta(days=2),
            meeting_id=None,
            now=T0,
        )
        done = add_commitment(
            conn,
            party_id=p.id,
            side="us",
            text="past thing",
            due_date=T0 - timedelta(days=1),
            meeting_id=None,
            now=T0,
        )
        set_commitment_status(conn, commitment_id=done.id, status="done", now=T0)

        opens = open_commitments(conn, p.id)
        assert [c.id for c in opens] == [near.id, far.id]


def test_commitment_without_due_date_comes_last(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        p = upsert_party(conn, name="V", domain="v.example", now=T0)
        no_due = add_commitment(
            conn,
            party_id=p.id,
            side="them",
            text="something",
            due_date=None,
            meeting_id=None,
            now=T0,
        )
        dated = add_commitment(
            conn,
            party_id=p.id,
            side="us",
            text="dated",
            due_date=T0 + timedelta(days=5),
            meeting_id=None,
            now=T0,
        )
        opens = open_commitments(conn, p.id)
        assert [c.id for c in opens] == [dated.id, no_due.id]


def test_agreed_terms_carry_confirmation_flag(tmp_path: Path) -> None:
    """A confirmed=False term must NOT be silently dropped or promoted.
    The render layer decides how to mark it — the query returns both."""
    with connect(tmp_path / "s.db") as conn:
        p = upsert_party(conn, name="V", domain="v.example", now=T0)
        add_agreed_term(
            conn,
            party_id=p.id,
            kind="price",
            value="10000 SAR",
            agreed_date=T0,
            source="email:thread-1",
            confirmed_by_owner=False,
            now=T0,
        )
        add_agreed_term(
            conn,
            party_id=p.id,
            kind="percent",
            value="15%",
            agreed_date=T0 + timedelta(days=1),
            source="meeting:m-2",
            confirmed_by_owner=True,
            now=T0,
        )

        terms = agreed_terms(conn, p.id)
        assert len(terms) == 2
        by_kind = {t.kind: t for t in terms}
        assert by_kind["price"].confirmed_by_owner is False
        assert by_kind["percent"].confirmed_by_owner is True


def test_last_contact_returns_most_recent(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        p = upsert_party(conn, name="V", domain="v.example", now=T0)
        log_contact(
            conn,
            party_id=p.id,
            kind="email",
            contact_date=T0 - timedelta(days=5),
            reference="thread-a",
            now=T0,
        )
        log_contact(
            conn,
            party_id=p.id,
            kind="meeting",
            contact_date=T0 - timedelta(days=1),
            reference="m-1",
            now=T0,
        )
        last = last_contact(conn, p.id)
        assert last is not None
        assert last.reference == "m-1"


def test_last_contact_for_unknown_party_is_none(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        p = upsert_party(conn, name="V", domain="v.example", now=T0)
        assert last_contact(conn, p.id) is None


def test_meeting_record_is_idempotent_by_calendar_id(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        p = upsert_party(conn, name="V", domain="v.example", now=T0)
        first = record_meeting(
            conn,
            calendar_id="cal-1",
            party_id=p.id,
            meeting_date=T0,
            title="Kickoff",
            attendees=["a@v.example"],
            now=T0,
        )
        second = record_meeting(
            conn,
            calendar_id="cal-1",
            party_id=p.id,
            meeting_date=T0,
            title="Kickoff",
            attendees=["a@v.example"],
            now=T0,
        )
        assert first.id == second.id


def test_recent_meetings_ordered_desc_and_limited(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        p = upsert_party(conn, name="V", domain="v.example", now=T0)
        for i in range(5):
            record_meeting(
                conn,
                calendar_id=f"cal-{i}",
                party_id=p.id,
                meeting_date=T0 - timedelta(days=i),
                title=f"m{i}",
                attendees=[],
                now=T0,
            )
        got = recent_meetings(conn, p.id, limit=3)
        assert [m.calendar_id for m in got] == ["cal-0", "cal-1", "cal-2"]


def test_person_upsert_by_email(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        p = upsert_party(conn, name="V", domain="v.example", now=T0)
        a = upsert_person(conn, party_id=p.id, name="A", email="a@v.example", now=T0)
        b = upsert_person(conn, party_id=p.id, name="A", email="A@V.EXAMPLE", now=T0)
        assert a.id == b.id


def test_sent_briefs_anti_duplicate(tmp_path: Path) -> None:
    """A meeting_id can be marked once; asking twice reads back True.
    Re-marking is a no-op — the cron pulse may re-fire, but does not
    double-write."""
    with connect(tmp_path / "s.db") as conn:
        assert has_brief_been_sent(conn, "cal-abc") is False
        mark_brief_sent(conn, meeting_id="cal-abc", now=T0)
        assert has_brief_been_sent(conn, "cal-abc") is True
        # Idempotent — second mark must not raise.
        mark_brief_sent(conn, meeting_id="cal-abc", now=T0 + timedelta(minutes=15))
        rows = conn.execute("SELECT COUNT(*) FROM sent_briefs").fetchone()
        assert rows[0] == 1


def test_has_bot_been_requested_true_after_one_request(tmp_path: Path) -> None:
    """The dedup check the orchestrator relies on: a single
    mark_bot_requested call must make has_bot_been_requested return True
    on every subsequent check for the same meeting_id."""
    with connect(tmp_path / "s.db") as conn:
        assert has_bot_been_requested(conn, "cal-abc") is False
        mark_bot_requested(conn, meeting_id="cal-abc", now=T0)
        assert has_bot_been_requested(conn, "cal-abc") is True
        # Asking again must still read back True — not a one-shot flag.
        assert has_bot_been_requested(conn, "cal-abc") is True


def test_mark_bot_requested_rejects_a_second_request_for_the_same_meeting(
    tmp_path: Path,
) -> None:
    """Unlike mark_brief_sent, this is NOT INSERT OR IGNORE — the caller
    is expected to check has_bot_been_requested first. A direct second
    call fails loudly on the UNIQUE constraint instead of silently
    returning a stale row id."""
    import sqlite3

    with connect(tmp_path / "s.db") as conn:
        mark_bot_requested(conn, meeting_id="cal-abc", now=T0)
        with pytest.raises(sqlite3.IntegrityError):
            mark_bot_requested(conn, meeting_id="cal-abc", now=T0 + timedelta(minutes=15))


def test_mark_bot_requested_returns_the_row_id(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        request_id = mark_bot_requested(conn, meeting_id="cal-abc", now=T0)
        row = conn.execute("SELECT id, status, bot_id FROM sent_bots").fetchone()
        assert row["id"] == request_id
        assert row["status"] == "requested"
        assert row["bot_id"] is None


def test_update_bot_status_sets_bot_id_and_status(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        request_id = mark_bot_requested(conn, meeting_id="cal-abc", now=T0)
        update_bot_status(
            conn,
            request_id=request_id,
            bot_id="db185b97-4059-41c6-b5a8-a25bbe972f88",
            status="completed",
            now=T0 + timedelta(minutes=90),
        )
        row = conn.execute(
            "SELECT bot_id, status FROM sent_bots WHERE id = ?", (request_id,)
        ).fetchone()
        assert row["bot_id"] == "db185b97-4059-41c6-b5a8-a25bbe972f88"
        assert row["status"] == "completed"


def test_get_transcript_returns_none_when_absent(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        p = upsert_party(conn, name="V", domain="v.example", now=T0)
        m = record_meeting(
            conn,
            calendar_id="cal-1",
            party_id=p.id,
            meeting_date=T0,
            title="Kickoff",
            attendees=[],
            now=T0,
        )
        assert get_transcript(conn, m.id) is None


def test_store_transcript_adds_a_retrievable_row(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        p = upsert_party(conn, name="V", domain="v.example", now=T0)
        m = record_meeting(
            conn,
            calendar_id="cal-1",
            party_id=p.id,
            meeting_date=T0,
            title="Kickoff",
            attendees=[],
            now=T0,
        )
        store_transcript(
            conn,
            meeting_id=m.id,
            transcript_text="مرحبا بالجميع",
            source="munsit",
            now=T0,
            credits_consumed=324,
        )
        assert get_transcript(conn, m.id) == "مرحبا بالجميع"


def test_store_transcript_credits_consumed_defaults_to_none(tmp_path: Path) -> None:
    with connect(tmp_path / "s.db") as conn:
        p = upsert_party(conn, name="V", domain="v.example", now=T0)
        m = record_meeting(
            conn,
            calendar_id="cal-1",
            party_id=p.id,
            meeting_date=T0,
            title="Kickoff",
            attendees=[],
            now=T0,
        )
        store_transcript(conn, meeting_id=m.id, transcript_text="نص", source="manual", now=T0)
        row = conn.execute(
            "SELECT credits_consumed FROM meeting_transcripts WHERE meeting_id = ?", (m.id,)
        ).fetchone()
        assert row["credits_consumed"] is None


def test_foreign_key_enforcement(tmp_path: Path) -> None:
    """FKs are enforced — inserting a commitment against a missing party fails."""
    import sqlite3

    with connect(tmp_path / "s.db") as conn, pytest.raises(sqlite3.IntegrityError):
        add_commitment(
            conn,
            party_id=99999,
            side="us",
            text="x",
            due_date=None,
            meeting_id=None,
            now=T0,
        )
