"""ingest_transcript is a thin pass-through to store_transcript — no
extraction logic. Verified via the same round-trip get_transcript uses."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rel_mcp.ingest import ingest_transcript
from rel_mcp.ledger import connect, get_transcript, record_meeting, upsert_party

T0 = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


def test_ingest_transcript_stores_via_store_transcript(tmp_path: Path) -> None:
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

        ingest_transcript(conn, m.id, "مرحبا بالجميع", "elevenlabs", T0, credits_consumed=42)

        assert get_transcript(conn, m.id) == "مرحبا بالجميع"


def test_ingest_transcript_defaults_credits_consumed_to_none(tmp_path: Path) -> None:
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

        ingest_transcript(conn, m.id, "نص", "manual", T0)

        row = conn.execute(
            "SELECT credits_consumed FROM meeting_transcripts WHERE meeting_id = ?", (m.id,)
        ).fetchone()
        assert row["credits_consumed"] is None
