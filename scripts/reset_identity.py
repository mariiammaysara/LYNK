"""Reset developer identity before handing the agent to its owner.

Run once, immediately before delivery. Prompts for confirmation on
every destructive step; nothing is irreversible without a `y` press.

Actions, in order:
  1. Delete `GOOGLE_TOKEN_PATH` — the refreshable token minted for the
     developer's Google account. Must be re-authorized as the owner.
  2. Delete `STATE_DB_PATH` — the ledger holds developer-side parties,
     people, meetings, terms. Starting fresh is the honest posture:
     the owner's ledger accumulates from their own future meetings.
  3. Archive `AUDIT_LOG_PATH` to a dated side-file, start empty.
  4. Warn if `.env` still names the developer's `OWNER_EMAIL`.

Companion script: `verify_identity.py` proves the swap succeeded.

USAGE:  uv run python scripts/reset_identity.py
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from rel_mcp.config import get_settings


def _confirm(prompt: str) -> bool:
    if os.environ.get("YES") == "1":
        print(f"{prompt} [YES via env]")
        return True
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def _delete_if_exists(path: Path, kind: str) -> None:
    if not path.exists():
        print(f"[skip] {kind} — {path} not present")
        return
    if not _confirm(f"delete {kind} at {path}?"):
        print(f"[keep] {kind}")
        return
    path.unlink()
    print(f"[deleted] {kind}")


def _archive_audit(audit_path: Path) -> None:
    if not audit_path.exists():
        print(f"[skip] audit — {audit_path} not present")
        return
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    archive = audit_path.with_name(f"{audit_path.stem}-pre-reset-{ts}{audit_path.suffix}")
    if not _confirm(f"archive audit log to {archive.name} and start fresh?"):
        print("[keep] audit log left in place")
        return
    shutil.move(str(audit_path), str(archive))
    print(f"[archived] audit → {archive.name}")


def _warn_env(owner_email: str, known_dev_addresses: frozenset[str]) -> None:
    if not known_dev_addresses:
        print()
        print("⚠️  DEV_OWNER_EMAILS is not set — cannot check whether OWNER_EMAIL")
        print("    is still a developer address. Set it in .env to enable this check.")
        return
    if owner_email in known_dev_addresses:
        print()
        print(f"⚠️  OWNER_EMAIL in .env is still a dev address: {owner_email}")
        print("    Update .env to the owner's email BEFORE re-running OAuth.")


def main() -> int:
    settings = get_settings()
    print(f"# reset_identity — targeting {settings.state_db_path.parent}")
    print()

    _delete_if_exists(settings.google_token_path, "Google OAuth token")
    _delete_if_exists(settings.state_db_path, "relationship ledger (state.db)")
    _archive_audit(settings.audit_log_path)
    _warn_env(settings.owner_email, settings.dev_owner_emails_set)

    print()
    print("Next steps:")
    print("  1. Update OWNER_EMAIL in .env to the owner's address (if warned above).")
    print("  2. Get a fresh credentials.json from the owner's Google Cloud project")
    print("     — the current project was set up by the developer.")
    print("  3. Run: uv run python scripts/google_check.py")
    print("     — will open browser; sign in as the owner.")
    print("  4. Run: uv run python scripts/verify_identity.py")
    print("     — proves no dev identity remains.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
