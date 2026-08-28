"""Prove the developer's identity has been fully swapped out.

Run AFTER `reset_identity.py` + fresh OAuth as the owner. Refuses to say
"pass" unless three things are true:

  1. Google's Gmail profile API reports the connected account exactly
     equals `OWNER_EMAIL`.
  2. The relationship ledger is empty — no parties, no people, no
     meetings, no commitments, no terms.
  3. No hardcoded personal email appears in `src/` or `tests/`.

Exit code 0 if all pass. Any failure exits non-zero AND prints what
needs fixing — never leave a partial handover to a "looks OK" glance.

USAGE:  uv run python scripts/verify_identity.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from googleapiclient.discovery import build

from rel_mcp.config import get_settings
from rel_mcp.errors import RelError
from rel_mcp.google.auth import get_credentials
from rel_mcp.ledger import connect

REPO_ROOT = Path(__file__).resolve().parents[1]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@(?:gmail|hotmail|outlook|yahoo|proton)\.com", re.I)


def _check_connected_account(owner_email: str) -> tuple[bool, str]:
    try:
        settings = get_settings()
        creds = get_credentials(settings)
    except RelError as exc:
        return False, f"auth: {exc}"

    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = gmail.users().getProfile(userId="me").execute()
    connected = str(profile.get("emailAddress", "")).lower()

    if connected != owner_email.lower():
        return False, f"connected as {connected!r} but OWNER_EMAIL is {owner_email!r}"
    return True, f"connected as {connected}"


def _check_ledger_empty(state_db_path: Path) -> tuple[bool, str]:
    if not state_db_path.exists():
        return True, "state.db not present (will be created fresh on next run)"

    tables = ("parties", "people", "meetings", "commitments", "agreed_terms", "contacts_log")
    with connect(state_db_path) as conn:
        counts: dict[str, int] = {}
        for table in tables:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(row[0])

    total = sum(counts.values())
    if total == 0:
        return True, "ledger is empty"
    return False, f"ledger has {total} rows: {counts}"


def _check_no_personal_emails(known_dev_addresses: frozenset[str]) -> tuple[bool, list[str]]:
    findings: list[str] = []
    for base in ("src", "tests"):
        base_path = REPO_ROOT / base
        for py in base_path.rglob("*.py"):
            content = py.read_text(encoding="utf-8")
            for match in EMAIL_RE.finditer(content):
                addr = match.group(0).lower()
                if addr in known_dev_addresses:
                    findings.append(f"{py.relative_to(REPO_ROOT)}: {addr}")
    return (not findings), findings


def main() -> int:
    settings = get_settings()
    print(f"# verify_identity — checking {settings.state_db_path.parent}")
    print()

    all_ok = True

    ok, msg = _check_connected_account(settings.owner_email)
    print(f"[{'ok' if ok else 'FAIL'}] Google account: {msg}")
    all_ok &= ok

    ok, msg = _check_ledger_empty(settings.state_db_path)
    print(f"[{'ok' if ok else 'FAIL'}] Ledger empty: {msg}")
    all_ok &= ok

    ok, findings = _check_no_personal_emails(settings.dev_owner_emails_set)
    print(f"[{'ok' if ok else 'FAIL'}] No personal emails in src/tests")
    for f in findings:
        print(f"    {f}")
    all_ok &= ok

    print()
    if all_ok:
        print("✓ identity verified — safe to hand over")
        return 0
    else:
        print("✗ handover blocked — resolve the failures above and re-run")
        return 1


if __name__ == "__main__":
    sys.exit(main())
