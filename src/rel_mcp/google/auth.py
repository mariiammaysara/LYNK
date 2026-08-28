"""Google OAuth for a single owner.

The whole file is one thing: turn `credentials.json` (a Google Cloud OAuth
client) plus a browser consent into a refreshable `Credentials` object,
persisted to `GOOGLE_TOKEN_PATH`. Everything downstream reads that token
and never touches OAuth again until it expires.

## Scopes

`SCOPES` is a single frozen constant, `readonly` for both calendar and
gmail. **Do not append to it.** Every write capability the agent grows
(compose draft, calendar event, etc.) is a separate consent screen and
belongs behind the approval gate — added deliberately in later phases,
not smuggled in here.

## Errors

Anything that goes wrong — missing credentials file, refresh failure,
consent screen abandoned — is re-raised as `GoogleAuthError` with the
specific reason, so upstream callers catch one exception type and can
log a coherent message. The underlying `google-auth` exceptions are
kept as `__cause__` for post-mortem debugging.
"""

from __future__ import annotations

import json
import os
import platform
import stat
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from rel_mcp.config import Settings
from rel_mcp.errors import GoogleAuthError

# Frozen tuple, not a list. A caller trying to `.append(...)` fails loudly.
SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
)


def get_credentials(settings: Settings) -> Credentials:
    """Return a valid `Credentials` for the owner, refreshing or prompting as needed.

    Behavior in order:
      1. If a saved token exists and is valid, return it — no browser.
      2. If it exists but is expired and has a refresh token, refresh it.
      3. If it doesn't exist or refresh fails, run `InstalledAppFlow` —
         this opens a browser window once. Then save.

    On success the token is written to `settings.google_token_path` with
    owner-read/write permissions (0600) so a shared machine doesn't leak it.
    """
    creds_path = settings.google_credentials_path
    token_path = settings.google_token_path

    if not creds_path.exists():
        raise GoogleAuthError(
            f"OAuth client file not found at {creds_path}. Download it from "
            "Google Cloud Console → APIs & Services → Credentials, and place "
            "it at the path in GOOGLE_CREDENTIALS_PATH."
        )

    creds = _load_saved_token(token_path)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            # A refresh failure usually means the token was revoked or
            # 7-day-expired (Testing-mode OAuth apps). Fall through to a
            # fresh flow rather than crashing — the caller can decide
            # whether opening a browser is acceptable.
            creds = None
            refresh_error: RefreshError | None = exc
        else:
            _save_token(creds, token_path)
            return creds
    else:
        refresh_error = None

    if creds is None:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), list(SCOPES))
            # NOTE: port fixed at 8080 for headless server SSH forwarding.
            # See docs/HANDOVER.md § "OAuth على سيرفر headless"
            creds = flow.run_local_server(port=8080, open_browser=False)
        except Exception as exc:
            cause = refresh_error or exc
            raise GoogleAuthError(
                f"OAuth consent flow failed: {exc}. If a token used to work, "
                "it may have been revoked or hit the 7-day expiry that applies "
                "to Testing-mode OAuth apps."
            ) from cause

    _save_token(creds, token_path)
    return creds


def _load_saved_token(token_path: Path) -> Credentials | None:
    if not token_path.exists():
        return None
    try:
        creds: Credentials = Credentials.from_authorized_user_file(str(token_path), list(SCOPES))
        return creds
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise GoogleAuthError(
            f"saved token at {token_path} is unreadable: {exc}. Delete the file "
            "and re-authorize."
        ) from exc


def _save_token(creds: Credentials, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")

    # chmod 600 has no meaning on Windows (ACLs are the mechanism there),
    # so we set it only where it matters. On POSIX a stray group-readable
    # token on a shared VPS would leak the owner's session.
    if platform.system() != "Windows":
        os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)
