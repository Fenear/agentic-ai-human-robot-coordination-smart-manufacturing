"""
tools.py — Data tools for the HRCA pipeline.

Adapted from v1 tools.py. Provides plain functions (no LangChain decorators)
for use by pipeline.py.

Provides: check_schedule(), check_robot_state()
"""

import os
import json
from datetime import datetime

import pandas as pd

STALE_THRESHOLD_SEC = int(os.getenv("STALE_THRESHOLD_SEC", "60"))


def check_schedule(csv_path: str) -> dict:
    """Read shift CSV, find who's assigned where right now.

    Returns {cell: [{"name": ..., "badge_id": ..., "shift_start": ..., "shift_end": ...}]}
    """
    df = pd.read_csv(csv_path, skipinitialspace=True)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    now = datetime.now().strftime("%H:%M")

    # Filter operators currently on shift
    active = df[(df["shift_start"] <= now) & (df["shift_end"] >= now)]

    result = {}
    for _, row in active.iterrows():
        cell = row["cell"].strip().lower()
        result.setdefault(cell, []).append({
            "name": row["name"].strip(),
            "badge_id": str(row["badge_id"]),
            "shift_start": row["shift_start"].strip(),
            "shift_end": row["shift_end"].strip(),
        })
    return result


def check_robot_state(source: str = "data/robot_status.json") -> dict:
    """Poll robot cell status from JSON file or REST endpoint.

    Returns {cell: 'active' | 'idle'}

    NOTE: robot_status.json is a temporary stand-in for OPC-UA/PLC feed.
    Upgrade path: replace with requests.get(OPC_UA_ENDPOINT).json()
    """
    if source.startswith("http"):
        import requests
        data = requests.get(source, timeout=5).json()
    else:
        # Check staleness
        mtime = os.path.getmtime(source)
        age = datetime.now().timestamp() - mtime
        if age > STALE_THRESHOLD_SEC:
            raise ValueError(
                f"robot_status.json is {int(age)}s old "
                f"(threshold {STALE_THRESHOLD_SEC}s) — stale data, skipping run"
            )
        with open(source) as f:
            data = json.load(f)

    return data  # {"cell_7": "active", "cell_3": "idle", ...}
