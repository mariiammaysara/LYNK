"""ElevenLabs client — network-isolated. Every test mocks the HTTP layer
with respx; none of them may reach the real network."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from rel_mcp.errors import ElevenLabsError
from rel_mcp.transcripts.elevenlabs_client import ELEVENLABS_TRANSCRIBE_URL, transcribe_audio

FIXED_NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)

# The exact response shape confirmed from a real successful call on
# 2026-08-23 via scripts/compare_elevenlabs_transcribe.py: a top-level
# "text" field, not wrapped in a "data" envelope like Meeting BaaS/Munsit.
REAL_CONFIRMED_RESPONSE = {"text": "مرحبا بالجميع"}


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.wav"
    path.write_bytes(b"not-real-audio-bytes")
    return path


def _read_audit_lines(audit_log_path: Path) -> list[dict[str, object]]:
    if not audit_log_path.exists():
        return []
    return [json.loads(line) for line in audit_log_path.read_text(encoding="utf-8").splitlines()]


@respx.mock
def test_successful_transcription_returns_result(tmp_path: Path, audio_file: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(ELEVENLABS_TRANSCRIBE_URL).mock(
        return_value=httpx.Response(200, json=REAL_CONFIRMED_RESPONSE)
    )

    result = transcribe_audio(
        audio_file, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW
    )

    assert result.ok is True
    assert result.text == "مرحبا بالجميع"
    assert result.duration_seconds is None


@respx.mock
def test_request_sends_api_key_header_and_model_id(tmp_path: Path, audio_file: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    route = respx.post(ELEVENLABS_TRANSCRIBE_URL).mock(
        return_value=httpx.Response(200, json=REAL_CONFIRMED_RESPONSE)
    )

    transcribe_audio(audio_file, "secret-key", audit_log_path=audit_log_path, now=FIXED_NOW)

    assert route.called
    sent_request = route.calls.last.request
    assert sent_request.headers["xi-api-key"] == "secret-key"
    assert b'name="model_id"' in sent_request.content
    assert b"scribe_v1" in sent_request.content


@respx.mock
def test_unauthorized_raises_elevenlabs_error(tmp_path: Path, audio_file: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(ELEVENLABS_TRANSCRIBE_URL).mock(
        return_value=httpx.Response(401, json={"detail": "invalid key"})
    )

    with pytest.raises(ElevenLabsError):
        transcribe_audio(audio_file, "bad-key", audit_log_path=audit_log_path, now=FIXED_NOW)


@respx.mock
def test_server_error_raises_elevenlabs_error(tmp_path: Path, audio_file: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(ELEVENLABS_TRANSCRIBE_URL).mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(ElevenLabsError):
        transcribe_audio(audio_file, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)


@respx.mock
def test_network_failure_raises_elevenlabs_error(tmp_path: Path, audio_file: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(ELEVENLABS_TRANSCRIBE_URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(ElevenLabsError):
        transcribe_audio(audio_file, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)


@respx.mock
def test_response_missing_text_field_raises_elevenlabs_error(
    tmp_path: Path, audio_file: Path
) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(ELEVENLABS_TRANSCRIBE_URL).mock(
        return_value=httpx.Response(200, json={"detail": "no idea"})
    )

    with pytest.raises(ElevenLabsError):
        transcribe_audio(audio_file, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)


@respx.mock
def test_non_json_response_raises_elevenlabs_error(tmp_path: Path, audio_file: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(ELEVENLABS_TRANSCRIBE_URL).mock(return_value=httpx.Response(200, text="not json"))

    with pytest.raises(ElevenLabsError):
        transcribe_audio(audio_file, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)


def test_missing_file_raises_before_any_network_call(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    missing = tmp_path / "does-not-exist.wav"

    with respx.mock, pytest.raises(FileNotFoundError):
        transcribe_audio(missing, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)

    # No audit entry either — a call that never reached the network isn't
    # an ElevenLabs call.
    assert not audit_log_path.exists()


@respx.mock
def test_successful_call_is_audited(tmp_path: Path, audio_file: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(ELEVENLABS_TRANSCRIBE_URL).mock(
        return_value=httpx.Response(200, json=REAL_CONFIRMED_RESPONSE)
    )

    transcribe_audio(audio_file, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)

    lines = _read_audit_lines(audit_log_path)
    assert len(lines) == 1
    entry = lines[0]
    assert entry["action"] == "elevenlabs_transcribe"
    payload = entry["payload"]
    assert payload["file_name"] == "sample.wav"
    assert payload["ok"] is True
    assert "call_seconds" in payload
    # The audio content itself must never appear in the audit log.
    assert "not-real-audio-bytes" not in json.dumps(entry, ensure_ascii=False)
    # Nor the transcript text.
    assert "مرحبا بالجميع" not in json.dumps(entry, ensure_ascii=False)


@respx.mock
def test_failed_call_is_still_audited(tmp_path: Path, audio_file: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(ELEVENLABS_TRANSCRIBE_URL).mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(ElevenLabsError):
        transcribe_audio(audio_file, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)

    lines = _read_audit_lines(audit_log_path)
    assert len(lines) == 1
    assert lines[0]["payload"]["ok"] is False
