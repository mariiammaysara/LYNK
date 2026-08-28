"""should_send_bot — deterministic, offline. Every case named after the
one condition it tests. run_meeting_bot_cycle tests below mock the
Meeting BaaS HTTP call with respx, same as test_meetingbaas_client.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from rel_mcp.google.calendar import Meeting
from rel_mcp.ledger import connect, has_bot_been_requested, mark_bot_requested
from rel_mcp.orchestrator import run_meeting_bot_cycle, should_send_bot
from rel_mcp.transcripts.meetingbaas_client import MEETINGBAAS_SEND_BOT_URL

NOW = datetime(2026, 4, 10, 8, 0, tzinfo=UTC)


def _meeting(
    *,
    meeting_id: str = "cal-1",
    minutes_from_now: int,
    is_external: bool = True,
    meet_link: str | None = "https://meet.google.com/abc-defg-hij",
) -> Meeting:
    start = NOW + timedelta(minutes=minutes_from_now)
    return Meeting(
        id=meeting_id,
        title=f"اجتماع {meeting_id}",
        start_utc=start,
        end_utc=start + timedelta(hours=1),
        attendees=[],
        description="",
        meet_link=meet_link,
        is_external=is_external,
    )


def test_meeting_in_the_middle_of_the_window_sends() -> None:
    assert should_send_bot(_meeting(minutes_from_now=60), NOW) is True


def test_meeting_at_lower_boundary_sends() -> None:
    assert should_send_bot(_meeting(minutes_from_now=45), NOW) is True


def test_meeting_at_upper_boundary_sends() -> None:
    assert should_send_bot(_meeting(minutes_from_now=75), NOW) is True


def test_meeting_too_soon_does_not_send() -> None:
    # 30 minutes out — inside P10's brief window territory, but not
    # yet the bot-send window.
    assert should_send_bot(_meeting(minutes_from_now=30), NOW) is False


def test_meeting_too_far_out_does_not_send() -> None:
    assert should_send_bot(_meeting(minutes_from_now=120), NOW) is False


def test_meeting_already_started_does_not_send() -> None:
    assert should_send_bot(_meeting(minutes_from_now=-5), NOW) is False


def test_internal_meeting_does_not_send_even_in_window() -> None:
    assert should_send_bot(_meeting(minutes_from_now=60, is_external=False), NOW) is False


def test_meeting_without_a_link_does_not_send() -> None:
    assert should_send_bot(_meeting(minutes_from_now=60, meet_link=None), NOW) is False


def test_internal_meeting_without_a_link_still_does_not_send() -> None:
    # Belt and suspenders: both disqualifying conditions at once must
    # not somehow cancel out to True.
    assert (
        should_send_bot(_meeting(minutes_from_now=60, is_external=False, meet_link=None), NOW)
        is False
    )


# ── run_meeting_bot_cycle ───────────────────────────────────────────────


@respx.mock
def test_cycle_sends_a_bot_to_a_due_meeting(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(200, json={"bot_id": "bot-abc", "status": "joining"})
    )

    with connect(tmp_path / "s.db") as ledger:
        results = run_meeting_bot_cycle(
            ledger,
            [_meeting(minutes_from_now=60)],
            NOW,
            "baas-key",
            "eleven-key",
            audit_log_path=audit_log_path,
            dry_run=False,
        )
        assert has_bot_been_requested(ledger, "cal-1") is True
        row = ledger.execute("SELECT bot_id, status FROM sent_bots").fetchone()
        assert row["bot_id"] == "bot-abc"
        assert row["status"] == "requested"

    assert len(results) == 1
    assert "bot-abc" in results[0]


@respx.mock
def test_cycle_skips_meeting_outside_the_window(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    route = respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(200, json={"bot_id": "bot-abc"})
    )

    with connect(tmp_path / "s.db") as ledger:
        results = run_meeting_bot_cycle(
            ledger,
            [_meeting(minutes_from_now=120)],
            NOW,
            "baas-key",
            "eleven-key",
            audit_log_path=audit_log_path,
            dry_run=False,
        )
        assert has_bot_been_requested(ledger, "cal-1") is False

    assert not route.called
    assert "خارج نافذة" in results[0]


@respx.mock
def test_cycle_does_not_send_a_second_bot_for_an_already_requested_meeting(
    tmp_path: Path,
) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    route = respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(200, json={"bot_id": "bot-abc"})
    )

    with connect(tmp_path / "s.db") as ledger:
        meeting = _meeting(minutes_from_now=60)
        first = run_meeting_bot_cycle(
            ledger, [meeting], NOW, "baas-key", "eleven-key",
            audit_log_path=audit_log_path, dry_run=False,
        )
        second = run_meeting_bot_cycle(
            ledger, [meeting], NOW, "baas-key", "eleven-key",
            audit_log_path=audit_log_path, dry_run=False,
        )

    assert route.call_count == 1  # only the first cycle actually sent
    assert "بوت اتبعت بنجاح" in first[0]
    assert "اتطلب قبل كده" in second[0]


@respx.mock
def test_cycle_continues_after_one_meeting_fails_to_send(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        side_effect=[
            httpx.Response(500, text="boom"),
            httpx.Response(200, json={"bot_id": "bot-second"}),
        ]
    )

    with connect(tmp_path / "s.db") as ledger:
        results = run_meeting_bot_cycle(
            ledger,
            [
                _meeting(meeting_id="cal-fails", minutes_from_now=60),
                _meeting(meeting_id="cal-succeeds", minutes_from_now=61),
            ],
            NOW,
            "baas-key",
            "eleven-key",
            audit_log_path=audit_log_path,
            dry_run=False,
        )

        rows = {
            r["meeting_id"]: (r["status"], r["bot_id"])
            for r in ledger.execute("SELECT meeting_id, status, bot_id FROM sent_bots")
        }

    assert len(results) == 2
    assert "فشل الإرسال" in results[0]
    assert "بوت اتبعت بنجاح" in results[1]
    assert rows["cal-fails"] == ("failed", None)
    assert rows["cal-succeeds"] == ("requested", "bot-second")


@respx.mock
def test_cycle_handles_unique_race_on_sent_bots_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulates a race: another writer (e.g. an overlapping cron pulse)
    # inserts the sent_bots row for this meeting_id between
    # has_bot_been_requested's check and this cycle's own
    # mark_bot_requested insert. We force that ordering directly: call
    # mark_bot_requested once here, before run_meeting_bot_cycle is
    # even invoked, then monkeypatch has_bot_been_requested to still
    # report False (as it would if the race won by a hair) so the
    # cycle's own mark_bot_requested call is the one that collides.
    audit_log_path = tmp_path / "audit.jsonl"
    route = respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(200, json={"bot_id": "bot-abc"})
    )

    with connect(tmp_path / "s.db") as ledger:
        mark_bot_requested(ledger, meeting_id="cal-1", now=NOW)

        monkeypatch.setattr(
            "rel_mcp.orchestrator.has_bot_been_requested", lambda *_a, **_k: False
        )

        results = run_meeting_bot_cycle(
            ledger,
            [_meeting(minutes_from_now=60)],
            NOW,
            "baas-key",
            "eleven-key",
            audit_log_path=audit_log_path,
            dry_run=False,
        )

    assert not route.called
    assert len(results) == 1
    assert "تخطي" in results[0]
    assert "تعارض" in results[0]


@respx.mock
def test_cycle_dry_run_touches_neither_ledger_nor_network(tmp_path: Path) -> None:
    audit_log_path = tmp_path / "audit.jsonl"
    route = respx.post(MEETINGBAAS_SEND_BOT_URL).mock(
        return_value=httpx.Response(200, json={"bot_id": "bot-abc"})
    )

    with connect(tmp_path / "s.db") as ledger:
        results = run_meeting_bot_cycle(
            ledger,
            [_meeting(minutes_from_now=60)],
            NOW,
            "baas-key",
            "eleven-key",
            audit_log_path=audit_log_path,
            # dry_run defaults to True — not passed explicitly here,
            # exercising the actual production default.
        )
        assert has_bot_been_requested(ledger, "cal-1") is False

    assert not route.called
    assert "[dry-run]" in results[0]
