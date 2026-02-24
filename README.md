# HRCA — Human-Robot Coordination Agent

**Titan Manufacturing | v2 — FastAPI + Streamlit (Free Tier)**

A two-service system that detects when a human operator is scheduled in a zone where a robot is active, generates a plain-language alert via LLM, and displays it on a live dashboard. No hardware changes required.

**Total ongoing cost: $0/month.**

---

## Architecture

```
Plant Network / MES                 Cloud (Free)
───────────────────                 ──────────────────────────────
MES/HR drops CSV        →           Railway — api/
  HTTP POST /upload                   FastAPI receives upload
  trigger_source=machine              run_pipeline()
                                       check_schedule()
Supervisor laptop        →             check_robot_state()
  Streamlit dashboard                  send_alert() → Slack/email
  uploads CSV manually                 log_event() → SQLite
  → POST /upload

                                    Streamlit Cloud — dashboard/
                                      reads /state and /events
                                      shows live dashboard
                                      supervisor upload widget
                                      auto-refresh every 30s
```

**Why two services:** Streamlit Cloud is stateless — it cannot receive HTTP POSTs from external systems or maintain a persistent filesystem. FastAPI on Railway handles all pipeline logic and writes to SQLite. Streamlit only reads and displays.

---

## File Structure

```
hrca-agent/
├── api/                        ← FastAPI service (deploys to Railway)
│   ├── main.py                 ← /upload, /state, /events, /health
│   ├── pipeline.py             ← run_pipeline(csv_path, trigger_source)
│   ├── tools.py                ← check_schedule(), check_robot_state()
│   ├── alert.py                ← send_alert() — Slack first, email fallback
│   ├── db.py                   ← SQLite init, get_state, log_event
│   ├── requirements.txt
│   └── Procfile                ← Railway start command
│
├── dashboard/                  ← Streamlit service (deploys to Streamlit Cloud)
│   ├── app.py                  ← Live dashboard + supervisor upload
│   └── requirements.txt
│
├── data/
│   ├── hrca.db                 ← SQLite (auto-created on first run)
│   ├── robot_status.json       ← Stand-in for OPC-UA/PLC feed
│   ├── shift_schedule.csv      ← Sample schedule
│   └── incoming/               ← Uploaded CSVs (auto-managed)
│       └── archive/
│
├── .env                        ← API keys (never commit)
├── .gitignore
├── CLAUDE.md
└── README.md
```

---

## Local Development (Two Terminals)

### Prerequisites

