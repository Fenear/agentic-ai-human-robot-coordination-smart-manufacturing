# context.md — Titan Manufacturing Corporation
## HRCA Project Context: Full Implementation Guide (Free Stack)

---

## What We're Building

A two-service system:
- **FastAPI app** (Railway) — receives CSV uploads from machines or supervisors, runs the conflict-detection pipeline, sends alerts, writes to SQLite
- **Streamlit app** (Streamlit Cloud) — reads SQLite, shows live dashboard, accepts supervisor CSV uploads and forwards them to FastAPI

Both are free to host. Both read/write the same SQLite database.

---

## Why Two Services (Not One)

Streamlit Cloud is a **stateless web server**. It cannot:
- Receive HTTP POST requests from external systems (MES, HR)
- Run background threads reliably across sessions
- Maintain a persistent filesystem between deploys

FastAPI on Railway **can** do all of these. So FastAPI owns the pipeline and state; Streamlit owns the UI.

---

## Project File Structure

```
hrca-agent/
│
├── api/                        ← FastAPI service (deploys to Railway)
│   ├── main.py                 ← FastAPI app, /upload endpoint
│   ├── pipeline.py             ← run_pipeline() — core agent logic
│   ├── tools.py                ← check_schedule(), check_robot_state()
│   ├── alert.py                ← send_alert() via Slack/email
│   ├── db.py                   ← SQLite setup, read/write helpers
│   ├── requirements.txt        ← FastAPI dependencies
│   └── Procfile                ← Railway start command
│
├── dashboard/                  ← Streamlit service (deploys to Streamlit Cloud)
│   ├── app.py                  ← Streamlit dashboard
│   ├── requirements.txt        ← Streamlit dependencies
│   └── .streamlit/
│       └── secrets.toml        ← API URL + keys (local only, never committed)
│
├── data/
│   ├── hrca.db                 ← SQLite shared state (created on first run)
│   ├── incoming/               ← active CSV files
│   └── incoming/archive/       ← processed CSV files
│
├── .env.example                ← all env vars documented
├── .gitignore
└── README.md
```

---

## Implementation — Step by Step

### Step 1 — Database (db.py)

```python
import sqlite3, os

DB_PATH = os.getenv("DB_PATH", "data/hrca.db")

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_state (
            id INTEGER PRIMARY KEY DEFAULT 1,
            current_csv TEXT,
            trigger_source TEXT,
            last_run_at TEXT,
            active_conflicts INTEGER DEFAULT 0,
            status TEXT DEFAULT 'idle'
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            cell TEXT,
            operator_name TEXT,
            badge_id TEXT,
            conflict_type TEXT,
            alert_sent INTEGER DEFAULT 0,
            trigger_source TEXT,
            alert_text TEXT
        )
    """)
    # ensure one row in pipeline_state
    con.execute("INSERT OR IGNORE INTO pipeline_state (id) VALUES (1)")
    con.commit()
    con.close()

def set_state(**kwargs):
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values())
    con = sqlite3.connect(DB_PATH)
    con.execute(f"UPDATE pipeline_state SET {fields} WHERE id=1", values)
    con.commit()
    con.close()

def get_state():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM pipeline_state WHERE id=1").fetchone()
    con.close()
    return dict(row) if row else {}

def log_event(**kwargs):
    con = sqlite3.connect(DB_PATH)
    cols = ", ".join(kwargs.keys())
    placeholders = ", ".join("?" * len(kwargs))
    con.execute(f"INSERT INTO events ({cols}) VALUES ({placeholders})",
                list(kwargs.values()))
    con.commit()
    con.close()

def get_events(limit=50):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]
```

---

### Step 2 — Tools (tools.py)

```python
import pandas as pd, json, os
from datetime import datetime

def check_schedule(csv_path: str) -> dict:
    """Returns {cell: [{"name": ..., "badge_id": ..., "shift_start": ..., "shift_end": ...}]}"""
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    now = datetime.now().strftime("%H:%M")
    # Filter operators currently on shift
    active = df[(df["shift_start"] <= now) & (df["shift_end"] >= now)]
    result = {}
    for _, row in active.iterrows():
        cell = row["cell"]
        result.setdefault(cell, []).append({
            "name": row["name"],
            "badge_id": str(row["badge_id"]),
            "shift_start": row["shift_start"],
            "shift_end": row["shift_end"]
        })
    return result

def check_robot_state(source: str = "data/robot_status.json") -> dict:
    """
    Returns {cell: 'active' | 'idle'}
    source can be a file path or REST endpoint URL.
    NOTE: robot_status.json is a temporary stand-in for OPC-UA/PLC feed.
    Upgrade path: replace with requests.get(OPC_UA_ENDPOINT).json()
    """
    if source.startswith("http"):
        import requests
        data = requests.get(source, timeout=5).json()
    else:
        # Check staleness
        mtime = os.path.getmtime(source)
        age = (datetime.now().timestamp() - mtime)
        if age > 60:
            raise ValueError(f"robot_status.json is {int(age)}s old — stale data, skipping run")
        with open(source) as f:
            data = json.load(f)
    return data  # {"cell_7": "active", "cell_3": "idle", ...}
```

