"""post_meeting.py — pure ledger logic, no LLM, no network."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rel_mcp.ledger import add_commitment, connect, open_commitments, record_meeting, upsert_party
from rel_mcp.post_meeting import apply_confirmation, build_confirmation_prompt

NOW = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


def _read_audit_lines(audit_log_path: Path) -> list[dict[str, object]]:
    if not audit_log_path.exists():
        return []
    return [json.loads(line) for line in audit_log_path.read_text(encoding="utf-8").splitlines()]


def test_prompt_lists_open_commitments_for_the_party(db_path: Path) -> None:
    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Najd", domain="najd.example", now=NOW)
        meeting = record_meeting(
            ledger,
            calendar_id="cal-1",
            party_id=party.id,
            meeting_date=NOW,
            title="متابعة",
            attendees=["a@najd.example"],
            now=NOW,
        )
        commitment = add_commitment(
            ledger,
            party_id=party.id,
            side="them",
            text="تسليم العرض",
            due_date=None,
            meeting_id=None,  # predates this meeting
            now=NOW,
        )

        prompt = build_confirmation_prompt("cal-1", ledger)

    assert prompt.party_id == party.id
    assert prompt.party_name == "Najd"
    assert len(prompt.items) == 1
    assert prompt.items[0].commitment_id == commitment.id
    assert prompt.items[0].text == "تسليم العرض"
    assert prompt.items[0].side == "them"
    assert meeting.calendar_id == "cal-1"


def test_prompt_is_empty_for_party_with_no_commitments(db_path: Path) -> None:
    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Alofoq", domain="alofoq.example", now=NOW)
        record_meeting(
            ledger,
            calendar_id="cal-2",
            party_id=party.id,
            meeting_date=NOW,
            title="أول اجتماع",
            attendees=[],
            now=NOW,
        )

        prompt = build_confirmation_prompt("cal-2", ledger)

    assert prompt.items == []


def test_prompt_is_empty_when_meeting_not_recorded_in_ledger(db_path: Path) -> None:
    with connect(db_path) as ledger:
        prompt = build_confirmation_prompt("cal-never-seen", ledger)

    assert prompt.items == []
    assert prompt.party_id is None


def test_prompt_excludes_commitments_created_in_this_same_meeting(db_path: Path) -> None:
    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Najd", domain="najd2.example", now=NOW)
        meeting = record_meeting(
            ledger,
            calendar_id="cal-3",
            party_id=party.id,
            meeting_date=NOW,
            title="متابعة",
            attendees=[],
            now=NOW,
        )
        # Predates this meeting — should be asked about.
        carry_over = add_commitment(
            ledger,
            party_id=party.id,
            side="us",
            text="مراجعة العقد",
            due_date=None,
            meeting_id=None,
            now=NOW,
        )
        # Created in this very meeting — must not be asked about.
        add_commitment(
            ledger,
            party_id=party.id,
            side="us",
            text="بند اتسجل فى نفس الاجتماع",
            due_date=None,
            meeting_id=meeting.id,
            now=NOW,
        )

        prompt = build_confirmation_prompt("cal-3", ledger)

    assert len(prompt.items) == 1
    assert prompt.items[0].commitment_id == carry_over.id


def test_apply_confirmation_resolved_true_marks_commitment_done(db_path: Path) -> None:
    audit_log_path = db_path.parent / "audit.jsonl"
    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Najd", domain="najd3.example", now=NOW)
        commitment = add_commitment(
            ledger,
            party_id=party.id,
            side="them",
            text="تسليم دراسة",
            due_date=None,
            meeting_id=None,
            now=NOW,
        )

        apply_confirmation(
            ledger, commitment.id, True, NOW, audit_log_path=audit_log_path
        )

        remaining = open_commitments(ledger, party.id)

    assert remaining == []

    lines = _read_audit_lines(audit_log_path)
    entries = [e for e in lines if e["action"] == "post_meeting_confirmation"]
    assert len(entries) == 1
    assert entries[0]["payload"]["resolved"] is True
    assert entries[0]["payload"]["new_status"] == "done"
    assert entries[0]["payload"]["commitment_id"] == commitment.id


def test_apply_confirmation_resolved_false_leaves_commitment_open(db_path: Path) -> None:
    audit_log_path = db_path.parent / "audit.jsonl"
    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Najd", domain="najd4.example", now=NOW)
        commitment = add_commitment(
            ledger,
            party_id=party.id,
            side="them",
            text="تسليم دراسة",
            due_date=None,
            meeting_id=None,
            now=NOW,
        )

        apply_confirmation(
            ledger, commitment.id, False, NOW, audit_log_path=audit_log_path
        )

        remaining = open_commitments(ledger, party.id)

    assert len(remaining) == 1
    assert remaining[0].id == commitment.id
    assert remaining[0].status == "open"

    lines = _read_audit_lines(audit_log_path)
    entries = [e for e in lines if e["action"] == "post_meeting_confirmation"]
    assert len(entries) == 1
    assert entries[0]["payload"]["resolved"] is False
    assert entries[0]["payload"]["new_status"] == "open"
