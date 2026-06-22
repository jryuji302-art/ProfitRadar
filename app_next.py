import html
import re
import sqlite3
import hashlib
from datetime import datetime
from email.utils import parsedate_to_datetime

import pandas as pd
import altair as alt
from revenue_engine import analyze_email, generate_follow_message as generate_revenue_follow_message
import streamlit as st

from gmail_reader import fetch_recent_emails
from lead_service import save_email_as_lead
from action_engine import send_gmail_reply, save_action
from ai_advisor_engine import build_ai_advice, format_ai_advice, build_ai_dashboard_advice, format_ai_dashboard_advice
from openai_advisor_engine import build_openai_advice
from openai_followup_engine import generate_followup as generate_openai_followup

DB = "profit_radar.db"


# =========================
# DB
# =========================














def save_ai_learning(lead_id, customer, subject, ai_decision, result, actual_revenue, note=""):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_learning (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            customer TEXT,
            subject TEXT,
            ai_decision TEXT,
            result TEXT,
            actual_revenue INTEGER DEFAULT 0,
            note TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        INSERT INTO ai_learning
        (lead_id, customer, subject, ai_decision, result, actual_revenue, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
    """, (
        int(lead_id),
        str(customer or ""),
        str(subject or ""),
        str(ai_decision or ""),
        str(result or ""),
        int(actual_revenue or 0),
        str(note or "")
    ))
    conn.commit()
    conn.close()

def get_revenue_chart_data():
    try:
        conn = sqlite3.connect(DB)
        df = pd.read_sql_query("""
            SELECT
                customer,
                category,
                pipeline_stage,
                estimated_profit,
                recoverable_profit,
                actual_revenue,
                created_at
            FROM profit_leads
        """, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

def get_customer_revenue_summary(customer):
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT
                COUNT(*) AS lead_count,
                COALESCE(SUM(estimated_profit), 0) AS total_estimated_profit,
                COALESCE(SUM(recoverable_profit), 0) AS total_recoverable_profit,
                COALESCE(SUM(actual_revenue), 0) AS total_actual_revenue,
                COALESCE(MAX(opportunity_score), 0) AS max_score,
                COALESCE(MAX(neglected_days), 0) AS max_neglected_days
            FROM profit_leads
            WHERE customer = ?
        """, (customer,))

        row = dict(c.fetchone())
        conn.close()
        return row
    except Exception:
        return {
            "lead_count": 0,
            "total_estimated_profit": 0,
            "total_recoverable_profit": 0,
            "total_actual_revenue": 0,
            "max_score": 0,
            "max_neglected_days": 0,
        }

def update_actual_revenue(lead_id, actual_revenue, user_id=None, company_id=None):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    if user_id is None or company_id is None:
        conn.close()
        raise ValueError("user_id / company_id がないため実回収利益の更新を停止しました。")

    c.execute("""
        UPDATE profit_leads
        SET actual_revenue=?
        WHERE id=? AND user_id=? AND company_id=?
    """, (int(actual_revenue or 0), int(lead_id), int(user_id), int(company_id)))

    if int(actual_revenue or 0) > 0:
        c.execute("""
            UPDATE profit_leads
            SET status='成約'
            WHERE id=? AND user_id=? AND company_id=?
        """, (int(lead_id), int(user_id), int(company_id)))

    conn.commit()
    conn.close()

def build_reply_subject(subject):
    subject = str(subject or "").strip()
    if not subject:
        return "Re:"
    if subject.lower().startswith("re:") or subject.startswith("Re:"):
        return subject
    return f"Re: {subject}"

def validate_send_body(body):
    """
    顧客に送ってはいけないAI内部文言が本文に混ざっていないか確認
    """
    forbidden = [
        "送る理由",
        "期待結果",
        "判断",
        "リスク",
        "推奨アクション",
        "AI分析",
        "案件参謀",
        "RUDIA",
        "ルディア",
    ]

    body_text = str(body or "")

    errors = []
    for word in forbidden:
        if word in body_text:
            errors.append(f"送信本文に内部文言「{word}」が含まれています。")

    if len(body_text.strip()) < 10:
        errors.append("送信本文が短すぎます。")

    return errors

def get_ai_advice_logs(limit=50):
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS ai_advice_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER,
                customer TEXT,
                subject TEXT,
                model TEXT,
                advice TEXT,
                created_at TEXT
            )
        """)
        conn.commit()

        c.execute("""
            SELECT id, lead_id, customer, subject, model, advice, created_at
            FROM ai_advice_logs
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS profit_leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gmail_id TEXT,
        customer TEXT,
        subject TEXT,
        content TEXT,
        estimated_profit INTEGER,
        risk_level TEXT,
        neglected_days INTEGER,
        next_action TEXT,
        status TEXT,
        created_at TEXT,
        reason TEXT,
        email_date TEXT,
        memo TEXT,
        category TEXT,
        opportunity_score INTEGER DEFAULT 0,
        hot_lead INTEGER DEFAULT 0,
        recoverable_profit INTEGER DEFAULT 0,
        pipeline_stage TEXT,
        actual_profit INTEGER DEFAULT 0,
        sales_temperature TEXT,
        user_id INTEGER DEFAULT 1,
        company_id INTEGER DEFAULT 1
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS profit_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER,
        action_type TEXT,
        message TEXT,
        result TEXT,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()


def repair_profit_leads_schema():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("PRAGMA table_info(profit_leads)")
    existing = {row[1] for row in c.fetchall()}

    required = {
        "gmail_id": "TEXT",
        "reason": "TEXT",
        "email_date": "TEXT",
        "memo": "TEXT",
        "category": "TEXT",
        "opportunity_score": "INTEGER DEFAULT 0",
        "hot_lead": "INTEGER DEFAULT 0",
        "recoverable_profit": "INTEGER DEFAULT 0",
        "pipeline_stage": "TEXT",
        "actual_profit": "INTEGER DEFAULT 0",
        "sales_temperature": "TEXT",
        "user_id": "INTEGER DEFAULT 1",
        "company_id": "INTEGER DEFAULT 1",
        "actual_revenue": "INTEGER DEFAULT 0",
    }

    for col, col_type in required.items():
        if col not in existing:
            c.execute(f"ALTER TABLE profit_leads ADD COLUMN {col} {col_type}")

    conn.commit()
    conn.close()


def ensure_columns():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("PRAGMA table_info(profit_leads)")
    cols = [r[1] for r in c.fetchall()]

    required = {
        "gmail_id": "TEXT",
        "reason": "TEXT",
        "email_date": "TEXT",
        "memo": "TEXT",
    }

    for col, typ in required.items():
        if col not in cols:
            c.execute(f"ALTER TABLE profit_leads ADD COLUMN {col} {typ}")

    conn.commit()
    conn.close()


def get_leads(user_id=None, company_id=None):
    conn = sqlite3.connect(DB)

    if user_id is not None and company_id is not None:
        df = pd.read_sql_query(
            "SELECT * FROM profit_leads WHERE user_id = ? AND company_id = ?",
            conn,
            params=(int(user_id), int(company_id))
        )
    else:
        df = pd.read_sql_query("SELECT * FROM profit_leads WHERE 1=0", conn)

    conn.close()

    if not df.empty:
        df["revenue_score"] = df.apply(calc_revenue_score, axis=1)
        sort_col = "opportunity_score" if "opportunity_score" in df.columns else "revenue_score"
        df = df.sort_values(sort_col, ascending=False)

    return df


def get_actions(user_id=None, company_id=None):
    conn = sqlite3.connect(DB)

    if user_id is not None and company_id is not None:
        df = pd.read_sql_query(
            """
            SELECT a.*
            FROM profit_actions a
            LEFT JOIN profit_leads l ON l.id = a.lead_id
            WHERE l.user_id = ? AND l.company_id = ?
            ORDER BY a.created_at DESC
            """,
            conn,
            params=(int(user_id), int(company_id))
        )
    else:
        df = pd.read_sql_query("SELECT * FROM profit_actions WHERE 1=0", conn)

    conn.close()
    return df


def reset_database(user_id=None, company_id=None):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    if user_id is not None and company_id is not None:
        c.execute("""
            DELETE FROM profit_actions
            WHERE lead_id IN (
                SELECT id FROM profit_leads WHERE user_id = ? AND company_id = ?
            )
        """, (int(user_id), int(company_id)))
        c.execute(
            "DELETE FROM profit_leads WHERE user_id = ? AND company_id = ?",
            (int(user_id), int(company_id))
        )
    else:
        raise ValueError("user_id / company_id がないためリセットを停止しました。")

    conn.commit()
    conn.close()


