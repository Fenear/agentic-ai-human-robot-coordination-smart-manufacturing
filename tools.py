"""
tools.py — LangChain tools for the HRCA agent.

Provides: check_schedule, check_robot_state, log_event
"""

import os
import csv
import json
from datetime import datetime, timedelta

import pandas as pd
from langchain.tools import tool

# ---------------------------------------------------------------------------
# Paths (relative to project root)
# ---------------------------------------------------------------------------
SCHEDULE_CSV = os.getenv("SCHEDULE_CSV", "shift_schedule.csv")
ROBOT_STATUS_SOURCE = os.getenv("ROBOT_STATUS_SOURCE", "robot_status.json")
EVENTS_CSV = os.getenv("EVENTS_CSV", "events.csv")
STALE_THRESHOLD_SEC = int(os.getenv("STALE_THRESHOLD_SEC", "60"))


# ---------------------------------------------------------------------------
# Tool: check_schedule
# ---------------------------------------------------------------------------
@tool
def check_schedule(cell: str) -> str:
    """Look up which operators are assigned to a given robot cell right now.

    Args:
        cell: The cell identifier, e.g. 'cell_7'.

    Returns:
        A summary of operators currently scheduled for that cell, or a
        message saying no one is assigned.
    """
    try:
        df = pd.read_csv(SCHEDULE_CSV, skipinitialspace=True)
    except FileNotFoundError:
        return f"ERROR: Schedule file '{SCHEDULE_CSV}' not found."

    # Normalise column names
    df.columns = [c.strip().lower() for c in df.columns]

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    matches = df[df["cell"].str.strip().str.lower() == cell.strip().lower()]
    if matches.empty:
        return f"No operators are assigned to {cell} in the current schedule."

    results = []
    for _, row in matches.iterrows():
        name = row["name"].strip()
        badge = row["badge_id"]
        shift_start = row["shift_start"].strip()
        shift_end = row["shift_end"].strip()

        # Parse times — assume today's date
        try:
            start_dt = datetime.strptime(f"{today_str} {shift_start}", "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(f"{today_str} {shift_end}", "%Y-%m-%d %H:%M")
        except ValueError:
            start_dt = end_dt = None

        status = "ON SHIFT" if start_dt and start_dt <= now <= end_dt else "OFF SHIFT"
        results.append(
            f"- {name} (Badge #{badge}) | Shift {shift_start}–{shift_end} | {status}"
        )

    return f"Operators assigned to {cell}:\n" + "\n".join(results)


# ---------------------------------------------------------------------------
# Tool: check_robot_state
# ---------------------------------------------------------------------------
@tool
def check_robot_state(cell: str) -> str:
    """Check whether a specific robot cell is active, idle, or in another state.

    Args:
        cell: The cell identifier, e.g. 'cell_7'.

    Returns:
        The current state of the cell, or an error if data is stale/missing.
    """
    source = ROBOT_STATUS_SOURCE

    try:
        if source.startswith("http"):
            import requests
            resp = requests.get(source, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        else:
            # Local JSON file
            stat = os.stat(source)
            age = datetime.now().timestamp() - stat.st_mtime
            if age > STALE_THRESHOLD_SEC:
                return (
                    f"WARNING: robot_status.json is {int(age)}s old "
                    f"(threshold {STALE_THRESHOLD_SEC}s). Data may be stale — skipping action."
                )
            with open(source, "r") as f:
                data = json.load(f)
    except FileNotFoundError:
        return f"ERROR: Robot status source '{source}' not found."
    except Exception as exc:
        return f"ERROR reading robot status: {exc}"

    cell_key = cell.strip().lower()
    # Try exact match then normalised match
    state = data.get(cell) or data.get(cell_key)
    if state is None:
        available = ", ".join(data.keys())
        return f"Cell '{cell}' not found in robot status. Available cells: {available}"

    return f"Cell {cell} is currently **{state}**."


# ---------------------------------------------------------------------------
# Tool: log_event
# ---------------------------------------------------------------------------
@tool
def log_event(cell: str, operator: str, badge_id: str, risk: str, action_taken: str) -> str:
    """Log a conflict event to the audit CSV file.

    Args:
        cell: The robot cell involved.
        operator: Name of the operator involved.
        badge_id: Badge ID of the operator.
        risk: Short description of the risk detected.
        action_taken: What was done (e.g. 'alert_sent').

    Returns:
        Confirmation that the event was logged.
    """
    file_exists = os.path.isfile(EVENTS_CSV)
    timestamp = datetime.now().isoformat()

    with open(EVENTS_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "cell", "operator", "badge_id", "risk", "action_taken"])
        writer.writerow([timestamp, cell, operator, badge_id, risk, action_taken])

    return f"Event logged at {timestamp} for {cell} / {operator}."
