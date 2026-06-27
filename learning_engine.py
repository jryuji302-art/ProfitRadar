import sqlite3
from datetime import datetime

DB = "profit_radar.db"

def init_learning_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

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

    conn.commit()
    conn.close()

def record_learning_event(lead_id, action_id, event_type, result, profit_amount=0, note=""):
    init_learning_db()

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    INSERT INTO learning_events
    (lead_id, action_id, event_type, result, profit_amount, note, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        lead_id,
        action_id,
        event_type,
        result,
        int(profit_amount or 0),
        note,
        datetime.now().isoformat()
    ))

    c.execute("""
    SELECT category
    FROM profit_leads
    WHERE id=?
    """, (lead_id,))
    row = c.fetchone()
    category = row[0] if row else "不明"

    pattern_name = f"{category}:{event_type}"

    c.execute("""
    SELECT id, success_count, failure_count, total_profit
    FROM learning_patterns
    WHERE pattern_name=?
    """, (pattern_name,))
    p = c.fetchone()

    is_success = result in ["回収成功", "成約", "返信あり", "入金確認"]
    is_failure = result in ["失注", "返信なし", "不要", "解約"]

    if p:
        pid, success_count, failure_count, total_profit = p

        if is_success:
            success_count += 1
            total_profit += int(profit_amount or 0)
        elif is_failure:
            failure_count += 1

        c.execute("""
        UPDATE learning_patterns
        SET success_count=?, failure_count=?, total_profit=?, updated_at=?
        WHERE id=?
        """, (
            success_count,
            failure_count,
            total_profit,
            datetime.now().isoformat(),
            pid
        ))
    else:
        c.execute("""
        INSERT INTO learning_patterns
        (pattern_name, category, success_count, failure_count, total_profit, note, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            pattern_name,
            category,
            1 if is_success else 0,
            1 if is_failure else 0,
            int(profit_amount or 0) if is_success else 0,
            "",
            datetime.now().isoformat()
        ))

    conn.commit()
    conn.close()

def get_learning_events():
    init_learning_db()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT *
    FROM learning_events
    ORDER BY created_at DESC
    LIMIT 100
    """)

    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_learning_patterns():
    init_learning_db()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT *,
        CASE
            WHEN success_count + failure_count = 0 THEN 0
            ELSE ROUND(success_count * 100.0 / (success_count + failure_count), 1)
        END AS success_rate
    FROM learning_patterns
    ORDER BY total_profit DESC, success_rate DESC
    """)

    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