---

### Step 3 — Alert (alert.py)

```python
import os, smtplib
from email.message import EmailMessage
import requests

def send_alert(message: str) -> bool:
    """Try Slack first, fall back to email. Returns True if sent."""
    slack_url = os.getenv("SLACK_WEBHOOK_URL")
    if slack_url:
        r = requests.post(slack_url, json={"text": message}, timeout=5)
        if r.status_code == 200:
            return True

    # Email fallback
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_EMAIL")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    smtp_to   = os.getenv("ALERT_RECIPIENT")

    if smtp_user and smtp_pass and smtp_to:
        msg = EmailMessage()
        msg["Subject"] = "⚠️ HRCA Conflict Alert"
        msg["From"] = smtp_user
        msg["To"] = smtp_to
        msg.set_content(message)
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)
        return True

    return False  # both failed — pipeline logs this
```

---

### Step 4 — Pipeline (pipeline.py)

```python
import os
from datetime import datetime
from langchain_groq import ChatGroq
from langchain.schema import SystemMessage, HumanMessage
from tools import check_schedule, check_robot_state
from alert import send_alert
from db import set_state, log_event

SYSTEM_PROMPT = """You are HRCA, a plant floor coordination assistant at Titan Manufacturing.
You detect when a human operator and an active robot cell are in conflict.
When given a conflict, write a clear alert under 3 sentences.
Always include: cell name, operator name, badge ID, and why it is a risk.
Never recommend disciplinary action. Always explain the risk plainly."""

llm = ChatGroq(model="llama3-8b-8192", temperature=0)

def run_pipeline(csv_path: str, trigger_source: str = "machine"):
    now = datetime.utcnow().isoformat()
    set_state(current_csv=csv_path, trigger_source=trigger_source,
              last_run_at=now, status="running")
    try:
        schedule = check_schedule(csv_path)
        robot_states = check_robot_state(
            os.getenv("ROBOT_STATE_SOURCE", "data/robot_status.json")
        )
    except ValueError as e:
        set_state(status="error")
        log_event(timestamp=now, cell="N/A", operator_name="N/A",
                  badge_id="N/A", conflict_type="stale_data",
                  alert_sent=0, trigger_source=trigger_source,
                  alert_text=str(e))
        return

    conflicts = []
    for cell, operators in schedule.items():
        if robot_states.get(cell) == "active":
            for op in operators:
                conflicts.append({"cell": cell, "operator": op})

    if not conflicts:
        set_state(status="ok", active_conflicts=0)
        return

    for c in conflicts:
        cell = c["cell"]
        op = c["operator"]

        # LLM alert generation with rule-based fallback
        try:
            prompt = (f"Cell: {cell}\nOperator: {op['name']} "
                      f"(Badge {op['badge_id']})\n"
                      f"Shift: {op['shift_start']}–{op['shift_end']}\n"
                      f"Robot status: ACTIVE\nWrite the alert.")
            response = llm.invoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt)
            ])
            alert_text = response.content
        except Exception:
            alert_text = (f"⚠️ {cell}: {op['name']} (Badge #{op['badge_id']}) "
                          f"is assigned to an active robot cell "
                          f"({op['shift_start']}–{op['shift_end']}). "
                          f"Please confirm zone is clear.")

        sent = send_alert(alert_text)
        log_event(timestamp=now, cell=cell, operator_name=op["name"],
                  badge_id=op["badge_id"], conflict_type="zone_overlap",
                  alert_sent=int(sent), trigger_source=trigger_source,
                  alert_text=alert_text)

    set_state(status="conflict", active_conflicts=len(conflicts))
```

---

### Step 5 — FastAPI (api/main.py)

