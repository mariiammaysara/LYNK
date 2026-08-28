"""Shared fixtures. Every test that touches `get_settings` needs a fresh
cache — the LRU wrapper otherwise carries the first test's env into the
next one."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from rel_mcp import config


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture
def valid_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Populate os.environ with a valid 9-var contract pointing at tmp_path."""
    env = {
        "ENVIRONMENT": "local",
        "DRY_RUN": "true",
        "GOOGLE_CREDENTIALS_PATH": str(tmp_path / "credentials.json"),
        "GOOGLE_TOKEN_PATH": str(tmp_path / "token.json"),
        "AUDIT_LOG_PATH": str(tmp_path / "audit.jsonl"),
        "STATE_DB_PATH": str(tmp_path / "state.db"),
        "TIMEZONE": "Asia/Riyadh",
        "OWNER_EMAIL": "owner@example.com",
        "KILL_SWITCH_PATH": str(tmp_path / "STOP"),
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Also prevent stray .env from leaking in during tests.
    monkeypatch.chdir(tmp_path)
    return env
