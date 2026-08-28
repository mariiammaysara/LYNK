"""Config loads the contract or refuses to start."""

from __future__ import annotations

import pytest

from rel_mcp.config import get_settings
from rel_mcp.errors import ConfigError

# ── Munsit (optional, P21) ──────────────────────────────────────────────


def test_munsit_api_key_defaults_to_none(valid_env: dict[str, str]) -> None:
    # No MUNSIT_API_KEY in valid_env — startup must still succeed, unlike
    # the core 9-var contract.
    assert get_settings().munsit_api_key is None


def test_require_munsit_api_key_raises_when_unset(valid_env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        get_settings().require_munsit_api_key()


def test_require_munsit_api_key_returns_value_when_set(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUNSIT_API_KEY", "test-key-123")
    assert get_settings().require_munsit_api_key() == "test-key-123"


# ── Meeting BaaS (optional, P21) ────────────────────────────────────────


def test_meetingbaas_api_key_defaults_to_none(valid_env: dict[str, str]) -> None:
    assert get_settings().meetingbaas_api_key is None


def test_require_meetingbaas_api_key_raises_when_unset(valid_env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        get_settings().require_meetingbaas_api_key()


def test_require_meetingbaas_api_key_returns_value_when_set(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEETINGBAAS_API_KEY", "test-key-456")
    assert get_settings().require_meetingbaas_api_key() == "test-key-456"


# ── ElevenLabs (optional, P21) ──────────────────────────────────────────


def test_elevenlabs_api_key_defaults_to_none(valid_env: dict[str, str]) -> None:
    assert get_settings().elevenlabs_api_key is None


def test_require_elevenlabs_api_key_raises_when_unset(valid_env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        get_settings().require_elevenlabs_api_key()


def test_require_elevenlabs_api_key_returns_value_when_set(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-789")
    assert get_settings().require_elevenlabs_api_key() == "test-key-789"


def test_loads_valid_environment(valid_env: dict[str, str]) -> None:
    settings = get_settings()
    assert settings.environment == "local"
    assert settings.dry_run is True
    assert settings.timezone == "Asia/Riyadh"
    assert settings.owner_email == "owner@example.com"


def test_missing_required_var_raises_config_error(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OWNER_EMAIL")
    with pytest.raises(ConfigError):
        get_settings()


def test_unknown_timezone_raises_config_error(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TIMEZONE", "Mars/Olympus_Mons")
    with pytest.raises(ConfigError):
        get_settings()


def test_bad_email_raises_config_error(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OWNER_EMAIL", "not-an-email")
    with pytest.raises(ConfigError):
        get_settings()


def test_dry_run_defaults_to_true_when_unset(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DRY_RUN")
    assert get_settings().dry_run is True


def test_owner_email_is_lowercased(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OWNER_EMAIL", "OWNER@Example.COM")
    assert get_settings().owner_email == "owner@example.com"
