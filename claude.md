# claude.md — Titan Manufacturing (Minimal Free Version)
## Human-Robot Coordination Agent (HRCA)

---

## 1. Agent Goal

**Primary Goal:** Detect robot-human scheduling conflicts on the plant floor and alert the right person in time to prevent safety incidents or downtime.

**Why it matters:** 17% of shifts have conflicts. A simple agent watching sensor + schedule data and sending alerts can cut that significantly with zero hardware changes.

**Success Metrics:**
- Conflicts caught before incident: ≥ 60%
- Alert delivered to supervisor in < 2 minutes
- Zero false-positive shutdowns per week

---

## 2. System Prompt

```
You are HRCA, a plant floor coordination assistant at Titan Manufacturing.

You monitor shift schedules and sensor alerts to detect when a human operator 
and an active robot cell are in conflict.

When you detect a conflict:
1. Identify which cell, which operator, and what the risk is
2. Send a clear plain-language alert to the shift supervisor
3. Log the event

Rules:
- Never act on sensor data older than 60 seconds
- If unsure, always alert a human — do not guess
- Keep every alert under 3 sentences
- Never recommend firing or disciplining anyone
- Always explain WHY you flagged something
```

---

## 3. Inputs

| Input | Source | How |
|---|---|---|
| Operator schedule | CSV export from HR system | Uploaded each shift start |
| Robot cell status | Manual entry or basic sensor JSON | Polled every 30 sec |
| Conflict trigger | Rule-based: human in zone + robot active | Local script |

---

## 4. Tools (Minimal Set)

| Tool | What it does | Free Option |
|---|---|---|
| `check_schedule` | Read shift CSV, find who's assigned where | Python + pandas |
| `check_robot_state` | Poll robot cell status (JSON/API) | requests library |
| `send_alert` | Notify supervisor | Email (SMTP) or Slack webhook |
| `log_event` | Write to log file | Python logging → local CSV |

---

## 5. Workflow

```
Every 30 seconds:
  1. Read robot cell states
  2. Read current shift schedule
  3. IF robot active AND operator assigned to same zone:
       → Generate alert via LLM
       → Send to supervisor (email/Slack)
       → Log to CSV
  4. ELSE: continue loop
```

---

## 6. Architecture Pattern

**Simple ReAct loop** — single agent, no orchestration needed.

```
Sensor/Schedule Data
        ↓
   Python Script
        ↓
   LLM (reasoning + alert text)
        ↓
   Email / Slack → Supervisor
        ↓
   Log to CSV
```

No cloud required. Runs on any laptop or cheap server on the plant network.

---

## 7. Risks & Guardrails

| Risk | Simple Fix |
|---|---|
| Stale sensor data | Skip action if data > 60s old; log warning |
| Too many false alerts | Add 5-minute cooldown per cell after each alert |
| LLM unavailable | Fallback: send raw rule-based alert without LLM reasoning |
| Wrong operator name | Always show both name + badge ID in alert |

**Human-in-the-loop:** Every alert requires supervisor acknowledgement. Agent never takes physical action — humans decide what to do.

---

## 8. Example Run

**Trigger:** Cell 7 is active. Schedule shows Operator Kim assigned to Cell 7 but shift ended 10 min ago.

**Agent reasoning:** Robot active + operator may still be present past scheduled time = conflict risk.

**Alert sent:**
> ⚠️ Cell 7 Alert: Operator Kim (Badge #4412) was scheduled to exit at 14:00 but cell is still active. Please confirm operator has cleared the zone. [14:23]

**Outcome:** Supervisor checks, Kim had already left. Alert logged, no action needed. Cooldown applied.

---

## 9. Tech Stack (All Free)

| Layer | Tool | Cost |
|---|---|---|
| LLM | Groq API (free tier) or Ollama (local llama3) | $0 |
| Language | Python 3.10+ | $0 |
| Agent framework | LangChain (open source) | $0 |
| Alerting | SMTP email or Slack Incoming Webhook | $0 |
| Storage | CSV files or SQLite | $0 |
| Hosting | Plant floor PC or Raspberry Pi 4 | ~$50 one-time |
| Scheduling | Python `schedule` library (cron-style) | $0 |

**Total ongoing cost: $0/month**
