"""Meeting BaaS client — network-isolated. Every test mocks the HTTP layer
with respx; none of them may reach the real network."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from rel_mcp.errors import MeetingBotError
from rel_mcp.transcripts.meetingbaas_client import (
    MEETINGBAAS_SEND_BOT_URL,
    MEETINGBAAS_STATUS_URL_TEMPLATE,
    get_recording_url,
    register_account_webhook,
    send_bot,
    wait_for_recording,
)

FIXED_NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
MEETING_URL = "https://meet.google.com/abc-defg-hij"
WEBHOOK_URL = "https://tunnel.example.com/webhooks/meetingbaas"

# The exact response body confirmed from a real GET /v2/bots/{bot_id}
# call on 2026-08-23 (URLs truncated — real ones carry a long presigned
# query string; only the shape matters for these tests).
REAL_CONFIRMED_STATUS_RESPONSE = {
    "success": True,
    "data": {
        "bot_id": "db185b97-4059-41c6-b5a8-a25bbe972f88",
        "bot_name": "SIM Meeting Bot",
        "meeting_url": "https://meet.google.com/zja-rtza-dfq",
        "status": "completed",
        "created_at": "2026-08-23T14:57:45.044Z",
        "duration_seconds": 253,
        "video": "https://meeting-baas-v2-artifacts.s3.fr-par.scw.cloud/db185b97/output.mp4?X-Amz-Expires=14400",
        "audio": "https://meeting-baas-v2-artifacts.s3.fr-par.scw.cloud/db185b97/output.flac?X-Amz-Expires=14400",
        "diarization": "https://meeting-baas-v2-artifacts.s3.fr-par.scw.cloud/db185b97/diarization.jsonl",
    },
}


def _status_url(bot_id: str) -> str:
    return MEETINGBAAS_STATUS_URL_TEMPLATE.format(bot_id=bot_id)


def _read_audit_lines(audit_log_path: Path) -> list[dict[str, object]]:
    if not audit_log_path.exists():
        return []
    return [json.loads(line) for line in audit_log_path.read_text(encoding="utf-8").splitlines()]


# ── send_bot ──────────────────────────────────────────────────────────


@respx.mock
def test_send_bot_returns_session(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "bot_id": "bot-123",
                "status": "joining",
                "created_at": "2026-08-23T12:00:00Z",
            },
        )
    )

    session = send_bot(MEETING_URL, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)

    assert session.bot_id == "bot-123"
    assert session.status == "joining"
    assert session.created_at.year == 2026


@respx.mock
def test_send_bot_unwraps_the_real_confirmed_envelope(tmp_path: Path) -> None:
    # Real API response, confirmed 2026-08-23: {"success": true, "data":
    # {"bot_id": ...}} — not the flat {"bot_id": ...} originally assumed.
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {"bot_id": "db185b97-4059-41c6-b5a8-a25bbe972f88"},
            },
        )
    )

    session = send_bot(MEETING_URL, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)

    assert session.bot_id == "db185b97-4059-41c6-b5a8-a25bbe972f88"
    # status/created_at were absent in the confirmed real response —
    # falls back to defaults rather than erroring.
    assert session.status == "joining"
    assert session.created_at == FIXED_NOW


@respx.mock
def test_send_bot_never_sends_webhook_url_in_body(tmp_path: Path) -> None:
    # A real test call showed the per-bot webhook_url field appears to be
    # ignored by the API — deliberately not sent at all. webhook_url is
    # still accepted as a parameter (compatibility) but must not leak
    # into the request body.
    audit_log_path = tmp_path / "audit.jsonl"
    route = respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(200, json={"bot_id": "bot-1"})
    )

    send_bot(
        MEETING_URL,
        "secret-key",
        bot_name="My Bot",
        webhook_url=WEBHOOK_URL,
        audit_log_path=audit_log_path,
        now=FIXED_NOW,
    )

    assert route.called
    sent_request = route.calls.last.request
    assert sent_request.headers["x-meeting-baas-api-key"] == "secret-key"
    body = json.loads(sent_request.content)
    assert body == {"meeting_url": MEETING_URL, "bot_name": "My Bot"}
    assert "webhook_url" not in body


@respx.mock
def test_send_bot_defaults_status_when_absent(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(200, json={"bot_id": "bot-1"})
    )

    session = send_bot(MEETING_URL, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)

    assert session.status == "joining"


@respx.mock
def test_send_bot_unauthorized_raises_meeting_bot_error(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid key"})
    )

    with pytest.raises(MeetingBotError):
        send_bot(MEETING_URL, "bad-key", audit_log_path=audit_log_path, now=FIXED_NOW)


@respx.mock
def test_send_bot_bad_request_raises_meeting_bot_error(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid meeting_url"})
    )

    with pytest.raises(MeetingBotError):
        send_bot(MEETING_URL, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)


@respx.mock
def test_send_bot_network_failure_raises_meeting_bot_error(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(MEETINGBAAS_SEND_BOT_URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(MeetingBotError):
        send_bot(MEETING_URL, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)


@respx.mock
def test_send_bot_missing_bot_id_raises_meeting_bot_error(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(200, json={"status": "joining"})
    )

    with pytest.raises(MeetingBotError):
        send_bot(MEETING_URL, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)


@respx.mock
def test_send_bot_audit_never_contains_meeting_url(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(200, json={"bot_id": "bot-1", "status": "joining"})
    )

    send_bot(
        MEETING_URL,
        "test-key",
        webhook_url=WEBHOOK_URL,
        audit_log_path=audit_log_path,
        now=FIXED_NOW,
    )

    lines = _read_audit_lines(audit_log_path)
    assert len(lines) == 1
    assert lines[0]["action"] == "meetingbaas_send_bot"
    dumped = json.dumps(lines[0], ensure_ascii=False)
    assert MEETING_URL not in dumped
    assert WEBHOOK_URL not in dumped


@respx.mock
def test_send_bot_failure_is_still_audited(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(MEETINGBAAS_SEND_BOT_URL).mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(MeetingBotError):
        send_bot(MEETING_URL, "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)

    lines = _read_audit_lines(audit_log_path)
    assert len(lines) == 1
    assert lines[0]["payload"]["ok"] is False


# ── get_recording_url ────────────────────────────────────────────────


@respx.mock
def test_get_recording_url_returns_none_while_in_progress(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.get(_status_url("bot-123")).mock(
        return_value=httpx.Response(200, json={"status": "recording"})
    )

    result = get_recording_url(
        "bot-123", "test-key", audit_log_path=audit_log_path, now=FIXED_NOW
    )

    assert result is None


@respx.mock
def test_get_recording_url_returns_urls_on_the_real_confirmed_response(tmp_path: Path) -> None:
    # The exact shape confirmed from a real API call — status="completed"
    # (with the "d"), video/audio fields, wrapped in {"success","data"}.
    audit_log_path = tmp_path / "audit.jsonl"
    respx.get(_status_url("db185b97-4059-41c6-b5a8-a25bbe972f88")).mock(
        return_value=httpx.Response(200, json=REAL_CONFIRMED_STATUS_RESPONSE)
    )

    result = get_recording_url(
        "db185b97-4059-41c6-b5a8-a25bbe972f88",
        "test-key",
        audit_log_path=audit_log_path,
        now=FIXED_NOW,
    )

    assert result is not None
    assert result.video_url == REAL_CONFIRMED_STATUS_RESPONSE["data"]["video"]
    assert result.audio_url == REAL_CONFIRMED_STATUS_RESPONSE["data"]["audio"]


@respx.mock
def test_get_recording_url_rejects_the_webhook_style_status_value(tmp_path: Path) -> None:
    # Regression guard, flipped from an earlier (wrong) assumption: the
    # POLLING endpoint's real status value is "completed" (with a "d").
    # "complete" (no "d" — the webhook's documented event value) must
    # NOT be treated as done here; the two fields use different spellings.
    audit_log_path = tmp_path / "audit.jsonl"
    respx.get(_status_url("bot-123")).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "complete",
                "video": "https://cdn.example/output.mp4",
                "audio": "https://cdn.example/output.flac",
            },
        )
    )

    result = get_recording_url(
        "bot-123", "test-key", audit_log_path=audit_log_path, now=FIXED_NOW
    )

    assert result is None


@respx.mock
def test_get_recording_url_returns_none_when_audio_missing(tmp_path: Path) -> None:
    # status is "completed" but the audio field is absent — treated as
    # not-ready rather than returning a partial/broken model.
    audit_log_path = tmp_path / "audit.jsonl"
    respx.get(_status_url("bot-123")).mock(
        return_value=httpx.Response(
            200,
            json={"status": "completed", "video": "https://cdn.example/output.mp4"},
        )
    )

    result = get_recording_url(
        "bot-123", "test-key", audit_log_path=audit_log_path, now=FIXED_NOW
    )

    assert result is None


@respx.mock
def test_get_recording_url_returns_none_when_failed(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.get(_status_url("bot-123")).mock(
        return_value=httpx.Response(200, json={"status": "failed"})
    )

    result = get_recording_url(
        "bot-123", "test-key", audit_log_path=audit_log_path, now=FIXED_NOW
    )

    assert result is None


@respx.mock
def test_get_recording_url_sends_correct_header(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    route = respx.get(_status_url("bot-123")).mock(
        return_value=httpx.Response(200, json={"status": "recording"})
    )

    get_recording_url("bot-123", "secret-key", audit_log_path=audit_log_path, now=FIXED_NOW)

    assert route.called
    assert route.calls.last.request.headers["x-meeting-baas-api-key"] == "secret-key"


@respx.mock
def test_get_recording_url_unauthorized_raises_meeting_bot_error(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.get(_status_url("bot-123")).mock(
        return_value=httpx.Response(401, json={"error": "invalid key"})
    )

    with pytest.raises(MeetingBotError):
        get_recording_url("bot-123", "bad-key", audit_log_path=audit_log_path, now=FIXED_NOW)


@respx.mock
def test_get_recording_url_network_failure_raises_meeting_bot_error(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.get(_status_url("bot-123")).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(MeetingBotError):
        get_recording_url("bot-123", "test-key", audit_log_path=audit_log_path, now=FIXED_NOW)


@respx.mock
def test_get_recording_url_is_audited_without_url_values(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.get(_status_url("db185b97-4059-41c6-b5a8-a25bbe972f88")).mock(
        return_value=httpx.Response(200, json=REAL_CONFIRMED_STATUS_RESPONSE)
    )

    get_recording_url(
        "db185b97-4059-41c6-b5a8-a25bbe972f88",
        "test-key",
        audit_log_path=audit_log_path,
        now=FIXED_NOW,
    )

    lines = _read_audit_lines(audit_log_path)
    assert len(lines) == 1
    entry = lines[0]
    assert entry["action"] == "meetingbaas_check_status"
    assert entry["payload"]["has_recording_urls"] is True
    dumped = json.dumps(entry, ensure_ascii=False)
    assert REAL_CONFIRMED_STATUS_RESPONSE["data"]["video"] not in dumped
    assert REAL_CONFIRMED_STATUS_RESPONSE["data"]["audio"] not in dumped


# ── wait_for_recording ───────────────────────────────────────────────


@respx.mock
def test_wait_for_recording_polls_until_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # time.sleep is mocked to a no-op — real pacing has nothing to do
    # with whether the loop logic itself is correct, and a real 30s
    # sleep per attempt would make this test unusable.
    monkeypatch.setattr(
        "rel_mcp.transcripts.meetingbaas_client.time.sleep", lambda _seconds: None
    )
    audit_log_path = tmp_path / "audit.jsonl"
    route = respx.get(_status_url("bot-123")).mock(
        side_effect=[
            httpx.Response(200, json={"status": "recording"}),
            httpx.Response(200, json={"status": "recording"}),
            httpx.Response(200, json=REAL_CONFIRMED_STATUS_RESPONSE),
        ]
    )

    result = wait_for_recording("bot-123", "test-key", audit_log_path=audit_log_path)

    assert result is not None
    assert result.audio_url == REAL_CONFIRMED_STATUS_RESPONSE["data"]["audio"]
    assert route.call_count == 3


@respx.mock
def test_wait_for_recording_returns_none_on_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # timeout_seconds=0 means the very first attempt's elapsed time
    # (a few milliseconds of real wall-clock, from the mocked HTTP call
    # alone) already exceeds it — the loop returns after exactly one
    # attempt, with no real sleep. This is what keeps the test fast
    # despite a 7200s production default: proof the mock actually works
    # is that this test does not take anywhere near 7200s to run.
    monkeypatch.setattr(
        "rel_mcp.transcripts.meetingbaas_client.time.sleep", lambda _seconds: None
    )
    audit_log_path = tmp_path / "audit.jsonl"
    route = respx.get(_status_url("bot-123")).mock(
        return_value=httpx.Response(200, json={"status": "recording"})
    )

    result = wait_for_recording(
        "bot-123", "test-key", timeout_seconds=0, audit_log_path=audit_log_path
    )

    assert result is None
    assert route.call_count == 1


@respx.mock
def test_wait_for_recording_logs_one_poll_attempt_per_try(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "rel_mcp.transcripts.meetingbaas_client.time.sleep", lambda _seconds: None
    )
    audit_log_path = tmp_path / "audit.jsonl"
    respx.get(_status_url("bot-123")).mock(
        side_effect=[
            httpx.Response(200, json={"status": "recording"}),
            httpx.Response(200, json={"status": "recording"}),
            httpx.Response(200, json=REAL_CONFIRMED_STATUS_RESPONSE),
        ]
    )

    wait_for_recording("bot-123", "test-key", audit_log_path=audit_log_path)

    lines = _read_audit_lines(audit_log_path)
    poll_lines = [entry for entry in lines if entry["action"] == "meetingbaas_poll_attempt"]
    assert len(poll_lines) == 3
    assert [entry["payload"]["attempt"] for entry in poll_lines] == [1, 2, 3]
    assert [entry["payload"]["found"] for entry in poll_lines] == [False, False, True]
    dumped = json.dumps(poll_lines, ensure_ascii=False)
    assert REAL_CONFIRMED_STATUS_RESPONSE["data"]["audio"] not in dumped


# ── register_account_webhook ─────────────────────────────────────────


def test_register_account_webhook_is_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        register_account_webhook(WEBHOOK_URL, "test-key", ["meeting.completed"])