```python
import uuid, os, shutil
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from db import init_db, get_state, get_events
from pipeline import run_pipeline
import hashlib, time

app = FastAPI()
init_db()

os.makedirs("data/incoming", exist_ok=True)
os.makedirs("data/incoming/archive", exist_ok=True)

# Debounce: track last file hash + time
_last_hash = None
_last_hash_time = 0

@app.post("/upload")
async def upload_csv(
    file: UploadFile = File(...),
    trigger_source: str = Form(default="machine")
):
    global _last_hash, _last_hash_time
    content = await file.read()

    # Debounce: ignore duplicate content within 10 seconds
    file_hash = hashlib.md5(content).hexdigest()
    if file_hash == _last_hash and (time.time() - _last_hash_time) < 10:
        return JSONResponse({"status": "debounced", "message": "Duplicate file ignored"})
    _last_hash = file_hash
    _last_hash_time = time.time()

    # Archive previous file if exists
    state = get_state()
    if state.get("current_csv") and os.path.exists(state["current_csv"]):
        shutil.move(state["current_csv"], 
                    f"data/incoming/archive/{os.path.basename(state['current_csv'])}")

    # Save new file with UUID + timestamp
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:6]
    filename = f"data/incoming/{ts}_{uid}.csv"
    with open(filename, "wb") as f:
        f.write(content)

    # Run pipeline (in background for fast response)
    import threading
    threading.Thread(target=run_pipeline, args=(filename, trigger_source)).start()

    return JSONResponse({"status": "accepted", "file": filename,
                         "trigger_source": trigger_source})

@app.get("/state")
def get_pipeline_state():
    return get_state()

@app.get("/events")
def get_recent_events(limit: int = 50):
    return get_events(limit)

@app.get("/health")
def health():
    return {"status": "ok"}
```

---

### Step 6 — Streamlit Dashboard (dashboard/app.py)

```python
import streamlit as st
import requests, os, time
from datetime import datetime

API_URL = os.getenv("HRCA_API_URL", st.secrets.get("HRCA_API_URL", "http://localhost:8000"))

st.set_page_config(page_title="HRCA Dashboard", layout="wide", page_icon="🏭")
st.title("🏭 HRCA — Human-Robot Coordination Agent")

# ── Sidebar: Upload ──────────────────────────────────────────
with st.sidebar:
    st.header("📂 Upload Shift Schedule")
    st.caption("Supervisor manual upload — or MES uploads automatically via API")
    uploaded = st.file_uploader("shift_schedule.csv", type=["csv"])
    if uploaded:
        with st.spinner("Sending to pipeline..."):
            r = requests.post(
                f"{API_URL}/upload",
                files={"file": (uploaded.name, uploaded.getvalue(), "text/csv")},
                data={"trigger_source": "supervisor"}
            )
        if r.status_code == 200:
            result = r.json()
            if result["status"] == "debounced":
                st.warning("Same file already processing — skipped.")
            else:
                st.success(f"✅ Uploaded. Pipeline running...")
        else:
            st.error("Upload failed — check API connection.")

# ── Fetch state ──────────────────────────────────────────────
try:
    state = requests.get(f"{API_URL}/state", timeout=3).json()
    events = requests.get(f"{API_URL}/events?limit=50", timeout=3).json()
    api_online = True
except Exception:
    state = {}
    events = []
    api_online = False

# ── Status Banner ─────────────────────────────────────────────
col1, col2, col3 = st.columns(3)

with col1:
    if not api_online:
        st.error("🔴 Pipeline Offline")
    elif state.get("status") == "conflict":
        st.error(f"🚨 {state['active_conflicts']} Active Conflict(s)")
    elif state.get("status") == "running":
        st.warning("🔄 Pipeline Running...")
    elif state.get("status") == "error":
        st.error("⚠️ Pipeline Error — Check logs")
    else:
        st.success("✅ No Conflicts")

with col2:
    src = state.get("trigger_source", "—")
    icon = "🤖" if src == "machine" else "👤"
    st.metric("Last Trigger", f"{icon} {src.capitalize()}")

with col3:
    last_run = state.get("last_run_at", "Never")
    if last_run != "Never":
        last_run = last_run[:19].replace("T", " ") + " UTC"
    st.metric("Last Run", last_run)

# ── Active conflict detail ────────────────────────────────────
if state.get("status") == "conflict" and events:
    st.divider()
    st.subheader("🚨 Active Alerts")
    for e in [e for e in events if e["conflict_type"] == "zone_overlap"][:3]:
        with st.container(border=True):
            st.error(e["alert_text"])
            st.caption(f"Cell: {e['cell']} | Operator: {e['operator_name']} "
                       f"(Badge #{e['badge_id']}) | {e['timestamp'][:19]} UTC")

# ── Events log ────────────────────────────────────────────────
st.divider()
st.subheader("📋 Events Log")
if events:
    import pandas as pd
    df = pd.DataFrame(events)
    df = df[["timestamp", "cell", "operator_name", "badge_id",
             "conflict_type", "alert_sent", "trigger_source"]]
    df.columns = ["Time", "Cell", "Operator", "Badge", "Type", "Alert Sent", "Source"]
    df["Alert Sent"] = df["Alert Sent"].map({1: "✅", 0: "❌"})
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("No events yet. Upload a shift schedule to start.")

# ── Current file ──────────────────────────────────────────────
if state.get("current_csv"):
    st.caption(f"Active schedule: `{os.path.basename(state['current_csv'])}`")

# ── Auto-refresh ──────────────────────────────────────────────
st.caption(f"Auto-refreshing every 30 seconds | {datetime.utcnow().strftime('%H:%M:%S')} UTC")
time.sleep(30)
st.rerun()
```

