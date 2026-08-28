"""Internal helpers shared across `transcripts` clients — not a public API.

Both Meeting BaaS and Munsit wrap their responses as `{<signal key>:
..., "data": {...}}` (`"success"` for Meeting BaaS, `"statusCode"` for
Munsit) — the signal key differs but the shape doesn't, so one unwrap
function covers both rather than drifting into two near-identical copies.
"""

from __future__ import annotations

from pydantic import BaseModel


def unwrap_data(body: object) -> dict[str, object]:
    """Unwrap a `{..., "data": {...}}` envelope.

    Falls back to `body` itself if there's no `data` dict, so an endpoint
    that isn't wrapped this way still works.
    """
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]  # type: ignore[no-any-return]
    return body if isinstance(body, dict) else {}


class TranscriptResult(BaseModel):
    """One successful transcription, from any engine (Munsit, ElevenLabs).

    Shared because the shape is identical across both — no engine-specific
    fields have shown up yet. If one needs a field the other doesn't,
    split them then rather than growing optional fields that are only
    ever populated by one engine.
    """

    text: str
    duration_seconds: float | None = None
    credits_consumed: int | None = None
    ok: bool = True
