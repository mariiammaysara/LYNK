# P21 — Live test findings (2026-08-23)

Permanent record of every real technical discovery from today's P21 test
(meeting bot + Arabic transcription) — so nobody (not Mariam, not anyone
after her) has to redo the same trial-and-error discovery. Every point
here is confirmed by a real API response or an actual live test, not an
assumption from public docs.

See `docs/HANDOVER.md` for the general project context; this file is for
P21-specific technical details only.

---

## Overall status

P21 (meeting bot + Arabic transcription) was built and fully tested at
the component level (bot → recording → download → transcription). Result:
the pipeline works end-to-end. The client's decision to actually enable
it (ongoing cost) is still pending, and the final transcription-engine
decision needs one more confirmation (a Gulf-dialect test, not just
Egyptian).

---

## Meeting BaaS — confirmed findings from real API responses

- `POST /v2/bots` returns `bot_id` inside `data`, not at the top level:
  `{"success": true, "data": {"bot_id": "..."}}`
- `GET /v2/bots/{bot_id}` — `status` returns `"completed"` (with the D) —
  different from the theoretical webhook value `"complete"` (docs only,
  not confirmed to actually arrive).
- Recording links live under two separate fields: `video` and `audio`
  (presigned S3, 4-hour expiry), not `recording_url` as the public docs
  say.
- The `webhook_url` sent in the `send_bot` request body did not work in
  a real test (4-minute meeting + 10+ minutes waiting, zero webhooks
  arrived). Meeting BaaS's official docs clarify that webhook
  registration is a separate account-level thing (completely different
  event names: `meeting.completed` instead of `complete`) — this
  alternative path hasn't been confirmed to work yet. The confirmed
  working alternative: GET polling via `get_recording_url`.

---

## Munsit — confirmed findings

- The correct model name is `"munsit"` or `"munsit-en-ar"` only.
  `"munsit-1"` (previously assumed from the docs) is wrong and throws
  `errorCode 40001`.
- The output text is under `data.transcription`, not `text` at the top
  level.
- On a clear Egyptian Arabic audio sample, the output text came out
  garbled and linguistically incoherent (not yet tested on a Gulf
  dialect).

---

## ElevenLabs Scribe — confirmed findings

- On the exact same sample (clear Egyptian Arabic), the output text was
  fully coherent and clear — a big quality gap versus Munsit.
- Pricing is published and clear: $0.22–0.34/hour (depending on add-on
  features).
- Not yet tested on a Gulf dialect — the final decision between Munsit
  and Scribe stays 100% unconfirmed until that test is done.

---

## Pending decisions

1. Test a Gulf-dialect sample on both engines before the final decision.
2. Client approval to enable P21 and the ongoing cost that comes with it.
3. The Recall.ai/Meeting BaaS and Munsit/ElevenLabs accounts currently
   sit on personal data (Mariam's email) — needs the same
   ownership-transfer treatment as Google Cloud (P11.5) if this actually
   gets adopted.
4. Account-level Meeting BaaS webhook registration hasn't been tested —
   if it works, it could remove the need for polling.

---

## Meeting-bot orchestrator status (update)

### 1. Components are built and tested

Every component of the meeting-bot orchestrator is built, tested (167
tests in the full suite), and manually reviewed:

- Extracting the meeting link (`meet_link`) from the event
- `should_send_bot` — the timing decision (45–75 minute window) +
  external + has a link
- `sent_bots` table (dedup) — `has_bot_been_requested` /
  `mark_bot_requested` / `update_bot_status`
- `wait_for_recording` / `get_recording_url` in `meetingbaas_client.py`
- `elevenlabs_client.py`
- `run_meeting_bot_cycle` — the full coordination layer

The review covered failure handling (one meeting failing doesn't stop
the rest of the cycle), `dry_run` mode (no network, no ledger writes),
and race-condition protection on `sent_bots` — if `has_bot_been_requested`
loses a race against another writer, `mark_bot_requested` throws
`sqlite3.IntegrityError` and the cycle logs "skipping... (conflict)"
instead of crashing entirely (see commit `fix(p21-orchestrator): handle
sent_bots UNIQUE race gracefully instead of crashing the cycle`).

### 2. Important: a ready library, not a running job

`run_meeting_bot_cycle` is **a "ready code library," not "a job that
runs automatically"** — exactly like `pre_meeting_brief.py` in P10.
**There is no real cron currently calling it.** The only call site in
the repo is `scripts/dry_run_orchestrator.py`, a manual check script
(`grep -rn "run_meeting_bot_cycle" src/ scripts/` confirms this), not a
job scheduled on any server or cron.

### 3. Required before real activation (`dry_run=False`)

For a meeting with a real external party, the following must happen
before activation:

- **The external party must know about and consent to** a recording bot
  being present, before the meeting — not after.
- **Wire `run_meeting_bot_cycle` into an actual scheduled job on the
  server** — part of P9, still blocked on SSH access from the client.
- **Final decision on the transcription engine** (Munsit vs.
  ElevenLabs) — still not 100% confirmed, since the only test so far was
  on Egyptian Arabic, not the Gulf dialect of the target user.

### 4. Account ownership is still personal

The Recall.ai/Meeting BaaS and Munsit/ElevenLabs accounts are still on
Mariam's personal data — this needs the same ownership-transfer
treatment as Google Cloud (P11.5) before any real production use.
