import sqlite3
from datetime import datetime
from email.utils import parseaddr

from action_engine import get_gmail_service, get_original_email_meta

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


def get_sent_gmail_replies(limit=30):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT id, lead_id, gmail_id, to_email, subject, sent_at, gmail_result_id
        FROM profit_actions
        WHERE action_type='gmail_reply'
          AND status='sent'
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def already_detected(action_id, gmail_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT id
        FROM reply_detection_logs
        WHERE action_id=? AND gmail_id=?
        LIMIT 1
    """, (action_id, gmail_id))
    row = c.fetchone()
    conn.close()
    return row is not None


def save_detection(lead_id, action_id, gmail_id, thread_id, from_email, subject):
    init_reply_detection_db()
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO reply_detection_logs
        (lead_id, action_id, gmail_id, thread_id, from_email, subject, detected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        lead_id,
        action_id,
        gmail_id,
        thread_id,
        from_email,
        subject,
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


def update_lead_after_reply(lead_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        UPDATE profit_leads
        SET status='返信あり',
            pipeline_stage='返信あり'
        WHERE id=?
    """, (lead_id,))
    conn.commit()
    conn.close()


def save_action_log(lead_id, message):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO profit_actions
        (lead_id, action_type, message, result, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        lead_id,
        "reply_detected",
        message,
        "done",
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


def detect_replies(limit=30):
    """
    送信済みgmail_replyのthreadを確認し、
    自分以外からの新しい返信を検知する。
    """
    init_reply_detection_db()
    service = get_gmail_service()
    sent_actions = get_sent_gmail_replies(limit=limit)

    detected = []

    for action in sent_actions:
        action_id = int(action.get("id"))
        lead_id = int(action.get("lead_id"))
        original_gmail_id = action.get("gmail_id", "")
        sent_gmail_id = action.get("gmail_result_id", "")
        to_email = str(action.get("to_email", "") or "").lower().strip()

        if not original_gmail_id:
            continue

        try:
            meta = get_original_email_meta(original_gmail_id)
            thread_id = meta.get("thread_id")
            if not thread_id:
                continue

            thread = service.users().threads().get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()

            messages = thread.get("messages", [])

            for msg in messages:
                msg_id = msg.get("id")

                if msg_id in [original_gmail_id, sent_gmail_id]:
                    continue

                headers = {
                    h["name"]: h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }

                _, from_email = parseaddr(headers.get("From", ""))
                from_email = from_email.lower().strip()
                subject = headers.get("Subject", "")

                if not from_email:
                    continue

                if from_email != to_email:
                    continue

                if already_detected(action_id, msg_id):
                    continue

                save_detection(
                    lead_id=lead_id,
                    action_id=action_id,
                    gmail_id=msg_id,
                    thread_id=thread_id,
                    from_email=from_email,
                    subject=subject
                )

                update_lead_after_reply(lead_id)
                save_action_log(
                    lead_id,
                    f"返信検知: {from_email} / {subject}"
                )

                detected.append({
                    "lead_id": lead_id,
                    "action_id": action_id,
                    "gmail_id": msg_id,
                    "from_email": from_email,
                    "subject": subject,
                })

        except Exception as e:
            detected.append({
                "lead_id": lead_id,
                "action_id": action_id,
                "error": str(e),
            })

    return detected


if __name__ == "__main__":
    results = detect_replies()
    if not results:
        print("返信検知なし")
    else:
        for r in results:
            print(r)
