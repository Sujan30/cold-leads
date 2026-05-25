# Cold Leads Agent

An AI-powered SMS outreach system that automatically engages cold real-estate leads, qualifies intent, and books meetings — all via text message.

## How It Works

Leads are loaded into the system and receive an initial SMS outreach. The AI agent (powered by Claude) then handles all replies in real time:

1. **Inbound message arrives** via Linq webhook
2. **Debounce sweeper** waits for rapid follow-up messages (6s window, 20s max) before processing
3. **Classifier** detects intent: interested, not interested, ready to book, needs more info, unclear
4. **State machine** decides the next action — reply, escalate to human agent, or book a meeting
5. **Cal.com integration** checks real availability and either auto-books the slot or sends a scheduling link

Lead states: `new → contacted → engaged → booked / not_interested / handed_off`

## Stack

- **FastAPI** — async HTTP server
- **SQLAlchemy + asyncpg** — async Postgres ORM
- **Alembic** — database migrations
- **Anthropic Claude** — intent classification, reply drafting, time extraction
- **Linq** — SMS send/receive via webhook
- **Cal.com** — meeting availability and booking
- **SendGrid** — email notifications
- **APScheduler** — follow-up cadence scheduling

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Fill in `.env`:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `DATABASE_URL` | Postgres connection string (e.g. Neon) |
| `LINQ_API_TOKEN` | Linq API token |
| `LINQ_PHONE_NUMBER` | Your Linq phone number (`+1...`) |
| `LINQ_WEBHOOK_SIGNING_SECRET` | Linq webhook secret (optional) |
| `NGROK_EXPOSED_URL` | Public URL for local dev (ngrok) |
| `SENDGRID_API_KEY` | SendGrid API key (for email alerts) |
| `SENDGRID_FROM_EMAIL` | Sender email address |
| `AGENTS_PHONE` | Agent's phone number for escalation |
| `AGENTS_NAME` | Agent's first name shown to leads (default: `Jason`) |
| `CAL_API_KEY` | Cal.com API key |
| `CAL_USERNAME` | Cal.com username slug |
| `CAL_EVENT_SLUG` | Cal.com event type URL slug |
| `CAL_EVENT_TYPE_ID` | Cal.com numeric event type ID |
| `MODE` | `dev` to auto-seed a test lead on startup, `prod` otherwise |

### 3. Run migrations

```bash
alembic upgrade head
```

### 4. Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

For local dev with Linq webhooks, expose the server via ngrok:

```bash
ngrok http 8000
```

Set `NGROK_EXPOSED_URL` to your ngrok URL and configure it as the webhook endpoint in your Linq dashboard.

## Project Structure

```
app/
├── ai/             # Claude client, prompt builder, AI models
├── channels/       # Linq (SMS) and SendGrid (email) integrations
├── integrations/   # Cal.com API (slots, booking)
├── models/         # SQLAlchemy ORM models
├── routers/        # FastAPI routes (webhooks, leads, admin, health)
├── services/       # Core logic
│   ├── state_machine.py   # Lead FSM — drives all transitions
│   ├── orchestrator.py    # Outbound cadence runner
│   ├── sweeper.py         # Debounce sweeper for rapid inbound messages
│   ├── classifier.py      # Intent classification via Claude
│   ├── drafter.py         # Reply drafting via Claude
│   ├── booking.py         # Time extraction and slot formatting
│   ├── escalation.py      # Human agent hand-off
│   └── cadence.py         # Follow-up scheduling logic
└── workers/        # APScheduler background jobs
alembic/            # Database migrations
scripts/            # Dev utilities (seed leads, test Linq)
```

## Dev Utilities

Seed a test lead on startup by setting `MODE=dev` in `.env`.

Or run manually:

```bash
python scripts/seed_test_leads.py
```
