"""delegation.py — pure ledger logic, no sim_mcp call, no network."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rel_mcp.delegation import build_delegation_options, delegate_task
from rel_mcp.errors import DelegationError
from rel_mcp.ledger import add_commitment, connect, upsert_party, upsert_team_member

NOW = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


def _read_audit_lines(audit_log_path: Path) -> list[dict[str, object]]:
    if not audit_log_path.exists():
        return []
    return [json.loads(line) for line in audit_log_path.read_text(encoding="utf-8").splitlines()]


def test_build_delegation_options_lists_team_members_alphabetically(db_path: Path) -> None:
    with connect(db_path) as ledger:
        upsert_team_member(ledger, name="سارة", role="مبيعات", now=NOW)
        upsert_team_member(ledger, name="أحمد", role="تنفيذ", now=NOW)

        options = build_delegation_options("cal-1", ledger)

    assert options == ["أحمد", "سارة"]


def test_build_delegation_options_empty_when_no_team_members(db_path: Path) -> None:
    with connect(db_path) as ledger:
        options = build_delegation_options("cal-1", ledger)

    assert options == []


def test_delegate_task_sets_delegated_to_and_audits(db_path: Path) -> None:
    audit_log_path = db_path.parent / "audit.jsonl"
    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Najd", domain="najd.example", now=NOW)
        commitment = add_commitment(
            ledger, party_id=party.id, side="us", text="تسليم العرض",
            due_date=None, meeting_id=None, now=NOW,
        )

        delegate_task(
            ledger, commitment.id, "أحمد", NOW, audit_log_path=audit_log_path
        )

        row = ledger.execute(
            "SELECT delegated_to FROM commitments WHERE id = ?", (commitment.id,)
        ).fetchone()

    assert row["delegated_to"] == "أحمد"

    lines = _read_audit_lines(audit_log_path)
    entries = [e for e in lines if e["action"] == "task_delegated"]
    assert len(entries) == 1
    assert entries[0]["payload"]["commitment_id"] == commitment.id
    assert entries[0]["payload"]["delegated_to"] == "أحمد"


def test_delegate_task_unknown_commitment_raises_delegation_error(db_path: Path) -> None:
    audit_log_path = db_path.parent / "audit.jsonl"
    with connect(db_path) as ledger, pytest.raises(DelegationError):
        delegate_task(ledger, 999999, "أحمد", NOW, audit_log_path=audit_log_path)

    # A clean failure before any write — no audit entry either.
    assert not audit_log_path.exists()
