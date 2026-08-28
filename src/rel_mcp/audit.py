"""Append-only JSONL audit log.

Every side-effect-carrying action passes through here — a Gmail query,
a brief sent, a token refresh, whatever. The file is opened and closed
per write so a crash between writes never loses the previous line;
lines are timestamped UTC ISO 8601 so log tooling doesn't need to know
the local timezone.

The log answers the question "what did the agent actually do?", which
means it must never be truncated, rotated in place, or edited. Rotation
belongs to an out-of-process backup step, not to this writer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def append_audit(
    log_path: Path,
    *,
    action: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> None:
    """Append one JSON line to `log_path`.

    `now` is injected so tests are deterministic; production callers omit
    it and get the real UTC clock. `payload` is optional — many entries
    are just an action name plus a one-line human summary.
    """
    if now is None:
        now = datetime.now(UTC)

    entry = {
        "ts": now.astimezone(UTC).isoformat(),
        "action": action,
        "summary": summary,
        "dry_run": dry_run,
        "payload": payload or {},
    }

    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Open-close per write: a killed process between two writes cannot
    # lose a buffered line, and file-locking on Windows stays simple.
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
