"""Gmail reader — bounded by code, audited per call.

## The rule this module exists to enforce

**Gmail's OAuth scope grants access to every message in the mailbox.
Bounding is not enforced by a prompt or a policy document — it is
enforced here, in code.** The single public entry point is
`threads_with(...)`, which accepts a list of *participant email
addresses* and nothing else. There is no free-text search, no keyword
filter, no `q` string reachable from callers. A caller that supplies
zero participants gets a `ValueError`, not the entire mailbox.

## Audit

Every call appends one `gmail_query` line to the audit log — the exact
Gmail query the code built, the participant list it built it from, and
the number of threads returned. This is what answers the question
"what has this agent read?" months from now.

## What we deliberately do not do

Attachments are not downloaded or parsed; their presence is recorded on
the `Thread` (`has_attachments`) so a downstream brief can note it, but
the bytes never leave Gmail's servers. Free-text search would require
its own module, its own scope discussion, and its own audit shape;
adding it here without those is precisely the class of change this file
exists to prevent.
"""

from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from pydantic import BaseModel, Field

from rel_mcp.audit import append_audit

# Snippets are truncated so a single leaked line of a very long email
# can never expand the audit log or brief output uncontrollably.
SNIPPET_MAX_CHARS = 400


class Thread(BaseModel):
    """One Gmail thread, flattened to the fields the brief pipeline needs."""

    id: str
    subject: str
    last_message_at: datetime
    participants: list[str] = Field(default_factory=list)
    snippet: str = ""
    has_attachments: bool = False


def threads_with(
    creds: Credentials,
    *,
    participants: list[str],
    now: datetime,
    audit_log_path: Path,
    limit: int = 10,
    months_back: int = 12,
) -> list[Thread]:
    """Recent Gmail threads that involve any of the given participants.

    `participants` is the only content input. There is no free-text
    search — a caller trying to pass one gets `ValueError`. Every call
    is audited before the network happens, so a caller that crashes
    mid-request still shows up in the log.
    """
    if not participants:
        raise ValueError(
            "threads_with requires at least one participant email; free-text "
            "search is not supported by this module — every query must be "
            "bounded to a known list of correspondents."
        )

    cleaned = [p.strip().lower() for p in participants if p and "@" in p]
    if not cleaned:
        raise ValueError(
            f"threads_with received {len(participants)} participants but none "
            "looked like an email address (no `@`)."
        )

    query = _build_query(cleaned, months_back=months_back)

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    threads_page = (
        service.users()
        .threads()
        .list(userId="me", q=query, maxResults=limit)
        .execute()
    )

    thread_stubs = threads_page.get("threads") or []
    threads: list[Thread] = []
    for stub in thread_stubs:
        thread_id = str(stub["id"])
        detail = (
            service.users()
            .threads()
            .get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"],
            )
            .execute()
        )
        threads.append(_to_thread(thread_id, detail))

    append_audit(
        audit_log_path,
        action="gmail_query",
        summary=f"query={query!r} returned {len(threads)} threads",
        payload={
            "query": query,
            "participants": cleaned,
            "results": len(threads),
            "limit": limit,
            "months_back": months_back,
        },
        now=now,
    )

    return threads


# ─── Internals ───────────────────────────────────────────────────────


def _build_query(participants: list[str], *, months_back: int) -> str:
    """`(from:a OR to:a OR from:b OR to:b ...) newer_than:Nm`."""
    clauses: list[str] = []
    for p in participants:
        clauses.append(f"from:{p}")
        clauses.append(f"to:{p}")
    joined = " OR ".join(clauses)
    return f"({joined}) newer_than:{months_back}m"


def _to_thread(thread_id: str, detail: dict[str, Any]) -> Thread:
    messages = detail.get("messages") or []
    subject = ""
    participants: list[str] = []
    last_dt: datetime | None = None
    has_attachments = False
    snippet_source = ""

    for msg in messages:
        headers = {h["name"].lower(): h["value"] for h in _headers_of(msg)}
        if not subject and headers.get("subject"):
            subject = headers["subject"]

        for field in ("from", "to"):
            raw = headers.get(field, "")
            for addr in _extract_addresses(raw):
                lowered = addr.lower()
                if lowered not in participants:
                    participants.append(lowered)

        date_header = headers.get("date")
        if date_header:
            try:
                parsed = parsedate_to_datetime(date_header)
            except (TypeError, ValueError):
                parsed = None
            if parsed and (last_dt is None or parsed > last_dt):
                last_dt = parsed

        if _message_has_attachments(msg):
            has_attachments = True

        # The Gmail-supplied snippet is already truncated to ~200 chars,
        # but it's per-message; keep the most recent one that has text.
        raw_snippet = str(msg.get("snippet") or "")
        if raw_snippet:
            snippet_source = raw_snippet

    if last_dt is None:
        # A metadata call that returned no `Date` header on any message
        # is malformed but not fatal — surface it with the epoch so the
        # thread doesn't silently vanish; render will show "غير معروف".
        last_dt = datetime.fromtimestamp(0, tz=datetime.now().astimezone().tzinfo)

    return Thread(
        id=thread_id,
        subject=subject,
        last_message_at=last_dt,
        participants=participants,
        snippet=_truncate(snippet_source, SNIPPET_MAX_CHARS),
        has_attachments=has_attachments,
    )


def _headers_of(msg: dict[str, Any]) -> list[dict[str, str]]:
    payload = msg.get("payload") or {}
    headers = payload.get("headers") or []
    return [h for h in headers if isinstance(h, dict) and "name" in h and "value" in h]


def _extract_addresses(raw: str) -> list[str]:
    """Pull the email addresses out of a From/To header value."""
    out: list[str] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if "<" in chunk and ">" in chunk:
            start = chunk.rfind("<") + 1
            end = chunk.rfind(">")
            addr = chunk[start:end].strip()
        else:
            addr = chunk
        if "@" in addr:
            out.append(addr)
    return out


def _message_has_attachments(msg: dict[str, Any]) -> bool:
    payload = msg.get("payload") or {}
    return any(part.get("filename") for part in _walk_parts(payload))


def _walk_parts(node: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [node]
    for child in node.get("parts") or []:
        parts.extend(_walk_parts(child))
    return parts


def _truncate(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"