def update_lead_status(lead_id, status, user_id=None, company_id=None):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    if user_id is not None and company_id is not None:
        c.execute(
            "UPDATE profit_leads SET status = ? WHERE id = ? AND user_id = ? AND company_id = ?",
            (status, int(lead_id), int(user_id), int(company_id))
        )
    else:
        raise ValueError("user_id / company_id がないためステータス更新を停止しました。")

    conn.commit()
    conn.close()


def update_lead_memo(lead_id, memo, user_id=None, company_id=None):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    if user_id is not None and company_id is not None:
        c.execute(
            "UPDATE profit_leads SET memo = ? WHERE id = ? AND user_id = ? AND company_id = ?",
            (memo, int(lead_id), int(user_id), int(company_id))
        )
    else:
        raise ValueError("user_id / company_id がないためメモ更新を停止しました。")

    conn.commit()
    conn.close()


def save_action_log(lead_id, action_type, message, result, user_id=None, company_id=None):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    if user_id is not None and company_id is not None:
        c.execute(
            "SELECT id FROM profit_leads WHERE id = ? AND user_id = ? AND company_id = ?",
            (int(lead_id), int(user_id), int(company_id))
        )
        if not c.fetchone():
            conn.close()
            raise ValueError("この案件は現在のユーザー/会社に紐づいていません。")
    else:
        conn.close()
        raise ValueError("user_id / company_id がないため操作ログ保存を停止しました。")

    c.execute("""
    INSERT INTO profit_actions
    (lead_id, action_type, message, result, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (
        int(lead_id),
        action_type,
        message,
        result,
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


# =========================
# Revenue Engine
# =========================

def calc_revenue_score(row):
    profit = int(row.get("estimated_profit", 0) or 0)
    days = int(row.get("neglected_days", 0) or 0)
    risk = row.get("risk_level", "中")

    risk_point = {"低": 10, "中": 30, "高": 50}.get(risk, 30)
    profit_point = min(profit // 10000, 50)
    days_point = min(days * 2, 40)

    return int(profit_point + risk_point + days_point)


def estimate_neglected_days(email_date):
    try:
        dt = parsedate_to_datetime(email_date)
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        return max((now - dt).days, 0)
    except Exception:
        return 7


# save_email_as_lead は lead_service.py に分離済み
def clean_history_value(v):
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ["nan", "none", "nat", "<na>"]:
        return ""
    return s


def build_followup_history(lead):
    """
    AIフォローVer2用。
    案件状態・メモ・実利益・過去送信履歴をAIへ渡す。
    nan/Noneを除去して、AIに汚い履歴を渡さない。
    """
    history_parts = []

    try:
        lead_id = int(lead.get("id", 0) or 0)
    except Exception:
        lead_id = 0

    history_parts.append(f"案件ステージ: {clean_history_value(lead.get('pipeline_stage', ''))}")
    history_parts.append(f"ステータス: {clean_history_value(lead.get('status', ''))}")
    history_parts.append(f"分類: {clean_history_value(lead.get('category', ''))}")
    history_parts.append(f"推定利益: {clean_history_value(lead.get('estimated_profit', 0))}")
    history_parts.append(f"回収可能利益: {clean_history_value(lead.get('recoverable_profit', 0))}")
    history_parts.append(f"実回収利益: {clean_history_value(lead.get('actual_revenue', 0))}")
    history_parts.append(f"メモ: {clean_history_value(lead.get('memo', ''))}")

    if lead_id > 0:
        try:
            conn = sqlite3.connect(DB)
            actions = pd.read_sql_query(
                """
                SELECT created_at, action_type, subject, body, message, status, result
                FROM profit_actions
                WHERE lead_id = ?
                ORDER BY id DESC
                LIMIT 5
                """,
                conn,
                params=[lead_id]
            )
            conn.close()

            if not actions.empty:
                history_parts.append("")
                history_parts.append("過去送信・対応履歴:")

                for _, r in actions.iterrows():
                    created_at = clean_history_value(r.get("created_at", ""))
                    action_type = clean_history_value(r.get("action_type", ""))
                    status = clean_history_value(r.get("status", "")) or clean_history_value(r.get("result", ""))
                    subject = clean_history_value(r.get("subject", ""))
                    body = clean_history_value(r.get("body", "")) or clean_history_value(r.get("message", ""))
                    body = body.replace("\n", " ")[:180]

                    line = f"- {created_at}｜{action_type}"
                    if status:
                        line += f"｜{status}"
                    if subject:
                        line += f"｜{subject}"
                    if body:
                        line += f"｜{body}"

                    history_parts.append(line)

        except Exception as e:
            history_parts.append(f"履歴取得エラー: {e}")

    return "\n".join(history_parts)


def generate_follow_message(customer, subject, content, category="", history=""):
    """
    AIフォローVer2。
    本文だけでなく、外部から渡された履歴も含めて返信文を生成する。
    """
    if not category:
        try:
            from revenue_engine import classify_email
            category = classify_email(f"{subject or ''} {content or ''}")
        except Exception:
            category = ""

    return generate_openai_followup(
        customer=customer,
        subject=subject,
        content=content,
        category=category,
        history=history or ""
    )


# =========================
# UI Helpers
# =========================

def safe(v):
    return html.escape(str(v if v is not None else ""))


def money(v):
    return f"¥{int(v or 0):,}"


def inject_css():
    st.markdown("""
<style>
.block-container {
    padding-top: 2.4rem;
    padding-left: 3.6rem;
    padding-right: 3.6rem;
    max-width: 1320px;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #061B33 0%, #020814 100%);
    border-right: 1px solid rgba(255,255,255,0.08);
}

[data-testid="stSidebar"] * {
    color: #EAF2FF;
}

[data-testid="stSidebar"] label {
    color: #B8C7D9 !important;
    font-size: 13px !important;
    font-weight: 800 !important;
}

[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea,
[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: white !important;
    color: #111827 !important;
    border-radius: 12px !important;
}

[data-testid="stSidebar"] .stButton button,
[data-testid="stSidebar"] .stDownloadButton button {
    width: 100%;
    height: 42px;
    border-radius: 14px;
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.14);
    color: white;
    font-weight: 850;
}

[data-testid="stSidebar"] .stButton button:hover,
[data-testid="stSidebar"] .stDownloadButton button:hover {
    background: linear-gradient(135deg, #10B981, #0EA5E9);
    border: none;
}

.sidebar-brand {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 22px;
}

.sidebar-logo {
    width: 42px;
    height: 42px;
    border-radius: 15px;
    display: grid;
    place-items: center;
    background: linear-gradient(135deg, #10B981, #0EA5E9);
    font-size: 21px;
    font-weight: 900;
}

.sidebar-title {
    font-size: 21px;
    font-weight: 950;
    color: white;
}

.sidebar-sub {
    font-size: 12px;
    color: #8EA4BF;
    font-weight: 700;
}

.sidebar-mini-label {
    color: #7FA0C4;
    font-size: 12px;
    font-weight: 950;
    letter-spacing: 0.08em;
    margin-top: 18px;
    margin-bottom: 10px;
}

.main-title {
    font-size: 42px;
    font-weight: 950;
    color: #0F172A;
    line-height: 1.15;
}

.sub-title {
    color: #64748B;
    font-size: 17px;
    margin-top: 8px;
    margin-bottom: 24px;
}

.hero-panel {
    background: linear-gradient(135deg, #FFFFFF 0%, #F8FAFC 55%, #ECFDF5 100%);
    border: 1px solid #E5E7EB;
    border-left: 7px solid #10B981;
    border-radius: 28px;
    padding: 30px 34px;
    margin: 18px 0 28px 0;
    box-shadow: 0 22px 55px rgba(15, 23, 42, 0.08);
    display: grid;
    grid-template-columns: 1.25fr 0.75fr;
    gap: 28px;
    align-items: center;
}

.hero-label {
    color: #64748B;
    font-size: 15px;
    font-weight: 900;
    margin-bottom: 10px;
}

.hero-value {
    color: #059669;
    font-size: 62px;
    font-weight: 950;
    letter-spacing: -0.06em;
    line-height: 1;
}

.hero-sub {
    margin-top: 14px;
    color: #64748B;
    font-size: 15px;
    font-weight: 750;
}

.hero-chart {
    height: 150px;
    border-radius: 22px;
    background:
        linear-gradient(180deg, rgba(16,185,129,0.16), rgba(16,185,129,0.02)),
        repeating-linear-gradient(to right, rgba(15,23,42,0.04) 0px, rgba(15,23,42,0.04) 1px, transparent 1px, transparent 42px);
    position: relative;
    overflow: hidden;
}

.hero-dot {
    position: absolute;
    right: 28px;
    top: 30px;
    width: 14px;
    height: 14px;
    background: #10B981;
    border-radius: 50%;
    box-shadow: 0 0 0 8px rgba(16,185,129,0.16);
}

.card {
    background: linear-gradient(180deg, #FFFFFF 0%, #FBFDFF 100%);
    border-radius: 22px;
    padding: 24px;
    border: 1px solid #E5E7EB;
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.06);
    min-height: 132px;
}

.card-title {
    color: #64748B;
    font-size: 14px;
    font-weight: 850;
}

.card-value {
    font-size: 36px;
    font-weight: 950;
    color: #059669;
    margin-top: 10px;
    letter-spacing: -0.04em;
}

.card-sub {
    color: #64748B;
    font-size: 13px;
    margin-top: 8px;
}

.lead-card {
    display: grid;
    grid-template-columns: minmax(330px, 2.2fr) 0.8fr 0.45fr 0.55fr 0.55fr;
    gap: 18px;
    align-items: center;
    background: #FFFFFF;
    padding: 22px 24px;
    border-radius: 22px;
    border: 1px solid #E5E7EB;
    margin-bottom: 14px;
    box-shadow: 0 14px 36px rgba(15, 23, 42, 0.055);
}

.lead-title {
    font-size: 18px;
    font-weight: 900;
    color: #111827;
}

.lead-sub {
    font-size: 13px;
    color: #64748B;
    margin-top: 6px;
    line-height: 1.45;
}

.ai-summary {
    margin-top: 12px;
    font-size: 13px;
    color: #2563EB;
    font-weight: 800;
}

.lead-money {
    font-size: 24px;
    font-weight: 950;
    color: #059669;
    text-align: right;
}

.risk-high, .risk-mid, .risk-low {
    padding: 8px 12px;
    border-radius: 999px;
    text-align: center;
    font-weight: 900;
    font-size: 13px;
}

.risk-high { background: #FEE2E2; color: #DC2626; }
.risk-mid { background: #FEF3C7; color: #D97706; }
.risk-low { background: #DCFCE7; color: #059669; }

.lead-days, .lead-score {
    font-size: 13px;
    color: #475569;
    font-weight: 850;
    text-align: center;
}

.notice {
    background: linear-gradient(90deg, #EFF6FF, #ECFDF5);
    border: 1px solid #BFDBFE;
    color: #1E40AF;
    padding: 16px 18px;
    border-radius: 18px;
    font-weight: 800;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 10px;
    border-bottom: 1px solid #E5E7EB;
}

.stTabs [data-baseweb="tab"] {
    height: 44px;
    padding: 0 14px;
    border-radius: 12px 12px 0 0;
    color: #64748B;
    font-weight: 850;
}

.stTabs [aria-selected="true"] {
    color: #059669 !important;
    background: #ECFDF5;
}

#MainMenu {visibility: visible;}
footer {visibility: visible;}
header {visibility: visible;}
</style>
""", unsafe_allow_html=True)


def metric_card(title, value, sub):
    st.markdown(f"""
    <div class="card">
        <div class="card-title">{safe(title)}</div>
        <div class="card-value">{safe(value)}</div>
        <div class="card-sub">{safe(sub)}</div>
    </div>
    """, unsafe_allow_html=True)


def lead_card(row):
    risk_level = str(row.get("risk_level", "中"))
    risk_class = "risk-high" if risk_level == "高" else "risk-mid" if risk_level == "中" else "risk-low"

    st.markdown(f"""
    <div class="lead-card">
        <div>
            <div class="lead-title">{safe(row.get("customer", ""))}</div>
            <div class="lead-sub">{safe(row.get("subject", ""))}</div>
            <div class="ai-summary">✦ {safe(row.get("reason", "判定理由なし"))}</div>
        </div>
        <div class="lead-money">{money(row.get("estimated_profit", 0))}</div>
        <div class="{risk_class}">{safe(risk_level)}</div>
        <div class="lead-days">{int(row.get("neglected_days", 0) or 0)}日放置</div>
        <div class="lead-score">Score {int(row.get("revenue_score", 0) or 0)} / Opp {int(row.get("opportunity_score", 0) or 0)}</div>
    </div>
    """, unsafe_allow_html=True)


# =========================
# App
# =========================


st.markdown("""
<style>\n/* SAFE_UI_CLEANUP */
.block-container {
    max-width: 1280px;
    padding-top: 2rem;
}
div[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #e8edf3;
    padding: 18px;
    border-radius: 16px;
    box-shadow: 0 6px 18px rgba(20,40,80,.06);
}
button[kind="secondary"] {
    border-radius: 12px !important;
}
.stButton > button {
    border-radius: 12px;
    font-weight: 700;
}
[data-testid="stDataFrame"] {
    border-radius: 14px;
    overflow: hidden;
}
</style>
""", unsafe_allow_html=True)


# ==============================
# Google OAuth Callback 自動処理
# ==============================
def handle_google_oauth_callback():
    import streamlit as st
    from gmail_oauth_web import exchange_code_for_token, parse_oauth_state

    try:
        params = st.query_params
        st.session_state["oauth_debug_params"] = dict(params)

        code = params.get("code")

        if code:
            oauth_state = params.get("state", "")
            oauth_user_id, oauth_company_id = parse_oauth_state(oauth_state)

            st.session_state["logged_in"] = True
            st.session_state["user_id"] = oauth_user_id
            st.session_state["company_id"] = oauth_company_id

            st.session_state["oauth_debug_code_received"] = True
            exchange_code_for_token(code, user_id=oauth_user_id, company_id=oauth_company_id)
            st.session_state["oauth_debug_saved"] = True

            st.query_params.clear()
            st.success("Gmail接続が完了しました。")
        else:
            st.session_state["oauth_debug_code_received"] = False

    except Exception as e:
        st.error(f"Gmail接続処理エラー: {e}")

handle_google_oauth_callback()


st.set_page_config(page_title="Profit Radar", layout="wide", initial_sidebar_state="expanded")
# sidebar force visible patch
st.markdown("""
<style>
section[data-testid="stSidebar"] {
    display: block !important;
    visibility: visible !important;
    width: 330px !important;
    min-width: 330px !important;
    max-width: 330px !important;
    transform: translateX(0px) !important;
}
section[data-testid="stSidebar"] > div {
    display: block !important;
    visibility: visible !important;
    width: 330px !important;
}
[data-testid="collapsedControl"] {
    display: block !important;
    visibility: visible !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
[data-testid="stSidebar"] {
    display: block !important;
    visibility: visible !important;
    min-width: 280px !important;
}
[data-testid="collapsedControl"] {
    display: block !important;
    visibility: visible !important;
}
</style>
""", unsafe_allow_html=True)


def ensure_auth_tables():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            name TEXT,
            password_hash TEXT,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            company_name TEXT,
            plan TEXT DEFAULT 'beta',
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def hash_password(password):
    return hashlib.sha256(str(password).encode("utf-8")).hexdigest()


def create_user_and_company(email, name, password, company_name):
    email = str(email or "").strip().lower()
    name = str(name or "").strip()
    company_name = str(company_name or "").strip()

    if not email or not password or not company_name:
        raise ValueError("メールアドレス、パスワード、会社名は必須です。")

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("SELECT id FROM users WHERE email = ?", (email,))
    if c.fetchone():
        conn.close()
        raise ValueError("このメールアドレスは既に登録されています。")

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    password_hash = hash_password(password)

    c.execute("""
        INSERT INTO users (email, name, password_hash, created_at)
        VALUES (?, ?, ?, ?)
    """, (email, name, password_hash, created_at))

    user_id = c.lastrowid

    c.execute("""
        INSERT INTO companies (user_id, company_name, plan, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, company_name, "beta", created_at))

    company_id = c.lastrowid

    conn.commit()
    conn.close()

    return user_id, company_id


def authenticate_user(email, password):
    email = str(email or "").strip().lower()
    password_hash = hash_password(password)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT id, email, name
        FROM users
        WHERE email = ? AND password_hash = ?
    """, (email, password_hash))

    user = c.fetchone()

    if not user:
        conn.close()
        return None

    c.execute("""
        SELECT id, company_name, plan
        FROM companies
        WHERE user_id = ?
        ORDER BY id ASC
        LIMIT 1
    """, (user["id"],))

    company = c.fetchone()
    conn.close()

    if not company:
        return None

    return {
        "user_id": int(user["id"]),
        "email": user["email"],
        "name": user["name"],
        "company_id": int(company["id"]),
        "company_name": company["company_name"],
        "plan": company["plan"],
    }


def render_auth_gate():
    if st.session_state.get("logged_in"):
        return

    st.title("Profit Radar")
    st.caption("ログインまたは新規登録してください。")

    login_tab, register_tab = st.tabs(["ログイン", "新規登録"])

    with login_tab:
        login_email = st.text_input("メールアドレス", key="login_email")
        login_password = st.text_input("パスワード", type="password", key="login_password")

        if st.button("ログイン", key="login_button"):
            user = authenticate_user(login_email, login_password)
            if user:
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = user["user_id"]
                st.session_state["company_id"] = user["company_id"]
                st.session_state["user_email"] = user["email"]
                st.session_state["user_name"] = user["name"]
                st.session_state["company_name"] = user["company_name"]
                st.session_state["plan"] = user["plan"]
                st.success("ログインしました。")
                st.rerun()
            else:
                st.error("メールアドレスまたはパスワードが違います。")

    with register_tab:
        reg_name = st.text_input("名前", key="register_name")
        reg_company = st.text_input("会社名・屋号", key="register_company")
        reg_email = st.text_input("メールアドレス", key="register_email")
        reg_password = st.text_input("パスワード", type="password", key="register_password")

        if st.button("新規登録", key="register_button"):
            try:
                user_id, company_id = create_user_and_company(reg_email, reg_name, reg_password, reg_company)

                st.session_state["logged_in"] = True
                st.session_state["user_id"] = user_id
                st.session_state["company_id"] = company_id
                st.session_state["user_email"] = reg_email.strip().lower()
                st.session_state["user_name"] = reg_name.strip()
                st.session_state["company_name"] = reg_company.strip()
                st.session_state["plan"] = "beta"

                st.success("登録しました。")
                st.rerun()
            except Exception as e:
                st.error(f"登録エラー: {e}")

    st.stop()


def render_logout_sidebar():
    st.sidebar.caption(f"ログイン中: {st.session_state.get('user_email', '')}")
    st.sidebar.caption(f"会社: {st.session_state.get('company_name', '')}")

    if st.sidebar.button("ログアウト"):
        for key in ["logged_in", "user_id", "company_id", "user_email", "user_name", "company_name", "plan"]:
            st.session_state.pop(key, None)
        st.rerun()


init_db()
ensure_columns()
ensure_auth_tables()
render_auth_gate()
render_logout_sidebar()

# Render旧DB対策：profit_actions不足カラム補修
def repair_profit_actions_schema():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("PRAGMA table_info(profit_actions)")
    existing = {row[1] for row in c.fetchall()}

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

    for col, col_type in required.items():
        if col not in existing:
            c.execute(f"ALTER TABLE profit_actions ADD COLUMN {col} {col_type}")

    conn.commit()
    conn.close()

repair_profit_actions_schema()

inject_css()


st.markdown("""
<style>
/* ===== Selectbox Clean Fix ===== */
[data-testid="stSidebar"] [data-baseweb="select"] {
    background: transparent !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: #F8FAFC !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 16px !important;
    min-height: 48px !important;
    box-shadow: none !important;
    overflow: hidden !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] > div > div {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] input {
    color: #111827 !important;
    font-weight: 850 !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] span {
    color: #111827 !important;
    font-weight: 850 !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] svg {
    color: #111827 !important;
    fill: #111827 !important;
}

/* Selectbox inside separator line removal */
[data-testid="stSidebar"] [data-baseweb="select"] [role="button"] {
    border-left: none !important;
    box-shadow: none !important;
}

/* Text input */
[data-testid="stSidebar"] .stTextInput input {
    background: #F8FAFC !important;
    color: #111827 !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 16px !important;
    min-height: 48px !important;
    box-shadow: none !important;
}
</style>
""", unsafe_allow_html=True)



st.markdown("""
<style>
/* ===== Sidebar Select Visibility Fix ===== */
[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: #F8FAFC !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 14px !important;
    min-height: 44px !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] div,
[data-testid="stSidebar"] [data-baseweb="select"] span {
    color: #111827 !important;
    font-weight: 800 !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] svg {
    fill: #111827 !important;
    color: #111827 !important;
}

[data-testid="stSidebar"] input {
    background: #F8FAFC !important;
    color: #111827 !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 14px !important;
    min-height: 44px !important;
}

[data-testid="stSidebar"] input::placeholder {
    color: #64748B !important;
    opacity: 1 !important;
}
</style>
""", unsafe_allow_html=True)


st.sidebar.markdown("""
<div class="sidebar-brand">
    <div class="sidebar-logo">◎</div>
    <div>
        <div class="sidebar-title">Profit Radar</div>
        <div class="sidebar-sub">利益漏れ検知AI</div>
    </div>
</div>
""", unsafe_allow_html=True)

st.sidebar.markdown('<div class="sidebar-mini-label">SEARCH</div>', unsafe_allow_html=True)

search_text = st.sidebar.text_input("顧客名・件名・本文・メモ")
st.sidebar.caption("検索対象：顧客名、件名、本文、分類、ステージ、理由、次アクション、メモ")

status_options = ["すべて", "未対応", "対応済み", "保留", "失注"]
risk_options = ["すべて", "低", "中", "高"]
pipeline_options = ["すべて", "新規", "提案", "交渉", "請求", "回収", "入金", "失注"]
category_options = [
    "すべて",
    "請求・入金",
    "提案・見積",
    "採用・人材",
    "契約・受注",
    "依頼・相談",
    "休眠顧客",
    "フォロー必要",
    "不明"
]

selected_status = st.sidebar.selectbox("ステータス", status_options)
selected_risk = st.sidebar.selectbox("危険度", risk_options)
selected_pipeline = st.sidebar.selectbox("Pipeline", pipeline_options)
selected_category = st.sidebar.selectbox("分類", category_options)

# データ取得：サイドバー整理時のdf未定義対策
try:
    df = get_leads(user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))
except Exception as e:
    st.error(f"案件データ取得エラー: {e}")
    df = pd.DataFrame()

if "revenue_score" not in df.columns:
    df["revenue_score"] = 0

df["revenue_score"] = df["revenue_score"].fillna(0)
max_score_value = df["revenue_score"].max()

if pd.isna(max_score_value):
    max_score_value = 0

max_score = int(max_score_value)

if max_score <= 0:
    min_score = 0
    st.sidebar.caption("Revenue Score: データなし")
else:
    min_score = st.sidebar.slider("Revenue Score", 0, max_score, 0)

max_profit_value = df["estimated_profit"].fillna(0).max() if "estimated_profit" in df.columns else 0
max_profit = int(max_profit_value) if not pd.isna(max_profit_value) else 0
if max_profit <= 0:
    min_profit = 0
    st.sidebar.caption("推定利益: データなし")
else:
    min_profit = st.sidebar.slider("推定利益 下限", 0, max_profit, 0)
only_open = st.sidebar.checkbox("未対応のみ", value=False)
only_hot = st.sidebar.checkbox("Hot Leadのみ", value=False)

df_view = df.copy()

# Render空DB・旧DB対策：不足カラムを補完
default_columns = {
    "opportunity_score": 0,
    "recoverable_profit": 0,
    "revenue_score": 0,
    "estimated_profit": 0,
    "status": "",
    "risk_level": "",
    "pipeline_stage": "",
    "category": "",
    "customer": "",
    "subject": "",
    "content": "",
    "memo": "",
    "reason": "",
    "next_action": "",
}
for col, default in default_columns.items():
    if col not in df_view.columns:
        df_view[col] = default

# 表示用スコア補正：revenue_scoreが無い/空の場合はopportunity_scoreを代用
if "revenue_score" not in df_view.columns:
    df_view["revenue_score"] = df_view.get("opportunity_score", 0)

df_view["revenue_score"] = df_view["revenue_score"].fillna(0)

if "opportunity_score" in df_view.columns:
    df_view.loc[df_view["revenue_score"] <= 0, "revenue_score"] = df_view["opportunity_score"].fillna(0)


if search_text:
    search_cols = ["customer", "subject", "content", "category", "pipeline_stage", "reason", "next_action", "memo"]
    mask = False

    for col in search_cols:
        if col in df_view.columns:
            mask = mask | df_view[col].astype(str).str.contains(search_text, case=False, na=False)

    df_view = df_view[mask]

if selected_status != "すべて":
    df_view = df_view[df_view["status"] == selected_status]

if selected_risk != "すべて":
    df_view = df_view[df_view["risk_level"] == selected_risk]

if selected_pipeline != "すべて" and "pipeline_stage" in df_view.columns:
    df_view = df_view[df_view["pipeline_stage"] == selected_pipeline]

if selected_category != "すべて" and "category" in df_view.columns:
    df_view = df_view[df_view["category"] == selected_category]

df_view = df_view[df_view["revenue_score"] >= min_score]

if "estimated_profit" in df_view.columns:
    df_view = df_view[df_view["estimated_profit"].fillna(0) >= min_profit]

if only_open:
    df_view = df_view[df_view["status"] == "未対応"]

if only_hot and "hot_lead" in df_view.columns:
    df_view = df_view[df_view["hot_lead"].fillna(0).astype(int) == 1]


st.markdown('<div class="main-title">Profit Radar</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">本日の利益候補と回収アクションを確認します。</div>', unsafe_allow_html=True)

total_profit = int(df_view[df_view["status"] == "未対応"]["estimated_profit"].sum())
recoverable_total = int(df_view[df_view["status"] == "未対応"]["recoverable_profit"].sum()) if "recoverable_profit" in df_view.columns else 0
if "recoverable_profit" in df_view.columns:
    recoverable_total = int(df_view[df_view["status"] == "未対応"]["recoverable_profit"].fillna(0).sum())
else:
    recoverable_total = 0
danger_count = len(df_view[(df_view["risk_level"] == "高") & (df_view["status"] == "未対応")])
open_count = len(df_view[df_view["status"] == "未対応"])
avg_score = int(df_view["revenue_score"].mean()) if not df_view.empty else 0

st.markdown(f"""
<div class="hero-panel">
    <div>
        <div class="hero-label">本日回収可能な売上</div>
        <div class="hero-value">{money(total_profit)}</div>
        <div class="hero-sub">未対応案件 {open_count}件 / 危険案件 {danger_count}件 / 平均Score {avg_score}</div>
    </div>
    <div class="hero-chart">
        <div class="hero-dot"></div>
    </div>
</div>
""", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
with c1:
    metric_card("推定利益", money(total_profit), "未対応案件の合計")
with c2:
    metric_card("回収可能利益", money(recoverable_total), "確率補正後の見込み")
with c2:
    metric_card("危険案件", f"{danger_count}件", "高リスク案件")
with c3:
    metric_card("未対応", f"{open_count}件", "本日確認対象")
with c4:
    metric_card("平均Revenue Score", avg_score, "高いほど優先")

st.divider()

# ==============================
# Gmail Web OAuth 接続UI
# ==============================
def render_gmail_oauth_settings():
    import streamlit as st
    from gmail_oauth_web import (
        get_authorization_url,
        load_credentials,
        init_gmail_connections_table,
    )

    st.subheader("Gmail接続")

    init_gmail_connections_table()
    creds = load_credentials(user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))

    if creds and (creds.valid or creds.refresh_token):
        st.success("Gmail接続済み")
        st.caption("Gmail解析・返信送信が利用できます。")
    else:
        st.warning("Gmail未接続")
        st.caption("Googleアカウントを接続すると、Gmail解析と返信送信が使えます。")

        try:
            auth_url, state = get_authorization_url(user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))
            st.link_button("Googleアカウントを接続", auth_url)
        except Exception as e:
            st.error(f"OAuth設定エラー: {e}")
            st.info("Render環境変数 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI を確認してください。")

dev_mode = str(st.query_params.get("dev", "0")) == "1"

tab_names = [
    "🏠 今日の利益",
    "🔥 今すぐ返信",
    "👥 顧客",
    "📈 実績",
    "⚙️ Gmail接続",
]

if dev_mode:
    tab_names.append("🛠 開発者")

tabs = st.tabs(tab_names)

hot_df = df_view[
    (df_view["status"] == "未対応") &
    (df_view.get("hot_lead", 0) == 1)
].sort_values("opportunity_score", ascending=False).head(5)

if not hot_df.empty:
    st.subheader("Hot Lead")
    for _, row in hot_df.iterrows():
        st.warning(
            f"{row.get('customer', '')}｜{row.get('subject', '')}｜"
            f"Opp {int(row.get('opportunity_score', 0) or 0)}｜"
            f"回収可能 {money(row.get('recoverable_profit', 0))}"
        )

priority_sort_col = "opportunity_score" if "opportunity_score" in df_view.columns else "revenue_score"
priority_df = df_view[df_view["status"] == "未対応"].sort_values(priority_sort_col, ascending=False).head(5)

with tabs[0]:
    st.subheader("🏠 今日の利益")
    st.caption("今日見るべき利益状況と優先案件を確認します。詳細対応は「🔥 今すぐ返信」で行います。")

    if df_view.empty:
        st.info("表示できる案件がありません。")
    else:
        priority_sort_col = "opportunity_score" if "opportunity_score" in df_view.columns else "revenue_score"
        dashboard_df = df_view.sort_values(priority_sort_col, ascending=False).copy()

        st.markdown("### 優先案件")
        for _, row in dashboard_df.head(8).iterrows():
            lead_card(row)


with tabs[1]:
    st.subheader("🔥 今すぐ返信")
    st.caption("未対応案件から、回収可能利益・放置日数・スコアが高い順に返信対象を表示します。")

    if df_view.empty:
        st.info("表示できる案件がありません。")
    else:
        reply_df = df_view.copy()

        for col in [
            "id", "gmail_id", "customer", "subject", "content", "category",
            "status", "recoverable_profit", "estimated_profit",
            "neglected_days", "opportunity_score", "revenue_score", "next_action"
        ]:
            if col not in reply_df.columns:
                reply_df[col] = ""

        for num_col in ["recoverable_profit", "estimated_profit", "neglected_days", "opportunity_score", "revenue_score"]:
            reply_df[num_col] = pd.to_numeric(reply_df[num_col], errors="coerce").fillna(0)

        score_col = "opportunity_score" if "opportunity_score" in reply_df.columns else "revenue_score"

        reply_df = reply_df[reply_df["status"] == "未対応"].copy()
        reply_df = reply_df.sort_values(
            ["recoverable_profit", "neglected_days", score_col],
            ascending=False
        )

        if reply_df.empty:
            st.success("現在、今すぐ返信が必要な未対応案件はありません。")
        else:
            lead_options = []
            lead_map = {}

            for _, r in reply_df.head(20).iterrows():
                lead_id_v = int(r.get("id", 0) or 0)
                label = (
                    f"#{lead_id_v}｜{r.get('customer', '不明顧客')}｜"
                    f"{r.get('subject', '件名なし')}｜"
                    f"回収可能 {money(r.get('recoverable_profit', 0))}｜"
                    f"{int(r.get('neglected_days', 0) or 0)}日放置"
                )
                lead_options.append(label)
                lead_map[label] = lead_id_v

            selected_label = st.selectbox("返信する案件を選択", lead_options, key="hot_reply_select")
            lead_id = lead_map[selected_label]
            lead = reply_df[reply_df["id"] == lead_id].iloc[0]

            st.divider()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("回収可能利益", money(lead.get("recoverable_profit", 0)))
            c2.metric("推定利益", money(lead.get("estimated_profit", 0)))
            c3.metric("放置日数", f"{int(lead.get('neglected_days', 0) or 0)}日")
            c4.metric("スコア", int(lead.get(score_col, 0) or 0))

            st.markdown(f"### {lead.get('customer', '不明顧客')}")
            st.write("件名：", lead.get("subject", "件名なし"))
            st.write("分類：", lead.get("category", "未分類"))

            with st.expander("メール本文を見る"):
                st.text_area(
                    "メール本文",
                    str(lead.get("content", "") or ""),
                    height=220,
                    key=f"hot_body_{lead_id}"
                )

            st.divider()
            st.markdown("### 🤖 AI案件参謀")
            st.caption("この案件をどう扱うべきか、AIが判断します。")

            try:
                ai_advice = build_ai_advice(lead)
                formatted_ai_advice = format_ai_advice(ai_advice)

                if isinstance(formatted_ai_advice, str):
                    st.markdown(formatted_ai_advice)
                else:
                    st.write(formatted_ai_advice)

            except Exception as e:
                st.warning(f"AI案件参謀を表示できませんでした: {e}")

                fallback_decision = str(lead.get("next_action", "") or "フォロー確認")
                fallback_risk = str(lead.get("risk_level", "") or "中")
                fallback_score = int(lead.get(score_col, 0) or 0)

                a1, a2, a3 = st.columns(3)
                a1.metric("判断", fallback_decision[:20])
                a2.metric("リスク", fallback_risk)
                a3.metric("優先度", fallback_score)

                st.info("AI詳細判断が取得できないため、保存済みの案件情報から簡易判断を表示しています。")

            st.divider()
            st.markdown("### 実利益を記録")
            st.caption("実際に回収できた金額を入力すると、案件は自動で成約扱いになります。")

            actual_revenue_input = st.number_input(
                "実回収利益",
                min_value=0,
                step=1000,
                value=int(lead.get("actual_revenue", 0) or 0),
                key=f"hot_actual_revenue_{lead_id}"
            )

            if st.button("実利益を保存", key=f"hot_save_actual_revenue_{lead_id}"):
                update_actual_revenue(
                    lead_id,
                    actual_revenue_input,
                    user_id=st.session_state.get("user_id"),
                    company_id=st.session_state.get("company_id")
                )
                save_ai_learning(
                    lead_id=int(lead_id),
                    customer=str(lead.get("customer", "")),
                    subject=str(lead.get("subject", "")),
                    ai_decision=str(lead.get("next_action", "")),
                    result="成約" if int(actual_revenue_input or 0) > 0 else "実利益更新",
                    actual_revenue=int(actual_revenue_input or 0),
                    note="今すぐ返信タブから実利益を保存"
                )
                st.success("実利益を保存しました。")
                st.rerun()

            st.divider()
            st.markdown("### フォロー文")

            safe_subject = str(lead.get("subject", "") or "").strip()
            if len(safe_subject) < 3:
                safe_subject = "ご確認のお願い"

            try:
                history_text = build_followup_history(lead)
            except Exception:
                history_text = ""

            try:
                default_follow = generate_follow_message(
                    lead.get("customer", ""),
                    safe_subject,
                    lead.get("content", ""),
                    category=lead.get("category", ""),
                    history=history_text
                )
            except Exception:
                default_follow = str(lead.get("next_action", "") or "")
                if len(default_follow) < 10:
                    default_follow = f"""{lead.get('customer', '')} 様

お世話になっております。

下記の件について、進行状況を確認させてください。

件名：{safe_subject}

ご確認いただき、進められそうであれば次の流れをご相談できればと思います。
よろしくお願いいたします。"""

            follow_body = st.text_area(
                "編集して保存・送信できます",
                default_follow,
                height=240,
                key=f"hot_follow_{lead_id}"
            )

            customer_raw = str(lead.get("customer", "") or "")
            email_match = re.search(r"<([^>]+)>", customer_raw)
            default_to_email = email_match.group(1).strip() if email_match else ""

            to_email = st.text_input(
                "送信先メールアドレス",
                default_to_email,
                key=f"hot_to_{lead_id}"
            )

            col_save, col_send, col_hold, col_done = st.columns(4)

            with col_save:
                if st.button("フォロー文を保存", key=f"hot_save_follow_{lead_id}"):
                    try:
                        save_action(
                            lead_id=int(lead_id),
                            gmail_id=str(lead.get("gmail_id", "")),
                            action_type="follow_text_saved",
                            to_email=to_email,
                            subject=safe_subject,
                            body=follow_body,
                            status="saved"
                        )
                        st.success("フォロー文を保存しました。")
                    except Exception as e:
                        save_action_log(int(lead_id), "follow_text_saved", follow_body, "saved")
                        st.warning(f"簡易保存しました: {e}")

            with col_send:
                if st.button("Gmail送信", key=f"hot_send_follow_{lead_id}"):
                    try:
                        if not to_email:
                            st.error("送信先メールアドレスを入力してください。")
                            raise RuntimeError("送信先メールアドレス未入力")

                        send_errors = validate_send_body(follow_body)
                        if send_errors:
                            st.error("送信停止：本文に問題があります。")
                            for err in send_errors:
                                st.warning(err)
                            raise RuntimeError("送信前安全チェックで停止しました。")

                        result = send_gmail_reply(
                            gmail_id=str(lead.get("gmail_id", "")),
                            to_email=to_email,
                            subject=safe_subject,
                            body=follow_body,
                            lead_id=int(lead_id),
                            action_type="gmail_reply",
                            force_send=False
                        )

                        gmail_result_id = result.get("id", "")

                        save_action(
                            lead_id=int(lead_id),
                            gmail_id=str(lead.get("gmail_id", "")),
                            action_type="gmail_reply",
                            to_email=to_email,
                            subject=safe_subject,
                            body=follow_body,
                            status="sent",
                            safety_ok=1,
                            gmail_result_id=gmail_result_id
                        )

                        update_lead_status(int(lead_id), "対応済み", user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))
                        st.success(f"Gmail送信完了: {gmail_result_id}")
                        st.rerun()

                    except Exception as e:
                        try:
                            save_action(
                                lead_id=int(lead_id),
                                gmail_id=str(lead.get("gmail_id", "")),
                                action_type="gmail_reply_failed",
                                to_email=to_email,
                                subject=safe_subject,
                                body=follow_body,
                                status="failed",
                                safety_ok=0,
                                safety_errors=str(e)
                            )
                        except Exception:
                            pass
                        st.error(f"Gmail送信エラー: {e}")

            with col_hold:
                if st.button("保留", key=f"hot_hold_{lead_id}"):
                    update_lead_status(int(lead_id), "保留", user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))
                    save_action_log(int(lead_id), "status_update", "保留に変更", "pending")
                    st.warning("保留にしました。")
                    st.rerun()

            with col_done:
                if st.button("対応済み", key=f"hot_done_{lead_id}"):
                    update_lead_status(int(lead_id), "対応済み", user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))
                    save_action_log(int(lead_id), "status_update", "対応済みに変更", "done")
                    st.success("対応済みにしました。")
                    st.rerun()


with tabs[2]:
    st.subheader("👥 顧客")

    customer_df = df_view.groupby("customer").agg(
        案件数=("id", "count"),
        累計推定利益=("estimated_profit", "sum"),
        最大未対応日数日数=("neglected_days", "max"),
        平均Score=("revenue_score", "mean")
    ).reset_index()

    if customer_df.empty:
        st.info("顧客データはありません。")
    else:
        for _, row in customer_df.iterrows():
            st.markdown(f"""
            <div class="lead-card">
                <div>
                    <div class="lead-title">{safe(row['customer'])}</div>
                    <div class="lead-sub">案件数：{int(row['案件数'])}件</div>
                </div>
                <div class="lead-money">{money(row['累計推定利益'])}</div>
                <div class="risk-mid">LTV</div>
                <div class="lead-days">{int(row['最大未対応日数日数'])}日</div>
                <div class="lead-score">Score {int(row['平均Score'])}</div>
            </div>
            """, unsafe_allow_html=True)

        st.divider()
        st.markdown("### 顧客詳細")

        try:
            customer_summary = get_customer_revenue_summary(selected_customer)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("累計実回収利益", money(customer_summary.get("total_actual_revenue", 0)))
            c2.metric("累計推定利益", money(customer_summary.get("total_estimated_profit", 0)))
            c3.metric("案件数", int(customer_summary.get("lead_count", 0) or 0))
            c4.metric("最大未対応日数", int(customer_summary.get("max_neglected_days", 0) or 0))
        except Exception as e:
            st.warning(f"顧客収益サマリーを表示できませんでした: {e}")

        selected_customer = st.selectbox(
            "詳細を見る顧客",
            customer_df["customer"].tolist(),
            key="customer_detail_select"
        )

        customer_leads = df_view[df_view["customer"] == selected_customer].copy()

        total_estimated = int(customer_leads["estimated_profit"].sum())
        total_recoverable = int(customer_leads["recoverable_profit"].sum()) if "recoverable_profit" in customer_leads.columns else 0
        max_score = int(customer_leads["revenue_score"].max()) if not customer_leads.empty else 0
        open_count = len(customer_leads[customer_leads["status"] == "未対応"])

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("案件数", len(customer_leads))
        c2.metric("累計推定利益", money(total_estimated))
        c3.metric("回収可能利益", money(total_recoverable))
        c4.metric("未対応", f"{open_count}件")

        st.markdown("#### 案件一覧")

        for _, lead_row in customer_leads.iterrows():
            st.markdown(f"""
            <div class="lead-card">
                <div>
                    <div class="lead-title">{safe(lead_row.get('subject', ''))}</div>
                    <div class="lead-sub">{safe(lead_row.get('category', ''))}｜{safe(lead_row.get('status', ''))}</div>
                </div>
                <div class="lead-money">{money(lead_row.get('estimated_profit', 0))}</div>
                <div class="risk-mid">{safe(lead_row.get('risk_level', ''))}</div>
                <div class="lead-days">{int(lead_row.get('neglected_days', 0) or 0)}日</div>
                <div class="lead-score">Score {int(lead_row.get('revenue_score', 0) or 0)}</div>
            </div>
            """, unsafe_allow_html=True)

            with st.expander(f"本文・メモを見る｜案件ID {int(lead_row.get('id', 0))}"):
                st.write("件名：", lead_row.get("subject", ""))
                st.write("ステージ：", lead_row.get("pipeline_stage", ""))
                st.text_area("メール本文", str(lead_row.get("content", "") or ""), height=180, key=f"cust_body_{lead_row.get('id')}")
                st.text_area("メモ", str(lead_row.get("memo", "") or ""), height=100, key=f"cust_memo_{lead_row.get('id')}")

        st.markdown("#### この顧客の保存・送信履歴")

        actions_df = get_actions(user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))
        if not actions_df.empty and "lead_id" in actions_df.columns:
            customer_lead_ids = customer_leads["id"].tolist()
            customer_actions = actions_df[actions_df["lead_id"].isin(customer_lead_ids)]

            if customer_actions.empty:
                st.info("この顧客の履歴はまだありません。")
            else:
                for _, action in customer_actions.iterrows():
                    label = str(action.get("action_type", "") or "")
                    subject_v = str(action.get("subject", "") or "")
                    status_v = str(action.get("status", "") or action.get("result", "") or "")
                    created_v = str(action.get("created_at", "") or "")
                    body_v = str(action.get("body", "") or action.get("message", "") or "")

                    with st.expander(f"{label}｜{created_v[:16]}｜{subject_v[:30]}"):
                        st.write("状態：", status_v)
                        st.write("件名：", subject_v)
                        st.text_area("本文", body_v, height=180, key=f"cust_action_{action.get('id', '')}")
        else:
            st.info("履歴はまだありません。")

if False:
    st.subheader("フォローアップ")

    lead_id = st.selectbox("案件を選択", df_view["id"].tolist(), key="followup")
    lead = df_view[df_view["id"] == lead_id].iloc[0]

    st.write(f"顧客：{lead['customer']}")
    st.write(f"件名：{lead['subject']}")

    if st.button("フォロー文を生成"):
        msg = generate_follow_message(lead["customer"], lead["subject"], lead["content"])
        save_action_log(int(lead_id), "follow_up_generated", msg, "generated")
        st.text_area("生成文面", msg, height=260)

    st.divider()

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("対応済みにする"):
            update_lead_status(int(lead_id), "対応済み", user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))
            save_action_log(int(lead_id), "status_update", "対応済みに変更", "done")
            st.success("対応済みにしました。")

    with col2:
        if st.button("保留にする"):
            update_lead_status(int(lead_id), "保留", user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))
            save_action_log(int(lead_id), "status_update", "保留に変更", "pending")
            st.warning("保留にしました。")

    with col3:
        if st.button("未対応に戻す"):
            update_lead_status(int(lead_id), "未対応", user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))
            save_action_log(int(lead_id), "status_update", "未対応に変更", "open")
            st.info("未対応に戻しました。")

with tabs[3]:
    st.subheader("📈 実績")
    st.caption("今日・今月・累計の利益と、利益を生んだ顧客を確認します。")

    chart_df = get_revenue_chart_data()

    if chart_df.empty:
        st.info("実績データがまだありません。Gmail解析・実回収利益の保存後に表示されます。")
    else:
        chart_df["actual_revenue"] = pd.to_numeric(chart_df.get("actual_revenue", 0), errors="coerce").fillna(0)
        chart_df["estimated_profit"] = pd.to_numeric(chart_df.get("estimated_profit", 0), errors="coerce").fillna(0)
        chart_df["recoverable_profit"] = pd.to_numeric(chart_df.get("recoverable_profit", 0), errors="coerce").fillna(0)

        for col in ["customer", "subject", "pipeline_stage", "sales_temperature", "created_at"]:
            if col not in chart_df.columns:
                chart_df[col] = ""

        chart_df["customer"] = chart_df["customer"].fillna("不明顧客").astype(str).replace("", "不明顧客")
        chart_df["subject"] = chart_df["subject"].fillna("件名なし").astype(str).replace("", "件名なし")
        chart_df["pipeline_stage"] = chart_df["pipeline_stage"].fillna("未分類").astype(str).replace("", "未分類")
        chart_df["sales_temperature"] = chart_df["sales_temperature"].fillna("未分類").astype(str).replace("", "未分類")

        chart_df["created_at_dt"] = pd.to_datetime(chart_df["created_at"], errors="coerce")
        today = pd.Timestamp.now().date()
        this_month = pd.Timestamp.now().month
        this_year = pd.Timestamp.now().year

        revenue_df = chart_df[chart_df["actual_revenue"] > 0].copy()

        today_revenue = int(chart_df[chart_df["created_at_dt"].dt.date == today]["actual_revenue"].sum())
        month_revenue = int(chart_df[
            (chart_df["created_at_dt"].dt.year == this_year) &
            (chart_df["created_at_dt"].dt.month == this_month)
        ]["actual_revenue"].sum())
        total_revenue = int(chart_df["actual_revenue"].sum())

        closed_count = int((chart_df["actual_revenue"] > 0).sum())
        avg_revenue = int(revenue_df["actual_revenue"].mean()) if not revenue_df.empty else 0
        total_recoverable = int(chart_df["recoverable_profit"].sum())

        st.markdown("### 今日の利益")

        k1, k2, k3 = st.columns(3)
        k1.metric("今日", money(today_revenue))
        k2.metric("今月", money(month_revenue))
        k3.metric("累計", money(total_revenue))

        k4, k5, k6 = st.columns(3)
        k4.metric("成約件数", f"{closed_count}件")
        k5.metric("平均回収単価", money(avg_revenue))
        k6.metric("未回収見込み", money(total_recoverable))

        st.divider()

        st.markdown("### 利益を生んだTOP顧客")

        top_customers = (
            revenue_df.groupby("customer", as_index=False)["actual_revenue"]
            .sum()
            .sort_values("actual_revenue", ascending=False)
            .head(3)
        )

        if top_customers.empty:
            st.info("実回収利益がある顧客はまだありません。")
        else:
            top_cols = st.columns(3)
            for idx, row in top_customers.reset_index(drop=True).iterrows():
                customer_name = str(row["customer"])
                amount = int(row["actual_revenue"])
                with top_cols[idx]:
                    st.metric(f"{idx + 1}位", money(amount))
                    st.caption(customer_name)

        st.divider()

        st.markdown("### 顧客別 実回収利益ランキング")

        customer_rank = (
            revenue_df.groupby("customer", as_index=False)["actual_revenue"]
            .sum()
            .sort_values("actual_revenue", ascending=False)
            .head(8)
        )

        if customer_rank.empty:
            st.info("実回収利益がある顧客はまだありません。")
        else:
            max_value = int(customer_rank["actual_revenue"].max()) or 1

            for i, row in customer_rank.reset_index(drop=True).iterrows():
                customer = str(row["customer"])
                value = int(row["actual_revenue"])
                rate = min(value / max_value, 1.0)

                left, right = st.columns([3, 1])
                left.markdown(f"**{i + 1}. {customer}**")
                left.progress(rate)
                right.metric("実利益", money(value))

        st.divider()

        st.markdown("### 最近の成約")

        if revenue_df.empty:
            st.info("最近の成約はまだありません。")
        else:
            recent_df = revenue_df.copy()
            recent_df = recent_df.sort_values("created_at_dt", ascending=False).head(5)
            recent_df["実回収利益"] = recent_df["actual_revenue"].apply(lambda x: money(int(x)))
            recent_df["日付"] = recent_df["created_at_dt"].dt.strftime("%Y/%m/%d").fillna("-")

            recent_show = recent_df[["日付", "customer", "subject", "実回収利益"]].rename(columns={
                "customer": "顧客",
                "subject": "案件",
            })

            st.dataframe(recent_show, use_container_width=True, hide_index=True)

        st.divider()

        st.markdown("### 案件状態")

        stage_chart = (
            chart_df.groupby("pipeline_stage", as_index=False)
            .size()
            .rename(columns={"pipeline_stage": "案件状態", "size": "件数"})
            .sort_values("件数", ascending=False)
        )

        if stage_chart.empty:
            st.info("案件状態データがありません。")
        else:
            max_stage = int(stage_chart["件数"].max()) or 1
            for _, row in stage_chart.iterrows():
                label = str(row["案件状態"])
                count = int(row["件数"])
                st.markdown(f"**{label}：{count}件**")
                st.progress(min(count / max_stage, 1.0))

        st.divider()

        st.markdown("### 営業温度")

        temp_chart = (
            chart_df.groupby("sales_temperature", as_index=False)
            .size()
            .rename(columns={"sales_temperature": "営業温度", "size": "件数"})
            .sort_values("件数", ascending=False)
        )

        if temp_chart.empty:
            st.info("営業温度データがありません。")
        else:
            max_temp = int(temp_chart["件数"].max()) or 1
            for _, row in temp_chart.iterrows():
                label = str(row["営業温度"])
                count = int(row["件数"])
                st.markdown(f"**{label}：{count}件**")
                st.progress(min(count / max_temp, 1.0))

        st.divider()

        st.markdown("### 実回収利益 一覧")

        if revenue_df.empty:
            st.info("実回収済みの案件はまだありません。")
        else:
            list_df = revenue_df.copy()
            list_df["実回収利益"] = list_df["actual_revenue"].apply(lambda x: money(int(x)))
            list_df["推定利益"] = list_df["estimated_profit"].apply(lambda x: money(int(x)))
            list_df["作成日"] = list_df["created_at_dt"].dt.strftime("%Y/%m/%d").fillna("-")

            list_df = list_df[["作成日", "customer", "subject", "pipeline_stage", "sales_temperature", "実回収利益", "推定利益"]].rename(columns={
                "customer": "顧客",
                "subject": "案件",
                "pipeline_stage": "案件状態",
                "sales_temperature": "営業温度",
            })

            st.dataframe(list_df, use_container_width=True, hide_index=True)


with tabs[4]:
    st.subheader("⚙️ 設定")
    render_gmail_oauth_settings()
    # AI分析履歴 は app_dev.py に分離済み

    st.markdown("### Gmail解析")
    st.caption("Gmailから利益候補を検出します。")

    analysis_limit = st.selectbox("Gmail解析件数", [5, 10, 20, 30, 50], index=2, key="settings_analysis_limit_restored")

    if st.button("Gmailを解析する", key="settings_gmail_scan_restored"):
        try:
            emails = fetch_recent_emails(limit=analysis_limit, user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))
            count = 0
            for email in emails:
                if save_email_as_lead(email, user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id")):
                    count += 1
            st.success(f"{count}件の利益候補を検出しました。")
        except Exception as e:
            st.error(f"Gmail解析エラー: {e}")

    if st.button("解析データをリセット", key="settings_reset_data_restored"):
        reset_database(user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))
        st.success("解析データをリセットしました。")

    df = get_leads(user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))

    if df.empty:
        st.markdown('<div class="main-title">Profit Radar</div>', unsafe_allow_html=True)
        st.markdown('<div class="sub-title">左の「Gmailを解析する」から利益候補を検出してください。</div>', unsafe_allow_html=True)
        st.stop()

    st.divider()

    st.markdown("### CSV出力")
    st.caption("現在表示中の案件一覧をCSVで保存します。")

    try:
        export_df = df_view.copy() if "df_view" in globals() else df.copy()
        csv_data = export_df.to_csv(index=False).encode("utf-8-sig")

        st.download_button(
            "案件一覧をCSV保存",
            csv_data,
            "profit_radar_leads.csv",
            "text/csv",
            key="settings_csv_download"
        )
    except Exception as e:
        st.warning(f"CSV出力を表示できません: {e}")

    st.divider()

    st.markdown("### Gmail返信検知")

    if st.button("Gmail返信をチェック"):
        try:
            from reply_detector import detect_replies

            results = detect_replies(limit=30)

            if not results:
                st.info("新しい返信は検知されませんでした。")
            else:
                st.success(f"{len(results)}件の返信を検知しました。")

                for r in results:
                    if "error" in r:
                        st.warning(f"lead_id={r.get('lead_id')} エラー: {r.get('error')}")
                    else:
                        st.write(
                            f"lead_id={r.get('lead_id')} / "
                            f"from={r.get('from_email')} / "
                            f"subject={r.get('subject')}"
                        )

        except Exception as e:
            st.error(f"返信検知エラー: {e}")

    st.markdown("### 活動履歴 / 返信検知ログ")

    try:
        conn = sqlite3.connect(DB)
        reply_logs = pd.read_sql_query(
            """
            SELECT lead_id, from_email, subject, detected_at
            FROM reply_detection_logs
            ORDER BY id DESC
            LIMIT 20
            """,
            conn
        )
        conn.close()

        if reply_logs.empty:
            st.info("返信検知ログはまだありません。")
        else:
            st.dataframe(reply_logs, use_container_width=True)

    except Exception as e:
        st.warning(f"返信検知ログを表示できません: {e}")


if dev_mode:
    with tabs[-1]:
        st.subheader("🛠 開発者")
        st.caption("管理者・開発者向けの確認機能です。通常利用者には見せない画面です。")

        st.markdown("### 👤 利用者情報管理")
        st.caption("現在ログイン中のユーザー・会社・Gmail接続・利用状況を確認します。")

        login_status = "ログイン中" if st.session_state.get("logged_in") else "未ログイン"
        current_user_id = st.session_state.get("user_id")
        current_company_id = st.session_state.get("company_id")

        user_email = st.session_state.get("user_email", "-")
        user_name = st.session_state.get("user_name", "-")
        company_name = st.session_state.get("company_name", "-")
        plan = st.session_state.get("plan", "-")

        gmail_status = "未接続"
        gmail_updated_at = "-"
        lead_count = 0
        total_actual_revenue = 0

        try:
            conn = sqlite3.connect(DB)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            try:
                c.execute("""
                    SELECT updated_at
                    FROM gmail_connections
                    WHERE user_id = ? AND company_id = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                """, (current_user_id, current_company_id))
                gmail_row = c.fetchone()
                if gmail_row:
                    gmail_status = "接続済み"
                    gmail_updated_at = gmail_row["updated_at"]
            except Exception:
                pass

            try:
                c.execute("""
                    SELECT
                        COUNT(*) AS lead_count,
                        COALESCE(SUM(actual_revenue), 0) AS total_actual_revenue
                    FROM profit_leads
                    WHERE user_id = ? AND company_id = ?
                """, (current_user_id, current_company_id))
                lead_row = c.fetchone()
                if lead_row:
                    lead_count = int(lead_row["lead_count"] or 0)
                    total_actual_revenue = int(lead_row["total_actual_revenue"] or 0)
            except Exception:
                pass

            conn.close()

        except Exception as e:
            st.error(f"DB確認エラー: {e}")

        st.markdown("#### ログイン情報")
        c1, c2, c3 = st.columns(3)
        c1.metric("ログイン状態", login_status)
        c2.metric("ユーザーID", current_user_id if current_user_id else "-")
        c3.metric("会社ID", current_company_id if current_company_id else "-")

        st.markdown("#### 利用者・会社情報")
        info_df = pd.DataFrame([
            {"項目": "メールアドレス", "内容": user_email},
            {"項目": "ユーザー名", "内容": user_name},
            {"項目": "会社名・屋号", "内容": company_name},
            {"項目": "プラン", "内容": plan},
        ])
        st.dataframe(info_df, use_container_width=True, hide_index=True)

        st.markdown("#### Gmail接続状況")
        g1, g2 = st.columns(2)
        g1.metric("接続状態", gmail_status)
        g2.metric("最終更新日時", gmail_updated_at)

        if gmail_status == "接続済み":
            st.success("Gmailは正常に接続されています。解析・返信送信が利用できます。")
        else:
            st.warning("Gmailは未接続です。利用者画面の Gmail接続 から接続してください。")

        st.markdown("#### 利用状況サマリー")
        s1, s2 = st.columns(2)
        s1.metric("案件数", f"{lead_count}件")
        s2.metric("累計実回収利益", money(total_actual_revenue))

        st.info("この情報は現在のセッションとデータベースの状態を表示しています。")

        st.divider()

        st.markdown("### 開発用リセット")
        st.warning("解析データを削除します。テスト時のみ使用してください。")

        if st.button("解析データをリセット", key="dev_reset_data"):
            reset_database(user_id=st.session_state.get("user_id"), company_id=st.session_state.get("company_id"))
            st.success("解析データをリセットしました。")

        st.divider()

        st.markdown("### Gmail返信検知")
        st.caption("送信済みフォローに対する返信をGmailから検知します。")

        if st.button("Gmail返信をチェック", key="dev_check_replies"):
            try:
                from reply_detection_engine import detect_replies

                results = detect_replies(
                    limit=30,
                    user_id=st.session_state.get("user_id"),
                    company_id=st.session_state.get("company_id")
                )

                if not results:
                    st.info("新しい返信は検知されませんでした。")
                else:
                    st.success(f"{len(results)}件の返信を検知しました。")
                    st.write(results)

            except Exception as e:
                st.error(f"返信検知エラー: {e}")

