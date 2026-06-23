import sqlite3
import base64
from db_adapter import patch_sqlite_for_database_url
patch_sqlite_for_database_url(sqlite3)
from datetime import datetime
from email.utils import parseaddr

from action_engine import get_gmail_service, get_original_email_meta

DB = "profit_radar.db"

def extract_gmail_body(payload):
    """
    Gmail payload から本文を取り出す。
    text/plain 優先。なければ text/html を簡易取得。
    """
    if not payload:
        return ""

    def decode_body(data):
        if not data:
            return ""
        try:
            data = data.replace("-", "+").replace("_", "/")
            missing = len(data) % 4
            if missing:
                data += "=" * (4 - missing)
            return base64.b64decode(data).decode("utf-8", errors="ignore")
        except Exception:
            return ""

    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if mime_type == "text/plain" and body_data:
        return decode_body(body_data)

    if mime_type == "text/html" and body_data:
        return decode_body(body_data)

    parts = payload.get("parts", []) or []

    # text/plain優先
    for part in parts:
        if part.get("mimeType") == "text/plain":
            body = decode_body(part.get("body", {}).get("data"))
            if body:
                return body

    # ネスト対応
    for part in parts:
        nested = extract_gmail_body(part)
        if nested:
            return nested

    # 最後にhtml
    for part in parts:
        if part.get("mimeType") == "text/html":
            body = decode_body(part.get("body", {}).get("data"))
            if body:
                return body

    return ""




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

    # 既存DB拡張
    for col_sql in [
        "ALTER TABLE reply_detection_logs ADD COLUMN reply_body TEXT",
        "ALTER TABLE reply_detection_logs ADD COLUMN reply_date TEXT"
    ]:
        try:
            c.execute(col_sql)
        except Exception:
            pass

    conn.commit()
    conn.close()


def get_sent_gmail_replies(limit=30, user_id=1, company_id=1):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT id, lead_id, gmail_id, to_email, subject, sent_at, gmail_result_id
        FROM profit_actions
        WHERE action_type='gmail_reply'
          AND status='sent'
          AND user_id=?
          AND company_id=?
        ORDER BY id DESC
        LIMIT ?
    """, (user_id, company_id, limit))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def already_detected(action_id, gmail_id, user_id=1, company_id=1):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT id
        FROM reply_detection_logs
        WHERE action_id=? AND gmail_id=? AND user_id=? AND company_id=?
        LIMIT 1
    """, (action_id, gmail_id, user_id, company_id))
    row = c.fetchone()
    conn.close()
    return row is not None


def save_detection(lead_id, action_id, gmail_id, thread_id, from_email, subject, reply_body='', reply_date='', user_id=1, company_id=1):
    init_reply_detection_db()
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # 二重保存防止
    c.execute("""
        SELECT id
        FROM reply_detection_logs
        WHERE gmail_id=? AND user_id=? AND company_id=?
        LIMIT 1
    """, (gmail_id, user_id, company_id))
    if c.fetchone():
        conn.close()
        return False

    c.execute("""
        INSERT INTO reply_detection_logs
        (lead_id, action_id, gmail_id, thread_id, from_email, subject, detected_at, user_id, company_id, reply_body, reply_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        lead_id,
        action_id,
        gmail_id,
        thread_id,
        from_email,
        subject,
        datetime.now().isoformat(),
        user_id,
        company_id,
        reply_body,
        reply_date
    ))
    conn.commit()
    conn.close()


def update_lead_after_reply(lead_id, user_id=1, company_id=1):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        UPDATE profit_leads
        SET status='返信あり',
            pipeline_stage='返信あり'
        WHERE id=? AND user_id=? AND company_id=?
    """, (lead_id, user_id, company_id))
    conn.commit()
    conn.close()


def save_action_log(lead_id, message, user_id=1, company_id=1):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO profit_actions
        (lead_id, action_type, message, result, created_at, user_id, company_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        lead_id,
        "reply_detected",
        message,
        "done",
        datetime.now().isoformat(),
        user_id,
        company_id
    ))
    conn.commit()
    conn.close()


def detect_replies(limit=30, user_id=1, company_id=1):
    """
    送信済みgmail_replyのthreadを確認し、
    自分以外からの新しい返信を検知する。
    """
    init_reply_detection_db()
    service = get_gmail_service(user_id=user_id, company_id=company_id)
    sent_actions = get_sent_gmail_replies(limit=limit, user_id=user_id, company_id=company_id)

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
            meta = get_original_email_meta(original_gmail_id, user_id=user_id, company_id=company_id)
            thread_id = meta.get("thread_id")
            if not thread_id:
                continue

            thread = service.users().threads().get(
                userId="me",
                id=thread_id,
                format="full",
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
                reply_date = headers.get("Date", "")
                reply_body = extract_gmail_body(msg.get("payload", {})).strip()

                if not from_email:
                    continue

                if from_email != to_email:
                    continue

                if already_detected(action_id, msg_id, user_id=user_id, company_id=company_id):
                    continue

                saved = save_detection(
                    lead_id=lead_id,
                    action_id=action_id,
                    gmail_id=msg_id,
                    thread_id=thread_id,
                    from_email=from_email,
                    subject=subject,
                    reply_body=reply_body,
                    reply_date=reply_date,
                    user_id=user_id,
                    company_id=company_id
                )

                if not saved:
                    continue

                update_lead_after_reply(lead_id, user_id=user_id, company_id=company_id)
                save_action_log(
                    lead_id,
                    f"返信検知: {from_email} / {subject}",
                    user_id=user_id,
                    company_id=company_id
                )

                detected.append({
                    "lead_id": lead_id,
                    "action_id": action_id,
                    "gmail_id": msg_id,
                    "from_email": from_email,
                    "subject": subject,
                    "reply_body": reply_body[:300],
                    "reply_date": reply_date,
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