---

### Step 7 — Environment Variables

```bash
# .env.example — copy to .env, never commit .env

# LLM
GROQ_API_KEY=your_groq_key_here

# Alerting (at least one required)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your@gmail.com
SMTP_PASSWORD=your_app_password
ALERT_RECIPIENT=supervisor@titan.com

# Robot state source (file path or REST URL)
ROBOT_STATE_SOURCE=data/robot_status.json

# Database
DB_PATH=data/hrca.db

# For Streamlit: URL of the deployed FastAPI
HRCA_API_URL=https://your-railway-app.up.railway.app
```

---

## Deployment

### Deploy FastAPI to Railway

```bash
# In api/ folder, create Procfile:
echo "web: uvicorn main:app --host 0.0.0.0 --port $PORT" > Procfile

# Push to GitHub, then:
# 1. railway.app → New Project → Deploy from GitHub
# 2. Select hrca-agent repo, root directory: api/
# 3. Add all env vars from .env in Railway dashboard
# 4. Railway gives you a public URL: https://hrca-xxxx.up.railway.app
```

### Deploy Streamlit to Streamlit Cloud

```bash
# 1. share.streamlit.io → New app
# 2. Repo: hrca-agent, Branch: main, File: dashboard/app.py
# 3. Advanced settings → Secrets:
#    HRCA_API_URL = "https://hrca-xxxx.up.railway.app"
#    GROQ_API_KEY = "your_key"  (if dashboard ever needs it)
# 4. Deploy
```

### Machine Upload (MES/HR System)

Configure your MES or HR system to POST the CSV on shift start:

```bash
# Example: curl from any system on the plant network
curl -X POST https://hrca-xxxx.up.railway.app/upload \
  -F "file=@shift_schedule.csv" \
  -F "trigger_source=machine"
```

```python
# Example: Python from MES integration script
import requests
with open("shift_schedule.csv", "rb") as f:
    requests.post(
        "https://hrca-xxxx.up.railway.app/upload",
        files={"file": f},
        data={"trigger_source": "machine"}
    )
```

---

## Claude Code Prompts to Build This

Run these in order from your project root:

```bash
# 1. Scaffold structure
claude "Create the folder structure from context.md: api/ and dashboard/ directories with empty files"

# 2. Database layer
claude "Implement api/db.py exactly as specified in context.md Step 1"

# 3. Tools
claude "Implement api/tools.py exactly as specified in context.md Step 2, including the staleness check and OPC-UA upgrade note"

# 4. Alerts
claude "Implement api/alert.py exactly as specified in context.md Step 3"

# 5. Pipeline
claude "Implement api/pipeline.py using the system prompt from CLAUDE.md section 2, and the logic from context.md Step 4"

# 6. FastAPI
claude "Implement api/main.py exactly as specified in context.md Step 5"

# 7. Dashboard
claude "Implement dashboard/app.py exactly as specified in context.md Step 6"

# 8. Config files
claude "Create api/requirements.txt, dashboard/requirements.txt, api/Procfile, .env.example, and .gitignore for this project"

# 9. Test locally
claude "Write a test script test_local.py that creates a sample shift_schedule.csv and robot_status.json, starts the FastAPI server, POSTs the CSV, and prints the /state and /events response"

# 10. README
claude "Write README.md covering: local dev setup, deploying FastAPI to Railway, deploying Streamlit to Streamlit Cloud, and how to configure MES machine upload using the curl and Python examples from context.md"
```

---

## Upgrade Path

```
v1 (Now — Free)              v2 (When needed)
─────────────────            ──────────────────────────
robot_status.json        →   OPC-UA / PLC REST feed
SQLite                   →   PostgreSQL (Railway add-on, ~$5/mo)
Groq free tier           →   Claude Haiku API
Single plant             →   Multi-plant (one Railway deploy per plant)
No auth on /upload       →   API key header on /upload endpoint
Manual robot_status.json →   IoT sensor feed via MQTT/Greengrass
```
