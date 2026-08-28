"""weekly_summary.py — pure ledger logic, no LLM, no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rel_mcp.ledger import (
    add_commitment,
    connect,
    log_contact,
    set_commitment_status,
    upsert_party,
)
from rel_mcp.weekly_summary import build_weekly_summary, render_weekly_summary

NOW = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
WITHIN_WEEK = NOW - timedelta(days=2)
OUTSIDE_WEEK = NOW - timedelta(days=10)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


def test_empty_week_reports_no_activity_explicitly(db_path: Path) -> None:
    with connect(db_path) as ledger:
        upsert_party(ledger, name="Najd", domain="najd.example", now=OUTSIDE_WEEK)

        summary = build_weekly_summary(ledger, NOW)
        text = render_weekly_summary(summary)

    assert summary.is_empty is True
    assert summary.parties_contacted == []
    assert summary.closed_commitments == []
    assert summary.new_commitments == []
    assert summary.overdue_commitments == []

    assert "مفيش نشاط الأسبوع ده." in text
    # No section headers over an empty section.
    assert "جهات حصل تواصل معاها" not in text
    assert "التزامات اتقفلت" not in text
    assert "التزامات جديدة" not in text
    assert "متأخر حاليًا" not in text


def test_week_with_varied_activity_populates_every_section(db_path: Path) -> None:
    with connect(db_path) as ledger:
        party_a = upsert_party(ledger, name="جهة أ", domain="a.example", now=OUTSIDE_WEEK)
        party_b = upsert_party(ledger, name="جهة ب", domain="b.example", now=OUTSIDE_WEEK)

        # Contacted within the window.
        log_contact(
            ledger, party_id=party_a.id, kind="email", contact_date=WITHIN_WEEK,
            reference="", now=WITHIN_WEEK,
        )
        # Contacted outside the window — must not appear.
        log_contact(
            ledger, party_id=party_b.id, kind="email", contact_date=OUTSIDE_WEEK,
            reference="", now=OUTSIDE_WEEK,
        )

        # Closed within the window.
        closed_recent = add_commitment(
            ledger, party_id=party_a.id, side="them", text="تسليم العرض",
            due_date=None, meeting_id=None, now=OUTSIDE_WEEK,
        )
        set_commitment_status(
            ledger, commitment_id=closed_recent.id, status="done", now=WITHIN_WEEK
        )
        # Closed outside the window — must not appear.
        closed_old = add_commitment(
            ledger, party_id=party_b.id, side="them", text="قفل قديم خارج النافذة",
            due_date=None, meeting_id=None, now=OUTSIDE_WEEK,
        )
        set_commitment_status(
            ledger, commitment_id=closed_old.id, status="done", now=OUTSIDE_WEEK
        )

        # New within the window.
        add_commitment(
            ledger, party_id=party_b.id, side="us", text="بند جديد",
            due_date=None, meeting_id=None, now=WITHIN_WEEK,
        )
        # New outside the window — must not appear.
        add_commitment(
            ledger, party_id=party_b.id, side="us", text="فتح قديم خارج النافذة",
            due_date=None, meeting_id=None, now=OUTSIDE_WEEK,
        )

        # Currently overdue.
        add_commitment(
            ledger, party_id=party_a.id, side="them", text="بند متأخر",
            due_date=NOW - timedelta(days=3), meeting_id=None, now=OUTSIDE_WEEK,
        )

        summary = build_weekly_summary(ledger, NOW)
        text = render_weekly_summary(summary)

    assert summary.is_empty is False

    assert [p.party_name for p in summary.parties_contacted] == ["جهة أ"]

    assert len(summary.closed_commitments) == 1
    assert summary.closed_commitments[0].text == "تسليم العرض"

    assert len(summary.new_commitments) == 1
    assert summary.new_commitments[0].text == "بند جديد"

    assert len(summary.overdue_commitments) == 1
    assert summary.overdue_commitments[0].text == "بند متأخر"
    assert summary.overdue_commitments[0].days_overdue == 3

    assert "جهة أ" in text
    assert "تسليم العرض" in text
    assert "بند جديد" in text
    assert "بند متأخر" in text
    assert "قفل قديم خارج النافذة" not in text
    assert "فتح قديم خارج النافذة" not in text


def test_render_stays_within_line_cap(db_path: Path) -> None:
    from rel_mcp.weekly_summary import MAX_LINES

    with connect(db_path) as ledger:
        party = upsert_party(ledger, name="Najd", domain="najd2.example", now=OUTSIDE_WEEK)
        for i in range(40):
            add_commitment(
                ledger, party_id=party.id, side="them", text=f"بند {i}",
                due_date=None, meeting_id=None, now=WITHIN_WEEK,
            )

        summary = build_weekly_summary(ledger, NOW)
        text = render_weekly_summary(summary)

    assert len(text.splitlines()) <= MAX_LINES
