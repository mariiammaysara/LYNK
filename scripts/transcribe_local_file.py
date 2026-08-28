"""Transcribe one local audio file via Munsit — no Meeting BaaS involved.

For testing `munsit_client.transcribe_audio` directly against a file
already on disk (e.g. from `fetch_and_transcribe.py` or
`meetingbaas_check.py`'s download step), without repeating a
`get_recording_url` call or risking a presigned URL that's since expired.

USAGE:
    uv run python scripts/transcribe_local_file.py path/to/audio.flac
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from rel_mcp.config import get_settings
from rel_mcp.errors import TranscriptionError
from rel_mcp.transcripts.munsit_client import transcribe_audio


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio_file", type=Path, help="path to a local audio file")
    args = parser.parse_args()

    if not args.audio_file.exists():
        print(f"[FAIL] الملف مش موجود: {args.audio_file}", file=sys.stderr)
        return 1

    settings = get_settings()
    api_key = settings.require_munsit_api_key()

    try:
        result = transcribe_audio(
            args.audio_file, api_key, audit_log_path=settings.audit_log_path
        )
    except TranscriptionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    print(result.text)

    transcript_path = args.audio_file.with_suffix(".txt")
    transcript_path.write_text(result.text, encoding="utf-8")
    print(f"[ok] saved to {transcript_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
