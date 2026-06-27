import sqlite3
from datetime import datetime, timedelta

DB = "profit_radar.db"

def init_followup_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

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

    conn.commit()
    conn.close()

def generate_followup_message(customer, subject, level):
    if level == "7days":
        return f"""{customer}

お世話になっております。

先日ご連絡した下記の件について、
念のため再度確認のご連絡です。

件名：{subject}

現在のご状況だけでもご共有いただけますと幸いです。
よろしくお願いいたします。
"""

    return f"""{customer}

お世話になっております。

下記の件について、再度確認のためご連絡いたしました。

件名：{subject}

もし現在対応不要であれば、その旨だけでも問題ございません。
必要であればこちらで次の対応を進めます。

よろしくお願いいたします。
"""

def detect_followup_candidates():
    init_followup_db()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT
        a.id as action_id,
        a.lead_id,
        a.gmail_id,
        a.to_email,
        a.subject,
        a.sent_at,
        l.customer,
        l.status
    FROM profit_actions a
    LEFT JOIN profit_leads l ON a.lead_id = l.id
    WHERE a.status = 'sent'
      AND a.sent_at IS NOT NULL
    """)

    rows = c.fetchall()
    created = 0
    now = datetime.now()

    for r in rows:
        try:
            sent_at = datetime.fromisoformat(r["sent_at"])
        except Exception:
            continue

        days = (now - sent_at).days

        if days >= 14:
            level = "14days"
        elif days >= 7:
            level = "7days"
        else:
            continue

        c.execute("""
        SELECT id FROM profit_followups
        WHERE action_id=? AND followup_level=?
        """, (r["action_id"], level))

        exists = c.fetchone()
        if exists:
            continue

        customer = r["customer"] or "ご担当者様"
        subject = r["subject"] or ""

        msg = generate_followup_message(customer, subject, level)

        c.execute("""
        INSERT INTO profit_followups
        (lead_id, action_id, gmail_id, customer, subject, followup_level, reason, recommended_message, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["lead_id"],
            r["action_id"],
            r["gmail_id"],
            customer,
            subject,
            level,
            f"送信後{days}日間、返信確認が必要",
            msg,
            "pending",
            now.isoformat()
        ))

        created += 1

    conn.commit()
    conn.close()
    return created

def get_followups():
    init_followup_db()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT *
    FROM profit_followups
    ORDER BY created_at DESC
    """)

    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def mark_followup_sent(followup_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
    UPDATE profit_followups
    SET status='sent'
    WHERE id=?
    """, (followup_id,))
    conn.commit()
    conn.close()
