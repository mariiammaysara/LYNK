"""Every Arabic string the render layer writes lives here.

Two reasons for one file:
  1. Tone review — a native reader can scan phrasing in one place
     without hunting through business logic.
  2. Change safety — golden-file tests break the moment a phrase
     changes, so knowing where phrasing lives makes an intended edit
     obvious (update phrase → update golden → commit both).

No f-string interpolation of user data in this file; templates carry
`{placeholders}` and the caller in `render.py` fills them.
"""

from __future__ import annotations

# ─── Section headers ─────────────────────────────────────────────────
HDR_PARTY = "الجهة: {name}"
HDR_ATTENDEES = "الحضور: {names}"
HDR_LAST_CONTACT = "آخر تواصل: {kind} من {days} يوم"
HDR_OUR_OPEN = "علينا:"
HDR_THEIR_OPEN = "عليهم:"
HDR_TERMS = "متفق عليه:"
HDR_THREADS = "أهم الثريدات:"
HDR_QUESTIONS = "أسئلة مقترحة:"
HDR_FLAGS = "ملاحظات:"

# ─── Bullet templates ────────────────────────────────────────────────
BUL_COMMIT_DATED = "• {text} (يستحق خلال {days} يوم)"
BUL_COMMIT_OVERDUE = "• {text} (متأخر {days} يوم)"
BUL_COMMIT_NO_DUE = "• {text}"
BUL_TERM_CONFIRMED = "• {kind}: {value}"
BUL_TERM_UNCONFIRMED = "• {kind}: {value} (غير مؤكد)"
BUL_THREAD = "• {subject} — من {days} يوم"
BUL_QUESTION = "• {text}"
BUL_FLAG = "• {text}"

# ─── Contact kind labels ─────────────────────────────────────────────
CONTACT_KIND: dict[str, str] = {
    "email": "بريد",
    "meeting": "اجتماع",
    "call": "مكالمة",
}

# ─── Flags ───────────────────────────────────────────────────────────
FLAG_NEW_PARTY = "أول اجتماع مسجّل مع الجهة دى — السجل عندنا فاضى."
FLAG_HAS_OVERDUE = "فيه التزام واحد على الأقل متأخر ميعاده."
FLAG_UNCONFIRMED_TERMS = "فيه أرقام غير مؤكدة فى القايمة — محتاجة توثيق."
FLAG_RECENT_TRANSCRIPT = "فيه محضر مسجّل لاجتماع سابق مع الجهة دى."

# ─── Meeting header ──────────────────────────────────────────────────
HDR_MEETING = "{title} — {when}"
MARK_EXTERNAL = "خارجى"
MARK_INTERNAL = "داخلى"

# ─── Fallbacks ───────────────────────────────────────────────────────
EMPTY_LEDGER_LINE = "أول اجتماع مسجّل مع الجهة دى."

# ─── Meeting summary (meeting_summary.py) ─────────────────────────────
# Same visual convention as BUL_TERM_UNCONFIRMED's "(غير مؤكد)" suffix
# in the ordinary brief — an uncertain point gets a leading, unmissable
# marker instead, since a summary point is a longer line than a term
# value and a trailing tag is easy to skim past.
BUL_SUMMARY_POINT = "• {text}"
BUL_SUMMARY_UNCERTAIN = "غير مؤكد: {text}"

# Decisions get their own, louder markers — a misheard "agreement" is a
# worse failure than a missed talking point, so "uncertain" on a
# decision reads more alarming than the plain BUL_SUMMARY_UNCERTAIN used
# for an ordinary key point.
SUMMARY_DECISION = "• قرار: {text}"
SUMMARY_DECISION_UNCERTAIN = "قرار محتمل (غير مؤكد): {text}"
# Shown only when there is at least one decision — never records a
# confirmation automatically; this just names the future tap-to-confirm
# interaction (P14) that would.
SUMMARY_CONFIRM_DECISIONS_PROMPT = "تأكيد القرارات دي؟"

SUMMARY_DISCLAIMER = "ده ملخص آلي، ممكن يفوته تفاصيل. لو محتاج التأكد من نقطة معينة، قولّي."

# ─── stop_agent tool (server.py) ───────────────────────────────────────
STOP_AGENT_NEEDS_CONFIRM = "لو متأكد تحب توقف الوكيل، ابعت stop_agent مع confirm=true."
STOP_AGENT_ALREADY_STOPPED = "الوكيل متوقف بالفعل."
STOP_AGENT_CONFIRMED = (
    "تم إيقاف الوكيل. لتشغيله تاني، امسح ملف KILL_SWITCH_PATH يدويًا "
    "أو استخدم start_agent (لو موجودة)."
)

# ─── dispatch_meeting_bots tool (server.py, P21) ────────────────────────
DISPATCH_BOTS_NONE_DUE = "مفيش اجتماعات مستحقة لإرسال بوت دلوقتي."
DISPATCH_BOTS_NEEDS_CONFIRM = (
    "فيه {count} اجتماع مستحق لإرسال بوت تسجيل (تكلفة فعلية بالدقيقة): "
    "{names}. لو متأكد، ابعت dispatch_meeting_bots مع confirm=true."
)
DISPATCH_BOTS_MISSING_KEYS = "مفتاح Meeting BaaS أو ElevenLabs مش متظبط."

# ─── get_meeting_summary tool (server.py, P21) ──────────────────────────
GET_MEETING_SUMMARY_NO_TRANSCRIPT = "مفيش محضر مسجّل لهذا الاجتماع."
GET_MEETING_SUMMARY_FAILED = "تعذّر تلخيص المحضر."

# ─── Post-meeting confirmation (post_meeting.py, P14) ──────────────────
# The only two options a confirmation button may resolve to — no free
# text. Hermes renders these as the two inline-keyboard button labels;
# this module only ever decides which commitments need asking.
CONFIRM_OPTION_DONE = "تم"
CONFIRM_OPTION_STILL_OPEN = "لسه مفتوح"

# ─── Daily overdue-commitment chase (chasing.py, P17) ──────────────────
# No party names here deliberately — build_daily_chase_message only ever
# sees `Commitment` rows (party_id, not a resolved name), so the summary
# counts distinct parties rather than naming them.
CHASE_SUMMARY_LINE = "فيه {count} التزام متأخر عبر {party_count} جهة."
CHASE_BULLET_US = "• {text} (علينا)"
CHASE_BULLET_THEM = "• {text} (عليهم)"

# ─── Weekly relationship digest (weekly_summary.py) ────────────────────
WEEKLY_HDR = "ملخص الأسبوع: {start} إلى {end}"
WEEKLY_HDR_CONTACTED = "جهات حصل تواصل معاها:"
WEEKLY_HDR_CLOSED = "التزامات اتقفلت:"
WEEKLY_HDR_NEW = "التزامات جديدة:"
WEEKLY_HDR_OVERDUE = "متأخر حاليًا:"
WEEKLY_BUL_PARTY = "• {name}"
WEEKLY_BUL_COMMIT = "• {party} — {text}"
WEEKLY_BUL_OVERDUE = "• {party} — {text} (متأخر {days} يوم)"
WEEKLY_EMPTY = "مفيش نشاط الأسبوع ده."
