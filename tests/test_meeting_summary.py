"""meeting_summary.py — network-isolated (respx mocks every OpenRouter
call; nothing here reaches the real network).

A crucial caveat about what these tests can and can't prove: they mock
the LLM's response, so they cannot verify real model judgment (e.g.
"would Haiku actually classify a garbled transcript as uncertain?").
What they verify is narrower but still load-bearing: (1) the system
prompt we send actually states the required constraints in the required
terms, (2) our own parsing/rendering code faithfully carries whatever
confidence and category the model assigns — it never re-classifies,
upgrades confidence, or fabricates points beyond what a response
contains, and (3) the disclaimer/confirmation framing is always present
regardless of content."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from rel_mcp.config import Settings, get_settings
from rel_mcp.errors import MeetingSummaryError
from rel_mcp.google.calendar import Meeting
from rel_mcp.meeting_summary import (
    MAX_POINTS_PER_CATEGORY,
    MAX_TELEGRAM_LINES,
    OPENROUTER_CHAT_URL,
    SUMMARY_SYSTEM_PROMPT,
    MeetingSummary,
    SummaryPoint,
    render_summary_for_telegram,
    summarize_transcript,
)

FIXED_NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)


def _meeting(meeting_id: str = "m1", title: str = "اجتماع متابعة") -> Meeting:
    start = FIXED_NOW
    return Meeting(
        id=meeting_id,
        title=title,
        start_utc=start,
        end_utc=start,
        attendees=[],
        description="",
        meet_link=None,
        is_external=True,
    )


def _mock_llm_response(key_points: list[dict[str, str]], decisions: list[dict[str, str]]) -> None:
    respx.post(OPENROUTER_CHAT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"key_points": key_points, "decisions": decisions},
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )
    )


@pytest.fixture
def settings_with_key(valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_settings.cache_clear()
    return get_settings()


def _read_audit_lines(audit_log_path: Path) -> list[dict[str, object]]:
    if not audit_log_path.exists():
        return []
    return [json.loads(line) for line in audit_log_path.read_text(encoding="utf-8").splitlines()]


# ─── summarize_transcript ──────────────────────────────────────────────


@respx.mock
def test_clear_transcript_produces_high_confidence_points(settings_with_key: Settings) -> None:
    _mock_llm_response(
        key_points=[{"text": "ناقشوا الميزانية الجديدة", "confidence": "high"}],
        decisions=[{"text": "اتفقنا على تسليم التقرير الأسبوع الجاى", "confidence": "high"}],
    )

    result = summarize_transcript(
        "كلام واضح ومفهوم بالكامل", _meeting(), settings=settings_with_key, now=FIXED_NOW
    )

    assert result.key_points[0].confidence == "high"
    assert result.decisions[0].confidence == "high"
    assert result.decisions[0].text == "اتفقنا على تسليم التقرير الأسبوع الجاى"


@respx.mock
def test_garbled_transcript_yields_few_or_uncertain_points(settings_with_key: Settings) -> None:
    # Simulates what a real garbled/low-quality-audio sample (see
    # docs/P21_FINDINGS.md's Munsit findings) should look like once
    # summarized: sparse, and marked uncertain rather than presented as
    # confident fact.
    _mock_llm_response(
        key_points=[{"text": "يبدو أن الموضوع كان عن جدول زمني", "confidence": "uncertain"}],
        decisions=[],
    )

    result = summarize_transcript(
        "نص مفكك وغير مفهوم لغويًا", _meeting(), settings=settings_with_key, now=FIXED_NOW
    )

    assert len(result.key_points) == 1
    assert result.key_points[0].confidence == "uncertain"
    assert result.decisions == []


@respx.mock
def test_decisions_only_from_explicit_agreement_language(settings_with_key: Settings) -> None:
    """A merely-speculative sentence ("ممكن نفكر فى...") must never land
    in `decisions`, even when its topic is decision-adjacent. This test
    can only verify our code doesn't move or reclassify what the model
    returns — real model judgment isn't testable offline — so it also
    asserts the constraint is actually stated to the model."""
    speculative_text = "ممكن نفكر فى تأجيل الموعد لو لزم الأمر"
    _mock_llm_response(
        key_points=[{"text": speculative_text, "confidence": "high"}],
        decisions=[],
    )

    result = summarize_transcript(
        "الترانسكريبت", _meeting(), settings=settings_with_key, now=FIXED_NOW
    )

    assert result.decisions == []
    assert any(p.text == speculative_text for p in result.key_points)

    # The strict criterion must actually be sent to the model, not just
    # assumed — this is the part a unit test CAN verify.
    assert "اتفقنا" in SUMMARY_SYSTEM_PROMPT
    assert "ممكن نفكر" in SUMMARY_SYSTEM_PROMPT


@respx.mock
def test_points_are_capped_per_category(settings_with_key: Settings) -> None:
    many = [{"text": f"نقطة {i}", "confidence": "high"} for i in range(10)]
    _mock_llm_response(key_points=many, decisions=many)

    result = summarize_transcript(
        "نص طويل", _meeting(), settings=settings_with_key, now=FIXED_NOW
    )

    assert len(result.key_points) == MAX_POINTS_PER_CATEGORY
    assert len(result.decisions) == MAX_POINTS_PER_CATEGORY


@respx.mock
def test_invalid_confidence_value_is_coerced_to_uncertain(settings_with_key: Settings) -> None:
    _mock_llm_response(
        key_points=[{"text": "نقطة", "confidence": "very sure"}], decisions=[]
    )

    result = summarize_transcript(
        "نص", _meeting(), settings=settings_with_key, now=FIXED_NOW
    )

    assert result.key_points[0].confidence == "uncertain"


@respx.mock
def test_non_json_model_response_raises_meeting_summary_error(
    settings_with_key: Settings,
) -> None:
    respx.post(OPENROUTER_CHAT_URL).mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "not json at all"}}]}
        )
    )

    with pytest.raises(MeetingSummaryError):
        summarize_transcript("نص", _meeting(), settings=settings_with_key, now=FIXED_NOW)


@respx.mock
def test_server_error_raises_meeting_summary_error(settings_with_key: Settings) -> None:
    respx.post(OPENROUTER_CHAT_URL).mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(MeetingSummaryError):
        summarize_transcript("نص", _meeting(), settings=settings_with_key, now=FIXED_NOW)


@respx.mock
def test_network_failure_raises_meeting_summary_error(settings_with_key: Settings) -> None:
    respx.post(OPENROUTER_CHAT_URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(MeetingSummaryError):
        summarize_transcript("نص", _meeting(), settings=settings_with_key, now=FIXED_NOW)


@respx.mock
def test_successful_call_is_audited_without_transcript_or_summary_content(
    settings_with_key: Settings,
) -> None:
    transcript_text = "هذا نص الترانسكريبت السري جدًا"
    _mock_llm_response(
        key_points=[{"text": "نقطة حساسة جدًا", "confidence": "high"}], decisions=[]
    )

    summarize_transcript(
        transcript_text, _meeting(), settings=settings_with_key, now=FIXED_NOW
    )

    lines = _read_audit_lines(settings_with_key.audit_log_path)
    brief_lines = [entry for entry in lines if entry["action"] == "meeting_summary"]
    assert len(brief_lines) == 1
    entry = brief_lines[0]
    assert entry["payload"]["ok"] is True
    assert entry["payload"]["key_point_count"] == 1
    assert entry["payload"]["decision_count"] == 0

    raw = json.dumps(entry, ensure_ascii=False)
    assert transcript_text not in raw
    assert "نقطة حساسة جدًا" not in raw


@respx.mock
def test_failed_call_is_still_audited(settings_with_key: Settings) -> None:
    respx.post(OPENROUTER_CHAT_URL).mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(MeetingSummaryError):
        summarize_transcript("نص", _meeting(), settings=settings_with_key, now=FIXED_NOW)

    lines = _read_audit_lines(settings_with_key.audit_log_path)
    brief_lines = [entry for entry in lines if entry["action"] == "meeting_summary"]
    assert len(brief_lines) == 1
    assert brief_lines[0]["payload"]["ok"] is False


def test_module_never_imports_the_ledger() -> None:
    """`summarize_transcript` must never write commitments or agreed_terms
    — a static guard, since a runtime test can't prove an absence of a
    write path as convincingly as the source simply never importing the
    writer functions."""
    import inspect

    import rel_mcp.meeting_summary as mod

    source = inspect.getsource(mod)
    assert "rel_mcp.ledger" not in source
    assert "import ledger" not in source


# ─── render_summary_for_telegram ───────────────────────────────────────


def test_disclaimer_is_always_the_last_line() -> None:
    cases = [
        MeetingSummary(meeting_id="m1"),
        MeetingSummary(
            meeting_id="m1",
            key_points=[SummaryPoint(text="نقطة", confidence="high")],
        ),
        MeetingSummary(
            meeting_id="m1",
            decisions=[SummaryPoint(text="قرار", confidence="uncertain")],
        ),
        MeetingSummary(
            meeting_id="m1",
            key_points=[SummaryPoint(text=f"نقطة {i}", confidence="high") for i in range(5)],
            decisions=[SummaryPoint(text=f"قرار {i}", confidence="high") for i in range(5)],
        ),
    ]
    for summary in cases:
        text = render_summary_for_telegram(summary)
        lines = text.splitlines()
        assert lines[-1] == "ده ملخص آلي، ممكن يفوته تفاصيل. لو محتاج التأكد من نقطة معينة، قولّي."
        assert len(lines) <= MAX_TELEGRAM_LINES


def test_uncertain_key_point_gets_plain_uncertain_prefix() -> None:
    summary = MeetingSummary(
        meeting_id="m1",
        key_points=[SummaryPoint(text="موعد التسليم", confidence="uncertain")],
    )
    text = render_summary_for_telegram(summary)
    assert "غير مؤكد: موعد التسليم" in text


def test_uncertain_decision_gets_louder_probable_decision_prefix() -> None:
    summary = MeetingSummary(
        meeting_id="m1",
        decisions=[SummaryPoint(text="تأجيل الاجتماع", confidence="uncertain")],
    )
    text = render_summary_for_telegram(summary)
    assert "قرار محتمل (غير مؤكد): تأجيل الاجتماع" in text
    # Must read differently from the plain key-point uncertainty marker.
    assert "غير مؤكد: تأجيل الاجتماع" not in text


def test_confident_decision_gets_decision_prefix() -> None:
    summary = MeetingSummary(
        meeting_id="m1",
        decisions=[SummaryPoint(text="تسليم المستند", confidence="high")],
    )
    text = render_summary_for_telegram(summary)
    assert "قرار: تسليم المستند" in text


def test_confirm_decisions_prompt_appears_only_when_there_are_decisions() -> None:
    with_decision = MeetingSummary(
        meeting_id="m1", decisions=[SummaryPoint(text="قرار", confidence="high")]
    )
    without_decision = MeetingSummary(
        meeting_id="m1", key_points=[SummaryPoint(text="نقطة", confidence="high")]
    )

    assert "تأكيد القرارات دي؟" in render_summary_for_telegram(with_decision)
    assert "تأكيد القرارات دي؟" not in render_summary_for_telegram(without_decision)


def test_decisions_are_prioritized_over_key_points_when_over_budget() -> None:
    # 5 decisions + 5 key points would need 12 lines; the 7-line budget
    # (minus 2 reserved for the confirm prompt + disclaimer) leaves room
    # for 5 lines of content — decisions must fill that before any key
    # point does.
    summary = MeetingSummary(
        meeting_id="m1",
        key_points=[SummaryPoint(text=f"نقطة {i}", confidence="high") for i in range(5)],
        decisions=[SummaryPoint(text=f"قرار {i}", confidence="high") for i in range(5)],
    )
    text = render_summary_for_telegram(summary)
    lines = text.splitlines()

    assert len(lines) == MAX_TELEGRAM_LINES
    assert all("قرار" in line for line in lines[:5])
    assert not any(f"نقطة {i}" in text for i in range(5))
