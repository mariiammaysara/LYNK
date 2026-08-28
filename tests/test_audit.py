"""Audit log appends without ever truncating, keeps UTC timestamps, and
survives a crash between writes by opening and closing per line."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rel_mcp.audit import append_audit


def test_two_writes_append_both_lines(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"

    append_audit(log, action="one", summary="first")
    append_audit(log, action="two", summary="second")

    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["action"] == "one"
    assert second["action"] == "two"


def test_creates_parent_directory(tmp_path: Path) -> None:
    log = tmp_path / "nested" / "audit.jsonl"
    append_audit(log, action="a", summary="s")
    assert log.exists()


def test_timestamp_is_utc_iso(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    append_audit(log, action="a", summary="s", now=fixed)

    entry = json.loads(log.read_text(encoding="utf-8"))
    parsed = datetime.fromisoformat(entry["ts"])
    assert parsed == fixed
    assert parsed.tzinfo is not None


def test_arabic_text_is_written_unescaped(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    append_audit(log, action="brief_sent", summary="اجتماع مع شركة سلمى")

    raw = log.read_text(encoding="utf-8")
    assert "سلمى" in raw, "Arabic must be written literally, not \\uXXXX-escaped"


def test_dry_run_flag_is_recorded(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    append_audit(log, action="a", summary="s", dry_run=True)
    entry = json.loads(log.read_text(encoding="utf-8"))
    assert entry["dry_run"] is True


def test_payload_defaults_to_empty_dict(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    append_audit(log, action="a", summary="s")
    entry = json.loads(log.read_text(encoding="utf-8"))
    assert entry["payload"] == {}


def test_lines_are_ordered_by_write(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(5):
        append_audit(log, action=f"a{i}", summary="s", now=t0 + timedelta(seconds=i))

    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [e["action"] for e in lines] == [f"a{i}" for i in range(5)]
