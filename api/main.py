import uuid, os, shutil
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from db import init_db, get_state, get_events
from pipeline import run_pipeline
import hashlib, time

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
