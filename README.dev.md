# rel-mcp — Developer Reference

The technical reference for anyone building on this code: architecture,
every module, environment contract, and the deliberate design decisions
worth knowing before the first edit. For the pitch, see
[README.md](./README.md).

## Architecture

```
Owner
   → Telegram                long-polled, no inbound port
   → Hermes Gateway          LLM + Telegram adapter + cron + approval prompts
   → rel_mcp (this repo)     Python MCP server, stdio subprocess
   → Google Workspace        Calendar + Gmail (read-only in this phase)
   → SQLite ledger           local relationship store, outside the code tree
```

`rel_mcp` never talks to Telegram directly, and holds no LLM
credentials — that boundary belongs to Hermes. `rel_mcp` holds no
owner-visible knowledge that didn't come out of a tool call in the
current turn; every "fact" it surfaces is either a row in the ledger,
an event on the calendar, or a header from a Gmail thread bounded to a
known participant.

## Boundary from `sim-agent`

`sim-agent` is the sibling profile on the same Hermes gateway — it
handles the CEO's task and staff management through the company's own
systems. `rel-mcp` runs alongside it as a **separate profile** with its own
model account, its own cron jobs, its own state. Neither profile reads
the other's storage, and neither is allowed to touch the other's
Hermes configuration.

## Quick start

```bash
cp .env.example .env               # fill in OWNER_EMAIL, keep DRY_RUN=true
uv sync --all-groups               # installs Python 3.11+ deps
uv run pytest -v                   # 82 tests, no network required

# then, with credentials.json in the repo root (from Google Cloud):
uv run python scripts/google_check.py     # one-time OAuth consent
uv run python scripts/mcp_selftest.py     # exercise every tool end-to-end
```

`DRY_RUN=true` by default — this phase has no write tools anyway, but
the safety default is intentional and inherited from the sim-agent
pattern.

## Environment contract

Nine variables, defined once in `.env.example` and validated at startup
by `Settings`. `tests/test_env_contract.py` fails the build the moment
the two lists diverge (either side).

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `local` \| `staging` \| `production` |
| `DRY_RUN` | Safe default `true`; must be flipped explicitly for production |
| `GOOGLE_CREDENTIALS_PATH` | OAuth client JSON from Google Cloud (Desktop app) |
| `GOOGLE_TOKEN_PATH` | Where the refreshable user token lives (0600 on POSIX) |
| `AUDIT_LOG_PATH` | Append-only JSONL — every action leaves one line |
| `STATE_DB_PATH` | SQLite ledger file |
| `TIMEZONE` | e.g. `Asia/Riyadh`; validated against `zoneinfo` at boot |
| `OWNER_EMAIL` | Must equal the Google account that ran OAuth |
| `KILL_SWITCH_PATH` | Presence of this file blocks every tool immediately |

## Modules

Everything lives under `src/rel_mcp/`. Every module has one
responsibility; nothing here does more than what its row says.

| Module | Responsibility |
|---|---|
| `config.py` | `Settings` + `get_settings()`; refuses to start on missing/malformed env |
| `errors.py` | `RelError` root; `ConfigError`, `GoogleAuthError`, `UpstreamError`, `KillSwitchError` |
| `audit.py` | Append-only JSONL writer; opens/closes per line; injectable `now` |
| `killswitch.py` | `is_stopped()` / `enforce()`; a file on disk is the mechanism |
| `google/auth.py` | InstalledAppFlow; SCOPES is a frozen tuple (calendar+gmail readonly) |
| `google/calendar.py` | `upcoming_meetings`, `just_ended`, deterministic external classification |
| `google/gmail.py` | `threads_with(participants)` — the ONLY entry point; every call audited |
| `ledger.py` | SQLite CRM; migrations tracked in `PRAGMA user_version`; FK enforcement on |
| `brief.py` | `build_brief(...)` — pure function, no network, no LLM, no clock |
| `render.py` | Brief → Arabic Telegram text; MAX_LINES cap; empty sections dropped |
| `phrases.py` | Every visible Arabic string lives here — one file to review tone |
| `server.py` | MCP stdio server; five read-only tools; `_now_utc()` isolates non-determinism |

