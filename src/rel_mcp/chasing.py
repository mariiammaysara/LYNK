"""Daily overdue-commitment chase — deterministic logic only (P17).

## Scope

`get_overdue_commitments` and `build_daily_chase_message` are pure
functions, same shape as `brief.py`: no network, no LLM, no wall-clock
read of their own (`now` is always injected). Actually delivering the
resulting text to Telegram is a later, separate step — a cron script
mirroring `scripts/pre_meeting_brief.py`, not built here.

`build_daily_chase_message` only ever receives `Commitment` rows, which
carry `party_id` but not a resolved party name (`Commitment` doesn't
join against `parties` — see `ledger.py`). So the message summarizes
*how many* commitments and *how many distinct parties* are involved,
never names them; a caller that wants names would need to resolve
`party_id` against the ledger separately, which is deliberately kept
out of this module to keep it a pure function of its input list.

## Dedup

`chase_sent_log` (added in `ledger.py`'s v5 migration) is a same-day
guard, mirroring `sent_briefs`/`sent_bots` exactly: a cron pulsing more
than once on the same calendar date must not send the digest twice.
`prepare_daily_chase_message` is the one function in this module that
touches the ledger for anything beyond a read — it checks the dedup
table, and marks it, but still never sends anything itself.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from rel_mcp.ledger import (
    Commitment,
    _commitment_from_row,  # same private-helper-reuse precedent as server.py's _party_from_row
    has_chase_been_sent_today,
    mark_chase_sent,
)
from rel_mcp.phrases import CHASE_BULLET_THEM, CHASE_BULLET_US, CHASE_SUMMARY_LINE
from rel_mcp.render import MAX_LINES  # same cap the ordinary brief uses


def get_overdue_commitments(ledger: sqlite3.Connection, now: datetime) -> list[Commitment]:
    """Every open commitment whose due date has passed, oldest-overdue first.

    "Overdue" uses the same calendar-date comparison the rest of the
    codebase already uses (see `brief.py`'s `_commitments_by_side`) —
    `due_date.date() < now.date()`, not a full-timestamp comparison.
    """
    rows = ledger.execute(
        "SELECT * FROM commitments WHERE status = 'open' AND due_date IS NOT NULL"
    ).fetchall()
    commitments = [_commitment_from_row(r) for r in rows]
    overdue = [c for c in commitments if c.due_date is not None and c.due_date.date() < now.date()]
    overdue.sort(key=lambda c: c.due_date)  # type: ignore[arg-type,return-value]
    return overdue


def build_daily_chase_message(overdue: list[Commitment]) -> str | None:
    """Render `overdue` as Telegram-ready Arabic text, or `None` if empty.

    `None` means "nothing to send today" — the caller must not send an
    empty or placeholder message; a quiet day produces no message at
    all, same "empty sections get dropped" discipline `render.py` uses.
    """
    if not overdue:
        return None

    party_count = len({c.party_id for c in overdue})
    lines = [CHASE_SUMMARY_LINE.format(count=len(overdue), party_count=party_count)]

    for c in overdue:
        template = CHASE_BULLET_US if c.side == "us" else CHASE_BULLET_THEM
        lines.append(template.format(text=c.text))

    return "\n".join(lines[:MAX_LINES])


def prepare_daily_chase_message(ledger: sqlite3.Connection, now: datetime) -> str | None:
    """The one entry point a cron script should call: dedup-checked,
    dedup-marked, message built — or `None` if there's nothing to send
    (no overdue commitments) or it already went out today.

    Marks `chase_sent_log` as part of building the message, not after
    some later delivery step — unlike `pre_meeting_brief.py`'s
    `--dry-run`/`--send` split, there is no external cost or delivery
    failure mode here worth guarding against with a two-phase commit;
    the only failure this dedup exists to prevent is the cron pulsing
    twice in one day.
    """
    if has_chase_been_sent_today(ledger, now):
        return None

    overdue = get_overdue_commitments(ledger, now)
    message = build_daily_chase_message(overdue)
    if message is None:
        return None

    mark_chase_sent(ledger, now=now)
    return message
