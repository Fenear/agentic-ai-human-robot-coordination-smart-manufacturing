# context.md — Titan Manufacturing (Minimal Free Version)
## HRCA Project Context: Simple, Free, Deployable in Days

---

## What We're Building

A lightweight Python script + free LLM that watches shift schedules and robot cell states, detects when a human and active robot might be in the same zone, and sends an alert to the supervisor. That's it.

No cloud. No Kubernetes. No enterprise contracts.

---

## Problem (Same, Simplified Focus)

Out of all the challenges Titan faces, this version tackles the single highest-impact, lowest-cost-to-solve one:

**Undetected human presence in active robot zones** — the root cause of most safety shutdowns and quality overrides.

Everything else (supply chain, predictive maintenance, cross-plant optimization) is out of scope for this version.

---

## Stakeholders (Minimal)

| Who | Role |
|---|---|
| Shift Supervisor | Receives alerts, takes action |
| Floor Operator | Subject of schedule data |
| IT contact | Helps with network/email setup |

That's the full team needed to deploy this version.

---

## Data Needed (Keep It Simple)

| Data | Format | Where it comes from |
|---|---|---|
| Shift schedule | CSV (name, badge, cell, start, end) | HR exports manually each shift |
| Robot cell status | JSON or simple REST endpoint | PLC vendor API or manual entry |

If robot cell data isn't available via API yet, a supervisor can update a shared Google Sheet every hour. The agent reads it. Not elegant, but it works.

---

## System Architecture

```
┌─────────────────────────────────────────┐
│           hrca.py (runs locally)        │
│                                         │
│  1. Load shift_schedule.csv             │
│  2. Poll robot_status.json (or API)     │
│  3. Check for conflicts (rule-based)    │
│  4. If conflict → call LLM for alert    │
│  5. Send alert via email or Slack       │
│  6. Log to events.csv                   │
│                                         │
│  Runs every 30 seconds via scheduler    │
└─────────────────────────────────────────┘
```

Runs on any machine connected to the plant network. No internet required if using Ollama (local LLM).

---

## Deployment Steps

### Step 1 — Install dependencies (15 minutes)
```bash
pip install langchain langchain-groq pandas requests schedule python-dotenv
```

### Step 2 — Get a free LLM

**Option A: Groq (recommended — fast, free tier)**
- Sign up at console.groq.com
- Get API key → paste in `.env` file
- Uses `llama3-8b-8192` model, free up to ~15K requests/day

**Option B: Ollama (fully local, no internet)**
```bash
# Install Ollama, then:
ollama pull llama3
```
- Runs entirely on plant network
- Needs a PC with 8GB+ RAM

### Step 3 — Prepare your data files
```
shift_schedule.csv:
name, badge_id, cell, shift_start, shift_end
Kim Chen, 4412, cell_7, 13:00, 14:00
Marco Rivera, 5531, cell_3, 13:00, 17:00

robot_status.json:
{"cell_7": "active", "cell_3": "idle", "cell_14": "active"}
```

### Step 4 — Configure alerts

**Slack (easiest):**
- Create a free Slack workspace
- Add an Incoming Webhook
- Paste URL in `.env`

**Email:**
- Use any Gmail account with App Password
- SMTP settings in `.env`

### Step 5 — Run it
```bash
python hrca.py
```
Agent starts polling every 30 seconds. Check `events.csv` for logs.

---

## File Structure

```
hrca/
├── hrca.py              ← main agent loop
├── tools.py             ← schedule + robot state tools
├── alert.py             ← email/Slack sender
├── shift_schedule.csv   ← updated each shift
├── robot_status.json    ← updated by PLC/manual
├── events.csv           ← audit log
├── .env                 ← API keys (never commit this)
└── requirements.txt
```

---

## Limitations of This Version (Honest)

| What it can't do | Why | Future fix |
|---|---|---|
| Autonomous cell pause | No write access to PLC in free setup | Add OPC-UA write in v2 |
| Predictive conflict (10 min ahead) | No ML model | Add simple time-series in v2 |
| Multi-plant | Runs on one plant network | Duplicate per plant or add central server |
| Real-time sensor fusion | Depends on manual/basic JSON | Add proper IoT feed in v2 |
| Learning from overrides | No memory | Add SQLite + embeddings in v2 |

This version is intentionally a **Minimum Viable Agent** — prove the concept, earn trust, then upgrade.

---

## Upgrade Path (When Ready)

```
v1 (Now — Free)          v2 (Low cost)           v3 (Full)
─────────────────        ──────────────           ──────────────
Local Python script  →   Cloud hosted (Railway)   AWS Bedrock + EKS
Groq free tier       →   Claude Haiku API (~$5/mo) Claude claude-opus-4-6
CSV schedules        →   MES API integration      Full MES + HRMS
Email/Slack alerts   →   Dashboard (Streamlit)    React dashboard
No memory            →   SQLite + RAG             OpenSearch vector store
1 plant              →   3 plants                 28 plants
```

Each step is independent. You don't need to jump to v3 — v1 already solves the core safety problem.

---

## Cost Summary

| Item | Cost |
|---|---|
| Groq API (free tier) | $0/month |
| Ollama (local LLM) | $0/month |
| Slack workspace | $0/month |
| Python + libraries | $0 |
| Hosting (existing plant PC) | $0 |
| **Total** | **$0/month** |

Optional upgrade: A dedicated mini PC (Intel NUC or Raspberry Pi 5) for ~$100 one-time if you don't want to use an existing machine.

---

## What You Need to Get Started

- [ ] Python 3.10+ installed on one plant PC
- [ ] Groq account (free) OR Ollama installed locally
- [ ] Slack workspace OR email account for alerts
- [ ] CSV export of shift schedule from HR
- [ ] Either: PLC vendor REST API, or someone to update `robot_status.json` manually each hour
- [ ] 30 minutes to configure and run
