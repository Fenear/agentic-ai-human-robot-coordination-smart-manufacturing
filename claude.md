# CLAUDE.md — Titan Manufacturing Corporation
## Human-Robot Coordination Agent (HRCA)
### Version 2 — Updated Architecture (Free, Production-Realistic)

---

## 1. Agent Goal

**Primary Goal:** Detect robot-human scheduling conflicts on the plant floor and alert the right person in time to prevent safety incidents or downtime.

**Why it matters:** 17% of shifts have conflicts. An agent watching schedule + robot state data and sending alerts can cut that significantly with zero hardware changes.

**Success Metrics:**
- Conflicts caught before incident: ≥ 60%
- Alert delivered to supervisor in < 2 minutes
- Zero false-positive shutdowns per week
- Pipeline auto-triggers within 5 seconds of any new CSV (machine or manual)

---

## 2. System Prompt

```
You are HRCA, a plant floor coordination assistant at Titan Manufacturing.

You monitor shift schedules and robot cell states to detect when a human 
operator and an active robot cell are in conflict.

When you detect a conflict:
1. Identify which cell, which operator, and what the risk is
2. Send a clear plain-language alert to the shift supervisor
3. Log the event with full context

Rules:
- Never act on robot state data older than 60 seconds — flag it as stale
- If unsure, always alert a human — do not guess
- Keep every alert under 3 sentences
- Never recommend firing or disciplining anyone
- Always explain WHY you flagged something
- If LLM is unavailable, fall back to rule-based alert — never stay silent
```

---

## 3. Inputs

| Input | Source | How |
|---|---|---|
| Operator schedule | CSV from MES/HR system | POST to `/upload` endpoint (machine) or Streamlit UI (supervisor) |
| Robot cell status | PLC/SCADA or robot_status.json (temp) | Polled every 30 sec via `check_robot_state()` |
| Conflict trigger | Rule: human in zone + robot active | run_pipeline() function |

**Note:** `robot_status.json` is a temporary stand-in for a proper OPC-UA or REST feed from PLCs. See upgrade path in context.md.

---

## 4. Tools

| Tool | What it does | Free Option |
|---|---|---|
| `check_schedule` | Read shift CSV, find who's assigned where | Python + pandas |
| `check_robot_state` | Poll robot cell status from JSON or REST | requests library |
| `send_alert` | Notify supervisor | Slack webhook or SMTP email |
| `log_event` | Write structured event to SQLite | Python sqlite3 |
| `get_pipeline_state` | Read current run state from SQLite | sqlite3 |
| `set_pipeline_state` | Write trigger source, timestamp, conflicts to SQLite | sqlite3 |

---

## 5. Workflow

```
TRIGGER (either source)
  → Machine: MES/HR POSTs CSV to FastAPI /upload
  → Supervisor: uploads CSV via Streamlit → Streamlit POSTs to FastAPI /upload

FastAPI receives file:
  1. Save to incoming/ with UUID + timestamp filename
  2. Archive any previous CSV to incoming/archive/
  3. Call run_pipeline(csv_path, trigger_source)

run_pipeline():
  1. check_schedule(csv_path) → active operators per cell
  2. check_robot_state() → active robot cells
  3. Find overlaps (operator assigned to active robot cell)
  4. For each conflict:
       → Call LLM to generate alert text
       → send_alert() via Slack/email
       → log_event() to SQLite
  5. set_pipeline_state() → write result to SQLite

Streamlit dashboard:
  → Reads SQLite every 30 seconds (st.rerun)
  → Shows live status, conflicts, events log
  → Supervisor upload → POST to FastAPI /upload
```

---

## 6. Architecture

**Split responsibilities: FastAPI handles pipeline, Streamlit handles UI**

```
Plant Network / MES                 Cloud (Free)
───────────────────                 ──────────────────────────────
MES/HR drops CSV        →           Railway — FastAPI app
  HTTP POST                           POST /upload (both sources)
  to /upload                          run_pipeline()
                                       check_schedule()
Supervisor laptop        →             check_robot_state()
  Streamlit UI                         send_alert()
  uploads CSV                          log_event() → SQLite
  → POST to /upload
                                    Streamlit Cloud — app.py
                                      reads SQLite (shared)
                                      shows dashboard
                                      supervisor upload widget
                                      auto-refresh every 30s
```

**Why split:** Streamlit Cloud is stateless — it cannot run background processes, maintain a filesystem, or receive HTTP POSTs from external systems. FastAPI on Railway handles all pipeline logic and persists state to SQLite. Streamlit only reads and displays.

---

## 7. Shared State (SQLite)

Single SQLite file `hrca.db` shared between FastAPI and Streamlit.

```sql
-- pipeline_state: one row, always updated
CREATE TABLE pipeline_state (
  id INTEGER PRIMARY KEY DEFAULT 1,
  current_csv TEXT,           -- path to active CSV
  trigger_source TEXT,        -- 'machine' or 'supervisor'
  last_run_at TEXT,           -- ISO timestamp
  active_conflicts INTEGER,   -- count
  status TEXT                 -- 'ok', 'conflict', 'error'
);

-- events: append-only audit log
CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT,
  cell TEXT,
  operator_name TEXT,
  badge_id TEXT,
  conflict_type TEXT,
  alert_sent INTEGER,         -- 0 or 1
  trigger_source TEXT,
  alert_text TEXT
);
```

---

## 8. Risks & Guardrails

| Risk | Fix |
|---|---|
| Stale robot data | Skip run if robot_status.json > 60s old; log warning to SQLite |
| Duplicate file drops | Debounce: if same content hash arrives within 10s, ignore second |
| Two supervisors open dashboard | Session state is per-user; all real state lives in SQLite |
| LLM unavailable | Fallback rule-based alert — pipeline never silently skips |
| Filename collision in archive | UUID + millisecond timestamp on every file |
| FastAPI down | Streamlit shows last known state with 'Pipeline offline' banner |

**Human-in-the-loop:** Every alert requires supervisor acknowledgement in the dashboard. Agent never takes physical action — humans decide.

---

## 9. Example Run

**Trigger:** MES system POSTs `shift_14h00.csv` to FastAPI `/upload` at 13:58.

**Pipeline:**
1. File saved as `incoming/2024-01-15_135800_a3f9.csv`
2. `check_schedule()` → Kim Chen (Badge #4412) assigned to Cell 7, 14:00–17:00
3. `check_robot_state()` → Cell 7 active
4. Conflict detected: operator scheduled to enter active cell at shift start
5. LLM generates: *"⚠️ Cell 7: Kim Chen (Badge #4412) is scheduled to enter at 14:00 but cell is currently active. Confirm cell is clear before shift handover. [13:58]"*
6. Slack alert sent, SQLite updated, dashboard refreshes

**Outcome:** Supervisor sees alert at 13:59, radios to confirm cell clear. Conflict avoided. Logged.

---

## 10. Tech Stack (All Free)

| Layer | Tool | Cost |
|---|---|---|
| LLM | Groq API (free tier) — llama3-8b | $0/month |
| Pipeline engine | FastAPI + Python 3.11 | $0 |
| Agent framework | LangChain (open source) | $0 |
| UI | Streamlit | $0 |
| Shared state | SQLite (hrca.db) | $0 |
| Alerting | Slack Incoming Webhook or SMTP | $0 |
| Pipeline hosting | Railway (free tier — 500hrs/month) | $0 |
| UI hosting | Streamlit Community Cloud | $0 |
| Version control | GitHub | $0 |

**Total ongoing cost: $0/month**
