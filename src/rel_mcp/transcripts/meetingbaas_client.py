"""Client for Meeting BaaS, the meeting-recording bot service
(https://meetingbaas.com/).

## Scope

Three public entry points, all pure clients: `send_bot(...)` asks a bot to
join a meeting URL and returns a `BotSession`; `get_recording_url(...)`
polls that bot's status once and returns its `video`/`audio` URLs once
ready, or `None` while still in progress; `wait_for_recording(...)` is a
blocking convenience wrapper that calls `get_recording_url` repeatedly
until it's ready or a timeout passes. None of the three makes a decision
about what happens to the recording — that's a downstream module's job,
once P21 gets past the capture stage (`get_recording_url(...).audio_url`
feeds `munsit_client.transcribe_audio`).

**Polling (`get_recording_url`) is the confirmed-working way to learn a
recording is ready — not the webhook.** See the CONFIRMED block below;
a real test call produced a finished recording with zero webhook
deliveries after 10+ minutes of waiting.

## API shape

- Send: `POST https://api.meetingbaas.com/v2/bots`, header
  `x-meeting-baas-api-key: {api_key}`, JSON body
  `{"meeting_url": ..., "bot_name": ...}`. **Confirmed against a real
  call (2026-08-23):** the response is wrapped —
  `{"success": true, "data": {"bot_id": ...}}` — not the flat
  `{"bot_id": ...}` originally assumed. `status` / `created_at` were not
  present in the confirmed response; `send_bot` falls back to `"joining"`
  / `now` when absent. `unwrap_data(...)` (in `_shared.py`, shared with
  `munsit_client.py` — both APIs use the same envelope shape) centralizes
  the unwrap so both entry points share it.
- Status (polling, confirmed working): `GET https://api.meetingbaas.com/v2/bots/{bot_id}`,
  same auth header, same `{"success", "data"}` envelope.

# CONFIRMED (2026-08-23, real test call, meeting duration 253s):
# - GET /v2/bots/{bot_id} returns status="completed" (with D)
# - Recording URLs are under "video" and "audio" fields (presigned
#   S3 URLs, 4-hour expiry), NOT "recording_url"
# - Per-request webhook_url in POST /v2/bots body did not fire a
#   webhook after a real 4-minute call and 10+ minutes of waiting.
#   Root cause not fully confirmed, but Meeting BaaS's Webhooks API
#   docs describe webhook registration as an account-level setting
#   (with a different event schema: "meeting.completed", not
#   "complete"), suggesting the per-bot field may simply be ignored.
# - Polling via get_recording_url is the CONFIRMED working method.
#   Do not treat webhooks as reliable until account-level
#   registration is tested and confirmed separately.

Run `scripts/meetingbaas_check.py` against a real (or throwaway test)
meeting before trusting any further assumption in this module — if the
real API disagrees, this module (and its tests) need updating, not the
calling code. Sending a real bot has a real per-minute cost; the check
script requires an explicit `--confirm` flag for that reason.

## Audit

Every call that reaches the network appends one line to the audit log —
`meetingbaas_send_bot` for `send_bot`, `meetingbaas_check_status` for
`get_recording_url` — with status and call duration, but never the
meeting URL or the recording URLs themselves; all are access-granting
and have no business sitting in a log file.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel

from rel_mcp.audit import append_audit
from rel_mcp.errors import MeetingBotError
from rel_mcp.transcripts._shared import unwrap_data

MEETINGBAAS_SEND_BOT_URL = "https://api.meetingbaas.com/v2/bots"
MEETINGBAAS_STATUS_URL_TEMPLATE = "https://api.meetingbaas.com/v2/bots/{bot_id}"

# Confirmed from a real GET /v2/bots/{bot_id} response (2026-08-23): the
# `status` field for a finished recording is "completed" — WITH the
# trailing "d". This is the polling endpoint's own value; it is NOT the
# same string as the webhook's documented `event` value ("complete",
# no "d") — two different fields, two different spellings. See the
# CONFIRMED block in the module docstring.
MEETINGBAAS_COMPLETED_STATUS = "completed"

MEETINGBAAS_TIMEOUT_SECONDS = 30.0


class BotSession(BaseModel):
    """One Meeting BaaS bot dispatch."""

    bot_id: str
    status: str
    created_at: datetime


class RecordingUrls(BaseModel):
    """Presigned S3 URLs for a finished Meeting BaaS recording.

    Confirmed field names (2026-08-23): `video` and `audio`, not a
    single `recording_url`. Both expire ~4 hours after the GET call
    that returned them (a real response's presigned URL carried
    `X-Amz-Expires=14400`) — fetch or hand off promptly, these are not
    durable links. Downstream code that only needs speech-to-text
    (`munsit_client.transcribe_audio`) wants `audio_url`, not `video_url`.
    """

    video_url: str
    audio_url: str


def send_bot(
    meeting_url: str,
    api_key: str,
    bot_name: str = "SIM Meeting Bot",
    *,
    webhook_url: str | None = None,
    audit_log_path: Path,
    now: datetime | None = None,
    timeout: float = MEETINGBAAS_TIMEOUT_SECONDS,
) -> BotSession:
    """Ask a Meeting BaaS bot to join `meeting_url`, and return its session.

    `webhook_url` is accepted for signature compatibility but is
    deliberately NOT sent in the request body: a real test call showed
    no webhook delivery after a completed recording and 10+ minutes of
    waiting. Meeting BaaS's Webhooks API docs describe webhook
    registration as an account-level setting (different event schema
    too — "meeting.completed", not "complete"), so a per-bot field is
    likely just ignored. Use `get_recording_url` polling — confirmed
    working — until account-level registration is implemented via
    `register_account_webhook` (currently a stub).

    Raises `MeetingBotError` for anything that goes wrong — a network
    failure, a non-2xx response, or a response missing `bot_id`. Never
    swallows an exception.
    """
    del webhook_url  # accepted for signature compatibility only, see docstring
    start = time.monotonic()
    ok = False
    status_value = "unknown"
    try:
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    MEETINGBAAS_SEND_BOT_URL,
                    headers={"x-meeting-baas-api-key": api_key},
                    json={
                        "meeting_url": meeting_url,
                        "bot_name": bot_name,
                    },
                )
        except httpx.HTTPError as exc:
            raise MeetingBotError(
                f"Meeting BaaS request failed for bot {bot_name!r}: {exc}"
            ) from exc

        if not (200 <= response.status_code < 300):
            raise MeetingBotError(
                f"Meeting BaaS API returned {response.status_code} sending bot "
                f"{bot_name!r}: {response.text[:300]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise MeetingBotError(
                f"Meeting BaaS API returned a non-JSON response for bot {bot_name!r}"
            ) from exc

        # Confirmed against a real call: the real shape is
        # {"success": true, "data": {"bot_id": ...}}, not a flat
        # {"bot_id": ...} — unwrap `data` when present.
        data = unwrap_data(body)

        bot_id = data.get("bot_id") if isinstance(data, dict) else None
        if not isinstance(bot_id, str) or not bot_id:
            raise MeetingBotError(
                f"Meeting BaaS API response for bot {bot_name!r} has no 'bot_id' "
                f"field: {body!r}"
            )

        raw_status = data.get("status") if isinstance(data, dict) else None
        status_value = raw_status if isinstance(raw_status, str) and raw_status else "joining"

        created_at = _parse_datetime(data.get("created_at") if isinstance(data, dict) else None)
        if created_at is None:
            created_at = now or datetime.now(UTC)

        session = BotSession(bot_id=bot_id, status=status_value, created_at=created_at)
        ok = True
        return session
    finally:
        elapsed = time.monotonic() - start
        append_audit(
            audit_log_path,
            action="meetingbaas_send_bot",
            summary=(
                f"bot {bot_name!r}: {'ok' if ok else 'failed'} in {elapsed:.2f}s "
                f"(status={status_value})"
            ),
            payload={
                "bot_name": bot_name,
                "status": status_value,
                "call_seconds": round(elapsed, 3),
                "ok": ok,
            },
            now=now,
        )


def get_recording_url(
    bot_id: str,
    api_key: str,
    *,
    audit_log_path: Path,
    now: datetime | None = None,
    timeout: float = MEETINGBAAS_TIMEOUT_SECONDS,
) -> RecordingUrls | None:
    """Return `RecordingUrls` for `bot_id` once ready, else `None`.

    Confirmed working (2026-08-23) — this is the reliable way to learn a
    recording is ready, not the webhook (see module docstring).

    `None` covers both "still in progress" and any other non-complete
    status (including a failed join) — this function only answers "is the
    recording ready," not "why isn't it." Raises `MeetingBotError` for a
    network failure, a non-2xx response, or a malformed response body.
    """
    start = time.monotonic()
    ok = False
    status_value = "unknown"
    has_urls = False
    try:
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.get(
                    MEETINGBAAS_STATUS_URL_TEMPLATE.format(bot_id=bot_id),
                    headers={"x-meeting-baas-api-key": api_key},
                )
        except httpx.HTTPError as exc:
            raise MeetingBotError(
                f"Meeting BaaS status request failed for bot {bot_id}: {exc}"
            ) from exc

        if not (200 <= response.status_code < 300):
            raise MeetingBotError(
                f"Meeting BaaS API returned {response.status_code} checking bot "
                f"{bot_id}: {response.text[:300]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise MeetingBotError(
                f"Meeting BaaS API returned a non-JSON response checking bot {bot_id}"
            ) from exc

        data = unwrap_data(body)

        raw_status = data.get("status") if isinstance(data, dict) else None
        status_value = raw_status if isinstance(raw_status, str) and raw_status else "unknown"

        video_url = data.get("video") if isinstance(data, dict) else None
        audio_url = data.get("audio") if isinstance(data, dict) else None
        result = (
            RecordingUrls(video_url=video_url, audio_url=audio_url)
            if status_value == MEETINGBAAS_COMPLETED_STATUS
            and isinstance(video_url, str)
            and isinstance(audio_url, str)
            else None
        )
        has_urls = result is not None
        ok = True
        return result
    finally:
        elapsed = time.monotonic() - start
        append_audit(
            audit_log_path,
            action="meetingbaas_check_status",
            summary=(
                f"bot {bot_id}: {'ok' if ok else 'failed'} in {elapsed:.2f}s "
                f"(status={status_value})"
            ),
            payload={
                "bot_id": bot_id,
                "status": status_value,
                "has_recording_urls": has_urls,
                "call_seconds": round(elapsed, 3),
                "ok": ok,
            },
            now=now,
        )


def wait_for_recording(
    bot_id: str,
    api_key: str,
    poll_interval_seconds: int = 30,
    timeout_seconds: int = 7200,
    *,
    audit_log_path: Path,
) -> RecordingUrls | None:
    """Call `get_recording_url` every `poll_interval_seconds` until it's
    ready, or `timeout_seconds` passes.

    Returns `None` on timeout — an expected outcome (meetings run long),
    not an error, so this is a return value rather than a raised
    exception; `get_recording_url` itself still raises `MeetingBotError`
    for a genuine API failure on any individual poll.

    Every attempt appends one `meetingbaas_poll_attempt` audit line —
    attempt number and elapsed seconds, never a URL — in addition to the
    `meetingbaas_check_status` line each underlying `get_recording_url`
    call already writes.
    """
    start = time.monotonic()
    attempt = 0
    while True:
        attempt += 1
        result = get_recording_url(bot_id, api_key, audit_log_path=audit_log_path)
        elapsed = time.monotonic() - start
        append_audit(
            audit_log_path,
            action="meetingbaas_poll_attempt",
            summary=(
                f"bot {bot_id}: attempt {attempt}, "
                f"{'found' if result else 'not ready'} at {elapsed:.1f}s"
            ),
            payload={
                "bot_id": bot_id,
                "attempt": attempt,
                "elapsed_seconds": round(elapsed, 3),
                "found": result is not None,
            },
        )

        if result is not None:
            return result
        if elapsed >= timeout_seconds:
            return None
        time.sleep(poll_interval_seconds)


def register_account_webhook(webhook_url: str, api_key: str, events: list[str]) -> None:
    """Register an account-level Meeting BaaS webhook. NOT YET IMPLEMENTED.

    Meeting BaaS's Webhooks API docs describe webhook registration as an
    account-level setting, not a per-bot field:
    `{"webhook_url": ..., "events": [...], "secret": ..., "enabled": true}`,
    with event names like `"meeting.completed"` (not `"complete"`) — a
    different shape than what `send_bot`'s now-unused `webhook_url`
    parameter assumed. This is a scaffold for whenever that path gets
    confirmed and built; it deliberately does not guess an endpoint path.
    """
    raise NotImplementedError(
        "Account-level webhook registration not yet confirmed — "
        "endpoint path unknown. See docs.meetingbaas.com Webhooks API. "
        "Register manually via dashboard.meetingbaas.com in the "
        "meantime, or continue using get_recording_url polling."
    )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
