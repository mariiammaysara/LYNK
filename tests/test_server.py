"""Server-layer tests — every tool returns a shape the model can rely on,
and every tool is registered read-only.

These tests do NOT spin up a full stdio server; they call the tool
functions directly with mocked externals. That's the fair test — the
stdio transport is the MCP SDK's business, not ours."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from rel_mcp import server as srv
from rel_mcp.config import Settings, get_settings
from rel_mcp.google.calendar import Meeting
from rel_mcp.transcripts.meetingbaas_client import MEETINGBAAS_SEND_BOT_URL


@pytest.fixture(autouse=True)
def _fresh_settings(valid_env: dict[str, str]) -> None:
    # `valid_env` (in conftest) sets the 9-var contract in os.environ
    # and cleans the LRU cache between tests.
    get_settings.cache_clear()


def _settings() -> Settings:
    return get_settings()


def test_every_tool_is_read_only() -> None:
    """The five registered tools must all carry `read_only_hint=True`.

    A write tool sneaking in without an approval gate would first show
    up as a missing hint here."""
    tools_attr = getattr(srv.mcp, "_tools", None) or getattr(srv.mcp, "tools", None)
    # Support either private or public tool registry on the MCPServer.
    if tools_attr is None:
        # Fall back: check the module-level decorated functions directly.
        pytest.skip("MCPServer tool registry not accessible in this build")
    names = set()
    for _name, tool in dict(tools_attr).items():
        annotations = getattr(tool, "annotations", None)
        assert annotations is not None, f"tool {_name} has no annotations"
        assert getattr(annotations, "read_only_hint", False) is True, (
            f"tool {_name} is missing read_only_hint=True"
        )
        names.add(_name)


def test_kill_switch_blocks_every_read_tool(tmp_path: Path) -> None:
    settings = _settings()
    settings.kill_switch_path.write_text("stopped", encoding="utf-8")

    import asyncio

    for coro in (
        srv.list_upcoming_meetings(),
        srv.list_open_commitments(),
        srv.get_party_status(party_name="anything"),
        srv.get_meeting_brief(meeting_id="whatever"),
    ):
        result = asyncio.run(coro)
        assert result["ok"] is False
        assert "موقّف" in result["human_summary"]


def test_health_reports_kill_switch_status() -> None:
    import asyncio

    settings = _settings()
    settings.kill_switch_path.write_text("", encoding="utf-8")

    with patch("rel_mcp.server.get_credentials", side_effect=Exception("no creds")):
        result = asyncio.run(srv.get_health())

    assert result["ok"] is True
    assert result["kill_switch_active"] is True


def test_health_reports_google_failure_gracefully() -> None:
    import asyncio

    from rel_mcp.errors import GoogleAuthError

    with patch("rel_mcp.server.get_credentials", side_effect=GoogleAuthError("no token")):
        result = asyncio.run(srv.get_health())

    assert result["ok"] is True
    assert result["google_ok"] is False
    assert "no token" in result["google_detail"]


def test_list_upcoming_meetings_returns_structured_shape() -> None:
    import asyncio
    from datetime import UTC, datetime, timedelta

    from rel_mcp.google.calendar import Attendee, Meeting

    fake_now = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    fake_meeting = Meeting(
        id="m1",
        title="Sync",
        start_utc=fake_now + timedelta(hours=2),
        end_utc=fake_now + timedelta(hours=3),
        attendees=[Attendee(email="ext@vendor.example", name="Ext")],
        description="",
        meet_link=None,
        is_external=True,
    )

    with (
        patch("rel_mcp.server.get_credentials", return_value=MagicMock()),
        patch("rel_mcp.server.upcoming_meetings", return_value=[fake_meeting]),
        patch("rel_mcp.server._now_utc", return_value=fake_now),
    ):
        result = asyncio.run(srv.list_upcoming_meetings(within_hours=24))

    assert result["ok"] is True
    assert "خارجى: 1" in result["human_summary"]
    assert result["meetings"][0]["id"] == "m1"
    assert result["meetings"][0]["is_external"] is True


def test_get_party_status_missing_party_fails_cleanly() -> None:
    import asyncio

    result = asyncio.run(srv.get_party_status(party_name="Nonexistent Corp"))
    assert result["ok"] is False
    assert "مافيش جهة" in result["human_summary"]


def test_get_party_status_existing_party_returns_real_data() -> None:
    import asyncio
    from datetime import UTC, datetime

    from rel_mcp.ledger import connect, upsert_party

    settings = _settings()
    with connect(settings.state_db_path) as ledger:
        upsert_party(
            ledger,
            name="Najd Consulting",
            domain="najd-consulting.example",
            now=datetime(2026, 4, 1, tzinfo=UTC),
        )

    result = asyncio.run(srv.get_party_status(party_name="Najd Consulting"))

    assert result["ok"] is True
    assert result["party"]["name"] == "Najd Consulting"
    assert result["party"]["domain"] == "najd-consulting.example"
    assert result["open_commitments"] == []
    assert result["agreed_terms"] == []


def test_get_meeting_brief_on_demand_and_scheduled_produce_identical_briefs() -> None:
    """`get_meeting_brief` (the MCP tool — an on-demand chat request) and
    `get_meeting_brief_for_cron` (the P10 cron worker's entry point) must
    run the exact same `build_brief` logic with the exact same accuracy —
    the only difference between them is bookkeeping (the `source` field
    recorded in the audit log), never the brief content itself."""
    import asyncio
    import json
    from datetime import UTC, datetime, timedelta

    from rel_mcp.google.calendar import Attendee, Meeting

    settings = _settings()
    fake_now = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    fake_meeting = Meeting(
        id="m1",
        title="Sync",
        start_utc=fake_now + timedelta(hours=1),
        end_utc=fake_now + timedelta(hours=2),
        attendees=[Attendee(email="ext@vendor.example", name="Ext")],
        description="",
        meet_link=None,
        is_external=True,
    )

    with (
        patch("rel_mcp.server.get_credentials", return_value=MagicMock()),
        patch("rel_mcp.server.upcoming_meetings", return_value=[fake_meeting]),
        patch("rel_mcp.server._now_utc", return_value=fake_now),
        patch("rel_mcp.server.threads_with", return_value=[]),
    ):
        on_demand = asyncio.run(srv.get_meeting_brief(meeting_id="m1"))
        scheduled = asyncio.run(srv.get_meeting_brief_for_cron(meeting_id="m1"))

    assert on_demand["ok"] is True
    assert scheduled["ok"] is True
    # Same meeting, same ledger, same clock — build_brief must not drift
    # by call path.
    assert on_demand["human_summary"] == scheduled["human_summary"]
    assert on_demand["brief"] == scheduled["brief"]

    audit_lines = [
        json.loads(line)
        for line in settings.audit_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    brief_lines = [e for e in audit_lines if e["action"] == "get_meeting_brief"]
    assert len(brief_lines) == 2
    assert brief_lines[0]["payload"]["source"] == "on_demand"
    assert brief_lines[1]["payload"]["source"] == "scheduled"
    assert brief_lines[0]["payload"]["ok"] is True
    assert brief_lines[1]["payload"]["ok"] is True


def test_p18_instant_query_tools_registered_at_server_startup() -> None:
    """get_party_status, get_meeting_brief, and list_open_commitments must
    be discoverable via the server's own `list_tools()` — the same call a
    real MCP client (Hermes) makes to discover tools on startup — not just
    present as module-level functions that were never wired to `@mcp.tool`."""
    import asyncio

    tools = asyncio.run(srv.mcp.list_tools())
    names = {t.name for t in tools}

    for expected in ("get_party_status", "get_meeting_brief", "list_open_commitments"):
        assert expected in names, f"{expected} is not registered on the running server"
        tool = next(t for t in tools if t.name == expected)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True


def test_list_open_commitments_on_empty_ledger() -> None:
    import asyncio

    result = asyncio.run(srv.list_open_commitments())
    assert result["ok"] is True
    assert result["items"] == []


def test_stop_agent_without_confirm_explains_and_does_not_create_file() -> None:
    import asyncio

    settings = _settings()
    assert not settings.kill_switch_path.exists()

    result = asyncio.run(srv.stop_agent())

    assert result["ok"] is True
    assert "confirm=true" in result["human_summary"]
    assert not settings.kill_switch_path.exists()


def test_stop_agent_without_confirm_still_audits_the_request() -> None:
    """A confirmation request must leave a trace even though it changes
    nothing — otherwise a stop attempt blocked upstream (e.g. by Hermes'
    own approval gate) or never followed up on leaves zero record that
    anyone ever asked to stop the agent."""
    import asyncio
    import json

    settings = _settings()

    asyncio.run(srv.stop_agent())

    lines = [
        json.loads(line)
        for line in settings.audit_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    requested = [e for e in lines if e["action"] == "stop_agent_confirmation_requested"]
    assert len(requested) == 1
    assert requested[0]["payload"]["kill_switch_path"] == str(settings.kill_switch_path)

    # Distinct from, and independent of, an actual confirmed stop — a
    # later confirm=True call gets its own separate action/line, not a
    # merge with this one.
    activated = [e for e in lines if e["action"] == "kill_switch_activated_via_telegram"]
    assert activated == []

    asyncio.run(srv.stop_agent(confirm=True))
    lines_after = [
        json.loads(line)
        for line in settings.audit_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len([e for e in lines_after if e["action"] == "stop_agent_confirmation_requested"]) == 1
    assert len([e for e in lines_after if e["action"] == "kill_switch_activated_via_telegram"]) == 1


def test_stop_agent_with_confirm_creates_kill_switch_and_audits() -> None:
    import asyncio
    import json

    settings = _settings()
    assert not settings.kill_switch_path.exists()

    result = asyncio.run(srv.stop_agent(confirm=True))

    assert result["ok"] is True
    assert "تم إيقاف الوكيل" in result["human_summary"]
    assert settings.kill_switch_path.exists()

    lines = [
        json.loads(line)
        for line in settings.audit_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    kill_lines = [e for e in lines if e["action"] == "kill_switch_activated_via_telegram"]
    assert len(kill_lines) == 1
    assert kill_lines[0]["payload"]["kill_switch_path"] == str(settings.kill_switch_path)


def test_stop_agent_when_already_stopped_reports_status_without_recreating_file() -> None:
    import asyncio
    import json

    settings = _settings()
    settings.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
    settings.kill_switch_path.write_text("SENTINEL", encoding="utf-8")

    result = asyncio.run(srv.stop_agent(confirm=True))

    assert result["ok"] is True
    assert "متوقف بالفعل" in result["human_summary"]
    # The existing file must be left untouched, not truncated/recreated.
    assert settings.kill_switch_path.read_text(encoding="utf-8") == "SENTINEL"

    audit_path = settings.audit_log_path
    lines = (
        [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if audit_path.exists()
        else []
    )
    kill_lines = [e for e in lines if e["action"] == "kill_switch_activated_via_telegram"]
    assert kill_lines == []


def _due_meeting(meeting_id: str, minutes_from_now: int, fake_now: datetime) -> Meeting:
    from datetime import timedelta

    from rel_mcp.google.calendar import Attendee, Meeting

    start = fake_now + timedelta(minutes=minutes_from_now)
    return Meeting(
        id=meeting_id,
        title=f"اجتماع {meeting_id}",
        start_utc=start,
        end_utc=start + timedelta(hours=1),
        attendees=[Attendee(email="ext@vendor.example", name="Ext")],
        description="",
        meet_link="https://meet.google.com/abc-defg-hij",
        is_external=True,
    )


@respx.mock
def test_dispatch_meeting_bots_without_confirm_lists_due_meetings_and_audits() -> None:
    import asyncio
    import json
    from datetime import UTC, datetime

    fake_now = datetime(2026, 4, 10, 8, 0, tzinfo=UTC)
    due = _due_meeting("m-due", 60, fake_now)
    not_due = _due_meeting("m-not-due", 200, fake_now)

    route = respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(200, json={"bot_id": "should-never-be-called"})
    )

    with (
        patch("rel_mcp.server.get_credentials", return_value=MagicMock()),
        patch("rel_mcp.server.upcoming_meetings", return_value=[due, not_due]),
        patch("rel_mcp.server._now_utc", return_value=fake_now),
        patch("rel_mcp.server.run_meeting_bot_cycle") as mock_cycle,
    ):
        result = asyncio.run(srv.dispatch_meeting_bots())

    assert result["ok"] is True
    assert "confirm=true" in result["human_summary"]
    assert result["due_meetings"] == ["اجتماع m-due"]
    mock_cycle.assert_not_called()
    assert not route.called

    settings = _settings()
    lines = [
        json.loads(line)
        for line in settings.audit_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    requested = [
        e for e in lines if e["action"] == "dispatch_meeting_bots_confirmation_requested"
    ]
    assert len(requested) == 1
    assert requested[0]["payload"]["due_count"] == 1


def test_dispatch_meeting_bots_without_confirm_and_nothing_due() -> None:
    import asyncio
    from datetime import UTC, datetime

    fake_now = datetime(2026, 4, 10, 8, 0, tzinfo=UTC)
    not_due = _due_meeting("m-not-due", 200, fake_now)

    with (
        patch("rel_mcp.server.get_credentials", return_value=MagicMock()),
        patch("rel_mcp.server.upcoming_meetings", return_value=[not_due]),
        patch("rel_mcp.server._now_utc", return_value=fake_now),
    ):
        result = asyncio.run(srv.dispatch_meeting_bots())

    assert result["ok"] is True
    assert "مفيش اجتماعات مستحقة" in result["human_summary"]
    assert result["due_meetings"] == []


@respx.mock
def test_dispatch_meeting_bots_with_confirm_sends_bot_via_mocked_http_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end through the REAL (unmocked) run_meeting_bot_cycle and
    meetingbaas_client — only the HTTP layer is mocked via respx. This is
    the test that actually proves no real network call reaches Meeting
    BaaS: `route.called` confirms the mock intercepted it, not a live
    request."""
    import asyncio
    from datetime import UTC, datetime

    from rel_mcp.config import get_settings

    monkeypatch.setenv("MEETINGBAAS_API_KEY", "baas-key")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-key")
    get_settings.cache_clear()

    route = respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(200, json={"bot_id": "bot-mocked", "status": "joining"})
    )

    fake_now = datetime(2026, 4, 10, 8, 0, tzinfo=UTC)
    due = _due_meeting("m-due", 60, fake_now)

    with (
        patch("rel_mcp.server.get_credentials", return_value=MagicMock()),
        patch("rel_mcp.server.upcoming_meetings", return_value=[due]),
        patch("rel_mcp.server._now_utc", return_value=fake_now),
    ):
        result = asyncio.run(srv.dispatch_meeting_bots(confirm=True))

    assert route.called
    assert result["ok"] is True
    assert "bot-mocked" in result["human_summary"]
    assert "بوت اتبعت بنجاح" in result["results"][0]


