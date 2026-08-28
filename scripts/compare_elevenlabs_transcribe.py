"""Compare ElevenLabs Scribe against Munsit on the same audio file.

Temporary diagnostic only — P21 is still evaluating transcription
engines, so this doesn't warrant a full client module (typed errors,
audit logging, a pydantic result model) the way `munsit_client.py` and
`meetingbaas_client.py` do. If ElevenLabs wins the comparison, build a
real `elevenlabs_client.py` mirroring that pattern instead of growing
this script. Reads `ELEVENLABS_API_KEY` straight from the environment
(via `.env`, loaded manually) rather than `rel_mcp.config.Settings`,
for the same reason — not part of the permanent 9+-var contract yet.

ElevenLabs's exact response shape is UNVERIFIED — this script does not
assume `{"text": ...}` is correct. If that key is missing, it prints the
full raw response instead of guessing, the same lesson learned the hard
way with Meeting BaaS and Munsit.

USAGE:
    uv run python scripts/compare_elevenlabs_transcribe.py path/to/audio.flac
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

import httpx
from dotenv import load_dotenv

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVENLABS_MODEL_ID = "scribe_v1"
TIMEOUT_SECONDS = 120.0


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio_file", type=Path, help="path to a local audio file")
    args = parser.parse_args()

    if not args.audio_file.exists():
        print(f"[FAIL] الملف مش موجود: {args.audio_file}", file=sys.stderr)
        return 1

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("[FAIL] ELEVENLABS_API_KEY مش موجود فى .env", file=sys.stderr)
        return 1

    content_type = mimetypes.guess_type(args.audio_file.name)[0] or "application/octet-stream"

    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            response = client.post(
                ELEVENLABS_URL,
                headers={"xi-api-key": api_key},
                data={"model_id": ELEVENLABS_MODEL_ID},
                files={
                    "file": (
                        args.audio_file.name,
                        args.audio_file.read_bytes(),
                        content_type,
                    )
                },
            )
    except httpx.HTTPError as exc:
        print(f"[FAIL] network error calling ElevenLabs: {exc}", file=sys.stderr)
        return 2

    if response.status_code >= 400:
        print(
            f"[FAIL] ElevenLabs returned HTTP {response.status_code}:\n{response.text}",
            file=sys.stderr,
        )
        return 2

    try:
        body = response.json()
    except ValueError:
        print(f"[FAIL] ElevenLabs returned a non-JSON response:\n{response.text}", file=sys.stderr)
        return 2

    text = body.get("text") if isinstance(body, dict) else None
    if not isinstance(text, str):
        print(
            "[WARN] الرد مفيهوش حقل 'text' زي المتوقع — الرد الخام كامل عشان "
            "نعرف الشكل الحقيقي:",
            file=sys.stderr,
        )
        print(body, file=sys.stderr)
        return 2

    print(text)

    transcript_path = args.audio_file.with_name(args.audio_file.stem + "_elevenlabs.txt")
    transcript_path.write_text(text, encoding="utf-8")
    print(f"[ok] saved to {transcript_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
