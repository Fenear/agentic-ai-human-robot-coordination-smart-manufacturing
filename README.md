# HRCA — Human-Robot Coordination Agent

**Titan Manufacturing | Minimum Viable Agent (v1 — Free Tier)**

A lightweight Python agent that watches shift schedules and robot cell states, detects when a human and an active robot might be in the same zone, and sends an alert to the supervisor.

No cloud. No Kubernetes. No enterprise contracts. **Total ongoing cost: $0/month.**

---

## Problem

**Undetected human presence in active robot zones** — the root cause of most safety shutdowns and quality overrides. 17 % of shifts have conflicts. This agent catches them before they become incidents.

---

## Architecture

```
┌─────────────────────────────────────────┐
│           hrca.py (runs locally)        │
│                                         │
│  1. Load shift_schedule.csv             │
│  2. Poll robot_status.json (or API)     │
│  3. Check for conflicts (rule-based)    │
│  4. If conflict → call LLM for alert   │
│  5. Send alert via email or Slack       │
│  6. Log to events.csv                   │
│                                         │
│  Runs every 30 seconds via scheduler    │
└─────────────────────────────────────────┘
```

---

## File Structure

```
hrca/
├── hrca.py              ← main agent loop
├── tools.py             ← schedule + robot state tools
├── alert.py             ← email / Slack sender
├── shift_schedule.csv   ← updated each shift
├── robot_status.json    ← updated by PLC / manual
├── events.csv           ← audit log
├── .env                 ← API keys (never commit this)
├── requirements.txt
└── README.md
```

---

## Deployment Steps

### Step 1 — Install dependencies (15 minutes)

Requires **Python 3.10+**.

```bash
pip install -r requirements.txt
```

Or install manually:

```bash
pip install langchain langchain-groq pandas requests schedule python-dotenv
```

### Step 2 — Get a free LLM

**Option A: Groq (recommended — fast, free tier)**

1. Sign up at [console.groq.com](https://console.groq.com)
2. Create an API key
3. Paste the key in `.env` under `GROQ_API_KEY`
4. Uses `llama3-8b-8192` model — free up to ~15 K requests/day

**Option B: Ollama (fully local, no internet)**

```bash
# Install Ollama (https://ollama.com), then:
ollama pull llama3
```

- Runs entirely on the plant network
- Needs a PC with 8 GB+ RAM
- Swap `ChatGroq` for `ChatOllama` in `hrca.py` to use this option

### Step 3 — Prepare your data files

**shift_schedule.csv** — exported from HR at the start of each shift:

```
name, badge_id, cell, shift_start, shift_end
Kim Chen, 4412, cell_7, 13:00, 14:00
Marco Rivera, 5531, cell_3, 13:00, 17:00
```

**robot_status.json** — updated by PLC vendor API or manually:

```json
{"cell_7": "active", "cell_3": "idle", "cell_14": "active"}
```

### Step 4 — Configure alerts

**Slack (easiest):**

1. Create a free Slack workspace (or use an existing one)
2. Add an **Incoming Webhook** integration
3. Paste the webhook URL in `.env` under `SLACK_WEBHOOK_URL`
4. Set `ALERT_METHOD=slack` in `.env`

**Email (SMTP):**

1. Use any Gmail account with an [App Password](https://support.google.com/accounts/answer/185833)
2. Fill in the SMTP fields in `.env`
3. Set `ALERT_METHOD=email` in `.env`

### Step 5 — Run it

```bash
python hrca.py
```

The agent starts polling every 30 seconds. Check `events.csv` for the audit log.

---

## Example Run

**Trigger:** Cell 7 is active. Schedule shows Operator Kim assigned to Cell 7 but shift ended 10 min ago.

**Agent reasoning:** Robot active + operator may still be present past scheduled time = conflict risk.

**Alert sent:**

> ⚠️ Cell 7 Alert: Operator Kim (Badge #4412) was scheduled to exit at 14:00 but cell is still active. Please confirm operator has cleared the zone. [14:23]

**Outcome:** Supervisor checks, Kim had already left. Alert logged, no action needed. Cooldown applied.

---

## Configuration Reference

All settings live in `.env`:

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | Your Groq API key |
| `LLM_MODEL` | `llama3-8b-8192` | Groq model to use |
| `ALERT_METHOD` | `slack` | `slack` or `email` |
| `SLACK_WEBHOOK_URL` | — | Slack incoming webhook URL |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server host |
| `SMTP_PORT` | `587` | SMTP server port |
| `SMTP_USER` | — | Email address for sending |
| `SMTP_PASSWORD` | — | Email app password |
| `ALERT_EMAIL_TO` | — | Supervisor email address |
| `SCHEDULE_CSV` | `shift_schedule.csv` | Path to schedule file |
| `ROBOT_STATUS_SOURCE` | `robot_status.json` | Path or URL for robot status |
| `EVENTS_CSV` | `events.csv` | Path to audit log |
| `POLL_INTERVAL_SEC` | `30` | Seconds between polling cycles |
| `COOLDOWN_MIN` | `5` | Minutes before re-alerting same cell |
| `STALE_THRESHOLD_SEC` | `60` | Max age (seconds) of robot status data |

---

## Guardrails

| Risk | Mitigation |
|---|---|
| Stale sensor data | Skips action if data > 60 s old; logs warning |
| Too many false alerts | 5-minute cooldown per cell after each alert |
| LLM unavailable | Fallback: sends raw rule-based alert without LLM |
| Wrong operator name | Always shows both name + badge ID in alert |

**Human-in-the-loop:** Every alert requires supervisor acknowledgement. The agent never takes physical action — humans decide what to do.

---

## Tech Stack

| Layer | Tool | Cost |
|---|---|---|
| LLM | Groq API (free tier) or Ollama | $0 |
| Language | Python 3.10+ | $0 |
| Agent framework | LangChain (open source) | $0 |
| Alerting | SMTP email or Slack webhook | $0 |
| Storage | CSV files | $0 |
| Hosting | Plant floor PC or Raspberry Pi | ~$50 one-time |
| Scheduling | Python `schedule` library | $0 |

---

## Stakeholders

| Who | Role |
|---|---|
| Shift Supervisor | Receives alerts, takes action |
| Floor Operator | Subject of schedule data |
| IT Contact | Helps with network / email setup |

---

## Limitations (v1)

| What it can't do | Why | Future fix |
|---|---|---|
| Autonomous cell pause | No write access to PLC | Add OPC-UA write in v2 |
| Predictive conflict (10 min ahead) | No ML model | Add time-series in v2 |
| Multi-plant | Runs on one plant network | Duplicate or add central server |
| Real-time sensor fusion | Depends on manual / basic JSON | Add IoT feed in v2 |
| Learning from overrides | No memory | Add SQLite + embeddings in v2 |

---

## Upgrade Path

```
v1 (Now — Free)          v2 (Low cost)            v3 (Full)
─────────────────        ──────────────           ──────────────
Local Python script  →   Cloud hosted (Railway)    AWS Bedrock + EKS
Groq free tier       →   Claude Haiku (~$5/mo)     Claude Opus
CSV schedules        →   MES API integration       Full MES + HRMS
Email/Slack alerts   →   Dashboard (Streamlit)     React dashboard
No memory            →   SQLite + RAG              OpenSearch vectors
1 plant              →   3 plants                  28 plants
```
