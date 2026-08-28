"""File-based kill switch.

Presence of `KILL_SWITCH_PATH` on disk stops every action. The check is
deliberately not a config flag or environment variable — those need a
restart to take effect, and the whole point of a kill switch is that
a non-technical operator can stop the agent right now, from any shell,
without editing code.

Restart semantics: the file survives reboots on purpose. Removing the
file is a two-step decision (find it, delete it), which is the right
friction for un-stopping a stopped agent.
"""

from __future__ import annotations

from pathlib import Path

from rel_mcp.errors import KillSwitchError


def is_stopped(kill_switch_path: Path) -> bool:
    """True iff the kill-switch file exists."""
    return kill_switch_path.exists()


def enforce(kill_switch_path: Path) -> None:
    """Raise `KillSwitchError` if the switch is on. Call at every action entry point."""
    if is_stopped(kill_switch_path):
        raise KillSwitchError(
            f"kill switch is active ({kill_switch_path}); remove the file to resume"
        )
