"""Brief composer and renderer.

Fixtures use ENTIRELY SYNTHETIC data — fake company names, fake emails,
made-up figures. Real calendar and mail data must never end up in a
committed fixture. If a golden diff is unclear, check the fixture, not
the render.

Set `UPDATE_GOLDENS=1` when you deliberately change tone in `phrases.py`:
the run overwrites the golden files, and the diff you commit shows the
tone change explicitly.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rel_mcp.brief import (
    Brief,
    LastContactRef,
    OpenCommitmentRef,
    TermFact,
    ThreadRef,
    build_brief,
)
from rel_mcp.google.calendar import Attendee, Meeting
from rel_mcp.google.gmail import Thread
from rel_mcp.ledger import (
    add_agreed_term,
    add_commitment,
    connect,
    log_contact,
    record_meeting,
    store_transcript,
    upsert_party,
)
from rel_mcp.render import MAX_LINES, render

GOLDENS = Path(__file__).parent / "goldens"
UPDATE = os.environ.get("UPDATE_GOLDENS") == "1"

NOW = datetime(2026, 4, 10, 8, 0, tzinfo=UTC)
LOCAL_TIME = "2026-04-10 12:00"


def _check_golden(name: str, rendered: str) -> None:
    path = GOLDENS / name
    if UPDATE or not path.exists():
        path.write_text(rendered + "\n", encoding="utf-8")
    expected = path.read_text(encoding="utf-8").rstrip("\n")
    assert rendered == expected, (
        f"golden {name} mismatch. If the change is intentional, rerun with "
        f"UPDATE_GOLDENS=1 to regenerate.\n--- expected\n{expected}\n--- got\n{rendered}"
    )


# ─── Render / golden tests ───────────────────────────────────────────


def test_golden_full_brief() -> None:
    brief = Brief(
        meeting_title="مراجعة عرض السعر",
        starts_at_local_iso=LOCAL_TIME,
        is_external=True,
        party_name="شركة الأفق للتقنية",
        attendee_names=["أحمد صالح", "منى القحطانى"],
        last_contact=LastContactRef(kind="email", days_ago=3),
        our_open=[
            OpenCommitmentRef(text="إرسال المسودة المعدّلة", days_to_due=2, overdue=False),
        ],
        their_open=[
            OpenCommitmentRef(text="ردّ فريقهم على البنود الفنية", days_to_due=5, overdue=False),
        ],
        terms=[
            TermFact(kind="سعر", value="180,000 ريال", confirmed=True),
        ],
        threads=[
            ThreadRef(subject="عرض السعر النهائى", days_ago=3),
            ThreadRef(subject="أسئلة على البنود الفنية", days_ago=7),
        ],
        suggested_questions=[
            "متى «ردّ فريقهم على البنود الفنية»؟",
        ],
    )
    _check_golden("brief_full.txt", render(brief))


def test_golden_new_party_brief() -> None:
    brief = Brief(
        meeting_title="لقاء تعارف",
        starts_at_local_iso=LOCAL_TIME,
        is_external=True,
        party_name=None,
        attendee_names=["ياسر الرشيدى"],
        threads=[],
        suggested_questions=[
            "الجهة والدور — تعارف مختصر",
            "الهدف من الاجتماع من وجهة نظرهم",
            "الخطوة الجاية بعد الاجتماع",
        ],
        flags=["new_party"],
    )
    _check_golden("brief_new_party.txt", render(brief))


def test_golden_brief_with_overdue() -> None:
    brief = Brief(
        meeting_title="متابعة المشروع",
        starts_at_local_iso=LOCAL_TIME,
        is_external=True,
        party_name="مؤسسة النجد للاستشارات",
        attendee_names=["فيصل العمر"],
        last_contact=LastContactRef(kind="meeting", days_ago=21),
        our_open=[
            OpenCommitmentRef(text="مراجعة العقد", days_to_due=-4, overdue=True),
        ],
        their_open=[
            OpenCommitmentRef(text="تسليم دراسة السوق", days_to_due=-9, overdue=True),
        ],
        suggested_questions=[
            "موقف «تسليم دراسة السوق» — متأخر من متى؟",
            "«مراجعة العقد» — لسه علينا، حالته إيه؟",
        ],
        flags=["has_overdue"],
    )
    _check_golden("brief_overdue.txt", render(brief))


def test_golden_brief_with_unconfirmed_terms() -> None:
    brief = Brief(
        meeting_title="تفاوض على السعر",
        starts_at_local_iso=LOCAL_TIME,
        is_external=True,
        party_name="مجموعة الرواد التجارية",
        attendee_names=["سارة الغامدى"],
        terms=[
            TermFact(kind="سعر", value="220,000 ريال", confirmed=False),
            TermFact(kind="نسبة", value="12%", confirmed=False),
            TermFact(kind="مدة", value="6 أشهر", confirmed=True),
        ],
        suggested_questions=[
            "تأكيد سعر: 220,000 ريال",
            "تأكيد نسبة: 12%",
        ],
        flags=["unconfirmed_terms"],
    )
    _check_golden("brief_unconfirmed_terms.txt", render(brief))


def test_golden_brief_with_recent_transcript() -> None:
    brief = Brief(
        meeting_title="متابعة المشروع",
        starts_at_local_iso=LOCAL_TIME,
        is_external=True,
        party_name="مؤسسة الرافد للتجارة",
        attendee_names=["خالد المطيرى"],
        has_recent_transcript=True,
    )
    _check_golden("brief_recent_transcript.txt", render(brief))


# ─── Render structural tests ─────────────────────────────────────────


def test_render_respects_line_cap() -> None:
    huge = Brief(
        meeting_title="Long",
        starts_at_local_iso=LOCAL_TIME,
        is_external=True,
        party_name="X",
        attendee_names=[f"person{i}" for i in range(50)],
        our_open=[OpenCommitmentRef(text=f"c{i}", days_to_due=1) for i in range(20)],
        their_open=[OpenCommitmentRef(text=f"c{i}", days_to_due=1) for i in range(20)],
    )
    lines = render(huge).splitlines()
    assert len(lines) <= MAX_LINES


def test_empty_sections_are_dropped_not_padded() -> None:
    minimal = Brief(
        meeting_title="مكالمة",
        starts_at_local_iso=LOCAL_TIME,
        is_external=True,
        party_name="شركة تجربة",
        attendee_names=["مسؤول"],
        # no last_contact, no commitments, no terms, no threads, no questions
    )
    rendered = render(minimal)
    assert "علينا" not in rendered
    assert "عليهم" not in rendered
    assert "متفق" not in rendered
    assert "الثريدات" not in rendered
    assert "أسئلة" not in rendered
    # But the header, party, and attendees are all present:
    assert "شركة تجربة" in rendered
    assert "مسؤول" in rendered


def test_external_marker_used_for_external_meetings() -> None:
    brief = Brief(
        meeting_title="x",
        starts_at_local_iso=LOCAL_TIME,
        is_external=True,
        party_name="Y",
    )
    assert "[خارجى]" in render(brief)


def test_internal_marker_used_for_internal_meetings() -> None:
    brief = Brief(
        meeting_title="x",
        starts_at_local_iso=LOCAL_TIME,
        is_external=False,
    )
    assert "[داخلى]" in render(brief)


# ─── Composer tests — build_brief pulls from ledger correctly ────────


@pytest.fixture
def synthetic_meeting() -> Meeting:
    return Meeting(
        id="cal-1",
        title="مراجعة العرض",
        start_utc=NOW + timedelta(hours=1),
        end_utc=NOW + timedelta(hours=2),
        attendees=[
            Attendee(email="counter@vendorx.example", name="محمد كامل", response="accepted"),
        ],
        description="",
        meet_link=None,
        is_external=True,
    )


def test_build_brief_returns_new_party_when_ledger_empty(
    tmp_path: Path, synthetic_meeting: Meeting
) -> None:
    with connect(tmp_path / "s.db") as ledger:
        brief = build_brief(
            meeting=synthetic_meeting,
            ledger=ledger,
            threads=[],
            now=NOW,
            starts_at_local_iso=LOCAL_TIME,
        )
    assert brief.party_name is None
    assert "new_party" in brief.flags
    assert len(brief.suggested_questions) == 3


def test_build_brief_pulls_open_commitments_by_side(
    tmp_path: Path, synthetic_meeting: Meeting
) -> None:
    with connect(tmp_path / "s.db") as ledger:
        p = upsert_party(ledger, name="شركة X", domain="vendorx.example", now=NOW)
        add_commitment(
            ledger,
            party_id=p.id,
            side="us",
            text="عمل تجربة",
            due_date=NOW + timedelta(days=3),
            meeting_id=None,
            now=NOW,
        )
        add_commitment(
            ledger,
            party_id=p.id,
            side="them",
            text="ردّ نهائى",
            due_date=NOW - timedelta(days=2),  # overdue
            meeting_id=None,
            now=NOW,
        )

        brief = build_brief(
            meeting=synthetic_meeting,
            ledger=ledger,
            threads=[],
            now=NOW,
            starts_at_local_iso=LOCAL_TIME,
        )

    assert brief.party_name == "شركة X"
    assert [c.text for c in brief.our_open] == ["عمل تجربة"]
    assert [c.text for c in brief.their_open] == ["ردّ نهائى"]
    assert brief.their_open[0].overdue is True
    assert "has_overdue" in brief.flags


def test_build_brief_flags_unconfirmed_terms(
    tmp_path: Path, synthetic_meeting: Meeting
) -> None:
    with connect(tmp_path / "s.db") as ledger:
        p = upsert_party(ledger, name="X", domain="vendorx.example", now=NOW)
        add_agreed_term(
            ledger,
            party_id=p.id,
            kind="سعر",
            value="100k",
            agreed_date=NOW - timedelta(days=1),
            source="email",
            confirmed_by_owner=False,
            now=NOW,
        )
        brief = build_brief(
            meeting=synthetic_meeting,
            ledger=ledger,
            threads=[],
            now=NOW,
            starts_at_local_iso=LOCAL_TIME,
        )
    assert brief.terms[0].confirmed is False
    assert "unconfirmed_terms" in brief.flags


def test_build_brief_includes_last_contact(
    tmp_path: Path, synthetic_meeting: Meeting
) -> None:
    with connect(tmp_path / "s.db") as ledger:
        p = upsert_party(ledger, name="X", domain="vendorx.example", now=NOW)
        log_contact(
            ledger,
            party_id=p.id,
            kind="email",
            contact_date=NOW - timedelta(days=6),
            reference="thread-a",
            now=NOW,
        )
        brief = build_brief(
            meeting=synthetic_meeting,
            ledger=ledger,
            threads=[],
            now=NOW,
            starts_at_local_iso=LOCAL_TIME,
        )
    assert brief.last_contact is not None
    assert brief.last_contact.kind == "email"
    assert brief.last_contact.days_ago == 6


def test_build_brief_flags_recent_transcript_from_prior_meeting(
    tmp_path: Path, synthetic_meeting: Meeting
) -> None:
    with connect(tmp_path / "s.db") as ledger:
        p = upsert_party(ledger, name="X", domain="vendorx.example", now=NOW)
        prior = record_meeting(
            ledger,
            calendar_id="cal-prior",
            party_id=p.id,
            meeting_date=NOW - timedelta(days=7),
            title="اجتماع سابق",
            attendees=[],
            now=NOW,
        )
        store_transcript(
            ledger,
            meeting_id=prior.id,
            transcript_text="نص المحضر",
            source="elevenlabs",
            now=NOW,
        )

        brief = build_brief(
            meeting=synthetic_meeting,
            ledger=ledger,
            threads=[],
            now=NOW,
            starts_at_local_iso=LOCAL_TIME,
        )

    assert brief.has_recent_transcript is True


def test_build_brief_has_recent_transcript_false_without_one(
    tmp_path: Path, synthetic_meeting: Meeting
) -> None:
    with connect(tmp_path / "s.db") as ledger:
        upsert_party(ledger, name="X", domain="vendorx.example", now=NOW)
        brief = build_brief(
            meeting=synthetic_meeting,
            ledger=ledger,
            threads=[],
            now=NOW,
            starts_at_local_iso=LOCAL_TIME,
        )
    assert brief.has_recent_transcript is False


def test_build_brief_takes_top_three_threads(
    tmp_path: Path, synthetic_meeting: Meeting
) -> None:
    with connect(tmp_path / "s.db") as ledger:
        upsert_party(ledger, name="X", domain="vendorx.example", now=NOW)
        threads = [
            Thread(
                id=f"t{i}",
                subject=f"موضوع {i}",
                last_message_at=NOW - timedelta(days=i),
                participants=["counter@vendorx.example"],
                snippet=f"snippet {i}",
                has_attachments=False,
            )
            for i in range(5)
        ]
        brief = build_brief(
            meeting=synthetic_meeting,
            ledger=ledger,
            threads=threads,
            now=NOW,
            starts_at_local_iso=LOCAL_TIME,
        )
    assert [t.subject for t in brief.threads] == ["موضوع 0", "موضوع 1", "موضوع 2"]
