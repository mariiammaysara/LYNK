"""Exception hierarchy for rel_mcp.

Every error the code raises inherits from `RelError`, so callers can catch
one type at the boundary and know it belongs to us. Each subclass names a
distinct failure surface — configuration, Google auth, upstream Google
APIs, or the deliberate kill switch — because messages that read the same
under `str(e)` still need to be handled and logged differently upstream.
"""


class RelError(Exception):
    """Root of every error raised by rel_mcp."""


class ConfigError(RelError):
    """The environment or a config file is missing or invalid."""


class GoogleAuthError(RelError):
    """OAuth flow, token refresh, or credential file failed."""


class UpstreamError(RelError):
    """A Google API call failed after auth succeeded."""


class TranscriptionError(RelError):
    """A transcription engine call (e.g. Munsit) failed — network, auth, or a malformed response."""


class MeetingBotError(RelError):
    """A meeting-recording bot call (e.g. Meeting BaaS) failed — joining a call is a distinct
    failure surface from transcribing the resulting audio, so this stays separate from
    `TranscriptionError`."""


class ElevenLabsError(RelError):
    """An ElevenLabs Scribe transcription call failed — network, auth, or a malformed response.
    Kept separate from `TranscriptionError` (Munsit) so a caller trying both engines can tell
    which one failed without parsing the message."""


class MeetingSummaryError(RelError):
    """A transcript-summarization LLM call failed — network, auth, or a response that
    doesn't parse as the expected points/confidence JSON shape."""


class DelegationError(RelError):
    """A delegation call referenced a commitment that doesn't exist."""


class KillSwitchError(RelError):
    """The kill-switch file is present — no action may run."""
