"""Local-only FastAPI receiver for Meeting BaaS webhooks.

## Scope

A diagnostic tool, not part of the permanent architecture. Meeting BaaS's
exact webhook shape was unverified when `meetingbaas_client.py` was
written (see that module's docstring); this receiver exists to point a
real Meeting BaaS webhook at during manual testing and see the real
payload printed to the terminal, so the assumptions in the client module
can be corrected against reality instead of guessed twice.

Not started by Hermes. Not deployed. Not on any production path — run it
with `scripts/run_webhook_receiver.py` when you need it, and stop it when
you're done.

## Behavior

The single endpoint always returns `200 {"status": "received"}`, even for
an unrecognized `event` value or a body that fails to parse — Meeting
BaaS would otherwise retry-storm a receiver that returns an error for
something it doesn't understand yet. Every event that reaches the
endpoint is printed in full to the terminal for manual inspection, and
logged to the audit log as `meetingbaas_webhook_received` with the event
type and bot_id only — never the recording or transcript URLs, which are
access-granting.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rel_mcp.audit import append_audit
from rel_mcp.config import get_settings

app = FastAPI(title="Meeting BaaS webhook receiver (local test only)")


@app.post("/webhooks/meetingbaas")
async def receive_meetingbaas_webhook(request: Request) -> JSONResponse:
    try:
        body: Any = await request.json()
    except Exception as exc:
        # A diagnostic receiver must never return an error for a body it
        # can't parse; Meeting BaaS would just retry it. Print, don't
        # hide, then still ack.
        print(f"=== Meeting BaaS webhook: could not parse body: {exc} ===")
        return JSONResponse(status_code=200, content={"status": "received"})

    print("=== Meeting BaaS webhook received ===")
    print(body)

    event = body.get("event") if isinstance(body, dict) else None
    bot_id = body.get("bot_id") if isinstance(body, dict) else None

    if event == "complete":
        recording_url = body.get("recording_url") if isinstance(body, dict) else None
        transcript_url = body.get("transcript_url") if isinstance(body, dict) else None
        print(f"*** COMPLETE — recording_url: {recording_url}")
        print(f"*** COMPLETE — transcript_url: {transcript_url}")
    elif event == "failed":
        reason = body.get("error") or body.get("reason") if isinstance(body, dict) else None
        print(f"*** FAILED — reason: {reason}")

    settings = get_settings()
    append_audit(
        settings.audit_log_path,
        action="meetingbaas_webhook_received",
        summary=f"event={event!r} bot_id={bot_id!r}",
        payload={"event": event, "bot_id": bot_id},
    )

    return JSONResponse(status_code=200, content={"status": "received"})
