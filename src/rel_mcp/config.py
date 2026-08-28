"""Settings loaded once from the environment.

`DRY_RUN` defaults to true — the safe default, so a fresh checkout or a
missing `.env` cannot accidentally send anything to the outside world.
Anything else the code needs is required; startup fails loudly if it's
missing, rather than the code discovering it two hours later during a
scheduled brief.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from rel_mcp.errors import ConfigError


class Settings(BaseSettings):
    """The 9-variable environment contract — see `.env.example`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # An unknown env var is almost always a typo; catch it at startup
        # rather than silently ignoring a misspelled OWNER_EMAIL.
        extra="ignore",
        case_sensitive=True,
    )

    environment: Literal["local", "staging", "production"] = Field(alias="ENVIRONMENT")
    dry_run: bool = Field(default=True, alias="DRY_RUN")
    google_credentials_path: Path = Field(alias="GOOGLE_CREDENTIALS_PATH")
    google_token_path: Path = Field(alias="GOOGLE_TOKEN_PATH")
    audit_log_path: Path = Field(alias="AUDIT_LOG_PATH")
    state_db_path: Path = Field(alias="STATE_DB_PATH")
    timezone: str = Field(alias="TIMEZONE")
    owner_email: str = Field(alias="OWNER_EMAIL", min_length=3)

    @field_validator("owner_email")
    @classmethod
    def _validate_owner_email(cls, value: str) -> str:
        # A single `@` with something on both sides is all the shape-check
        # this earns — real verification is that Google's own profile API
        # returns the same address (see `scripts/google_check.py`).
        if value.count("@") != 1 or value.startswith("@") or value.endswith("@"):
            raise ValueError(f"not an email: {value!r}")
        return value.lower()
    kill_switch_path: Path = Field(alias="KILL_SWITCH_PATH")

    # Optional, unlike the core 9-var contract: most tool calls never touch
    # Munsit, so a deployment without it configured should still start.
    # A caller that actually needs transcription calls
    # `require_munsit_api_key()` and fails there, not at process boot.
    munsit_api_key: str | None = Field(default=None, alias="MUNSIT_API_KEY")

    def require_munsit_api_key(self) -> str:
        """Return `MUNSIT_API_KEY`, or raise a clear `ConfigError` if unset."""
        if not self.munsit_api_key:
            raise ConfigError(
                "MUNSIT_API_KEY is not set. Add it to .env before calling any "
                "Munsit transcription function."
            )
        return self.munsit_api_key

    # Same pattern, same reason: optional, checked lazily at the call site
    # that actually needs it, not at process boot.
    meetingbaas_api_key: str | None = Field(default=None, alias="MEETINGBAAS_API_KEY")

    def require_meetingbaas_api_key(self) -> str:
        """Return `MEETINGBAAS_API_KEY`, or raise a clear `ConfigError` if unset."""
        if not self.meetingbaas_api_key:
            raise ConfigError(
                "MEETINGBAAS_API_KEY is not set. Add it to .env before calling any "
                "Meeting BaaS bot function."
            )
        return self.meetingbaas_api_key

    # Same pattern again: optional, checked lazily at the call site.
    elevenlabs_api_key: str | None = Field(default=None, alias="ELEVENLABS_API_KEY")

    def require_elevenlabs_api_key(self) -> str:
        """Return `ELEVENLABS_API_KEY`, or raise a clear `ConfigError` if unset."""
        if not self.elevenlabs_api_key:
            raise ConfigError(
                "ELEVENLABS_API_KEY is not set. Add it to .env before calling any "
                "ElevenLabs transcription function."
            )
        return self.elevenlabs_api_key

    # Same pattern again. This is a *separate* OpenRouter key from the one
    # Hermes holds in its own auth store (`hermes auth add openrouter`) for
    # the conversational agent model — see `meeting_summary.py`'s module
    # docstring for why the summarizer calls OpenRouter directly instead of
    # routing through Hermes, and thus needs its own credential here.
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")

    def require_openrouter_api_key(self) -> str:
        """Return `OPENROUTER_API_KEY`, or raise a clear `ConfigError` if unset."""
        if not self.openrouter_api_key:
            raise ConfigError(
                "OPENROUTER_API_KEY is not set. Add it to .env before calling any "
                "meeting-summary function."
            )
        return self.openrouter_api_key

    # Optional: comma-separated "known developer" email addresses, used only
    # by scripts/reset_identity.py and scripts/verify_identity.py to detect
    # leftover dev-account state before handover. Not needed for normal
    # operation, so a deployment without it configured still starts fine.
    dev_owner_emails: str | None = Field(default=None, alias="DEV_OWNER_EMAILS")

    @property
    def dev_owner_emails_set(self) -> frozenset[str]:
        """Parse `DEV_OWNER_EMAILS` into a lowercase set; empty if unset."""
        if not self.dev_owner_emails:
            return frozenset()
        return frozenset(
            email.strip().lower()
            for email in self.dev_owner_emails.split(",")
            if email.strip()
        )

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        # zoneinfo raises on load if the zone isn't known — surface it now,
        # not the first time a cron job tries to convert a UTC timestamp.
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {value!r}") from exc
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process; re-raise validation errors as `ConfigError`."""
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as exc:
        raise ConfigError(f"invalid environment: {exc}") from exc
