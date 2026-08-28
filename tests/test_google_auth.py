"""Google auth logic — tested without ever touching the network.

The three paths we care about are all decisions made before any HTTP
would happen: (a) a valid saved token skips the browser, (b) an expired
token with a refresh token gets refreshed, (c) a missing credentials
file raises `GoogleAuthError` with a message that tells you what to do.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rel_mcp.errors import GoogleAuthError
from rel_mcp.google.auth import SCOPES, get_credentials


def _make_settings(tmp_path: Path, *, with_creds_file: bool = True) -> MagicMock:
    settings = MagicMock()
    settings.google_credentials_path = tmp_path / "credentials.json"
    settings.google_token_path = tmp_path / "token.json"
    if with_creds_file:
        settings.google_credentials_path.write_text('{"installed": {}}', encoding="utf-8")
    return settings


def test_scopes_are_readonly_only() -> None:
    for scope in SCOPES:
        assert "readonly" in scope, f"scope {scope!r} is not read-only"
    assert isinstance(SCOPES, tuple), "SCOPES must be an immutable tuple"


def test_scopes_cover_calendar_and_gmail_only() -> None:
    assert set(SCOPES) == {
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/gmail.readonly",
    }


def test_missing_credentials_file_raises_with_actionable_message(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, with_creds_file=False)
    with pytest.raises(GoogleAuthError, match="OAuth client file not found"):
        get_credentials(settings)


def test_valid_saved_token_skips_browser(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    settings.google_token_path.write_text("{}", encoding="utf-8")

    valid_creds = MagicMock()
    valid_creds.valid = True

    with (
        patch(
            "rel_mcp.google.auth.Credentials.from_authorized_user_file",
            return_value=valid_creds,
        ),
        patch("rel_mcp.google.auth.InstalledAppFlow") as flow_cls,
    ):
        result = get_credentials(settings)

    assert result is valid_creds
    flow_cls.from_client_secrets_file.assert_not_called()


def test_expired_token_with_refresh_token_gets_refreshed(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    settings.google_token_path.write_text("{}", encoding="utf-8")

    expired_creds = MagicMock()
    expired_creds.valid = False
    expired_creds.expired = True
    expired_creds.refresh_token = "refresh_me"
    expired_creds.to_json = MagicMock(return_value='{"refreshed": true}')

    with (
        patch(
            "rel_mcp.google.auth.Credentials.from_authorized_user_file",
            return_value=expired_creds,
        ),
        patch("rel_mcp.google.auth.InstalledAppFlow") as flow_cls,
    ):
        get_credentials(settings)

    expired_creds.refresh.assert_called_once()
    flow_cls.from_client_secrets_file.assert_not_called()
    assert settings.google_token_path.read_text(encoding="utf-8") == '{"refreshed": true}'


def test_no_saved_token_runs_installed_app_flow(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    # No token file at all.

    fresh_creds = MagicMock()
    fresh_creds.to_json = MagicMock(return_value='{"fresh": true}')

    flow_instance = MagicMock()
    flow_instance.run_local_server = MagicMock(return_value=fresh_creds)

    with patch("rel_mcp.google.auth.InstalledAppFlow") as flow_cls:
        flow_cls.from_client_secrets_file = MagicMock(return_value=flow_instance)
        get_credentials(settings)

    flow_cls.from_client_secrets_file.assert_called_once()
    flow_instance.run_local_server.assert_called_once()
    assert settings.google_token_path.read_text(encoding="utf-8") == '{"fresh": true}'
