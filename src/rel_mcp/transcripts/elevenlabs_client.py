"""Client for ElevenLabs Scribe, an alternative Arabic speech-to-text
engine (https://elevenlabs.io/) — evaluated as a quality comparison
against Munsit (see `docs/P21_FINDINGS.md`: on one real Egyptian-Arabic
sample, Scribe's output was coherent where Munsit's was not). This
module replaces `scripts/compare_elevenlabs_transcribe.py`, which was
deliberately throwaway diagnostic code for the evaluation itself — this
is the production client, same architecture as `munsit_client.py`.

## Scope

`transcribe_audio(...)` is the only public entry point, and it is a
client in the strictest sense: send one audio file, get one
`TranscriptResult` back (shared with `munsit_client.py` — see
`_shared.py`). It makes no decision about where the text goes, whether
it's stored, or how it feeds a brief — that belongs to a module built on
top of this one.

## API shape

- Endpoint: `POST https://api.elevenlabs.io/v1/speech-to-text`
- Auth: `xi-api-key: {api_key}`
- Body: `multipart/form-data`, a `model_id="scribe_v1"` field, and the
  audio bytes under a `file` field.
- Response: **confirmed against a real successful call (2026-08-23, via
  `scripts/compare_elevenlabs_transcribe.py`)** — the transcript is a
  top-level `text` field, e.g. `{"text": "..."}`. Unlike Meeting BaaS
  and Munsit, this is NOT wrapped in a `data` envelope. That run only
  captured `text` (the script printed just that field on success); no
  `duration` or credits/usage field was directly observed, so
  `duration_seconds` and `credits_consumed` stay best-effort/optional
  here exactly as in `munsit_client.py` — confirm the full raw response
  shape before relying on either.

## Audit

Every call that reaches the network appends one `elevenlabs_transcribe`
line to the audit log with the file name (never the audio content), the
wall-clock duration of the call, and whether it succeeded — the same
shape as `munsit_transcribe`, so cost is trackable per engine.
"""

from __future__ import annotations

import mimetypes
import time
from datetime import datetime
from pathlib import Path

import httpx

from rel_mcp.audit import append_audit
from rel_mcp.errors import ElevenLabsError
from rel_mcp.transcripts._shared import TranscriptResult

ELEVENLABS_TRANSCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVENLABS_MODEL_ID = "scribe_v1"

# Transcription can run well past a typical HTTP timeout for a long
# recording; generous on purpose, same rationale as munsit_client.py.
ELEVENLABS_TIMEOUT_SECONDS = 120.0


def transcribe_audio(
    file_path: Path,
    api_key: str,
    *,
    audit_log_path: Path,
    now: datetime | None = None,
    timeout: float = ELEVENLABS_TIMEOUT_SECONDS,
) -> TranscriptResult:
    """Send `file_path` to ElevenLabs Scribe and return the transcript.

    Raises `FileNotFoundError` before any network call if `file_path`
    doesn't exist. Raises `ElevenLabsError` for anything that goes wrong
    afterward — a network failure, a non-2xx response, or a response
    that doesn't look like a transcript. Never swallows an exception.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"audio file not found: {file_path}")

    start = time.monotonic()
    ok = False
    try:
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    ELEVENLABS_TRANSCRIBE_URL,
                    headers={"xi-api-key": api_key},
                    data={"model_id": ELEVENLABS_MODEL_ID},
                    files={"file": (file_path.name, file_path.read_bytes(), content_type)},
                )
        except httpx.HTTPError as exc:
            raise ElevenLabsError(
                f"ElevenLabs request failed for {file_path.name}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise ElevenLabsError(
                f"ElevenLabs API returned {response.status_code} for {file_path.name}: "
                f"{response.text[:300]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ElevenLabsError(
                f"ElevenLabs API returned a non-JSON response for {file_path.name}"
            ) from exc

        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise ElevenLabsError(
                f"ElevenLabs API response for {file_path.name} has no 'text' field: {body!r}"
            )

        raw_duration = body.get("duration") if isinstance(body, dict) else None
        duration_seconds = float(raw_duration) if isinstance(raw_duration, int | float) else None

        result = TranscriptResult(text=text, duration_seconds=duration_seconds, ok=True)
        ok = True
        return result
    finally:
        elapsed = time.monotonic() - start
        append_audit(
            audit_log_path,
            action="elevenlabs_transcribe",
            summary=f"{file_path.name}: {'ok' if ok else 'failed'} in {elapsed:.2f}s",
            payload={
                "file_name": file_path.name,
                "call_seconds": round(elapsed, 3),
                "ok": ok,
            },
            now=now,
        )
