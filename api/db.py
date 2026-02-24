import sqlite3, os
from pathlib import Path

_ROOT = Path(__file__).parent.parent
DB_PATH = os.getenv("DB_PATH", str(_ROOT / "data" / "hrca.db"))


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
