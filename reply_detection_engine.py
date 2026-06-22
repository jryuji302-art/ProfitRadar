import sqlite3
from db_adapter import patch_sqlite_for_database_url
patch_sqlite_for_database_url(sqlite3)
from datetime import datetime
from email.utils import parseaddr

from action_engine import get_gmail_service

DB = "profit_radar.db"

def init_reply_detection_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS reply_detection_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER,
        action_id INTEGER,
        gmail_id TEXT,
        thread_id TEXT,
        from_email TEXT,
        subject TEXT,
        detected_at TEXT
    )
    """)
    conn.commit()
    conn.close()

def save_reply_detection_log(lead_id, action_id, gmail_id, thread_id, from_email, subject, user_id=1, company_id=1):
    init_reply_detection_db()
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    SELECT id FROM reply_detection_logs
    WHERE action_id=? AND from_email=? AND thread_id=? AND user_id=? AND company_id=?
    """, (action_id, from_email, thread_id, user_id, company_id))

    if c.fetchone():
        conn.close()
        return False

    c.execute("""
    INSERT INTO reply_detection_logs
    (lead_id, action_id, gmail_id, thread_id, from_email, subject, detected_at, user_id, company_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        lead_id,
        action_id,
        gmail_id,
        thread_id,
        from_email,
        subject,
        datetime.now().isoformat(),
        user_id,
        company_id
    ))

    conn.commit()
    conn.close()
    return True

def _headers_to_dict(message):
    headers = message.get("payload", {}).get("headers", [])
    return {h.get("name", ""): h.get("value", "") for h in headers}

def _get_my_email(service):
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "").lower()

def detect_replies(user_id=1, company_id=1):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT id, lead_id, gmail_id, to_email, subject, sent_at
    FROM profit_actions
    WHERE status='sent'
      AND gmail_id IS NOT NULL
      AND sent_at IS NOT NULL
      AND user_id=?
      AND company_id=?
    ORDER BY sent_at DESC
    LIMIT 100
    """, (user_id, company_id))

    actions = [dict(r) for r in c.fetchall()]
    service = get_gmail_service(user_id=user_id, company_id=company_id)
    my_email = _get_my_email(service)

    detected = 0
    now = datetime.now().isoformat()

    for a in actions:
        try:
            original = service.users().messages().get(
                userId="me",
                id=a["gmail_id"],
                format="metadata",
                metadataHeaders=["From", "To", "Date", "Subject"]
            ).execute()

            thread_id = original.get("threadId")
            if not thread_id:
                continue

            thread = service.users().threads().get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=["From", "To", "Date", "Subject"]
            ).execute()

            messages = thread.get("messages", [])
            if len(messages) <= 1:
                continue

            has_customer_reply = False
            customer_reply_email = ""

            for msg in messages:
                headers = _headers_to_dict(msg)
                from_raw = headers.get("From", "")
                _, from_email = parseaddr(from_raw)
                from_email = from_email.lower()

                # 自分の送信メールは除外
                if from_email == my_email:
                    continue

                # 相手側メールなら返信あり扱い
                if from_email and from_email != my_email:
                    has_customer_reply = True
                    customer_reply_email = from_email
                    break

            if not has_customer_reply:
                continue

            saved = save_reply_detection_log(
                lead_id=a["lead_id"],
                action_id=a["id"],
                gmail_id=a["gmail_id"],
                thread_id=thread_id,
                from_email=customer_reply_email,
                subject=a.get("subject") or "",
                user_id=user_id,
                company_id=company_id
            )

            if not saved:
                continue

            c.execute("""
            UPDATE profit_followups
            SET status='reply_detected'
            WHERE lead_id=? AND status='pending'
            """, (a["lead_id"],))

            # 返信が来た案件はPipelineを交渉へ進める
            c.execute("""
            SELECT COALESCE(pipeline_stage, '新規')
            FROM profit_leads
            WHERE id=? AND user_id=? AND company_id=?
            """, (a["lead_id"], user_id, company_id))
            stage_row = c.fetchone()
            from_stage = stage_row[0] if stage_row else "新規"

            c.execute("""
            UPDATE profit_leads
            SET pipeline_stage='交渉'
            WHERE id=? AND user_id=? AND company_id=?
              AND COALESCE(pipeline_stage, '新規') NOT IN ('請求', '回収', '入金', '失注')
            """, (a["lead_id"], user_id, company_id))

            if from_stage not in ('請求', '回収', '入金', '失注') and from_stage != '交渉':
                try:
                    from recovery_crm import add_pipeline_history
                    add_pipeline_history(
                        a["lead_id"],
                        from_stage,
                        "交渉",
                        reason="reply_detected"
                    )
                except Exception:
                    pass

            try:
                from learning_engine import record_learning_event
                record_learning_event(
                    lead_id=a["lead_id"],
                    action_id=a["id"],
                    event_type="Gmail返信検知",
                    result="返信あり",
                    profit_amount=0,
                    note=f"相手返信を検知: {now}"
                )
            except Exception:
                pass

            detected += 1

        except Exception:
            continue

    conn.commit()
    conn.close()
    return detected
