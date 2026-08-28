"""The environment contract lives in two places — `.env.example` and the
`Settings` class — and they drift silently. This test fails the build the
moment they disagree: a variable renamed in code but not in the example,
or added to one side without the other. Fix the drift by editing whichever
file lags."""

from __future__ import annotations

import re
from pathlib import Path

from rel_mcp.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _keys_in_env_example() -> set[str]:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    keys: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Z][A-Z0-9_]*)\s*=", stripped)
        if match:
            keys.add(match.group(1))
    return keys


def _keys_in_settings_class() -> set[str]:
    keys: set[str] = set()
    for field in Settings.model_fields.values():
        # We alias every field explicitly to its UPPER_CASE env name; the
        # contract test checks aliases, not the snake_case attribute names.
        assert field.alias is not None, "every Settings field must set an alias"
        keys.add(field.alias)
    return keys


def test_env_example_and_settings_agree() -> None:
    example = _keys_in_env_example()
    code = _keys_in_settings_class()

    missing_from_example = code - example
    extra_in_example = example - code

    assert not missing_from_example, (
        f"Variables read by Settings but absent from .env.example: {sorted(missing_from_example)}. "
        "Add them to .env.example with a comment."
    )
    assert not extra_in_example, (
        "Variables documented in .env.example but not read by Settings: "
        f"{sorted(extra_in_example)}. Wire them up, or remove them."
    )


def test_env_example_committed() -> None:
    # A missing .env.example silently defeats this whole contract check.
    assert ENV_EXAMPLE.exists(), ".env.example must be checked in at the repo root"
