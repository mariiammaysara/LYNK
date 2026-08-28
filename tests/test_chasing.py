"""chasing.py — pure ledger logic, no LLM, no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rel_mcp.chasing import (
    build_daily_chase_message,
    get_overdue_commitments,
    prepare_daily_chase_message,
)
from rel_mcp.ledger import add_commitment, connect, upsert_party

NOW = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


# ─── get_overdue_commitments ────────────────────────────────────────────


def test_get_overdue_commitments_returns_only_open_past_due_items(db_path: Path) -> None:
    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Najd", domain="najd.example", now=NOW)

        overdue_old = add_commitment(
            ledger, party_id=party.id, side="them", text="الأقدم تأخرًا",
            due_date=NOW - timedelta(days=10), meeting_id=None, now=NOW,
        )
        overdue_recent = add_commitment(
            ledger, party_id=party.id, side="us", text="الأحدث تأخرًا",
            due_date=NOW - timedelta(days=1), meeting_id=None, now=NOW,
        )
        # Not overdue — due in the future.
        add_commitment(
            ledger, party_id=party.id, side="them", text="لسه مش مستحق",
            due_date=NOW + timedelta(days=5), meeting_id=None, now=NOW,
        )
        # No due date at all — never counts as overdue.
        add_commitment(
            ledger, party_id=party.id, side="us", text="من غير تاريخ استحقاق",
            due_date=None, meeting_id=None, now=NOW,
        )

        result = get_overdue_commitments(ledger, NOW)

    assert [c.id for c in result] == [overdue_old.id, overdue_recent.id]


def test_get_overdue_commitments_empty_when_nothing_is_overdue(db_path: Path) -> None:
    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Najd", domain="najd2.example", now=NOW)
        add_commitment(
            ledger, party_id=party.id, side="them", text="لسه مش مستحق",
            due_date=NOW + timedelta(days=1), meeting_id=None, now=NOW,
        )

        result = get_overdue_commitments(ledger, NOW)

    assert result == []


def test_get_overdue_commitments_excludes_done_items(db_path: Path) -> None:
    from rel_mcp.ledger import set_commitment_status

    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Najd", domain="najd3.example", now=NOW)
        done = add_commitment(
            ledger, party_id=party.id, side="them", text="اتقفل بالفعل",
            due_date=NOW - timedelta(days=3), meeting_id=None, now=NOW,
        )
        set_commitment_status(ledger, commitment_id=done.id, status="done", now=NOW)

        result = get_overdue_commitments(ledger, NOW)

    assert result == []


# ─── build_daily_chase_message ──────────────────────────────────────────


def test_build_daily_chase_message_returns_none_for_empty_list() -> None:
    assert build_daily_chase_message([]) is None


def test_build_daily_chase_message_summarizes_count_and_party_count(db_path: Path) -> None:
    with connect(db_path) as ledger:
        party_a = upsert_party(ledger, name="A", domain="a.example", now=NOW)
        party_b = upsert_party(ledger, name="B", domain="b.example", now=NOW)
        add_commitment(
            ledger, party_id=party_a.id, side="them", text="تسليم العرض",
            due_date=NOW - timedelta(days=2), meeting_id=None, now=NOW,
        )
        add_commitment(
            ledger, party_id=party_b.id, side="us", text="مراجعة العقد",
            due_date=NOW - timedelta(days=5), meeting_id=None, now=NOW,
        )

        overdue = get_overdue_commitments(ledger, NOW)
        text = build_daily_chase_message(overdue)

    assert text is not None
    assert "2" in text  # count
    assert "جهة" in text
    assert "تسليم العرض" in text
    assert "مراجعة العقد" in text
    assert "(عليهم)" in text
    assert "(علينا)" in text


def test_build_daily_chase_message_stays_within_line_cap(db_path: Path) -> None:
    from rel_mcp.render import MAX_LINES

    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Najd", domain="najd4.example", now=NOW)
        for i in range(30):
            add_commitment(
                ledger, party_id=party.id, side="them", text=f"بند {i}",
                due_date=NOW - timedelta(days=1), meeting_id=None, now=NOW,
            )

        overdue = get_overdue_commitments(ledger, NOW)
        text = build_daily_chase_message(overdue)

    assert text is not None
    assert len(text.splitlines()) <= MAX_LINES


# ─── prepare_daily_chase_message (dedup) ────────────────────────────────


def test_prepare_daily_chase_message_none_when_nothing_overdue(db_path: Path) -> None:
    with connect(db_path) as ledger:
        upsert_party(ledger, name="Najd", domain="najd5.example", now=NOW)
        result = prepare_daily_chase_message(ledger, NOW)

    assert result is None


def test_prepare_daily_chase_message_second_call_same_day_is_deduped(db_path: Path) -> None:
    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Najd", domain="najd6.example", now=NOW)
        add_commitment(
            ledger, party_id=party.id, side="them", text="تسليم العرض",
            due_date=NOW - timedelta(days=2), meeting_id=None, now=NOW,
        )

        first = prepare_daily_chase_message(ledger, NOW)
        second = prepare_daily_chase_message(ledger, NOW + timedelta(hours=1))

    assert first is not None
    assert "تسليم العرض" in first
    assert second is None


def test_prepare_daily_chase_message_sends_again_on_a_new_day(db_path: Path) -> None:
    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Najd", domain="najd7.example", now=NOW)
        add_commitment(
            ledger, party_id=party.id, side="them", text="تسليم العرض",
            due_date=NOW - timedelta(days=2), meeting_id=None, now=NOW,
        )

        day_one = prepare_daily_chase_message(ledger, NOW)
        day_two = prepare_daily_chase_message(ledger, NOW + timedelta(days=1))

    assert day_one is not None
    assert day_two is not None
