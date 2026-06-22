import os
import json
import sqlite3
from db_adapter import patch_sqlite_for_database_url
patch_sqlite_for_database_url(sqlite3)
from datetime import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

DB = "profit_radar.db"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
]

def init_gmail_connections_table():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS gmail_connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER DEFAULT 1,
        company_id INTEGER DEFAULT 1,
        google_email TEXT,
        token_json TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    conn.commit()
    conn.close()

def get_oauth_config():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")

    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError(
            "Google OAuth環境変数が不足しています: "
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI"
        )

    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }, redirect_uri

def create_flow():
    config, redirect_uri = get_oauth_config()
    return Flow.from_client_config(
        config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )

def get_authorization_url(user_id=1, company_id=1):
    flow = create_flow()
    state = f"user:{int(user_id)}|company:{int(company_id)}"
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return authorization_url, state


def parse_oauth_state(state):
    try:
        text = str(state or "")
        user_id = 1
        company_id = 1

        for part in text.split("|"):
            if part.startswith("user:"):
                user_id = int(part.replace("user:", "").strip())
            elif part.startswith("company:"):
                company_id = int(part.replace("company:", "").strip())

        return user_id, company_id
    except Exception:
        return 1, 1

def save_credentials(creds, user_id=1, company_id=1):
    init_gmail_connections_table()

    token_json = creds.to_json()
    now = datetime.now().isoformat(timespec="seconds")

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    SELECT id FROM gmail_connections
    WHERE user_id = ? AND company_id = ?
    ORDER BY id DESC
    LIMIT 1
    """, (user_id, company_id))

    row = c.fetchone()

    if row:
        c.execute("""
        UPDATE gmail_connections
        SET token_json = ?, updated_at = ?
        WHERE id = ?
        """, (token_json, now, row[0]))
    else:
        c.execute("""
        INSERT INTO gmail_connections
        (user_id, company_id, google_email, token_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, company_id, "", token_json, now, now))

    conn.commit()
    conn.close()

def exchange_code_for_token(code, user_id=1, company_id=1):
    flow = create_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    save_credentials(creds, user_id=user_id, company_id=company_id)
    return creds

def load_credentials(user_id=1, company_id=1):
    init_gmail_connections_table()

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
    SELECT token_json FROM gmail_connections
    WHERE user_id = ? AND company_id = ?
    ORDER BY id DESC
    LIMIT 1
    """, (user_id, company_id))
    row = c.fetchone()
    conn.close()

    if not row or not row[0]:
        return None

    data = json.loads(row[0])
    return Credentials.from_authorized_user_info(data, SCOPES)

def get_gmail_service_web(user_id=1, company_id=1):
    creds = load_credentials(user_id=user_id, company_id=company_id)

    if not creds:
        raise RuntimeError("Gmail未接続です。設定画面からGoogle接続してください。")

    if not creds.valid and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        save_credentials(creds, user_id=user_id, company_id=company_id)

    if not creds.valid:
        raise RuntimeError("Gmail認証が無効です。再接続してください。")

    return build("gmail", "v1", credentials=creds)
