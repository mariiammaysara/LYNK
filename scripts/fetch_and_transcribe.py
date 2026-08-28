"""Fetch a finished Meeting BaaS recording and transcribe it via Munsit —
one manual diagnostic pass, for validating both clients against a real
audio file end to end.

Not part of the permanent pipeline: this wires `get_recording_url` and
`transcribe_audio` together by hand, for a bot_id you already have from
`meetingbaas_check.py`. A real downstream module (not written yet) would
do this automatically once P21 moves past the validation stage.

USAGE:
    uv run python scripts/fetch_and_transcribe.py <bot_id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

import httpx

from rel_mcp.config import get_settings
from rel_mcp.errors import RelError
from rel_mcp.transcripts.meetingbaas_client import get_recording_url
from rel_mcp.transcripts.munsit_client import transcribe_audio

DOWNLOAD_TIMEOUT_SECONDS = 60.0


def _audio_suffix(audio_url: str) -> str:
    # The real confirmed URL is a .flac, not .mp3 — infer the real
    # extension from the URL path instead of hardcoding one, so
    # munsit_client's content-type guess (from the filename) is
    # accurate. Falls back to .mp3 only if the URL has no extension.
    suffix = Path(urlsplit(audio_url).path).suffix
    return suffix if suffix else ".mp3"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bot_id", help="Meeting BaaS bot_id from meetingbaas_check.py")
    args = parser.parse_args()

    settings = get_settings()

    try:
        baas_key = settings.require_meetingbaas_api_key()
        urls = get_recording_url(
            args.bot_id, baas_key, audit_log_path=settings.audit_log_path
        )
    except RelError as exc:
        print(f"[FAIL] checking recording status: {exc}", file=sys.stderr)
        return 2

    if urls is None:
        print(
            "لسه التسجيل مش جاهز أو الرابط منتهي — جرّبي تاني كمان شوية، "
            "أو ابعتي bot_id مختلف.",
            file=sys.stderr,
        )
        return 1

    audio_dir = Path("var/tmp_audio")
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"{args.bot_id}{_audio_suffix(urls.audio_url)}"

    try:
        with httpx.Client(timeout=DOWNLOAD_TIMEOUT_SECONDS) as client:
            response = client.get(urls.audio_url)
        if not (200 <= response.status_code < 300):
            print(
                f"[FAIL] downloading audio: HTTP {response.status_code} "
                f"(presigned URL may have expired — 4h limit)",
                file=sys.stderr,
            )
            return 2
        audio_path.write_bytes(response.content)
    except httpx.HTTPError as exc:
        print(f"[FAIL] downloading audio: {exc}", file=sys.stderr)
        return 2

    print(f"[ok] audio saved to {audio_path} ({audio_path.stat().st_size} bytes)")

    try:
        munsit_key = settings.require_munsit_api_key()
        result = transcribe_audio(
            audio_path, munsit_key, audit_log_path=settings.audit_log_path
        )
    except RelError as exc:
        print(f"[FAIL] transcribing audio: {exc}", file=sys.stderr)
        return 2

    transcript_path = audio_dir / f"{args.bot_id}_transcript.txt"
    transcript_path.write_text(result.text, encoding="utf-8")

    print(f"=== transcript ({transcript_path}) ===")
    print(result.text)
    if result.duration_seconds is not None:
        print(f"\n[audio duration: {result.duration_seconds:.1f}s]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
