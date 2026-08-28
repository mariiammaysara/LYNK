"""Render a `Brief` to Arabic text for Telegram.

Two rules the render obeys:

1. **Empty sections get dropped.** A brief with no last contact, no
   commitments, and no threads is shorter, not padded. The only line
   that appears when data is missing is a single flag at the end that
   names the absence honestly ("أول اجتماع مسجّل مع الجهة دى").

2. **≤ 15 lines.** Telegram messages that exceed a phone screen get
   skimmed and misread. Threads and questions are truncated to 3 items
   each; the caller can raise those limits in `build_brief` if a
   specific brief needs to.

The renderer contains no Arabic string literals — every visible word
lives in `phrases.py`. That's what lets a native reader review tone in
one file, and what makes the golden-file diffs meaningful.
"""

from __future__ import annotations

from rel_mcp.brief import Brief, OpenCommitmentRef
from rel_mcp.phrases import (
    BUL_COMMIT_DATED,
    BUL_COMMIT_NO_DUE,
    BUL_COMMIT_OVERDUE,
    BUL_FLAG,
    BUL_QUESTION,
    BUL_TERM_CONFIRMED,
    BUL_TERM_UNCONFIRMED,
    BUL_THREAD,
    CONTACT_KIND,
    FLAG_HAS_OVERDUE,
    FLAG_NEW_PARTY,
    FLAG_RECENT_TRANSCRIPT,
    FLAG_UNCONFIRMED_TERMS,
    HDR_ATTENDEES,
    HDR_FLAGS,
    HDR_LAST_CONTACT,
    HDR_MEETING,
    HDR_OUR_OPEN,
    HDR_PARTY,
    HDR_QUESTIONS,
    HDR_TERMS,
    HDR_THEIR_OPEN,
    HDR_THREADS,
    MARK_EXTERNAL,
    MARK_INTERNAL,
)

FLAG_STRINGS: dict[str, str] = {
    "new_party": FLAG_NEW_PARTY,
    "has_overdue": FLAG_HAS_OVERDUE,
    "unconfirmed_terms": FLAG_UNCONFIRMED_TERMS,
}

MAX_LINES = 15


def render(brief: Brief) -> str:
    """Return the brief as Telegram-ready plain text."""
    lines: list[str] = []

    marker = MARK_EXTERNAL if brief.is_external else MARK_INTERNAL
    header = HDR_MEETING.format(title=brief.meeting_title, when=brief.starts_at_local_iso)
    lines.append(f"[{marker}] {header}")

    if brief.party_name:
        lines.append(HDR_PARTY.format(name=brief.party_name))

    if brief.attendee_names:
        lines.append(HDR_ATTENDEES.format(names="، ".join(brief.attendee_names)))

    if brief.last_contact:
        kind = CONTACT_KIND.get(brief.last_contact.kind, brief.last_contact.kind)
        lines.append(
            HDR_LAST_CONTACT.format(kind=kind, days=brief.last_contact.days_ago)
        )

    if brief.our_open:
        lines.append(HDR_OUR_OPEN)
        lines.extend(_render_commitments(brief.our_open))

    if brief.their_open:
        lines.append(HDR_THEIR_OPEN)
        lines.extend(_render_commitments(brief.their_open))

    if brief.terms:
        lines.append(HDR_TERMS)
        for term in brief.terms:
            tpl = BUL_TERM_CONFIRMED if term.confirmed else BUL_TERM_UNCONFIRMED
            lines.append(tpl.format(kind=term.kind, value=term.value))

    if brief.threads:
        lines.append(HDR_THREADS)
        for thread in brief.threads:
            lines.append(BUL_THREAD.format(subject=thread.subject, days=thread.days_ago))

    if brief.suggested_questions:
        lines.append(HDR_QUESTIONS)
        for q in brief.suggested_questions:
            lines.append(BUL_QUESTION.format(text=q))

    if brief.flags or brief.has_recent_transcript:
        lines.append(HDR_FLAGS)
        for f in brief.flags:
            phrased = FLAG_STRINGS.get(f, f)
            lines.append(BUL_FLAG.format(text=phrased))
        if brief.has_recent_transcript:
            lines.append(BUL_FLAG.format(text=FLAG_RECENT_TRANSCRIPT))

    return "\n".join(_cap(lines, MAX_LINES))


def _render_commitments(commits: list[OpenCommitmentRef]) -> list[str]:
    out: list[str] = []
    for c in commits:
        if c.days_to_due is None:
            out.append(BUL_COMMIT_NO_DUE.format(text=c.text))
        elif c.overdue:
            out.append(BUL_COMMIT_OVERDUE.format(text=c.text, days=abs(c.days_to_due)))
        else:
            out.append(BUL_COMMIT_DATED.format(text=c.text, days=c.days_to_due))
    return out


def _cap(lines: list[str], limit: int) -> list[str]:
    if len(lines) <= limit:
        return lines
    return lines[:limit]
