#!/usr/bin/env python3
"""
hrca.py — Human-Robot Coordination Agent (HRCA)
Titan Manufacturing — Minimum Viable Agent (v1, free tier)

Monitors shift schedules and robot cell states every 30 seconds.
When a conflict is detected (human assigned to an active robot cell),
the agent generates a plain-language alert via an LLM, sends it to
the supervisor, and logs the event.

Usage:
    python hrca.py
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
import schedule
from dotenv import load_dotenv
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq

from alert import send_alert
from tools import check_schedule, check_robot_state, log_event

# ---------------------------------------------------------------------------
# Load environment
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "30"))
COOLDOWN_MIN = int(os.getenv("COOLDOWN_MIN", "5"))
SCHEDULE_CSV = os.getenv("SCHEDULE_CSV", "shift_schedule.csv")
ROBOT_STATUS_SOURCE = os.getenv("ROBOT_STATUS_SOURCE", "robot_status.json")

SYSTEM_PROMPT = """\
You are HRCA, a plant floor coordination assistant at Titan Manufacturing.

You monitor shift schedules and sensor alerts to detect when a human operator \
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

You have access to the following tools:

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
Thought:{agent_scratchpad}"""

# ---------------------------------------------------------------------------
# Cooldown tracker: cell -> last alert datetime
# ---------------------------------------------------------------------------
_cooldowns: dict[str, datetime] = {}


def _is_cooled_down(cell: str) -> bool:
    """Return True if enough time has passed since the last alert for this cell."""
    last = _cooldowns.get(cell)
    if last is None:
        return True
    return datetime.now() - last >= timedelta(minutes=COOLDOWN_MIN)


def _record_cooldown(cell: str) -> None:
    _cooldowns[cell] = datetime.now()


# ---------------------------------------------------------------------------
# LLM + Agent setup
# ---------------------------------------------------------------------------
def _build_agent() -> AgentExecutor:
    """Create the LangChain ReAct agent with all HRCA tools."""
    llm = ChatGroq(
        model_name=os.getenv("LLM_MODEL", "llama3-8b-8192"),
        temperature=0,
        api_key=os.getenv("GROQ_API_KEY"),
    )

    tools = [check_schedule, check_robot_state, send_alert, log_event]

    prompt = PromptTemplate.from_template(SYSTEM_PROMPT)

    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)

    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=6,
    )


# ---------------------------------------------------------------------------
# Fallback: rule-based alert (when LLM is unavailable)
# ---------------------------------------------------------------------------
def _fallback_alert(cell: str, operator: str, badge_id: str, risk: str) -> None:
    """Send a raw rule-based alert without LLM reasoning."""
    now = datetime.now().strftime("%H:%M")
    message = (
        f"⚠️ {cell.upper()} ALERT: Operator {operator} (Badge #{badge_id}) "
        f"may be in conflict with an active robot cell. {risk} [{now}]"
    )
    result = send_alert.invoke({"message": message})
    log_event.invoke({
        "cell": cell,
        "operator": operator,
        "badge_id": str(badge_id),
        "risk": risk,
        "action_taken": f"fallback_alert_sent | {result}",
    })
    print(f"[FALLBACK] {message}")


# ---------------------------------------------------------------------------
# Core polling loop
# ---------------------------------------------------------------------------
def poll_and_check(agent: AgentExecutor) -> None:
    """Run one cycle: read status, detect conflicts, alert if needed."""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Polling…")

    # 1. Read robot cell states
    try:
        source = ROBOT_STATUS_SOURCE
        if source.startswith("http"):
            import requests
            data = requests.get(source, timeout=5).json()
        else:
            with open(source, "r") as f:
                data = json.load(f)
    except Exception as exc:
        print(f"  ✗ Could not read robot status: {exc}")
        return

    # 2. Read schedule
    try:
        df = pd.read_csv(SCHEDULE_CSV, skipinitialspace=True)
        df.columns = [c.strip().lower() for c in df.columns]
    except Exception as exc:
        print(f"  ✗ Could not read schedule: {exc}")
        return

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # 3. Detect conflicts: robot active AND operator assigned to same cell
    active_cells = [cell for cell, state in data.items() if state.lower() == "active"]

    if not active_cells:
        print("  No active robot cells — all clear.")
        return

    for cell in active_cells:
        # Find operators assigned to this cell
        assigned = df[df["cell"].str.strip().str.lower() == cell.strip().lower()]
        if assigned.empty:
            continue

        for _, row in assigned.iterrows():
            name = row["name"].strip()
            badge_id = row["badge_id"]
            shift_start = row["shift_start"].strip()
            shift_end = row["shift_end"].strip()

            # Determine risk: operator's shift overlaps with now, or ended recently
            try:
                start_dt = datetime.strptime(f"{today_str} {shift_start}", "%Y-%m-%d %H:%M")
                end_dt = datetime.strptime(f"{today_str} {shift_end}", "%Y-%m-%d %H:%M")
            except ValueError:
                continue

            on_shift = start_dt <= now <= end_dt
            recently_ended = end_dt < now <= end_dt + timedelta(minutes=15)

            if not (on_shift or recently_ended):
                continue

            if not _is_cooled_down(cell):
                print(f"  ⏳ Cooldown active for {cell} — skipping alert.")
                continue

            # Build a conflict query for the agent
            if recently_ended:
                risk = (
                    f"Operator {name} (Badge #{badge_id}) was scheduled until "
                    f"{shift_end} but cell {cell} is still active "
                    f"({int((now - end_dt).total_seconds() // 60)} min past shift end)."
                )
            else:
                risk = (
                    f"Operator {name} (Badge #{badge_id}) is ON SHIFT in {cell} "
                    f"which is currently ACTIVE. Confirm operator is clear of the zone."
                )

            query = (
                f"Conflict detected in {cell}: {risk} "
                f"Check the schedule for {cell}, confirm the robot state, "
                f"send an alert to the supervisor, and log the event."
            )

            print(f"  ⚠ Conflict: {cell} / {name}")

            # Try LLM agent; fall back to raw alert on failure
            try:
                agent.invoke({"input": query})
            except Exception as exc:
                print(f"  ✗ LLM agent failed ({exc}). Using fallback alert.")
                _fallback_alert(cell, name, badge_id, risk)

            _record_cooldown(cell)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("  HRCA — Human-Robot Coordination Agent")
    print("  Titan Manufacturing (v1 — Free Tier)")
    print("=" * 60)
    print(f"  Poll interval : {POLL_INTERVAL_SEC}s")
    print(f"  Cooldown      : {COOLDOWN_MIN} min per cell")
    print(f"  Schedule file : {SCHEDULE_CSV}")
    print(f"  Robot status  : {ROBOT_STATUS_SOURCE}")
    print(f"  Alert method  : {os.getenv('ALERT_METHOD', 'slack')}")
    print("=" * 60)

    agent = _build_agent()

    # Run once immediately, then on schedule
    poll_and_check(agent)

    schedule.every(POLL_INTERVAL_SEC).seconds.do(poll_and_check, agent=agent)

    print(f"\n🔄 Agent running — polling every {POLL_INTERVAL_SEC}s. Press Ctrl+C to stop.\n")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Agent stopped by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
