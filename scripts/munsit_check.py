"""Transcribe one real audio file through Munsit and print the result.

For judging transcription quality by ear/eye against a real sample — this
is the only way to verify the request/response shape assumed by
`rel_mcp.transcripts.munsit_client` actually matches the live API.

USAGE:
    uv run python scripts/munsit_check.py path/to/sample.wav
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from rel_mcp.config import get_settings
from rel_mcp.errors import RelError
from rel_mcp.transcripts.munsit_client import transcribe_audio


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio_file", type=Path, help="path to a local audio file")
    args = parser.parse_args()

    try:
        settings = get_settings()
        api_key = settings.require_munsit_api_key()
        result = transcribe_audio(
            args.audio_file, api_key, audit_log_path=settings.audit_log_path
        )
    except RelError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    print(f"=== transcript for {args.audio_file.name} ===")
    print(result.text)
    if result.duration_seconds is not None:
        print(f"\n[audio duration: {result.duration_seconds:.1f}s]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
