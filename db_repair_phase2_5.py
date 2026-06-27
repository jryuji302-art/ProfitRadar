import sqlite3

DB = "profit_radar.db"

conn = sqlite3.connect(DB)
c = conn.cursor()

# profit_actions 修復
c.execute("""
CREATE TABLE IF NOT EXISTS profit_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    gmail_id TEXT,
    action_type TEXT,
    to_email TEXT,
    subject TEXT,
    body TEXT,
    status TEXT,
    sent_at TEXT,
    created_at TEXT,
    safety_ok INTEGER DEFAULT 0,
    safety_errors TEXT,
    safety_warnings TEXT,
    gmail_result_id TEXT
)
""")

c.execute("PRAGMA table_info(profit_actions)")
cols = [r[1] for r in c.fetchall()]

required_cols = {
    "gmail_id": "TEXT",
    "action_type": "TEXT",
    "to_email": "TEXT",
    "subject": "TEXT",
    "body": "TEXT",
    "status": "TEXT",
    "sent_at": "TEXT",
    "created_at": "TEXT",
    "safety_ok": "INTEGER DEFAULT 0",
    "safety_errors": "TEXT",
    "safety_warnings": "TEXT",
    "gmail_result_id": "TEXT",
}

for col, col_type in required_cols.items():
    if col not in cols:
        c.execute(f"ALTER TABLE profit_actions ADD COLUMN {col} {col_type}")
        print("追加:", col)

# profit_followups 作成
c.execute("""
CREATE TABLE IF NOT EXISTS profit_followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    action_id INTEGER,
    gmail_id TEXT,
    customer TEXT,
    subject TEXT,
    followup_level TEXT,
    reason TEXT,
    recommended_message TEXT,
    status TEXT,
    created_at TEXT
)
""")

# learning
c.execute("""
CREATE TABLE IF NOT EXISTS learning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    action_id INTEGER,
    event_type TEXT,
    result TEXT,
    profit_amount INTEGER,
    note TEXT,
    created_at TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS learning_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_name TEXT,
    category TEXT,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    total_profit INTEGER DEFAULT 0,
    note TEXT,
    updated_at TEXT
)
""")

# recovery
c.execute("""
CREATE TABLE IF NOT EXISTS recovery_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    note TEXT,
    created_at TEXT
)
""")

conn.commit()
conn.close()

print("DB修復完了")
