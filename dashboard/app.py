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
            try:
                r = requests.post(
                    f"{API_URL}/upload",
                    files={"file": (uploaded.name, uploaded.getvalue(), "text/csv")},
                    data={"trigger_source": "supervisor"},
                    timeout=10,
                )
                if r.status_code == 200:
                    result = r.json()
                    if result["status"] == "debounced":
                        st.warning("Same file already processing — skipped.")
                    else:
                        st.success("✅ Uploaded. Pipeline running...")
                else:
                    st.error("Upload failed — check API connection.")
            except requests.exceptions.ConnectionError:
                st.error(f"❌ Cannot reach API at `{API_URL}`. Is the backend deployed?")
            except requests.exceptions.Timeout:
                st.error("❌ API request timed out.")

# ── Fetch state ──────────────────────────────────────────────
try:
    state = requests.get(f"{API_URL}/state", timeout=3).json()
    events = requests.get(f"{API_URL}/events?limit=50", timeout=3).json()
    api_online = True
except Exception:
    state = {}
    events = []
    api_online = False

# ── Toast notifications for new conflicts ─────────────────────
if "last_notified_id" not in st.session_state:
    st.session_state.last_notified_id = 0

new_conflicts = [
    e for e in events
    if e["conflict_type"] == "zone_overlap"
    and e["id"] > st.session_state.last_notified_id
]
for e in new_conflicts:
    st.toast(
        f"⚠️ **{e['cell'].upper()}** — {e['operator_name']} (Badge #{e['badge_id']}) in active robot zone",
        icon="🚨",
    )
    st.session_state.last_notified_id = max(st.session_state.last_notified_id, e["id"])

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
    src = state.get("trigger_source") or "—"
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