Scripts (`scripts/`):

| Script | Purpose |
|---|---|
| `google_check.py` | One-time OAuth flow + prints `connected as:` and calendar count |
| `preview_meetings.py` | Prints the next 48h of meetings from the real calendar |
| `mcp_selftest.py` | Calls every MCP tool in order — proves the pipeline without Hermes |

## Deliberate design decisions

Six choices worth knowing before editing. Reversing any of them requires
knowing why they're there.

### 1. Every visible Arabic word lives in `phrases.py`

One file to review tone in. A single f-string interpolation of user
data in a business-logic module makes tone review a diff hunt across
the codebase.

### 2. `SCOPES` is a frozen tuple, not a list

Read-only, calendar + gmail only. **Do not append to it.** Every write
capability (compose, event create, ...) is a separate consent screen
and belongs behind the approval gate — added deliberately in a later
phase, never smuggled in here.

### 3. Gmail access is bounded in code, not in the prompt

The scope grants access to the whole mailbox. `threads_with(participants)`
is the ONLY entry point, and rejects empty inputs with `ValueError`.
Every call appends one `gmail_query` line to the audit log with the
exact query, participants, and result count — the answer to "what has
this agent read from my mail?" months from now.

### 4. `confirmed_by_owner` survives every layer

An `agreed_terms` row with `confirmed_by_owner = 0` must never surface
to the reader as fact. The ledger returns the flag on every row; the
brief carries it as `TermFact.confirmed`; the render marks it
`(غير مؤكد)`. No layer can silently promote it.

### 5. `now` is injected everywhere the reader path touches

`rules`, `brief`, `calendar`, `gmail`, `ledger` — all take `now` as a
parameter. The one exception is `server._now_utc()`, deliberately
isolated to the tool-entry seam so tests remain deterministic and the
same inputs give the same brief.

### 6. Empty sections in the brief are dropped, not padded

A brand-new counterparty legitimately has no last-contact line and no
open commitments. The render omits those sections rather than writing
"no previous history yet"; a single flag line at the end
("أول اجتماع مسجّل مع الجهة دى") names the absence honestly.

## Tests

```bash
uv run pytest -v          # 82 tests, ~2s, no network
uv run ruff check .       # lint (RUF001-003 ignored — Arabic text)
uv run mypy src           # strict; Google APIs' missing stubs overridden
```

Golden files live under `tests/goldens/` and are built from **entirely
synthetic data** (fake companies, invented figures). Real calendar or
mail data must never end up in a committed fixture. To regenerate
goldens after a deliberate tone change:

```bash
UPDATE_GOLDENS=1 uv run pytest tests/test_brief.py
```

## Roadmap

Current phase (P0–P8) is **read-only** and complete: OAuth, calendar,
bounded Gmail, ledger, deterministic brief, MCP server, SOUL.md. The
pipeline works end-to-end on a developer machine.

What's next, in order, gated on the server being available:

| Step | What it adds |
|---|---|
| P9 | `docs/DEPLOY.md` and the agent's Hermes profile on the VPS |
| P10 | Cron job (every 15 min) that sends briefs to Telegram before external meetings |
| P11 | First real brief lands on Telegram unattended |
| P11.5 | Identity swap from developer to the owner's own accounts before delivery |
| P12+ | CI/CD, backups, approval gate, post-meeting capture, follow-up drafts |

## Documentation map

| Document | For | What's in it |
|---|---|---|
| `README.md` | Anyone deciding whether to adopt this | The pitch |
| `README.dev.md` | This file — anyone building on the code | Modules, contract, decisions |
| `docs/` | (not yet — arrives in P9) | DEPLOY, RUNBOOK, HANDOVER |
