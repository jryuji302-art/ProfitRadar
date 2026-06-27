import sqlite3
from db_adapter import patch_sqlite_for_database_url

patch_sqlite_for_database_url(sqlite3)


def connect(db_path):
    return sqlite3.connect(db_path)


def init_db(db_path):
    conn = connect(db_path)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS profit_leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gmail_id TEXT,
        customer TEXT,
        subject TEXT,
        content TEXT,
        category TEXT,
        status TEXT DEFAULT '未対応',
        estimated_profit INTEGER DEFAULT 0,
        recoverable_profit INTEGER DEFAULT 0,
        actual_revenue INTEGER DEFAULT 0,
        risk_level TEXT,
        neglected_days INTEGER DEFAULT 0,
        opportunity_score INTEGER DEFAULT 0,
        revenue_score INTEGER DEFAULT 0,
        next_action TEXT,
        reason TEXT,
        memo TEXT,
        email_date TEXT,
        created_at TEXT,
        user_id INTEGER DEFAULT 1,
        company_id INTEGER DEFAULT 1
    )
    """)

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
        safety_ok INTEGER DEFAULT 0,
        safety_errors TEXT,
        safety_warnings TEXT,
        gmail_result_id TEXT,
        user_id INTEGER DEFAULT 1,
        company_id INTEGER DEFAULT 1
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS ai_self_evaluation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER,
        customer TEXT,
        subject TEXT,
        ai_decision TEXT,
        generated_text TEXT,
        result TEXT,
        actual_revenue INTEGER DEFAULT 0,
        note TEXT,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()


def add_missing_columns(db_path, table, required):
    conn = connect(db_path)
    c = conn.cursor()

    c.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in c.fetchall()}

    for col, col_type in required.items():
        if col not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")

    conn.commit()
    conn.close()


def repair_profit_leads_schema(db_path):
    required = {
        "gmail_id": "TEXT",
        "reason": "TEXT",
        "email_date": "TEXT",
        "memo": "TEXT",
        "hot_lead": "INTEGER DEFAULT 0",
        "recoverable_profit": "INTEGER DEFAULT 0",
        "pipeline_stage": "TEXT",
        "actual_profit": "INTEGER DEFAULT 0",
        "sales_temperature": "TEXT",
        "user_id": "INTEGER DEFAULT 1",
        "company_id": "INTEGER DEFAULT 1",
        "actual_revenue": "INTEGER DEFAULT 0",
        "profit_basis": "TEXT",
        "profit_confidence": "INTEGER DEFAULT 0",
        "unit_price_detected": "INTEGER DEFAULT 0",
        "people_detected": "REAL DEFAULT 1",
        "days_detected": "REAL DEFAULT 1",
    }
    add_missing_columns(db_path, "profit_leads", required)


def ensure_columns(db_path):
    required = {
        "gmail_id": "TEXT",
        "reason": "TEXT",
        "email_date": "TEXT",
        "memo": "TEXT",
    }
    add_missing_columns(db_path, "profit_leads", required)


def ensure_reply_detection_columns(db_path):
    required = {
        "reply_body": "TEXT",
        "reply_date": "TEXT",
        "user_id": "INTEGER DEFAULT 1",
        "company_id": "INTEGER DEFAULT 1",
    }
    add_missing_columns(db_path, "reply_detection_logs", required)


def repair_profit_actions_schema(db_path):
    required = {
        "gmail_id": "TEXT",
        "to_email": "TEXT",
        "subject": "TEXT",
        "body": "TEXT",
        "status": "TEXT",
        "sent_at": "TEXT",
        "safety_ok": "INTEGER DEFAULT 0",
        "safety_errors": "TEXT",
        "safety_warnings": "TEXT",
        "gmail_result_id": "TEXT",
        "user_id": "INTEGER DEFAULT 1",
        "company_id": "INTEGER DEFAULT 1",
    }
    add_missing_columns(db_path, "profit_actions", required)
