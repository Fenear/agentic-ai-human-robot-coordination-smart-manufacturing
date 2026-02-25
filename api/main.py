import uuid, os, shutil
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse
from db import init_db, get_state, get_events, set_state, log_event
from pipeline import run_pipeline
import hashlib, time, traceback

_ROOT = Path(__file__).parent.parent
INCOMING = _ROOT / "data" / "incoming"
ARCHIVE = INCOMING / "archive"

app = FastAPI()
init_db()

os.makedirs(INCOMING, exist_ok=True)
os.makedirs(ARCHIVE, exist_ok=True)

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
                    str(ARCHIVE / os.path.basename(state["current_csv"])))

    # Save new file with UUID + timestamp
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:6]
    filename = str(INCOMING / f"{ts}_{uid}.csv")
    with open(filename, "wb") as f:
        f.write(content)

    # Run pipeline in background for fast response
    import threading

    def _run(fn, ts):
        try:
            run_pipeline(fn, ts)
        except Exception:
            tb = traceback.format_exc()
            print(f"[HRCA] Pipeline thread crashed:\n{tb}", flush=True)
            try:
                set_state(status="error")
                log_event(
                    timestamp=datetime.utcnow().isoformat(),
                    cell="N/A", operator_name="N/A", badge_id="N/A",
                    conflict_type="thread_crash", alert_sent=0,
                    trigger_source=ts, alert_text=tb[:2000],
                )
            except Exception:
                pass

    threading.Thread(target=_run, args=(filename, trigger_source)).start()

    return JSONResponse({"status": "accepted", "file": filename,
                         "trigger_source": trigger_source})


@app.get("/state")
def get_pipeline_state():
    return get_state()


@app.get("/events")
def get_recent_events(limit: int = 50):
    return get_events(limit)


@app.post("/robot-status")
async def update_robot_status(request: Request):
    """Update robot cell states at runtime (replaces static robot_status.json).
    Body: {"cell_7": "active", "cell_3": "idle", ...}
    Writes to data/robot_status.json and touches its mtime so staleness check passes.
    """
    import json
    body = await request.json()
    robot_path = _ROOT / "data" / "robot_status.json"
    os.makedirs(robot_path.parent, exist_ok=True)
    with open(robot_path, "w") as f:
        json.dump(body, f)
    return {"status": "updated", "cells": body}


@app.get("/robot-status")
def get_robot_status():
    """Return current robot cell states from robot_status.json."""
    import json
    robot_path = _ROOT / "data" / "robot_status.json"
    if not robot_path.exists():
        return {}
    with open(robot_path) as f:
        return json.load(f)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug")
def debug():
    import sys, importlib.metadata
    groq_key = os.getenv("GROQ_API_KEY", "")
    try:
        groq_ver = importlib.metadata.version("groq")
    except Exception:
        groq_ver = "NOT INSTALLED"
    return {
        "python": sys.version,
        "groq_version": groq_ver,
        "groq_key_set": bool(groq_key),
        "groq_key_prefix": groq_key[:8] + "..." if groq_key else "NOT SET",
        "llm_model": os.getenv("LLM_MODEL", "llama3-8b-8192"),
    }
