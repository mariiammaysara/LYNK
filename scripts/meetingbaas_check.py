"""Send one real Meeting BaaS bot to a meeting and print its bot_id/status.

For manual verification only — this is the only way to confirm the
request/response shape assumed by `rel_mcp.transcripts.meetingbaas_client`
actually matches the live API.

**This costs real money per minute the bot is in the meeting.** It will
not run without an explicit `--confirm` flag — do not add that flag until
you are actually ready to send a bot into a real meeting.

USAGE:
    uv run python scripts/meetingbaas_check.py https://meet.google.com/xxx-yyyy-zzz --confirm

After it returns a bot_id, poll `get_recording_url(bot_id, ...)` — that's
the confirmed-working way to learn when the recording is ready, not a
webhook (see meetingbaas_client.py's module docstring for why).

`--webhook-url` is accepted but currently has no effect: a real test call
showed no webhook delivery. Kept only so a future account-level webhook
integration doesn't need a CLI change.
"""

from __future__ import annotations

import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from rel_mcp.config import get_settings
from rel_mcp.errors import RelError
from rel_mcp.transcripts.meetingbaas_client import send_bot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meeting_url", help="the meeting URL the bot should join")
    parser.add_argument("--bot-name", default="SIM Meeting Bot")
    parser.add_argument(
        "--webhook-url",
        default=None,
        help=(
            "currently has no effect — see run_webhook_receiver.py and "
            "meetingbaas_client.py's module docstring"
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually send the bot — this has a real per-minute cost",
    )
    args = parser.parse_args()

    if not args.confirm:
        print(
            "[STOP] هذا السكربت هيبعت بوت فعلي لاجتماع حقيقي — وده بتكلفة "
            "فعلية بالدقيقة. لو فعلاً جاهزة، شغّليه تاني بإضافة --confirm.",
            file=sys.stderr,
        )
        return 1

    try:
        settings = get_settings()
        api_key = settings.require_meetingbaas_api_key()
        session = send_bot(
            args.meeting_url,
            api_key,
            bot_name=args.bot_name,
            webhook_url=args.webhook_url,
            audit_log_path=settings.audit_log_path,
        )
    except RelError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    print(f"bot_id: {session.bot_id}")
    print(f"status: {session.status}")
    print(f"created_at: {session.created_at}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
