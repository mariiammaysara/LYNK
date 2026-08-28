<div align="center">

# LYNK

### Meeting & relationship intelligence for people who work through relationships.

**Turn every external meeting into relationship intelligence — automatically.**

<br>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square\&logo=python\&logoColor=white)](#)
[![MCP](https://img.shields.io/badge/MCP-Model_Context_Protocol-000000?style=flat-square)](#)
[![SQLite](https://img.shields.io/badge/SQLite-local-003B57?style=flat-square\&logo=sqlite\&logoColor=white)](#)
[![Telegram](https://img.shields.io/badge/Telegram-integrated-26A5E4?style=flat-square\&logo=telegram\&logoColor=white)](#)
[![Tests](https://img.shields.io/badge/tests-220%2B-brightgreen?style=flat-square)](#)

</div>

<br>

---

## Remember the relationship. Not just the meeting.

Your calendar tells you **who you're meeting**.

Your inbox tells you **what happened before**.

Your CRM tells you **what's on record**.

Your memory is supposed to connect all three.

**LYNK does that part.**

LYNK is a Telegram-based AI agent that builds persistent context around the people and organizations you work with.

Before a meeting, it prepares you with the relevant history.

After a meeting, it can capture what happened.

Between meetings, it keeps track of what is still open.

It's designed for **anyone whose work depends on recurring external relationships** — sales reps, account managers, consultants, recruiters, founders, freelancers, agencies, executives, and anyone else who needs to remember what was said, what was promised, and what happens next.

<br>

<div align="center">

### BEFORE

**Know the history.**

↓

### DURING

**Capture what happened.**

↓

### AFTER

**Keep the relationship moving.**

</div>

---

## Before the meeting

### Walk in already knowing the context.

45–75 minutes before an external meeting, LYNK sends a briefing directly to Telegram.

Not a calendar summary.

A **relationship briefing** built from the history you already have with that person or organization.

It can surface:

* **Last contact** — when you last spoke and what happened
* **Commitments** — what you owe them and what they owe you
* **Agreements** — terms that were actually confirmed
* **Open loops** — questions, tasks, and follow-ups that are still unresolved
* **Suggested questions** — useful things to ask based on the relationship history

> **The goal isn't to tell you what's on your calendar.**
>
> **It's to remind you what matters before you walk in.**

---

## The part that matters

Most AI systems are very good at summarizing.

LYNK cares about something harder:

### **What do we actually know?**

A conversation can contain something that was:

**said → discussed → suggested → agreed → confirmed**

Those aren't the same thing.

LYNK keeps that distinction explicit.

```text
        DISCUSSION
             │
             ▼
        ┌──────────┐
        │ DECISION │
        └────┬─────┘
             │
             ▼
       ┌────────────┐
       │ COMMITMENT │
       └──────┬─────┘
              │
              ▼
       ┌────────────┐
       │ CONFIRMED  │
       └────────────┘
```

**An AI-generated statement doesn't become a fact just because it sounds confident.**

Unverified information stays unverified until it is confirmed.

---

## After the meeting

LYNK can turn the meeting itself into structured relationship data.

```text
JOIN → RECORD → TRANSCRIBE → EXTRACT → UPDATE
```

It can capture:

* key discussion points
* decisions
* commitments
* open questions
* follow-up items

The same rule applies after the meeting:

> **Discussion is not automatically a decision.**
>
> **A statement is not automatically a commitment.**

The relationship record gets updated without quietly rewriting history.

---

## A relationship that remembers

At the center of LYNK is a persistent local relationship ledger.

It accumulates context across interactions with people and organizations:

```text
                         RELATIONSHIP
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
       PEOPLE             INTERACTIONS       ORGANIZATIONS
          │                   │                   │
          └───────────────────┼───────────────────┘
                              │
                     ┌────────┴────────┐
                     │                 │
                COMMITMENTS        AGREEMENTS
                     │                 │
                     └────────┬────────┘
                              │
                         OPEN LOOPS
```

Over time, LYNK becomes less like a meeting assistant and more like a **memory layer for your professional relationships**.

---

## Ask it when you need it

You don't have to wait for the next scheduled brief.

Just ask.

```text
"What did we agree on last time?"

"What are they waiting for from us?"

"What commitments are overdue?"

"When did we last talk?"

"What's our status with Acme?"
```

LYNK queries the accumulated relationship context instead of starting from zero.

---

## And then it keeps working

Once enabled, LYNK can quietly handle recurring relationship maintenance:

**Weekly relationship digest**
A compact view of meaningful relationship activity.

**Overdue commitment nudges**
Surface things that are still waiting on someone.

**Task delegation**
Turn a conversation into an action without leaving Telegram.

**Post-meeting intelligence**
Capture decisions, commitments, and follow-ups automatically.

**Remote kill switch**
Stop the agent directly from Telegram when needed.

<br>

**No dashboard to maintain.
No relationship database to keep updated manually.**

The system maintains the context.

You use it.

---

# Run LYNK

LYNK can run in two ways:

**Local** — everything runs on your own computer.

**Server** — the agent stays online 24/7 on a Linux VPS, even when your computer is off.

If you're setting up LYNK for the first time, **start locally**. Once it works, move the same setup to a server.

<details>
<summary><strong>▶ Local setup</strong></summary>

<br>

### What you need

| What                 | Why                                            |
| -------------------- | ---------------------------------------------- |
| **Python 3.11+**     | Runs the LYNK MCP server                       |
| **Google account**   | Calendar + Gmail access                        |
| **Telegram account** | Bot delivery and interaction                   |
| **Hermes Agent**     | Model, orchestration, Telegram, and scheduling |

### 1. Install Python

LYNK requires **Python 3.11+**.

Check your version:

```bash
python --version
```

or:

```bash
python3 --version
```

You need Python 3.11 or newer.

### 2. Install `uv`

LYNK uses [`uv`](https://docs.astral.sh/uv/) for Python environments and dependencies.

macOS / Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal and verify:

```bash
uv --version
```

On Windows, install `uv` using its Windows instructions and verify the same command from PowerShell.

### 3. Clone LYNK

```bash
git clone https://github.com/mariiammaysara/LYNK.git
cd LYNK
```

### 4. Install dependencies

```bash
uv sync --all-groups
```

Then run the tests:

```bash
uv run pytest
```

LYNK currently has **220+ tests**.

### 5. Create a Google Cloud project

Open Google Cloud Console:

https://console.cloud.google.com/

Create a new project, for example:

```text
lynk-agent
```

Then go to:

**APIs & Services → Library**

Enable:

* Google Calendar API
* Gmail API

### 6. Configure Google OAuth

Go to:

**APIs & Services → OAuth consent screen**

Choose **Internal** for a Workspace-only application or **External** for a personal Gmail account.

Add the read-only scopes:

```text
https://www.googleapis.com/auth/calendar.readonly
https://www.googleapis.com/auth/gmail.readonly
```

If the app is external and in testing mode, add your own Google account under **Test users**.

Then go to:

**APIs & Services → Credentials → Create Credentials → OAuth client ID**

Choose:

**Desktop app**

Download the credentials and save them as:

```text
credentials.json
```

in the project root:

```text
LYNK/
├── credentials.json
├── rel_mcp/
├── scripts/
└── ...
```

The file is already ignored by Git.

**Never commit it.**

### 7. Configure the environment

Create your environment file:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Configure:

```text
GOOGLE_CREDENTIALS_PATH=./credentials.json
OWNER_EMAIL=<your Google email>
TIMEZONE=<your timezone>
```

For Egypt:

```text
TIMEZONE=Africa/Cairo
```

### 8. Authenticate with Google

Run:

```bash
uv run python scripts/google_check.py
```

A browser should open.

Sign in with the Google account you configured and approve the requested read-only permissions.

A successful setup should report something like:

```text
connected as: you@example.com
```

At this point, the Google side of LYNK is ready.

### 9. Create a Telegram bot

Open Telegram and message **@BotFather**.

Send:

```text
/newbot
```

Choose a display name and a username ending in `bot`.

BotFather will give you a bot token.

**Treat it like a password.**

Open the new bot and press **Start**.

### 10. Configure Hermes

Install Hermes separately, then create the LYNK profile:

```bash
hermes profile create lynk \
  --description "Meeting and relationship agent"
```

Configure a model provider:

```bash
hermes -p lynk auth add openrouter
```

Use another provider supported by Hermes if preferred.

Set your timezone:

```bash
hermes -p lynk config set timezone Africa/Cairo
```

Configure Telegram:

```bash
hermes gateway setup
```

Provide the Telegram bot token when prompted.

### 11. Start the gateway

```bash
hermes gateway run
```

Send your bot a message such as:

```text
What's my status with Acme?
```

or:

```text
When did we last talk?
```

Then verify that an upcoming external meeting produces its scheduled brief.

For local scheduled jobs, your computer must remain **on and connected to the internet**.

</details>

<details>
<summary><strong>▶ 24/7 server setup</strong></summary>

<br>

Once local setup works, deploy LYNK to a Linux VPS.

A VPS is simply a remote Linux machine that stays online while your own computer is off.

### 1. Connect to the server

Create a Linux VPS and connect over SSH:

```bash
ssh youruser@YOUR_SERVER_IP
```

### 2. Prepare the server

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl
```

Verify Python:

```bash
python3 --version
```

Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify:

```bash
uv --version
```

### 3. Install LYNK

```bash
git clone https://github.com/mariiammaysara/LYNK.git
cd LYNK

uv sync --all-groups
uv run pytest
```

Make sure the tests pass before continuing.

### 4. Configure the environment

```bash
cp .env.example .env
```

Set:

```text
GOOGLE_CREDENTIALS_PATH=./credentials.json
OWNER_EMAIL=<your Google email>
TIMEZONE=<your timezone>
```

Copy `credentials.json` securely to the server.

From your local machine:

```bash
scp credentials.json youruser@YOUR_SERVER_IP:/path/to/LYNK/credentials.json
```

Then on the server:

```bash
chmod 600 credentials.json
```

### 5. Authenticate Google

A headless server normally doesn't have a browser.

If the OAuth flow needs one, create an SSH tunnel from your local computer:

```bash
ssh -L 8080:localhost:8080 youruser@YOUR_SERVER_IP
```

Keep that SSH session open.

On the server:

```bash
cd LYNK
uv run python scripts/google_check.py
```

Complete the Google login in your local browser.

The resulting authentication state should remain on the server.

**Never commit OAuth tokens or credentials.**

### 6. Configure Hermes

Install Hermes on the server and create the profile:

```bash
hermes profile create lynk \
  --description "Meeting and relationship agent"

hermes -p lynk auth add openrouter
hermes -p lynk config set timezone Africa/Cairo
hermes gateway setup
```

Enter the Telegram bot token.

Test manually first:

```bash
hermes gateway run
```

Send a Telegram message and make sure it works.

**Do not configure `systemd` until this manual test succeeds.**

### 7. Run it permanently

Find the Hermes executable:

```bash
which hermes
```

Create:

```bash
sudo nano /etc/systemd/system/lynk.service
```

Use:

```ini
[Unit]
Description=LYNK Hermes gateway
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/opt/lynk
ExecStart=/usr/local/bin/hermes gateway run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Adjust `User`, `WorkingDirectory`, and `ExecStart` for your server.

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable lynk
sudo systemctl start lynk
```

Check:

```bash
sudo systemctl status lynk
```

Follow logs with:

```bash
sudo journalctl -u lynk -f
```

LYNK will now start automatically after a server reboot and continue running after you disconnect from SSH.

</details>

<details>
<summary><strong>▶ Server checklist & security</strong></summary>

<br>

Before considering the deployment complete:

```text
[ ] Python 3.11+ installed
[ ] uv installed
[ ] LYNK dependencies installed
[ ] pytest passes
[ ] Google Calendar API enabled
[ ] Gmail API enabled
[ ] OAuth credentials configured
[ ] Google authentication succeeds
[ ] Telegram bot created
[ ] Telegram bot responds
[ ] Hermes profile configured
[ ] Model provider works
[ ] Hermes gateway works manually
[ ] systemd service starts
[ ] Service survives SSH logout
[ ] Service starts after reboot
[ ] Scheduled brief arrives
```

### Keep secrets out of Git

Never commit:

```text
.env
credentials.json
OAuth tokens
Telegram bot tokens
API keys
private databases
```

### Protect the server

Use SSH keys where possible and avoid exposing unnecessary ports.

### Protect Telegram

Treat the Telegram bot token like a password.

If it is exposed, revoke or regenerate it through BotFather.

### Protect relationship data

The local database can contain information about contacts, organizations, meetings, commitments, and conversations.

Treat the server and its backups as sensitive data stores.

### Google permissions

LYNK's Google integration uses read-only Calendar and Gmail scopes.

</details>

---

# Architecture

LYNK separates **deterministic business logic** from **agent reasoning**.

```text
Calendar + Gmail + CRM
          │
          ▼
     ┌──────────┐
     │ rel_mcp  │
     │ facts +  │
     │  rules   │
     └────┬─────┘
          │
          ▼
     ┌──────────┐
     │  Hermes  │
     │   agent  │
     └────┬─────┘
          │
          ▼
       Telegram
```

`rel_mcp` owns retrieval, relationship state, classification, and deterministic business rules.

Hermes provides the model, orchestration, Telegram, scheduling, and approval layer.

**The LLM is not the source of truth.**

---

# Built

| Core — built & tested          | Additional — built & tested              |
| ------------------------------ | ---------------------------------------- |
| ✓ Pre-meeting intelligence     | ✓ Weekly relationship digest             |
| ✓ Relationship ledger          | ✓ Daily commitment nudges                |
| ✓ Commitment tracking          | ✓ Task delegation                        |
| ✓ Overdue detection            | ✓ Remote kill switch                     |
| ✓ Instant relationship queries | ✓ Post-meeting recording & transcription |
|                                | ✓ Decision & commitment extraction       |

---

For implementation details and the reasoning behind the deterministic rules, confirmation handling, environment contract, and testing decisions, see [`README.dev.md`](./README.dev.md).

---

<div align="center">

**Built by [Mariam Maysara](https://mariammaysara.com)**

</div>