- Python 3.11+
- A [Groq API key](https://console.groq.com) (free tier)
- Optional: Slack Incoming Webhook URL or Gmail App Password for real alerts

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/Fenear/agentic-ai-human-robot-coordination-smart-manufacturing
cd agentic-ai-human-robot-coordination-smart-manufacturing

# 2. Install API dependencies
cd api && pip install -r requirements.txt && cd ..

# 3. Install dashboard dependencies
cd dashboard && pip install -r requirements.txt && cd ..

# 4. Configure environment
# Edit .env and set your GROQ_API_KEY and (optionally) SLACK_WEBHOOK_URL
```

### Terminal 1 — Start the API

```bash
cd api
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.
- `GET /health` → `{"status": "ok"}`
- `GET /state` → current pipeline state from SQLite
- `GET /events` → recent conflict events
- `POST /upload` → trigger pipeline with a CSV file

### Terminal 2 — Start the Dashboard

```bash
cd dashboard
HRCA_API_URL=http://localhost:8000 streamlit run app.py
```

Open `http://localhost:8501` in your browser. The dashboard will connect to the API and auto-refresh every 30 seconds.

### Test the Pipeline

```bash
# POST the sample schedule directly (simulates MES machine upload)
curl -X POST http://localhost:8000/upload \
  -F "file=@data/shift_schedule.csv" \
  -F "trigger_source=machine"

# Check state
curl http://localhost:8000/state

# Check events
curl http://localhost:8000/events
```

**Note:** `data/robot_status.json` must be less than 60 seconds old. If you see `status: error` with `stale_data`, touch the file to refresh it:

```bash
# Linux/Mac
touch data/robot_status.json

# Windows (PowerShell)
(Get-Item data\robot_status.json).LastWriteTime = Get-Date
```

---

## Deploy FastAPI to Railway

1. Push your repo to GitHub (already done)
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
3. Select your repo, set **Root Directory** to `api/`
4. Add environment variables in the Railway dashboard:
   ```
   GROQ_API_KEY=your_groq_key
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
   LLM_MODEL=llama3-8b-8192
   STALE_THRESHOLD_SEC=60
   ```
5. Railway will detect `Procfile` and start:
   ```
   web: uvicorn main:app --host 0.0.0.0 --port $PORT
   ```
6. Note your public URL: `https://hrca-xxxx.up.railway.app`

---

## Deploy Dashboard to Streamlit Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**
2. Repo: your GitHub repo | Branch: `main` | File: `dashboard/app.py`
3. **Advanced settings → Secrets** — add:
   ```toml
   HRCA_API_URL = "https://hrca-xxxx.up.railway.app"
   ```
4. Click **Deploy**

The dashboard will pull live state and events from your Railway API.

---

## Machine Upload (MES/HR System)

Configure your MES or HR system to POST the shift CSV automatically at shift start:

**curl (from any system on the plant network):**

```bash
curl -X POST https://hrca-xxxx.up.railway.app/upload \
  -F "file=@shift_schedule.csv" \
  -F "trigger_source=machine"
```

**Python (from MES integration script):**

```python
import requests

with open("shift_schedule.csv", "rb") as f:
    requests.post(
        "https://hrca-xxxx.up.railway.app/upload",
        files={"file": f},
        data={"trigger_source": "machine"}
    )
```

The API responds immediately with `{"status": "accepted"}` and runs the pipeline in a background thread.

---

## Schedule CSV Format

```csv
name, badge_id, cell, shift_start, shift_end
Kim Chen, 4412, cell_7, 06:00, 14:00
Marco Rivera, 5531, cell_3, 06:00, 14:00
Aisha Patel, 6678, cell_14, 14:00, 22:00
```

Times are 24-hour `HH:MM`. Cell names must match keys in `robot_status.json`.

---

## Robot Status Format

`data/robot_status.json` (temporary stand-in for OPC-UA/PLC feed):

```json
{"cell_7": "active", "cell_3": "idle", "cell_14": "active"}
```

This file must be refreshed within 60 seconds or the pipeline will skip and log a `stale_data` event. Upgrade path: set `ROBOT_STATE_SOURCE` to a REST endpoint URL.

---

## Configuration Reference

All settings in `.env` (see `.env` for full list):

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Groq API key (required) |
| `LLM_MODEL` | Groq model (default: `llama3-8b-8192`) |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL |
| `SMTP_EMAIL` / `SMTP_PASSWORD` | Gmail for email fallback |
| `ALERT_RECIPIENT` | Supervisor email address |
| `STALE_THRESHOLD_SEC` | Max age of robot data in seconds (default: 60) |
| `HRCA_API_URL` | FastAPI URL for Streamlit to connect to |

---

## Guardrails

| Risk | Fix |
|---|---|
| Stale robot data | Pipeline skips and logs `stale_data` — never silently ignores |
| Duplicate file uploads | MD5 hash debounce: same content within 10s is ignored |
| LLM unavailable | Rule-based fallback alert — pipeline never stays silent |
| Two supervisors on dashboard | All state in SQLite — no session-state conflicts |
| FastAPI down | Streamlit shows last known state with "Pipeline Offline" banner |

**Human-in-the-loop:** Every alert requires supervisor acknowledgement. The agent never takes physical action.

---

## Tech Stack

| Layer | Tool | Cost |
|---|---|---|
| LLM | Groq API (llama3-8b-8192, free tier) | $0/month |
| Pipeline API | FastAPI + Python 3.11 | $0 |
| Dashboard | Streamlit | $0 |
| Shared state | SQLite (hrca.db) | $0 |
| Alerting | Slack Incoming Webhook or SMTP | $0 |
| API hosting | Railway (500 hrs/month free) | $0 |
| Dashboard hosting | Streamlit Community Cloud | $0 |

---

## Upgrade Path

```
v2 (Now — Free)          v3 (When needed)
─────────────────         ──────────────────────────
robot_status.json     →   OPC-UA / PLC REST feed
SQLite                →   PostgreSQL (Railway add-on, ~$5/mo)
Groq free tier        →   Claude Haiku API
Single plant          →   Multi-plant (one Railway deploy per plant)
No auth on /upload    →   API key header on /upload endpoint
```
