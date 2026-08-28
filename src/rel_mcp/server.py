"""MCP stdio server for `rel-mcp`.

This is the seam where the library above becomes a Hermes tool. Two
rules the wiring here obeys:

**Nothing writes to stdout.** stdout carries the JSON-RPC protocol
frames; a stray `print()` corrupts the stream and Hermes drops the
connection. Every user-visible message from a tool goes into the
returned dict; every diagnostic goes to stderr.

**Every tool is read-only, marked `readOnlyHint=True`, and returns a
dict** — with two deliberate exceptions: `stop_agent` (creates the
kill-switch file) and `dispatch_meeting_bots` (sends real,
per-minute-billed Meeting BaaS bots). Every write capability beyond
those two still comes in a later phase behind an approval gate (see
README.dev.md decision #2); both exceptions share the same shape —
gated by their own explicit `confirm=True` parameter and, as long as
the Hermes profile keeps `trust: untrusted` (mandatory — Hermes
otherwise trusts a server's own `readOnlyHint` claim and skips its own
approval prompt), by Hermes' own approval prompt on top of that. That
approval prompt only actually blocks on a real answer inside a live
gateway session or an interactive `chat` session with a real
terminal — a one-shot `-z` call has neither, so it auto-denies
near-instantly (see `docs/HANDOVER.md`'s "اختبار أدوات الكتابة"
section for why, verified against Hermes' own source — the same
section any future write tool needs testing through, not `-z`). Every
other tool returns a dict shaped
`{human_summary: str, ...structured}` — the model reads the summary,
structured fields are there if it needs them. Errors return as
`_fail(...)` dicts, never as unhandled exceptions bubbling into the
model turn.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from rel_mcp.audit import append_audit
from rel_mcp.brief import build_brief
from rel_mcp.config import Settings, get_settings
from rel_mcp.errors import ConfigError, GoogleAuthError, KillSwitchError, MeetingSummaryError
from rel_mcp.google.auth import get_credentials
from rel_mcp.google.calendar import Meeting, upcoming_meetings
from rel_mcp.google.gmail import Thread, threads_with
from rel_mcp.killswitch import enforce
from rel_mcp.ledger import connect, get_transcript, open_commitments
from rel_mcp.meeting_summary import render_summary_for_telegram, summarize_transcript
from rel_mcp.orchestrator import run_meeting_bot_cycle, should_send_bot
from rel_mcp.phrases import (
    DISPATCH_BOTS_MISSING_KEYS,
    DISPATCH_BOTS_NEEDS_CONFIRM,
    DISPATCH_BOTS_NONE_DUE,
    GET_MEETING_SUMMARY_FAILED,
    GET_MEETING_SUMMARY_NO_TRANSCRIPT,
    STOP_AGENT_ALREADY_STOPPED,
    STOP_AGENT_CONFIRMED,
    STOP_AGENT_NEEDS_CONFIRM,
)
from rel_mcp.render import render as render_brief

logger = logging.getLogger("rel_mcp.server")

mcp = MCPServer(
    name="rel",
    instructions=(
        "أدوات قراءة للاجتماعات والعلاقات، وأداتا كتابة محميتان بتأكيد "
        "صريح (stop_agent, dispatch_meeting_bots). كل اللى بترجعه دالة "
        "human_summary + بيانات مهيكلة."
    ),
)

_READ_ONLY: Final = ToolAnnotations(read_only_hint=True)
# Shared by the two non-read-only tools below (stop_agent,
# dispatch_meeting_bots). Both are idempotent in effect — stop_agent via
# the "already stopped" check, dispatch_meeting_bots via
# run_meeting_bot_cycle's own sent_bots dedup — and neither is
# destructive: a kill-switch file is trivially removable, and a
# re-confirmed dispatch call simply skips meetings already sent a bot.
_CONFIRM_GATED_WRITE: Final = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True
)


# ─── Result helpers ──────────────────────────────────────────────────


def _ok(summary: str, **fields: Any) -> dict[str, Any]:
    return {"ok": True, "human_summary": summary, **fields}


def _fail(summary: str, *, detail: str = "") -> dict[str, Any]:
    return {"ok": False, "human_summary": summary, "detail": detail}


def _stopped(exc: KillSwitchError) -> dict[str, Any]:
    return _fail(
        "الوكيل موقّف بمفتاح الإيقاف. مافيش أى قراءة أو كتابة بتشتغل.",
        detail=str(exc),
    )


# ─── State ───────────────────────────────────────────────────────────


def _load_settings() -> Settings:
    return get_settings()


def _local(dt: datetime, tz_name: str) -> str:
    return dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")


def _now_utc() -> datetime:
    # The one place a wall-clock read happens in the server layer; every
    # deeper module takes `now` as a parameter, so this is the only
    # source of non-determinism and it's isolated to tool entry.
    return datetime.now(UTC)


# ─── Tools ───────────────────────────────────────────────────────────


@mcp.tool(annotations=_READ_ONLY)
async def list_upcoming_meetings(within_hours: int = 48) -> dict[str, Any]:
    """اجتماعات الفترة الجاية من الكالندر — عناوين، توقيت، داخلى/خارجى."""
    settings = _load_settings()
    try:
        enforce(settings.kill_switch_path)
    except KillSwitchError as exc:
        return _stopped(exc)

    try:
        creds = get_credentials(settings)
    except GoogleAuthError as exc:
        return _fail("مافيش اتصال بجوجل — التوكن ناقص أو منتهى.", detail=str(exc))

    now = _now_utc()
    meetings = upcoming_meetings(
        creds,
        now=now,
        owner_email=settings.owner_email,
        within_hours=within_hours,
    )

    ext = sum(1 for m in meetings if m.is_external)
    summary = (
        f"عدد الاجتماعات فى الـ {within_hours} ساعة الجاية: {len(meetings)} · خارجى: {ext}"
    )
    return _ok(
        summary,
        meetings=[_meeting_row(m, settings.timezone) for m in meetings],
        generated_at=now.isoformat(),
    )


async def _run_meeting_brief(meeting_id: str, *, source: str) -> dict[str, Any]:
    """Shared implementation behind `get_meeting_brief` (the MCP tool —
    called on demand, e.g. when the owner asks for a brief in chat) and
    `get_meeting_brief_for_cron` (called by the P10 cron worker,
    `scripts/pre_meeting_brief.py`, on its 15-minute pulse).

    `build_brief` and everything around it (calendar read, ledger read,
    render) runs identically either way — same function, same code path,
    same accuracy. The *only* difference between a scheduled brief and an
    on-demand one is who asked and why, which is not visible from inside
    `build_brief` itself. That's why the distinction lives in exactly one
    place: the `source` value ("on_demand" | "scheduled") recorded on
    every audit line this function writes, rather than as two diverging
    implementations.
    """
    settings = _load_settings()
    now = _now_utc()

    def _audited(result: dict[str, Any]) -> dict[str, Any]:
        append_audit(
            settings.audit_log_path,
            action="get_meeting_brief",
            summary=result["human_summary"],
            payload={"meeting_id": meeting_id, "source": source, "ok": result["ok"]},
            now=now,
        )
        return result

    try:
        enforce(settings.kill_switch_path)
    except KillSwitchError as exc:
        return _audited(_stopped(exc))

    try:
        creds = get_credentials(settings)
    except GoogleAuthError as exc:
        return _audited(_fail("مافيش اتصال بجوجل.", detail=str(exc)))

    meetings = upcoming_meetings(
        creds,
        now=now - timedelta(hours=1),  # allow "just about to start" meetings
        owner_email=settings.owner_email,
        within_hours=72,
    )
    meeting = next((m for m in meetings if m.id == meeting_id), None)
    if meeting is None:
        return _audited(
            _fail(f"مافيش اجتماع بالمعرّف ده فى نافذة الـ ٧٢ ساعة: {meeting_id}")
        )

    external_emails = [a.email for a in meeting.attendees if a.email]

    with connect(settings.state_db_path) as ledger:
        threads: list[Thread] = []
        if external_emails:
            try:
                threads = threads_with(
                    creds,
                    participants=external_emails,
                    now=now,
                    audit_log_path=settings.audit_log_path,
                )
            except Exception as exc:
                logger.warning("gmail read failed: %s", exc)

        brief = build_brief(
            meeting=meeting,
            ledger=ledger,
            threads=threads,
            now=now,
            starts_at_local_iso=_local(meeting.start_utc, settings.timezone),
        )

    text = render_brief(brief)
    return _audited(
        _ok(
            text,
            brief=brief.model_dump(mode="json"),
            meeting_id=meeting_id,
            generated_at=now.isoformat(),
        )
    )


@mcp.tool(annotations=_READ_ONLY)
async def get_meeting_brief(meeting_id: str) -> dict[str, Any]:
    """Brief كامل لاجتماع محدّد: الجهة، الالتزامات، الأرقام، الثريدات."""
    return await _run_meeting_brief(meeting_id, source="on_demand")


async def get_meeting_brief_for_cron(meeting_id: str) -> dict[str, Any]:
    """Same brief as `get_meeting_brief`, for the P10 cron worker.

    Deliberately not decorated with `@mcp.tool` — this must never be
    reachable by the model, only by `scripts/pre_meeting_brief.py`. The
    only behavioral difference from `get_meeting_brief` is the `source`
    value this records in the audit log.
    """
    return await _run_meeting_brief(meeting_id, source="scheduled")


@mcp.tool(annotations=_READ_ONLY)
async def get_party_status(party_name: str) -> dict[str, Any]:
    """آخر موقف مع جهة: الالتزامات المفتوحة والأرقام المتفق عليها."""
    settings = _load_settings()
    try:
        enforce(settings.kill_switch_path)
    except KillSwitchError as exc:
        return _stopped(exc)

    with connect(settings.state_db_path) as ledger:
        party = _find_party_by_name(ledger, party_name)
        if party is None:
            return _fail(f"مافيش جهة بالاسم ده فى السجل: {party_name!r}")

        opens = open_commitments(ledger, party.id)
        from rel_mcp.ledger import agreed_terms

        terms = agreed_terms(ledger, party.id)

    summary = (
        f"{party.name} — التزامات مفتوحة: {len(opens)} · أرقام متفق عليها: {len(terms)}"
    )
    return _ok(
        summary,
        party={"id": party.id, "name": party.name, "domain": party.domain},
        open_commitments=[c.model_dump(mode="json") for c in opens],
        agreed_terms=[t.model_dump(mode="json") for t in terms],
    )


@mcp.tool(annotations=_READ_ONLY)
async def list_open_commitments() -> dict[str, Any]:
    """كل الالتزامات المفتوحة عبر كل الجهات، مرتّبة حسب الاستحقاق."""
    settings = _load_settings()
    try:
        enforce(settings.kill_switch_path)
    except KillSwitchError as exc:
        return _stopped(exc)

    with connect(settings.state_db_path) as ledger:
        rows = ledger.execute(
            "SELECT c.*, p.name AS party_name FROM commitments c"
            " JOIN parties p ON p.id = c.party_id"
            " WHERE c.status = 'open'"
            " ORDER BY c.due_date IS NULL, c.due_date ASC, c.id ASC"
        ).fetchall()

    now = _now_utc()
    items: list[dict[str, Any]] = []
    overdue_count = 0
    for r in rows:
        due_iso = r["due_date"]
        overdue = False
        if due_iso:
            due_dt = datetime.fromisoformat(due_iso).astimezone(UTC)
            overdue = due_dt.date() < now.date()
        if overdue:
            overdue_count += 1
        items.append(
            {
                "id": r["id"],
                "party_name": r["party_name"],
                "side": r["side"],
                "text": r["text"],
                "due_date": due_iso,
                "overdue": overdue,
            }
        )

    summary = f"مفتوحة: {len(items)} · متأخر: {overdue_count}"
    return _ok(summary, items=items, generated_at=now.isoformat())


@mcp.tool(annotations=_READ_ONLY)
async def get_health() -> dict[str, Any]:
    """حالة الاتصال بجوجل، مفتاح الإيقاف، وآخر سطر فى سجل التدقيق."""
    settings = _load_settings()
    kill = settings.kill_switch_path.exists()

    google_ok = True
    google_detail = ""
    try:
        get_credentials(settings)
    except Exception as exc:
        google_ok = False
        google_detail = str(exc)

    last_audit = _tail_audit(settings.audit_log_path)

    summary = (
        f"جوجل: {'ok' if google_ok else 'fail'} · "
        f"kill_switch: {'active' if kill else 'off'}"
    )
    return _ok(
        summary,
        google_ok=google_ok,
        google_detail=google_detail,
        kill_switch_active=kill,
        last_audit_line=last_audit,
        environment=settings.environment,
        dry_run=settings.dry_run,
    )


@mcp.tool(annotations=_CONFIRM_GATED_WRITE)
async def stop_agent(confirm: bool = False) -> dict[str, Any]:
    """إيقاف طارئ فورى للوكيل. محتاج confirm=true صراحة، منعًا لإيقاف بالغلط."""
    settings = _load_settings()

    # Deliberately does NOT call enforce(settings.kill_switch_path) like
    # every other tool — this tool must still work (and report status
    # honestly) when the agent is already stopped; that's the whole
    # point of the "already stopped" branch below.
    if not confirm:
        # Recorded as its own event, independent of whatever the caller
        # does next — a confirmation request is a real thing that
        # happened (someone asked to stop the agent) even though it has
        # zero effect on kill-switch state. Without this line, an
        # unconfirmed stop request left no trace in the audit log at
        # all: it could be blocked upstream by Hermes' own approval gate
        # before ever reaching this tool, or a human could simply never
        # follow up, and either way the ledger of "what was asked of
        # this agent" would have a gap.
        append_audit(
            settings.audit_log_path,
            action="stop_agent_confirmation_requested",
            summary="stop_agent called without confirm=true — awaiting confirmation",
            payload={"kill_switch_path": str(settings.kill_switch_path)},
        )
        return _ok(STOP_AGENT_NEEDS_CONFIRM)

    if settings.kill_switch_path.exists():
        return _ok(STOP_AGENT_ALREADY_STOPPED)

    settings.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
    # Same mechanism killswitch.py already checks for — presence of the
    # file, not its content. An empty file is enough.
    settings.kill_switch_path.write_text("", encoding="utf-8")

    append_audit(
        settings.audit_log_path,
        action="kill_switch_activated_via_telegram",
        summary="kill switch activated via stop_agent tool",
        payload={"kill_switch_path": str(settings.kill_switch_path)},
    )

    return _ok(STOP_AGENT_CONFIRMED)


@mcp.tool(annotations=_CONFIRM_GATED_WRITE)
async def dispatch_meeting_bots(confirm: bool = False) -> dict[str, Any]:
    """إرسال بوت تسجيل Meeting BaaS للاجتماعات المستحقة (نافذة ٤٥-٧٥
    دقيقة). محتاج confirm=true صراحة — تكلفة فعلية بالدقيقة."""
    settings = _load_settings()
    try:
        enforce(settings.kill_switch_path)
    except KillSwitchError as exc:
        return _stopped(exc)

    try:
        creds = get_credentials(settings)
    except GoogleAuthError as exc:
        return _fail("مافيش اتصال بجوجل.", detail=str(exc))

    now = _now_utc()
    # 3h is deliberately wider than the 45-75min should_send_bot window
    # itself — same margin logic as get_meeting_brief's 72h lookahead:
    # enough room that a slightly-early or slightly-late confirm=false
    # preview still shows a meeting that's about to enter the window,
    # not just ones already inside it.
    meetings = upcoming_meetings(
        creds, now=now, owner_email=settings.owner_email, within_hours=3
    )
    due = [m for m in meetings if should_send_bot(m, now)]

    if not confirm:
        # Same discipline as stop_agent's confirmation-request line: an
        # unconfirmed dispatch request is a real event worth a trace,
        # independent of whether a later confirm=true call follows —
        # see the stop_agent comment above for why this matters when the
        # call could be blocked upstream by Hermes' own approval gate
        # before ever reaching a confirmed attempt.
        append_audit(
            settings.audit_log_path,
            action="dispatch_meeting_bots_confirmation_requested",
            summary=f"dispatch_meeting_bots called without confirm=true — {len(due)} due",
            payload={"due_count": len(due)},
        )
        if not due:
            return _ok(DISPATCH_BOTS_NONE_DUE, due_meetings=[])
        names = "، ".join(m.title for m in due)
        return _ok(
            DISPATCH_BOTS_NEEDS_CONFIRM.format(count=len(due), names=names),
            due_meetings=[m.title for m in due],
        )

    try:
        meetingbaas_key = settings.require_meetingbaas_api_key()
        elevenlabs_key = settings.require_elevenlabs_api_key()
    except ConfigError as exc:
        return _fail(DISPATCH_BOTS_MISSING_KEYS, detail=str(exc))

    # webhook_url is deliberately not sourced from config/env: P21's real
    # test (docs/P21_FINDINGS.md) confirmed Meeting BaaS's per-request
    # webhook_url never fires, and meetingbaas_client.send_bot already
    # `del`s the parameter rather than sending it — adding a WEBHOOK_URL
    # setting here would configure a value the client throws away.
    # get_recording_url polling is the only confirmed-working retrieval
    # path (see meetingbaas_client.py's module docstring).
    with connect(settings.state_db_path) as ledger:
        results = run_meeting_bot_cycle(
            ledger,
            meetings,
            now,
            meetingbaas_key,
            elevenlabs_key,
            audit_log_path=settings.audit_log_path,
            dry_run=False,
        )

    summary = "\n".join(results) if results else DISPATCH_BOTS_NONE_DUE
    return _ok(summary, results=results)


@mcp.tool(annotations=_READ_ONLY)
async def get_meeting_summary(meeting_id: int) -> dict[str, Any]:
    """ملخص محضر اجتماع مخزّن (لو موجود) — نقاط عامة وقرارات، بمستوى
    ثقة لكل بند. قراءة وعرض فقط؛ لا تكتب فى الـledger."""
    settings = _load_settings()
    try:
        enforce(settings.kill_switch_path)
    except KillSwitchError as exc:
        return _stopped(exc)

    with connect(settings.state_db_path) as ledger:
        transcript_text = get_transcript(ledger, meeting_id)
        if transcript_text is None:
            return _fail(GET_MEETING_SUMMARY_NO_TRANSCRIPT)

        row = ledger.execute(
            "SELECT calendar_id, title, meeting_date FROM meetings WHERE id = ?",
            (meeting_id,),
        ).fetchone()

    if row is None:
        # get_transcript succeeding already implies a meetings row exists
        # (meeting_transcripts.meeting_id is a foreign key) — this branch
        # is defensive, not expected to fire.
        return _fail(GET_MEETING_SUMMARY_NO_TRANSCRIPT)

    # summarize_transcript only reads `.title` and `.id` off the Meeting
    # it's given — the rest of these fields are unused placeholders, not
    # fabricated business data. The real title and calendar id come
    # straight from the ledger row already tied to this transcript.
    meeting_date = datetime.fromisoformat(row["meeting_date"]).astimezone(UTC)
    meeting_stub = Meeting(
        id=row["calendar_id"],
        title=row["title"],
        start_utc=meeting_date,
        end_utc=meeting_date,
        attendees=[],
        description="",
        meet_link=None,
        is_external=True,
    )

    try:
        digest = summarize_transcript(transcript_text, meeting_stub, settings=settings)
    except MeetingSummaryError as exc:
        return _fail(GET_MEETING_SUMMARY_FAILED, detail=str(exc))

    text = render_summary_for_telegram(digest)
    return _ok(text, meeting_summary=digest.model_dump(mode="json"))


# ─── Internals ───────────────────────────────────────────────────────


def _meeting_row(m: Meeting, tz_name: str) -> dict[str, Any]:
    return {
        "id": m.id,
        "title": m.title,
        "starts_at_local": _local(m.start_utc, tz_name),
        "starts_at_utc": m.start_utc.isoformat(),
        "is_external": m.is_external,
        "attendees": [{"email": a.email, "name": a.name} for a in m.attendees],
        "meet_link": m.meet_link,
    }


def _find_party_by_name(conn: sqlite3.Connection, name: str) -> Any:
    from rel_mcp.ledger import _party_from_row

    row = conn.execute(
        "SELECT * FROM parties WHERE name = ? COLLATE NOCASE"
        " OR name LIKE ? COLLATE NOCASE LIMIT 1",
        (name, f"%{name}%"),
    ).fetchone()
    return _party_from_row(row) if row else None


def _tail_audit(audit_path: Any) -> str:
    try:
        text = audit_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _configure_logging() -> None:
    """Route logging to stderr. stdout is reserved for JSON-RPC frames."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def main() -> None:
    _configure_logging()
    # Warm-load settings so a broken .env fails at server boot, not at
    # first tool call — Hermes surfaces the traceback in its own logs.
    settings = _load_settings()
    append_audit(
        settings.audit_log_path,
        action="server_start",
        summary=f"rel_mcp server starting in {settings.environment}",
    )
    mcp.run()


if __name__ == "__main__":
    main()
