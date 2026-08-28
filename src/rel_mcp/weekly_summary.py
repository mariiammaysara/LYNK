"""Weekly relationship-activity digest — deterministic, offline (like
`brief.py` and `chasing.py`: a pure function of the ledger's rows and
`now`, no network, no LLM, no wall-clock read of its own).

## The four sections, and where each one's data comes from

- **Parties contacted** — every party with at least one `contacts_log`
  row in the last 7 days (email or meeting contact events already
  recorded there; this module doesn't log anything new).
- **Closed commitments** — commitments whose `status` is `'done'` and
  whose `updated_at` falls in the last 7 days. `updated_at` moves only
  when `set_commitment_status` runs, so this is "closed this week", not
  "created this week and happens to be done".
- **New commitments** — commitments whose `created_at` falls in the last
  7 days, regardless of current status.
- **Overdue commitments** — reuses `chasing.get_overdue_commitments`
  rather than re-deriving the same "open, past due date" filter a second
  time; this section is "overdue as of `now`", not "became overdue this
  week" (a commitment that's been overdue for a month still belongs
  here — the digest should not let it quietly stop being mentioned).

## Why raw SQL here, not new ledger.py functions

`open_commitments`/`agreed_terms`/`last_contact` are all scoped to one
party at a time, because every existing caller (`brief.py`) already
knows which party it's asking about. This module is the first one that
needs a *cross-party*, *time-windowed* view — closer to
`server.py`'s own `list_open_commitments` tool, which already queries
`commitments` directly with a join rather than going through a
per-party ledger function. This module follows that same precedent
rather than inventing a one-off ledger.py function for each of four
narrow, single-caller queries.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from rel_mcp.chasing import get_overdue_commitments
from rel_mcp.ledger import _iso  # same private-helper-reuse precedent as elsewhere in this codebase
from rel_mcp.phrases import (
    WEEKLY_BUL_COMMIT,
    WEEKLY_BUL_OVERDUE,
    WEEKLY_BUL_PARTY,
    WEEKLY_EMPTY,
    WEEKLY_HDR,
    WEEKLY_HDR_CLOSED,
    WEEKLY_HDR_CONTACTED,
    WEEKLY_HDR_NEW,
    WEEKLY_HDR_OVERDUE,
)

PERIOD_DAYS = 7

# Deliberately its own constant, not imported from render.py — a weekly
# digest legitimately covers more ground than a pre-meeting brief and
# earns a longer budget, not the same one (see the module docstring in
# chasing.py for the contrasting case where reusing render.py's exact
# cap *was* the right call).
MAX_LINES = 25


class PartyRef(BaseModel):
    party_id: int
    party_name: str


class CommitmentRef(BaseModel):
    party_name: str
    text: str
    side: Literal["us", "them"]


class OverdueCommitmentRef(BaseModel):
    party_name: str
    text: str
    side: Literal["us", "them"]
    days_overdue: int


class WeeklySummary(BaseModel):
    period_start: datetime
    period_end: datetime
    parties_contacted: list[PartyRef] = Field(default_factory=list)
    closed_commitments: list[CommitmentRef] = Field(default_factory=list)
    new_commitments: list[CommitmentRef] = Field(default_factory=list)
    overdue_commitments: list[OverdueCommitmentRef] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (
            self.parties_contacted
            or self.closed_commitments
            or self.new_commitments
            or self.overdue_commitments
        )


def build_weekly_summary(ledger: sqlite3.Connection, now: datetime) -> WeeklySummary:
    """Aggregate the last `PERIOD_DAYS` days of relationship activity."""
    period_start = now - timedelta(days=PERIOD_DAYS)
    since = _iso(period_start)

    contacted_rows = ledger.execute(
        "SELECT DISTINCT p.id AS party_id, p.name AS party_name"
        " FROM contacts_log c JOIN parties p ON p.id = c.party_id"
        " WHERE c.contact_date >= ?"
        " ORDER BY p.name",
        (since,),
    ).fetchall()
    parties_contacted = [
        PartyRef(party_id=r["party_id"], party_name=r["party_name"]) for r in contacted_rows
    ]

    closed_rows = ledger.execute(
        "SELECT c.text, c.side, p.name AS party_name"
        " FROM commitments c JOIN parties p ON p.id = c.party_id"
        " WHERE c.status = 'done' AND c.updated_at >= ?"
        " ORDER BY c.updated_at",
        (since,),
    ).fetchall()
    closed_commitments = [
        CommitmentRef(party_name=r["party_name"], text=r["text"], side=r["side"])
        for r in closed_rows
    ]

    new_rows = ledger.execute(
        "SELECT c.text, c.side, p.name AS party_name"
        " FROM commitments c JOIN parties p ON p.id = c.party_id"
        " WHERE c.created_at >= ?"
        " ORDER BY c.created_at",
        (since,),
    ).fetchall()
    new_commitments = [
        CommitmentRef(party_name=r["party_name"], text=r["text"], side=r["side"])
        for r in new_rows
    ]

    overdue = get_overdue_commitments(ledger, now)
    party_names = _party_name_map(ledger)
    overdue_commitments = [
        OverdueCommitmentRef(
            party_name=party_names.get(c.party_id, "?"),
            text=c.text,
            side=c.side,
            days_overdue=(now.date() - c.due_date.date()).days,
        )
        for c in overdue
        if c.due_date is not None  # get_overdue_commitments already guarantees this
    ]

    return WeeklySummary(
        period_start=period_start,
        period_end=now,
        parties_contacted=parties_contacted,
        closed_commitments=closed_commitments,
        new_commitments=new_commitments,
        overdue_commitments=overdue_commitments,
    )


def render_weekly_summary(summary: WeeklySummary) -> str:
    """Render `summary` as Telegram-ready Arabic text, at most `MAX_LINES`.

    An entirely quiet week says so explicitly (`WEEKLY_EMPTY`) instead of
    printing a header over nothing — the same "an absence gets named
    honestly, not left to look like missing data" discipline `render.py`
    already applies to a brand-new counterparty.
    """
    header = WEEKLY_HDR.format(
        start=summary.period_start.date().isoformat(),
        end=summary.period_end.date().isoformat(),
    )
    lines = [header]

    if summary.is_empty:
        lines.append(WEEKLY_EMPTY)
        return "\n".join(lines)

    if summary.parties_contacted:
        lines.append(WEEKLY_HDR_CONTACTED)
        for p in summary.parties_contacted:
            lines.append(WEEKLY_BUL_PARTY.format(name=p.party_name))

    if summary.closed_commitments:
        lines.append(WEEKLY_HDR_CLOSED)
        for c in summary.closed_commitments:
            lines.append(WEEKLY_BUL_COMMIT.format(party=c.party_name, text=c.text))

    if summary.new_commitments:
        lines.append(WEEKLY_HDR_NEW)
        for c in summary.new_commitments:
            lines.append(WEEKLY_BUL_COMMIT.format(party=c.party_name, text=c.text))

    if summary.overdue_commitments:
        lines.append(WEEKLY_HDR_OVERDUE)
        for o in summary.overdue_commitments:
            lines.append(
                WEEKLY_BUL_OVERDUE.format(
                    party=o.party_name, text=o.text, days=o.days_overdue
                )
            )

    return "\n".join(lines[:MAX_LINES])


def _party_name_map(ledger: sqlite3.Connection) -> dict[int, str]:
    rows = ledger.execute("SELECT id, name FROM parties").fetchall()
    return {r["id"]: r["name"] for r in rows}
