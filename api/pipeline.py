"""
pipeline.py — HRCA conflict detection pipeline.

Adapted from hrca.py for FastAPI integration.
Renamed run loop to run_pipeline(csv_path, trigger_source).

Core logic preserved: LLM-generated alerts via Groq/llama3, rule-based
fallback if LLM unavailable, staleness guard on robot data.
"""

import os
from datetime import datetime
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv, find_dotenv

from tools import check_schedule, check_robot_state
from alert import send_alert
from db import set_state, log_event

load_dotenv(find_dotenv())

_ROOT = Path(__file__).parent.parent

SYSTEM_PROMPT = """\
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
"""

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
_model = genai.GenerativeModel(
    model_name=os.getenv("LLM_MODEL", "gemini-1.5-flash"),
    system_instruction=SYSTEM_PROMPT,
)


def run_pipeline(csv_path: str, trigger_source: str = "machine"):
    """Run one conflict-detection cycle for the given CSV schedule file.

    Called by FastAPI /upload endpoint (from machine or supervisor upload).
    Writes results to SQLite via db.py.
    """
    now = datetime.utcnow().isoformat()
    set_state(
        current_csv=csv_path,
        trigger_source=trigger_source,
        last_run_at=now,
        status="running",
    )

    # 1. Read schedule and robot state
    try:
        schedule = check_schedule(csv_path)
        robot_states = check_robot_state(
            os.getenv("ROBOT_STATE_SOURCE", str(_ROOT / "data" / "robot_status.json"))
        )
    except (ValueError, FileNotFoundError) as e:
        # Stale data or missing file — log and abort (never stay silent)
        set_state(status="error")
        log_event(
            timestamp=now, cell="N/A", operator_name="N/A",
            badge_id="N/A", conflict_type="stale_data",
            alert_sent=0, trigger_source=trigger_source,
            alert_text=str(e),
        )
        return

    # 2. Detect conflicts: operator assigned to cell where robot is active
    conflicts = []
    for cell, operators in schedule.items():
        if robot_states.get(cell) == "active":
            for op in operators:
                conflicts.append({"cell": cell, "operator": op})

    if not conflicts:
        set_state(status="ok", active_conflicts=0)
        return

    # 3. For each conflict: generate alert, send, log
    for c in conflicts:
        cell = c["cell"]
        op = c["operator"]

        # LLM alert generation with rule-based fallback
        try:
            prompt = (
                f"Cell: {cell}\n"
                f"Operator: {op['name']} (Badge {op['badge_id']})\n"
                f"Shift: {op['shift_start']}–{op['shift_end']}\n"
                f"Robot status: ACTIVE\n"
                f"Write the alert."
            )
            response = _model.generate_content(prompt)
            alert_text = response.text
        except Exception as llm_exc:
            print(f"[HRCA] LLM error ({type(llm_exc).__name__}): {llm_exc}", flush=True)
            # Fallback: rule-based alert — never stay silent
            alert_text = (
                f"⚠️ {cell}: {op['name']} (Badge #{op['badge_id']}) "
                f"is assigned to an active robot cell "
                f"({op['shift_start']}–{op['shift_end']}). "
                f"Please confirm zone is clear."
            )

        sent = send_alert(alert_text)
        log_event(
            timestamp=now, cell=cell, operator_name=op["name"],
            badge_id=op["badge_id"], conflict_type="zone_overlap",
            alert_sent=int(sent), trigger_source=trigger_source,
            alert_text=alert_text,
        )

    set_state(status="conflict", active_conflicts=len(conflicts))
