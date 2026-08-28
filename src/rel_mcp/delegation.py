"""Task delegation — record-only, deterministic (P14/P15 groundwork).

## Where the team roster comes from

sim-agent (the sibling profile, see `README.dev.md`'s "Boundary from
sim-agent") already has an `employee_links` table
(`src/sim_mcp/employees.py` in that repo) — but it answers a different
question (which Telegram id maps to which verified company user, for
gating outbound notifications) and lives in a separate database this
profile is architecturally forbidden from reading: "Neither profile
reads the other's storage, and neither is allowed to touch the other's
Hermes configuration." So this module does not read it. Instead,
`ledger.py`'s v6 migration adds a small local `team_members` table
(name, role) — reviewed against sim-agent first, added only because no
shared, in-boundary source exists yet.

## What this module deliberately does NOT do

`delegate_task` never calls `sim_mcp` — it only records the delegation
in this ledger (`commitments.delegated_to`). Turning that into an
actual task in the company's task system (via the existing `sim_mcp` tools, not a
duplicate write path — see `docs/HANDOVER.md`'s P15 roadmap entry) is a
separate, later integration step. Recording a delegation here is
reversible and local; creating a real task in another system is not,
and deserves its own explicit build and its own review — the same
reasoning `meeting_summary.py` and `post_meeting.py` already apply to
keeping an LLM-derived or human-confirmed fact out of the ledger's
"real" tables until a deliberate promotion step does it on purpose.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from rel_mcp.audit import append_audit
from rel_mcp.config import get_settings
from rel_mcp.errors import DelegationError
from rel_mcp.ledger import _iso, list_team_members  # same precedent as _party_from_row in server.py


def build_delegation_options(meeting_id: str, ledger: sqlite3.Connection) -> list[str]:
    """Names of team members available for delegation.

    `meeting_id` is accepted for a future per-meeting/per-party filter
    (e.g. only the people relevant to this account, not the whole
    roster) but isn't used to filter yet — every team member on record
    is currently offered for every meeting. Kept in the signature now
    rather than added later so callers don't need a breaking change once
    that filter exists.
    """
    del meeting_id  # reserved for a future per-meeting filter, see docstring
    return [m.name for m in list_team_members(ledger)]


def delegate_task(
    ledger: sqlite3.Connection,
    commitment_id: int,
    delegated_to: str,
    now: datetime,
    *,
    audit_log_path: Path | None = None,
) -> None:
    """Record that `commitment_id` was delegated to `delegated_to`.

    Raises `DelegationError` if no commitment with `commitment_id`
    exists — a clear, immediate failure rather than a silent no-op
    update that touches zero rows.
    """
    exists = ledger.execute(
        "SELECT 1 FROM commitments WHERE id = ?", (commitment_id,)
    ).fetchone()
    if exists is None:
        raise DelegationError(f"no commitment with id {commitment_id}")

    ledger.execute(
        "UPDATE commitments SET delegated_to = ?, updated_at = ? WHERE id = ?",
        (delegated_to, _iso(now), commitment_id),
    )

    audit_path = audit_log_path or get_settings().audit_log_path
    append_audit(
        audit_path,
        action="task_delegated",
        summary=f"commitment {commitment_id} delegated to {delegated_to}",
        payload={"commitment_id": commitment_id, "delegated_to": delegated_to},
        now=now,
    )
