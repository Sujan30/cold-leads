# Cold Leads Agent

An AI-powered SMS outreach system that automatically engages cold real-estate leads, qualifies intent, and books meetings — no human intervention needed until a lead is ready to talk.

Built for Bay Area real estate agents. The AI texts leads as the agent's assistant, qualifies them through natural conversation, and books 30-minute calls directly on the agent's Cal.com calendar.

---

## How It Works

```
Lead added → first SMS sent → lead replies → AI classifies intent → reply drafted → repeat
                                                    ↓ ready_to_book
                                              Cal.com checked → auto-book or offer slots
                                                    ↓ not_interested / handed_off
                                              State updated → agent notified via SMS
```

### Lead States

| State | Meaning |
|-------|---------|
| `new` | Just added — outreach not yet sent |
| `contacted` | First message sent, no reply yet |
| `engaged` | Lead has replied |
| `qualifying` | Lead has shown interest, qualifying in progress |
| `booked` | Meeting scheduled on Cal.com |
| `handed_off` | Escalated to human agent |
| `no_reply` | No response after cadence |
| `dormant` | Not interested or 30+ days inactive |

### Intent Classification

Every inbound message is classified into one of: `interested`, `not_interested`, `question`, `ready_to_book`, `wrong_number`, `unclear`.

- **interested** — answering qualifying questions, sharing budget/timeline, saying yes
- **ready_to_book** — explicitly wants to schedule a call (must mention scheduling or a time)
- **not_interested / wrong_number** → lead moves to `dormant`
- **question** → Sonnet used for deeper reply; Haiku for everything else

### Debounce Sweeper

Rapid back-to-back messages are batched before the AI replies. If a lead sends three messages in quick succession, they're combined into a single context before classification and drafting. Window: 10s (hard cap: 20s).

### Cal.com Auto-Booking

When a lead says they want to meet:
1. If they named a time → check if that slot is available → auto-book or offer alternatives
2. If no time mentioned → fetch the next 3 open slots and offer them
3. If no email on file → send the booking link
4. Slots before 9 AM Pacific are filtered out regardless of Cal.com settings

---

## Tech Stack

| Layer | Tech |
|-------|------|
| API server | FastAPI + uvicorn |
| Database | PostgreSQL (Neon) via SQLAlchemy async + asyncpg |
| Migrations | Alembic |
| AI | Anthropic Claude (Haiku for drafting/classification, Sonnet for complex replies) |
| SMS | Linq (webhook + send API) |
| Email | SendGrid |
| Scheduling | Cal.com v2 API |
| Background jobs | APScheduler |

---

## Setup

### 1. Clone and install

```bash
git clone <repo-url>
cd cold-leads
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | ✅ | Anthropic API key |
| `DATABASE_URL` | ✅ | Postgres connection string (e.g. Neon) |
| `LINQ_API_TOKEN` | ✅ | Linq API token |
| `LINQ_PHONE_NUMBER` | ✅ | Your Linq phone number (`+1...`) |
| `LINQ_WEBHOOK_SIGNING_SECRET` | | Linq webhook HMAC secret (recommended) |
| `NGROK_EXPOSED_URL` | | Public URL for local dev |
| `SENDGRID_API_KEY` | | SendGrid API key |
| `SENDGRID_FROM_EMAIL` | | Sender email address |
| `AGENTS_PHONE` | | Agent's phone — receives escalation alerts |
| `AGENTS_NAME` | | Agent's first name shown to leads (default: `Jason`) |
| `CAL_API_KEY` | | Cal.com API key |
| `CAL_USERNAME` | | Cal.com username slug |
| `CAL_EVENT_SLUG` | | Cal.com event type URL slug (e.g. `chat-with-me`) |
| `CAL_EVENT_TYPE_ID` | | Cal.com numeric event type ID |
| `MODE` | | `dev` auto-seeds test leads on startup; default `prod` |

### 3. Run migrations

```bash
alembic upgrade head
```

### 4. Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

### 5. Expose via ngrok (local dev)

```bash
ngrok http 8000
```

Set `NGROK_EXPOSED_URL` to your ngrok HTTPS URL, then point your Linq webhook to that URL.

---

## Project Structure

```
app/
├── ai/
│   ├── client.py          # Anthropic client with prompt caching
│   ├── models.py          # Shared model constants
│   └── prompts.py         # All system/user prompts and intent classifier
├── channels/
│   ├── linq.py            # SMS send/receive via Linq API
│   └── sendgrid.py        # Email via SendGrid
├── integrations/
│   └── calcom.py          # Cal.com slot availability + booking
├── models/                # SQLAlchemy ORM models (Lead, Message, FollowUp)
├── routers/
│   ├── webhooks.py        # Linq inbound webhook handler
│   ├── leads.py           # Lead management endpoints
│   └── admin.py           # Admin endpoints
├── services/
│   ├── state_machine.py   # Core FSM — all lead state transitions
│   ├── sweeper.py         # Debounce sweeper (asyncio event-driven)
│   ├── orchestrator.py    # Outbound cadence runner
│   ├── classifier.py      # Intent classification via Claude
│   ├── drafter.py         # Reply drafting via Claude
│   ├── booking.py         # Time extraction and slot formatting
│   ├── escalation.py      # Human agent hand-off via SMS
│   └── cadence.py         # Follow-up scheduling logic
└── workers/
    └── scheduler.py       # APScheduler background job runner

alembic/versions/          # Database migration history
scripts/
├── seed_test_leads.py     # Seed dev leads into the database
└── test_linq.py           # Interactive Linq send test
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhook/linq` | Linq inbound SMS webhook |
| `POST` | `/` | Root Linq webhook fallback |
| `GET` | `/health` | Health check |
| `GET` | `/leads` | List all leads |
| `POST` | `/leads` | Add a new lead |
| `GET` | `/admin/leads` | Admin lead overview |

---

## Development

### Seed test leads

```bash
python scripts/seed_test_leads.py
```

Or set `MODE=dev` in `.env` to auto-seed on every startup (wipes existing leads).

### Test Linq SMS

```bash
python scripts/test_linq.py
```

Prompts for a phone number and sends a test message.
