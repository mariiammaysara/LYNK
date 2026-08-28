"""Client for Munsit, the Arabic speech-to-text engine (https://cntxt.tools/).

## Scope

`transcribe_audio(...)` is the only public entry point, and it is a client
in the strictest sense: send one audio file, get one `TranscriptResult`
back. It makes no decision about where the text goes, whether it's stored,
or how it feeds a brief — that belongs to a module built on top of this
one, once P21 gets past the transcription-engine stage.

## API shape

- Endpoint: `POST https://api.cntxt.tools/audio/transcribe`
- Auth: `Authorization: Bearer {api_key}`
- Body: `multipart/form-data`, a `model` field, and the audio bytes under
  a `file` field. **Confirmed (2026-08-23) via a real error response**
  (`errorCode 40001: "model must be one of: munsit, munsit-en-ar"`):
  the model must be `"munsit"` or `"munsit-en-ar"` — `"munsit-1"`
  (the original assumption) is rejected outright.
- Response: **confirmed against a real successful call (2026-08-23)** —
  wrapped, same shape as Meeting BaaS's:
  `{"statusCode": 200, "data": {"transcription": "...", "attributes":
  {...word-level timestamps...}, "audioUrl": ..., "stats":
  {"creditsConsumed": N, ...}}, "message": "Success"}`.
  The transcript text is `data.transcription`, **not** a top-level
  `text` field (the original assumption). No `duration` field was
  present in the confirmed response — `duration_seconds` stays `None`
  unless a future response includes one. `data.stats.creditsConsumed`
  is tracked for cost visibility (see `TranscriptResult.credits_consumed`).
  `unwrap_data(...)` (in `_shared.py`, shared with `meetingbaas_client.py`
  — both APIs use the same envelope shape) centralizes the unwrap.

Run `scripts/munsit_check.py` against a real audio sample before trusting
any remaining assumption in this module — if the real API disagrees,
this module (and its tests) need updating, not the calling code.

## Audit

Every call that reaches the network appends one `munsit_transcribe` line
to the audit log with the file name (never the audio content), the wall-
clock duration of the call, credits consumed (when Munsit reports it),
and whether it succeeded — the same shape as `gmail_query`, so Munsit
usage is trackable for cost the same way.
"""

from __future__ import annotations

import mimetypes
import time
from datetime import datetime
from pathlib import Path

import httpx

from rel_mcp.audit import append_audit
from rel_mcp.errors import TranscriptionError
from rel_mcp.transcripts._shared import TranscriptResult, unwrap_data

MUNSIT_TRANSCRIBE_URL = "https://api.cntxt.tools/audio/transcribe"
# Confirmed (2026-08-23) via a real error response — "munsit-1" is
# rejected; only "munsit" and "munsit-en-ar" are accepted.
# munsit-en-ar is available as an alternative when the text has a heavy
# mix of Arabic and English — try it if plain munsit does poorly on
# English terms.
MUNSIT_MODEL = "munsit"

# Transcription can run well past a typical HTTP timeout for a long
# recording; generous on purpose. Tune down once real call times are known.
MUNSIT_TIMEOUT_SECONDS = 120.0


def transcribe_audio(
    file_path: Path,
    api_key: str,
    *,
    audit_log_path: Path,
    now: datetime | None = None,
    timeout: float = MUNSIT_TIMEOUT_SECONDS,
) -> TranscriptResult:
    """Send `file_path` to Munsit and return the transcript.

    Raises `FileNotFoundError` before any network call if `file_path`
    doesn't exist. Raises `TranscriptionError` for anything that goes
    wrong afterward — a network failure, a non-2xx response, or a response
    that doesn't look like a transcript. Never swallows an exception.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"audio file not found: {file_path}")

    start = time.monotonic()
    ok = False
    credits_consumed: int | None = None
    try:
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    MUNSIT_TRANSCRIBE_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    data={"model": MUNSIT_MODEL},
                    files={"file": (file_path.name, file_path.read_bytes(), content_type)},
                )
        except httpx.HTTPError as exc:
            raise TranscriptionError(
                f"Munsit request failed for {file_path.name}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise TranscriptionError(
                f"Munsit API returned {response.status_code} for {file_path.name}: "
                f"{response.text[:300]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise TranscriptionError(
                f"Munsit API returned a non-JSON response for {file_path.name}"
            ) from exc

        # Confirmed against a real successful call: the real shape is
        # {"statusCode": 200, "data": {"transcription": ..., "stats":
        # {"creditsConsumed": N}}}, not a flat {"text": ...} — unwrap
        # `data` when present (see module docstring).
        data = unwrap_data(body)

        text = data.get("transcription")
        if not isinstance(text, str):
            raise TranscriptionError(
                f"Munsit API response for {file_path.name} has no 'transcription' "
                f"field: {body!r}"
            )

        raw_duration = data.get("duration")
        duration_seconds = float(raw_duration) if isinstance(raw_duration, int | float) else None

        stats = data.get("stats")
        raw_credits = stats.get("creditsConsumed") if isinstance(stats, dict) else None
        credits_consumed = raw_credits if isinstance(raw_credits, int) else None

        result = TranscriptResult(
            text=text,
            duration_seconds=duration_seconds,
            credits_consumed=credits_consumed,
            ok=True,
        )
        ok = True
        return result
    finally:
        elapsed = time.monotonic() - start
        append_audit(
            audit_log_path,
            action="munsit_transcribe",
            summary=f"{file_path.name}: {'ok' if ok else 'failed'} in {elapsed:.2f}s",
            payload={
                "file_name": file_path.name,
                "call_seconds": round(elapsed, 3),
                "credits_consumed": credits_consumed,
                "ok": ok,
            },
            now=now,
        )
