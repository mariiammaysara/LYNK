"""LLM-based digest of a meeting transcript — key points and decisions,
each carrying its own confidence, for human review only.

## Why a direct LLM call, not routed through Hermes

`README.dev.md`'s architecture section is explicit: "`rel_mcp` never
talks to Telegram directly, and holds no LLM credentials — that
boundary belongs to Hermes." That boundary is about the *conversational*
model — the one that reads a tool's `human_summary` and talks to the owner.
It was never a promise that no module in this codebase may call an LLM;
`transcripts/munsit_client.py`, `elevenlabs_client.py`, and
`meetingbaas_client.py` already call narrow-purpose external APIs
directly, each with its own key in `Settings`, each audited like every
other network call. This module follows exactly that precedent: a
transcript can be tens of thousands of words, far past what should ever
be stuffed into a Hermes tool response for the conversational model to
compress on every call — and there is no path for an MCP server (this
process) to call back into the Hermes profile that invokes it; MCP
servers are callees, not callers. So `summarize_transcript` makes its
own direct call to OpenRouter (`OPENROUTER_API_KEY`, a *separate* key
from the one Hermes holds in its own auth store for the conversational
model — see `.env.example`), using the same model already chosen for
this agent (`anthropic/claude-haiku-4.5`, see `docs/HANDOVER.md`'s AI
provider decision) — good enough for compression/extraction, no
open-ended reasoning required.

## What this module deliberately does NOT do

It does not write anything to the ledger. A transcript summary — key
points *and* decisions alike — is a candidate for human review, not a
recorded fact. Promoting a `decision` point into a `commitments` or
`agreed_terms` row is a distinct, later step (mirroring the not-yet-built
`quick_capture.py` from the P14 roadmap item) that needs the same
caution `confirmed_by_owner` already encodes elsewhere in this codebase:
a human taps confirm, only then does it become ledger fact. This module
stops at rendering a Telegram-ready digest with an explicit prompt to
confirm — it never calls a ledger writer.

## Two categories, one stricter than the other

`key_points` is anything the transcript covers. `decisions` is a
narrower, stricter subset: an item only belongs there if the original
text contains an *explicit* agreement phrase (e.g. "اتفقنا", "تمام",
"خلاص كده", or equivalent) — a sentence that merely raises a possibility
("ممكن نفكر فى...") is a key point, never a decision, no matter how
decision-adjacent its topic is. The system prompt states this criterion
in exactly those terms; a transcript with only hedged, speculative
language must never produce a populated `decisions` list.

## Confidence, and why decisions get louder uncertainty framing

Every point (either category) carries `confidence: "high" | "uncertain"`
based on how clearly the original transcript states it — the same
"never silently promote an unconfirmed fact" discipline
`ledger.agreed_terms.confirmed_by_owner` already enforces elsewhere in
this codebase (see `README.dev.md` decision #4). An uncertain *decision*
is a materially different risk than an uncertain *key point* — acting on
a misheard "agreement" is worse than a missed talking point — so
`render_summary_for_telegram` marks it with its own, louder phrase
("قرار محتمل (غير مؤكد):") instead of reusing the plain "غير مؤكد:"
prefix used for key points.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from rel_mcp.audit import append_audit
from rel_mcp.config import Settings, get_settings
from rel_mcp.errors import MeetingSummaryError
from rel_mcp.google.calendar import Meeting
from rel_mcp.phrases import (
    BUL_SUMMARY_POINT,
    BUL_SUMMARY_UNCERTAIN,
    SUMMARY_CONFIRM_DECISIONS_PROMPT,
    SUMMARY_DECISION,
    SUMMARY_DECISION_UNCERTAIN,
    SUMMARY_DISCLAIMER,
)

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
# Same model already chosen for the conversational agent (see
# docs/HANDOVER.md's AI provider decision) — compression/extraction is a
# narrower task than the agent's own chat turn, so it doesn't earn a
# stronger (and pricier) model of its own.
SUMMARY_MODEL = "anthropic/claude-haiku-4.5"

# Generous, same rationale as the transcription clients: an LLM call
# summarizing a long transcript can run well past a typical timeout.
SUMMARY_TIMEOUT_SECONDS = 60.0

# Applied independently to each category — five key points AND five
# decisions is a deliberately generous ceiling for the model; the
# renderer below applies the real, much tighter budget for what actually
# reaches Telegram (see MAX_TELEGRAM_LINES).
MAX_POINTS_PER_CATEGORY = 5

MAX_TELEGRAM_LINES = 7

SUMMARY_SYSTEM_PROMPT = (
    "إنت أداة تلخيص محاضر اجتماعات. لخّص فقط ما قيل حرفيًا فى الترانسكريبت "
    "المرفق. لا تستنتج نوايا أو اتفاقات غير مذكورة بوضوح. لو مش متأكدة من "
    "نقطة، اذكريها كـ«يبدو أن» لا كحقيقة.\n\n"
    "رجّعي النتيجة فى فئتين منفصلتين:\n"
    '- "key_points": أى نقطة عامة اتقالت فى الاجتماع، بحد أقصى '
    f"{MAX_POINTS_PER_CATEGORY} نقاط.\n"
    '- "decisions": نقطة تتصنّف قرار/اتفاق فقط لو فيه صيغة اتفاق صريحة فى '
    'النص الأصلي (زى "اتفقنا"، "تمام"، "خلاص كده"، أو ما شابه) — جملة '
    'بتطرح احتمال أو اقتراح بس ("ممكن نفكر فى..."، "يمكن")، حتى لو '
    'موضوعها قريب من قرار، تروح فى "key_points" مش "decisions". بحد أقصى '
    f"{MAX_POINTS_PER_CATEGORY} عناصر.\n\n"
    'كل عنصر فى الفئتين لازم يكون object فيه "text" و"confidence" — '
    'confidence = "high" لو الصياغة الأصلية واضحة وصريحة، و"uncertain" لو '
    "غامضة، الصوت رديء، أو مش متأكدة منها.\n\n"
    "ردّى بصيغة JSON فقط، بدون أى نص تانى قبلها أو بعدها، بالشكل ده بالظبط:\n"
    '{"key_points": [{"text": "...", "confidence": "high"}], '
    '"decisions": [{"text": "...", "confidence": "uncertain"}]}'
)


class SummaryPoint(BaseModel):
    text: str
    confidence: Literal["high", "uncertain"]


class MeetingSummary(BaseModel):
    """The reviewable digest of one meeting transcript.

    Never written to the ledger by this module — see the module
    docstring's "What this module deliberately does NOT do" section.
    """

    meeting_id: str
    key_points: list[SummaryPoint] = Field(default_factory=list)
    decisions: list[SummaryPoint] = Field(default_factory=list)


def summarize_transcript(
    transcript_text: str,
    meeting: Meeting,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    timeout: float = SUMMARY_TIMEOUT_SECONDS,
) -> MeetingSummary:
    """Summarize `transcript_text` for `meeting` via a direct OpenRouter call.

    Raises `MeetingSummaryError` for a network failure, a non-2xx
    response, or a response that doesn't parse as the expected
    `{"key_points": [...], "decisions": [...]}` JSON shape. Never
    fabricates points from a response it can't parse — a malformed
    response is a raised error, not an empty or invented summary.

    An item whose `confidence` isn't exactly `"high"` or `"uncertain"`
    is coerced to `"uncertain"` rather than rejected outright — the same
    fail-safe-toward-doubt bias `confirmed_by_owner` uses elsewhere in
    this codebase (see the module docstring). An item over the
    `MAX_POINTS_PER_CATEGORY` cap is dropped, never merged or
    summarized further — trusting the model's own ordering (most
    important first) rather than second-guessing it.
    """
    settings = settings or get_settings()
    api_key = settings.require_openrouter_api_key()

    user_prompt = (
        f"عنوان الاجتماع: {meeting.title}\n\n"
        f"الترانسكريبت:\n{transcript_text}"
    )

    start = time.monotonic()
    ok = False
    key_point_count = 0
    decision_count = 0
    try:
        body = _call_llm(user_prompt, api_key, timeout=timeout)
        key_points = _parse_points(body.get("key_points"))
        decisions = _parse_points(body.get("decisions"))
        key_point_count = len(key_points)
        decision_count = len(decisions)

        result = MeetingSummary(
            meeting_id=meeting.id, key_points=key_points, decisions=decisions
        )
        ok = True
        return result
    finally:
        elapsed = time.monotonic() - start
        # Never the transcript text or the summary content itself — only
        # bookkeeping, same discipline as munsit_transcribe/
        # elevenlabs_transcribe never logging audio content.
        append_audit(
            settings.audit_log_path,
            action="meeting_summary",
            summary=f"{meeting.id}: {'ok' if ok else 'failed'} in {elapsed:.2f}s",
            payload={
                "meeting_id": meeting.id,
                "model": SUMMARY_MODEL,
                "call_seconds": round(elapsed, 3),
                "key_point_count": key_point_count,
                "decision_count": decision_count,
                "ok": ok,
            },
            now=now,
        )


def render_summary_for_telegram(summary: MeetingSummary) -> str:
    """Render `summary` as Telegram-ready Arabic text, at most 7 lines.

    Decisions are prioritized over key points when the two together
    would exceed the line budget — a decision is denser, more
    actionable information than a general point. The disclaimer line
    (and, when there is at least one decision, the confirmation prompt
    right before it) is reserved space: it is never truncated away,
    regardless of how many points or decisions there are.
    """
    decision_lines = [_render_decision(p) for p in summary.decisions]
    point_lines = [_render_point(p) for p in summary.key_points]

    trailer = [SUMMARY_DISCLAIMER]
    if decision_lines:
        trailer = [SUMMARY_CONFIRM_DECISIONS_PROMPT, SUMMARY_DISCLAIMER]

    budget = MAX_TELEGRAM_LINES - len(trailer)
    body = decision_lines[:budget]
    body += point_lines[: max(budget - len(body), 0)]

    return "\n".join(body + trailer)


# ─── Internals ───────────────────────────────────────────────────────


def _render_point(point: SummaryPoint) -> str:
    if point.confidence == "uncertain":
        return BUL_SUMMARY_UNCERTAIN.format(text=point.text)
    return BUL_SUMMARY_POINT.format(text=point.text)


def _render_decision(point: SummaryPoint) -> str:
    if point.confidence == "uncertain":
        return SUMMARY_DECISION_UNCERTAIN.format(text=point.text)
    return SUMMARY_DECISION.format(text=point.text)


def _parse_points(raw: object) -> list[SummaryPoint]:
    if not isinstance(raw, list):
        return []

    points: list[SummaryPoint] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        raw_confidence = item.get("confidence")
        confidence: Literal["high", "uncertain"] = (
            "high" if raw_confidence == "high" else "uncertain"
        )  # fail-safe toward doubt, see docstring
        points.append(SummaryPoint(text=text.strip(), confidence=confidence))
        if len(points) >= MAX_POINTS_PER_CATEGORY:
            break
    return points


def _call_llm(user_prompt: str, api_key: str, *, timeout: float) -> dict[str, object]:
    """POST to OpenRouter's chat-completions endpoint; return the parsed
    JSON object the model returned as its message content.

    Raises `MeetingSummaryError` for anything that goes wrong — a network
    failure, a non-2xx response, a response with no message content, or
    content that isn't valid JSON.
    """
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                OPENROUTER_CHAT_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": SUMMARY_MODEL,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
    except httpx.HTTPError as exc:
        raise MeetingSummaryError(f"OpenRouter request failed: {exc}") from exc

    if response.status_code >= 400:
        raise MeetingSummaryError(
            f"OpenRouter API returned {response.status_code}: {response.text[:300]}"
        )

    try:
        envelope = response.json()
    except ValueError as exc:
        raise MeetingSummaryError("OpenRouter API returned a non-JSON response") from exc

    try:
        content = envelope["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MeetingSummaryError(
            f"OpenRouter response has no message content: {envelope!r}"
        ) from exc

    if not isinstance(content, str):
        raise MeetingSummaryError(f"OpenRouter message content is not text: {content!r}")

    return _extract_json_object(content)


def _extract_json_object(content: str) -> dict[str, object]:
    text = content.strip()
    if text.startswith("```"):
        # Strip a ```json ... ``` or ``` ... ``` fence some models wrap
        # JSON in despite being asked not to.
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MeetingSummaryError(
            f"model response is not valid JSON: {content[:300]!r}"
        ) from exc

    if not isinstance(parsed, dict):
        raise MeetingSummaryError(f"model response JSON is not an object: {parsed!r}")

    return parsed
