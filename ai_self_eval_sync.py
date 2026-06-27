import sqlite3
from datetime import datetime

DB = "profit_radar.db"


def sync_followups_to_self_eval():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS ai_self_evaluation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER,
        customer TEXT,
        subject TEXT,
        ai_type TEXT,
        generated_text TEXT,
        result_status TEXT,
        actual_revenue INTEGER DEFAULT 0,
        evaluation_note TEXT,
        created_at TEXT
    )
    """)

    c.execute("""
    INSERT INTO ai_self_evaluation
    (lead_id, customer, subject, ai_type, generated_text, result_status, actual_revenue, evaluation_note, created_at)
    SELECT
        NULL,
        f.customer,
        f.subject,
        'followup',
        f.generated_text,
        '未評価',
        0,
        'ai_followup_logsから同期',
        ?
    FROM ai_followup_logs f
    WHERE NOT EXISTS (
        SELECT 1
        FROM ai_self_evaluation e
        WHERE e.ai_type='followup'
          AND e.customer=f.customer
          AND e.subject=f.subject
          AND e.generated_text=f.generated_text
    )
    """, (datetime.now().isoformat(),))

    inserted = c.rowcount
    conn.commit()
    conn.close()
    return inserted


if __name__ == "__main__":
    n = sync_followups_to_self_eval()
    print(f"同期完了: {n}件")
