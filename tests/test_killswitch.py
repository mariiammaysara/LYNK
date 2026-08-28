"""The kill switch is an on-disk file. If present, no action runs."""

from __future__ import annotations

from pathlib import Path

import pytest

from rel_mcp.errors import KillSwitchError
from rel_mcp.killswitch import enforce, is_stopped


def test_absent_file_means_not_stopped(tmp_path: Path) -> None:
    assert is_stopped(tmp_path / "STOP") is False


def test_present_file_means_stopped(tmp_path: Path) -> None:
    stop = tmp_path / "STOP"
    stop.write_text("")
    assert is_stopped(stop) is True


def test_enforce_raises_when_stopped(tmp_path: Path) -> None:
    stop = tmp_path / "STOP"
    stop.write_text("")
    with pytest.raises(KillSwitchError, match="kill switch is active"):
        enforce(stop)


def test_enforce_passes_when_not_stopped(tmp_path: Path) -> None:
    # Must not raise.
    enforce(tmp_path / "STOP")


def test_directory_at_kill_path_also_stops(tmp_path: Path) -> None:
    # A stray directory named STOP is still a positive signal — the check
    # is "does this path exist" not "is it a file". A false positive here
    # is cheap; a false negative is not.
    (tmp_path / "STOP").mkdir()
    assert is_stopped(tmp_path / "STOP") is True
