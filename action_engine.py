import sqlite3
from db_adapter import patch_sqlite_for_database_url
patch_sqlite_for_database_url(sqlite3)
import base64
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import parseaddr

from googleapiclient.discovery import build

DB = "profit_radar.db"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

def get_gmail_service(user_id=1, company_id=1):
    from gmail_oauth_web import get_gmail_service_web
    return get_gmail_service_web(user_id=user_id, company_id=company_id)

def init_action_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
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
    conn.commit()
    conn.close()

def get_lead(lead_id, user_id=1, company_id=1):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM profit_leads WHERE id=? AND user_id=? AND company_id=?",
        (lead_id, user_id, company_id)
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_original_email_meta(gmail_id, user_id=1, company_id=1):
    service = get_gmail_service(user_id=user_id, company_id=company_id)
    msg = service.users().messages().get(
        userId="me",
        id=gmail_id,
        format="metadata",
        metadataHeaders=["From", "To", "Subject", "Message-ID", "References"]
    ).execute()

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

    from_name, from_email = parseaddr(headers.get("From", ""))
    return {
        "thread_id": msg.get("threadId"),
        "from_email": from_email,
        "subject": headers.get("Subject", ""),
        "message_id": headers.get("Message-ID", ""),
        "references": headers.get("References", ""),
    }

def generate_reply_body(lead):
    customer = lead.get("customer") or "ご担当者様"
    category = lead.get("category") or "案件"
    subject = lead.get("subject") or ""
    estimated_profit = lead.get("estimated_profit") or 0

    if category == "請求・入金":
        return f"""{customer}

お世話になっております。

下記の件について、念のため確認のご連絡です。

件名：{subject}

請求・入金関連の確認が必要な可能性があるため、
現在の状況をご確認いただけますでしょうか。

行き違いでしたら申し訳ございません。
何卒よろしくお願いいたします。
"""

    if category == "提案・見積":
        return f"""{customer}

お世話になっております。

以前ご相談いただいた下記の件について、
その後のご状況を確認したくご連絡いたしました。

件名：{subject}

必要であれば、改めて条件整理・お見積り・提案内容の調整が可能です。

ご検討状況だけでもご返信いただけますと幸いです。
よろしくお願いいたします。
"""

    if category == "採用・人材":
        return f"""{customer}

お世話になっております。

下記の人材・採用関連の件について、
現在も募集・稼働・面談調整の必要があるか確認させてください。

件名：{subject}

必要であれば、候補者確認や条件整理を進めます。

よろしくお願いいたします。
"""

    return f"""{customer}

お世話になっております。

下記の件について、状況確認のためご連絡いたしました。

件名：{subject}

現在も対応が必要であれば、こちらで次の対応を進めます。

ご確認よろしくお願いいたします。
"""

def ensure_action_columns():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("PRAGMA table_info(profit_actions)")
    cols = [r[1] for r in c.fetchall()]

    additions = {
        "safety_ok": "INTEGER DEFAULT 0",
        "safety_errors": "TEXT",
        "safety_warnings": "TEXT",
        "gmail_result_id": "TEXT",
    }

    for col, col_type in additions.items():
        if col not in cols:
            c.execute(f"ALTER TABLE profit_actions ADD COLUMN {col} {col_type}")

    conn.commit()
    conn.close()

def save_action(
    lead_id,
    gmail_id,
    action_type,
    to_email,
    subject,
    body,
    status,
    safety_ok=0,
    safety_errors="",
    safety_warnings="",
    gmail_result_id="",
    user_id=1,
    company_id=1
):
    ensure_action_columns()

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
    INSERT INTO profit_actions
    (lead_id, gmail_id, action_type, to_email, subject, body, status, sent_at, created_at,
     safety_ok, safety_errors, safety_warnings, gmail_result_id, user_id, company_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        lead_id,
        gmail_id,
        action_type,
        to_email,
        subject,
        body,
        status,
        datetime.now().isoformat() if status == "sent" else None,
        datetime.now().isoformat(),
        int(safety_ok or 0),
        safety_errors,
        safety_warnings,
        gmail_result_id,
        user_id,
        company_id
    ))
    conn.commit()
    conn.close()

def send_gmail_reply(
    gmail_id,
    to_email,
    subject,
    body,
    lead_id=None,
    action_type="reply",
    force_send=False,
    user_id=1,
    company_id=1
):
    from safety_engine import check_message_safety, check_duplicate_send

    safety = check_message_safety(to_email, subject, body)
    if not safety["ok"]:
        raise ValueError("送信前チェックNG: " + " / ".join(safety["errors"]))

    if lead_id is not None and not force_send:
        duplicate = check_duplicate_send(lead_id, action_type=action_type, days=3)
        if not duplicate["ok"]:
            raise ValueError(duplicate["message"])

    service = get_gmail_service(user_id=user_id, company_id=company_id)
    meta = get_original_email_meta(gmail_id, user_id=user_id, company_id=company_id)

    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to_email
    msg["Subject"] = "Re: " + subject.replace("Re:", "").strip()

    if meta.get("message_id"):
        msg["In-Reply-To"] = meta["message_id"]
        msg["References"] = (meta.get("references", "") + " " + meta["message_id"]).strip()

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    payload = {
        "raw": raw,
        "threadId": meta.get("thread_id")
    }

    return service.users().messages().send(userId="me", body=payload).execute()
