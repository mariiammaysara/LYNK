"""Populate the ledger with entirely synthetic data for demo/testing.

The data here is FAKE — no real company, no real person, no real
number. Two Arabic-named parties with a plausible mix of open
commitments (some overdue), agreed terms (some unconfirmed), and a
prior contact event each. Running this against a fresh state.db lets
you see a rich brief without waiting for real meetings to accumulate.

Safe to re-run: every write is idempotent by natural key (party
domain, calendar_id, email).

RUN WITH:  uv run python scripts/seed_ledger.py
UNDO WITH: rm var/state.db  (then re-run migrations by opening the app)
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from rel_mcp.config import get_settings
from rel_mcp.ledger import (
    add_agreed_term,
    add_commitment,
    connect,
    log_contact,
    open_commitments,
    upsert_party,
    upsert_person,
)


def main() -> int:
    settings = get_settings()
    now = datetime.now(UTC)

    with connect(settings.state_db_path) as ledger:
        # ─── Party 1: شركة الأفق للتقنية ──────────────────
        p1 = upsert_party(
            ledger,
            name="شركة الأفق للتقنية",
            domain="alofoq-tech.example",
            note="مزوّد برمجيات، شغّال معانا من ٢٠٢٤",
            now=now,
        )
        upsert_person(
            ledger,
            party_id=p1.id,
            name="أحمد صالح",
            email="ahmed@alofoq-tech.example",
            role="مدير حسابات",
            now=now,
        )
        add_commitment(
            ledger,
            party_id=p1.id,
            side="us",
            text="إرسال المسودة المعدّلة للعقد",
            due_date=now + timedelta(days=2),
            meeting_id=None,
            now=now,
        )
        add_commitment(
            ledger,
            party_id=p1.id,
            side="them",
            text="ردّ الفريق الفنى على البنود الفنية",
            due_date=now + timedelta(days=5),
            meeting_id=None,
            now=now,
        )
        add_agreed_term(
            ledger,
            party_id=p1.id,
            kind="سعر",
            value="180,000 ريال",
            agreed_date=now - timedelta(days=14),
            source="اجتماع ١٥ يناير",
            confirmed_by_owner=True,
            now=now,
        )
        log_contact(
            ledger,
            party_id=p1.id,
            kind="email",
            contact_date=now - timedelta(days=3),
            reference="thread-alofoq-quote",
            now=now,
        )

        # ─── Party 2: مؤسسة النجد للاستشارات (with overdue + unconfirmed) ──
        p2 = upsert_party(
            ledger,
            name="مؤسسة النجد للاستشارات",
            domain="najd-consulting.example",
            note="استشارات إدارية",
            now=now,
        )
        upsert_person(
            ledger,
            party_id=p2.id,
            name="فيصل العمر",
            email="faisal@najd-consulting.example",
            role="مستشار أول",
            now=now,
        )
        add_commitment(
            ledger,
            party_id=p2.id,
            side="us",
            text="مراجعة مسودة العقد",
            due_date=now - timedelta(days=4),  # overdue by 4 days
            meeting_id=None,
            now=now,
        )
        add_commitment(
            ledger,
            party_id=p2.id,
            side="them",
            text="تسليم دراسة السوق المطلوبة",
            due_date=now - timedelta(days=9),  # overdue by 9 days
            meeting_id=None,
            now=now,
        )
        add_agreed_term(
            ledger,
            party_id=p2.id,
            kind="نسبة",
            value="12%",
            agreed_date=now - timedelta(days=7),
            source="بريد فيصل",
            confirmed_by_owner=False,  # deliberately unconfirmed
            now=now,
        )
        log_contact(
            ledger,
            party_id=p2.id,
            kind="meeting",
            contact_date=now - timedelta(days=21),
            reference="cal-najd-jan",
            now=now,
        )

        print(f"seeded 2 parties into {settings.state_db_path}")
        print(f"  · {p1.name}: {len(open_commitments(ledger, p1.id))} open commitments")
        print(f"  · {p2.name}: {len(open_commitments(ledger, p2.id))} open commitments (متأخر)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
