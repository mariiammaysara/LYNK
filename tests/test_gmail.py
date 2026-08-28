"""Gmail bounded reader — the rules the module docstring calls out.

Every test names one guarantee: the query is built from participants
only, empty input is rejected, an audit line is written for every call,
and long snippets are truncated. No network — the Gmail service is
mocked at the discovery-build boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from rel_mcp.google.gmail import SNIPPET_MAX_CHARS, _build_query, _truncate, threads_with

FIXED_NOW = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


def _mock_service(threads: list[dict[str, Any]] | None = None) -> MagicMock:
    """A fake gmail service with two threads.list/threads.get chains."""
    service = MagicMock()

    threads_list_resp = MagicMock()
    threads_list_resp.execute.return_value = {"threads": threads or []}
    service.users.return_value.threads.return_value.list.return_value = threads_list_resp

    return service


def test_empty_participants_raises_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one participant"):
        threads_with(
            MagicMock(),
            participants=[],
            now=FIXED_NOW,
            audit_log_path=tmp_path / "audit.jsonl",
        )


def test_participants_without_at_sign_raise(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="none looked like an email"):
        threads_with(
            MagicMock(),
            participants=["not-an-email", ""],
            now=FIXED_NOW,
            audit_log_path=tmp_path / "audit.jsonl",
        )


def test_query_contains_only_participant_clauses() -> None:
    query = _build_query(["a@x.com", "b@y.com"], months_back=6)
    # Query shape: `(clause OR clause ...) newer_than:6m`. Extract the
    # inside of the parens and check every clause is bound to one of the
    # given participants — no stray free-text terms.
    inner = query.split(")", 1)[0].lstrip("(")
    clauses = [c.strip() for c in inner.split(" OR ")]
    for c in clauses:
        assert c.startswith(("from:", "to:")), f"unexpected clause shape: {c!r}"
        addr = c.split(":", 1)[1]
        assert addr in {"a@x.com", "b@y.com"}, f"unexpected addr: {addr!r}"


def test_query_includes_recency_window() -> None:
    query = _build_query(["a@x.com"], months_back=9)
    assert "newer_than:9m" in query


def test_call_is_audited_before_return(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"

    with patch("rel_mcp.google.gmail.build", return_value=_mock_service()):
        threads_with(
            MagicMock(),
            participants=["counterparty@vendor.example"],
            now=FIXED_NOW,
            audit_log_path=log,
        )

    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["action"] == "gmail_query"
    assert entry["payload"]["participants"] == ["counterparty@vendor.example"]
    assert entry["payload"]["results"] == 0
    assert "from:counterparty@vendor.example" in entry["payload"]["query"]
    assert "to:counterparty@vendor.example" in entry["payload"]["query"]


def test_participants_are_lowercased_and_stripped(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"

    with patch("rel_mcp.google.gmail.build", return_value=_mock_service()):
        threads_with(
            MagicMock(),
            participants=["  Contact@Vendor.EXAMPLE  "],
            now=FIXED_NOW,
            audit_log_path=log,
        )

    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert entry["payload"]["participants"] == ["contact@vendor.example"]


def test_snippet_truncation_at_limit() -> None:
    long = "س" * (SNIPPET_MAX_CHARS + 200)
    out = _truncate(long, SNIPPET_MAX_CHARS)
    assert len(out) == SNIPPET_MAX_CHARS
    assert out.endswith("…")


def test_short_snippet_left_alone() -> None:
    assert _truncate("hello", 400) == "hello"


def test_thread_populates_from_metadata(tmp_path: Path) -> None:
    thread_detail = {
        "messages": [
            {
                "snippet": "First message snippet.",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Q4 pricing"},
                        {"name": "From", "value": "Sales Team <sales@vendor.example>"},
                        {"name": "To", "value": "owner@acme.example"},
                        {"name": "Date", "value": "Mon, 05 Jan 2026 09:00:00 +0000"},
                    ]
                },
            },
            {
                "snippet": "Latest reply.",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Re: Q4 pricing"},
                        {"name": "From", "value": "owner@acme.example"},
                        {"name": "To", "value": "sales@vendor.example"},
                        {"name": "Date", "value": "Wed, 07 Jan 2026 14:30:00 +0000"},
                    ],
                    "parts": [{"filename": "quote.pdf", "mimeType": "application/pdf"}],
                },
            },
        ]
    }

    service = _mock_service(threads=[{"id": "t1"}])
    thread_get = service.users.return_value.threads.return_value.get.return_value
    thread_get.execute.return_value = thread_detail

    with patch("rel_mcp.google.gmail.build", return_value=service):
        results = threads_with(
            MagicMock(),
            participants=["sales@vendor.example"],
            now=FIXED_NOW,
            audit_log_path=tmp_path / "audit.jsonl",
        )

    assert len(results) == 1
    t = results[0]
    assert t.id == "t1"
    assert t.subject == "Q4 pricing"
    assert set(t.participants) == {"sales@vendor.example", "owner@acme.example"}
    assert t.has_attachments is True
    assert t.last_message_at == datetime(2026, 1, 7, 14, 30, tzinfo=UTC)
    assert t.snippet == "Latest reply."
