"""Post-meeting confirmation — deterministic logic only (P14).

## What this module is

After an external meeting ends, the open commitments already on record
for that party are candidates for a one-tap confirmation: "تم" (done) or
"لسه مفتوح" (still open) — see `CONFIRM_OPTION_DONE` /
`CONFIRM_OPTION_STILL_OPEN` in `phrases.py`. `build_confirmation_prompt`
decides *which* commitments belong in that prompt; `apply_confirmation`
applies exactly one tap's result. Neither function accepts free text —
the two-button shape is enforced by `apply_confirmation`'s `resolved:
bool` parameter itself, not by validating a string later.

## What this module is not

It does not render Telegram inline-keyboard buttons and does not talk
to Hermes — that wiring is a later, separate step (the module docstring
this repeats from `meeting_summary.py` and `orchestrator.py`: a pure
decision layer under an approval-gated action layer, never the two
merged). It also never invents a commitment; every item in a
`ConfirmationPrompt` is a row `open_commitments` already returned.

## "قبل الاجتماع ده" — which commitments are asked about

A commitment created *during* the very meeting this prompt is for
(`commitment.meeting_id` equal to this meeting's internal ledger row
id) is excluded — asking "is it done yet?" about something recorded
minutes ago in the same meeting makes no sense. Only commitments that
predate this meeting are candidates, matching the P14 use case: closing
the loop on carry-over items from *before* this meeting, not on
same-meeting notes.

If this meeting's calendar id has no `meetings` row yet (nothing has
called `ledger.record_meeting` for it), or that row has no
`party_id`, the prompt is empty — the same "first meeting, empty
ledger" honesty `brief.py` already applies elsewhere.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from rel_mcp.audit import append_audit
from rel_mcp.config import get_settings
from rel_mcp.ledger import CommitmentSide, open_commitments, set_commitment_status


class ConfirmationItem(BaseModel):
    commitment_id: int
    text: str
    side: CommitmentSide


class ConfirmationPrompt(BaseModel):
    """The reviewable list for one meeting's post-meeting confirmation tap.

    `items` is empty whenever there is nothing to confirm — a brand-new
    party, a meeting not yet recorded in the ledger, or a party with no
    open commitments from before this meeting. An empty prompt means
    "nothing to ask", not an error.
    """

    meeting_id: str
    party_id: int | None = None
    party_name: str | None = None
    items: list[ConfirmationItem] = Field(default_factory=list)


def build_confirmation_prompt(
    meeting_id: str, ledger: sqlite3.Connection
) -> ConfirmationPrompt:
    """Build the confirmation prompt for `meeting_id` (a calendar event id).

    Pure read: no writes, no audit line (nothing happened yet — see
    `apply_confirmation` for the function that does).
    """
    meeting_row = ledger.execute(
        "SELECT id, party_id FROM meetings WHERE calendar_id = ?", (meeting_id,)
    ).fetchone()
    if meeting_row is None or meeting_row["party_id"] is None:
        return ConfirmationPrompt(meeting_id=meeting_id, items=[])

    internal_meeting_id = meeting_row["id"]
    party_id = meeting_row["party_id"]

    party_row = ledger.execute(
        "SELECT name FROM parties WHERE id = ?", (party_id,)
    ).fetchone()
    party_name = party_row["name"] if party_row else None

    commitments = open_commitments(ledger, party_id)
    items = [
        ConfirmationItem(commitment_id=c.id, text=c.text, side=c.side)
        for c in commitments
        if c.meeting_id != internal_meeting_id  # exclude same-meeting notes
    ]

    return ConfirmationPrompt(
        meeting_id=meeting_id, party_id=party_id, party_name=party_name, items=items
    )


def apply_confirmation(
    ledger: sqlite3.Connection,
    commitment_id: int,
    resolved: bool,
    now: datetime,
    *,
    audit_log_path: Path | None = None,
) -> None:
    """Apply one confirmation tap for `commitment_id`.

    `resolved=True` sets the commitment's status to `"done"`.
    `resolved=False` changes nothing — the commitment stays `"open"`,
    exactly where it already was. Either way, the tap itself is audited:
    a human explicitly saying "still open" is a real event worth
    recording, even though it produces no ledger write.
    """
    audit_path = audit_log_path or get_settings().audit_log_path

    new_status: Literal["done", "open"]
    if resolved:
        set_commitment_status(
            ledger, commitment_id=commitment_id, status="done", now=now
        )
        new_status = "done"
    else:
        new_status = "open"

    append_audit(
        audit_path,
        action="post_meeting_confirmation",
        summary=f"commitment {commitment_id}: {'تم' if resolved else 'لسه مفتوح'}",
        payload={
            "commitment_id": commitment_id,
            "resolved": resolved,
            "new_status": new_status,
        },
        now=now,
    )
