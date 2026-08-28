"""Link a real transcript to a meeting already in the ledger.

Deliberately minimal for now: `ingest_transcript` stores the text and
nothing else. No commitment extraction, no term extraction, no parsing
of the transcript at all — that is a separate, later step. Extracting
facts from free text needs the same scrutiny `agreed_terms` already
applies via `confirmed_by_owner`; folding it into ingestion here would
let unconfirmed claims slip into the ledger as a side effect of storage,
which is exactly what that flag exists to prevent.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from rel_mcp.ledger import TranscriptSource, store_transcript


def ingest_transcript(
    ledger: sqlite3.Connection,
    meeting_id: int,
    transcript_text: str,
    source: TranscriptSource,
    now: datetime,
    credits_consumed: int | None = None,
) -> None:
    """Store `transcript_text` against `meeting_id`. Storage only."""
    store_transcript(
        ledger,
        meeting_id=meeting_id,
        transcript_text=transcript_text,
        source=source,
        now=now,
        credits_consumed=credits_consumed,
    )