@respx.mock
def test_dispatch_meeting_bots_with_confirm_send_failure_returns_clean_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Meeting BaaS failure (mocked 500) must surface as a normal
    result line, never as an unhandled exception bubbling into the model
    turn — same discipline every other tool in this file holds to."""
    import asyncio
    from datetime import UTC, datetime

    from rel_mcp.config import get_settings

    monkeypatch.setenv("MEETINGBAAS_API_KEY", "baas-key")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-key")
    get_settings.cache_clear()

    route = respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(500, text="boom")
    )

    fake_now = datetime(2026, 4, 10, 8, 0, tzinfo=UTC)
    due = _due_meeting("m-due", 60, fake_now)

    with (
        patch("rel_mcp.server.get_credentials", return_value=MagicMock()),
        patch("rel_mcp.server.upcoming_meetings", return_value=[due]),
        patch("rel_mcp.server._now_utc", return_value=fake_now),
    ):
        result = asyncio.run(srv.dispatch_meeting_bots(confirm=True))

    assert route.called
    assert result["ok"] is True  # the tool call itself succeeded
    assert "فشل الإرسال" in result["results"][0]


def test_dispatch_meeting_bots_with_confirm_calls_run_meeting_bot_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from datetime import UTC, datetime

    from rel_mcp.config import get_settings

    monkeypatch.setenv("MEETINGBAAS_API_KEY", "baas-key")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-key")
    get_settings.cache_clear()

    fake_now = datetime(2026, 4, 10, 8, 0, tzinfo=UTC)
    due = _due_meeting("m-due", 60, fake_now)

    with (
        patch("rel_mcp.server.get_credentials", return_value=MagicMock()),
        patch("rel_mcp.server.upcoming_meetings", return_value=[due]),
        patch("rel_mcp.server._now_utc", return_value=fake_now),
        patch(
            "rel_mcp.server.run_meeting_bot_cycle",
            return_value=["بوت اتبعت بنجاح: اجتماع m-due — bot_id=bot-123"],
        ) as mock_cycle,
    ):
        result = asyncio.run(srv.dispatch_meeting_bots(confirm=True))

    assert result["ok"] is True
    assert result["results"] == ["بوت اتبعت بنجاح: اجتماع m-due — bot_id=bot-123"]
    assert "bot-123" in result["human_summary"]

    mock_cycle.assert_called_once()
    _, kwargs = mock_cycle.call_args
    assert kwargs["dry_run"] is False
    args = mock_cycle.call_args.args
    assert args[1] == [due]
    assert args[3] == "baas-key"
    assert args[4] == "eleven-key"


def test_dispatch_meeting_bots_with_confirm_missing_api_keys_fails_cleanly() -> None:
    import asyncio
    from datetime import UTC, datetime

    fake_now = datetime(2026, 4, 10, 8, 0, tzinfo=UTC)
    due = _due_meeting("m-due", 60, fake_now)

    with (
        patch("rel_mcp.server.get_credentials", return_value=MagicMock()),
        patch("rel_mcp.server.upcoming_meetings", return_value=[due]),
        patch("rel_mcp.server._now_utc", return_value=fake_now),
        patch("rel_mcp.server.run_meeting_bot_cycle") as mock_cycle,
    ):
        result = asyncio.run(srv.dispatch_meeting_bots(confirm=True))

    assert result["ok"] is False
    assert "Meeting BaaS" in result["human_summary"] or "ElevenLabs" in result["human_summary"]
    mock_cycle.assert_not_called()


def test_get_meeting_summary_returns_rendered_summary_when_transcript_exists() -> None:
    import asyncio
    from datetime import UTC, datetime

    from rel_mcp.ledger import connect, record_meeting, store_transcript
    from rel_mcp.meeting_summary import MeetingSummary, SummaryPoint

    settings = _settings()
    now = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
    with connect(settings.state_db_path) as ledger:
        meeting = record_meeting(
            ledger,
            calendar_id="cal-1",
            party_id=None,
            meeting_date=now,
            title="اجتماع متابعة",
            attendees=[],
            now=now,
        )
        store_transcript(
            ledger,
            meeting_id=meeting.id,
            transcript_text="نص الترانسكريبت",
            source="manual",
            now=now,
        )

    fake_summary = MeetingSummary(
        meeting_id="cal-1",
        key_points=[SummaryPoint(text="نقطة", confidence="high")],
    )

    with patch(
        "rel_mcp.server.summarize_transcript", return_value=fake_summary
    ) as mock_summarize:
        result = asyncio.run(srv.get_meeting_summary(meeting_id=meeting.id))

    assert result["ok"] is True
    assert "نقطة" in result["human_summary"]
    assert "ده ملخص آلي" in result["human_summary"]
    mock_summarize.assert_called_once()
    call_args = mock_summarize.call_args
    assert call_args.args[0] == "نص الترانسكريبت"
    assert call_args.args[1].title == "اجتماع متابعة"


def test_get_meeting_summary_without_transcript_fails_cleanly_and_skips_llm() -> None:
    import asyncio

    with patch("rel_mcp.server.summarize_transcript") as mock_summarize:
        result = asyncio.run(srv.get_meeting_summary(meeting_id=999999))

    assert result["ok"] is False
    assert "مفيش محضر" in result["human_summary"]
    mock_summarize.assert_not_called()


def test_stop_agent_then_every_other_tool_rejects_with_kill_switch() -> None:
    import asyncio

    asyncio.run(srv.stop_agent(confirm=True))

    for coro in (
        srv.list_upcoming_meetings(),
        srv.list_open_commitments(),
        srv.get_party_status(party_name="anything"),
        srv.get_meeting_brief(meeting_id="whatever"),
    ):
        result = asyncio.run(coro)
        assert result["ok"] is False
        assert "موقّف" in result["human_summary"]
