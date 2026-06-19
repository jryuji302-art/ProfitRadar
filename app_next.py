import html
import re
import sqlite3
from datetime import datetime
from email.utils import parsedate_to_datetime

import pandas as pd
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

def update_actual_revenue(lead_id, actual_revenue):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        UPDATE profit_leads
        SET actual_revenue=?
        WHERE id=?
    """, (int(actual_revenue or 0), int(lead_id)))
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
        memo TEXT
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


def get_leads():
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query("SELECT * FROM profit_leads", conn)
    conn.close()

    if not df.empty:
        df["revenue_score"] = df.apply(calc_revenue_score, axis=1)
        sort_col = "opportunity_score" if "opportunity_score" in df.columns else "revenue_score"
        df = df.sort_values(sort_col, ascending=False)

    return df


def get_actions():
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT * FROM profit_actions ORDER BY created_at DESC",
        conn
    )
    conn.close()
    return df


def reset_database():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("DELETE FROM profit_leads")
    c.execute("DELETE FROM profit_actions")
    conn.commit()
    conn.close()


def update_lead_status(lead_id, status):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE profit_leads SET status = ? WHERE id = ?", (status, lead_id))
    conn.commit()
    conn.close()


def update_lead_memo(lead_id, memo):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE profit_leads SET memo = ? WHERE id = ?", (memo, lead_id))
    conn.commit()
    conn.close()


def save_action_log(lead_id, action_type, message, result):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
    INSERT INTO profit_actions
    (lead_id, action_type, message, result, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (
        lead_id,
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

init_db()
ensure_columns()
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
    df = get_leads()
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
min_score = st.sidebar.slider("Revenue Score", 0, max_score, 0)

max_profit_value = df["estimated_profit"].fillna(0).max() if "estimated_profit" in df.columns else 0
max_profit = int(max_profit_value) if not pd.isna(max_profit_value) else 0
min_profit = st.sidebar.slider("推定利益 下限", 0, max_profit, 0)
only_open = st.sidebar.checkbox("未対応のみ", value=False)
only_hot = st.sidebar.checkbox("Hot Leadのみ", value=False)

df_view = df.copy()

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
recoverable_total = int(df_view[df_view["status"] == "未対応"].get("recoverable_profit", 0).sum())
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
        exchange_code_for_token,
        load_credentials,
        init_gmail_connections_table,
    )

    st.subheader("Gmail接続")

    init_gmail_connections_table()
    creds = load_credentials(user_id=1, company_id=1)

    if creds:
        st.success("Gmail接続済み")
    else:
        st.warning("Gmail未接続")

    try:
        auth_url, state = get_authorization_url()
        st.link_button("Googleアカウントを接続", auth_url)
    except Exception as e:
        st.error(f"OAuth設定エラー: {e}")
        st.info("Render環境変数 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI を確認してください。")

    st.divider()

    st.caption("Google認証後、URLに表示された code= の値を貼り付けて接続します。")
    code = st.text_input("認証コード", key="gmail_oauth_code")

    if st.button("Gmail接続を保存"):
        if not code.strip():
            st.error("認証コードを入力してください。")
        else:
            try:
                exchange_code_for_token(code.strip(), user_id=1, company_id=1)
                st.success("Gmail接続を保存しました。画面を再読み込みしてください。")
            except Exception as e:
                st.error(f"Gmail接続保存エラー: {e}")


tabs = st.tabs([
    "🏠 今日の利益",
    "🔥 今すぐ返信",
    "👥 顧客",
    "📈 分析",
    "⚙️ 設定"
])

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

        actions_df = get_actions()
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
            update_lead_status(int(lead_id), "対応済み")
            save_action_log(int(lead_id), "status_update", "対応済みに変更", "done")
            st.success("対応済みにしました。")

    with col2:
        if st.button("保留にする"):
            update_lead_status(int(lead_id), "保留")
            save_action_log(int(lead_id), "status_update", "保留に変更", "pending")
            st.warning("保留にしました。")

    with col3:
        if st.button("未対応に戻す"):
            update_lead_status(int(lead_id), "未対応")
            save_action_log(int(lead_id), "status_update", "未対応に変更", "open")
            st.info("未対応に戻しました。")

with tabs[3]:
    st.subheader("📈 分析")

    st.markdown("### 利益グラフ")

    chart_df = get_revenue_chart_data()

    if chart_df.empty:
        st.info("グラフ表示できるデータがありません。")
    else:
        chart_df["actual_revenue"] = pd.to_numeric(chart_df["actual_revenue"], errors="coerce").fillna(0)
        chart_df["estimated_profit"] = pd.to_numeric(chart_df["estimated_profit"], errors="coerce").fillna(0)
        chart_df["recoverable_profit"] = pd.to_numeric(chart_df["recoverable_profit"], errors="coerce").fillna(0)

        st.markdown("#### 顧客別 実回収利益")
        customer_chart = chart_df.groupby("customer", as_index=False)["actual_revenue"].sum()
        customer_chart = customer_chart.sort_values("actual_revenue", ascending=False).head(20)
        st.bar_chart(customer_chart, x="customer", y="actual_revenue")

        st.markdown("#### 分類別 実回収利益")
        category_chart = chart_df.groupby("category", as_index=False)["actual_revenue"].sum()
        category_chart = category_chart.sort_values("actual_revenue", ascending=False)
        st.bar_chart(category_chart, x="category", y="actual_revenue")

        st.markdown("#### ステージ別 案件数")
        stage_chart = chart_df.groupby("pipeline_stage", as_index=False).size()
        st.bar_chart(stage_chart, x="pipeline_stage", y="size")

        if "sales_temperature" in chart_df.columns:
            st.markdown("#### 営業温度別 案件数")
            temp_chart = chart_df.groupby("sales_temperature", as_index=False).size()
            st.bar_chart(temp_chart, x="sales_temperature", y="size")

        total_actual = int(chart_df["actual_revenue"].sum())
        total_estimated = int(chart_df["estimated_profit"].sum())
        total_recoverable = int(chart_df["recoverable_profit"].sum())

        g1, g2, g3 = st.columns(3)
        g1.metric("累計実回収利益", money(total_actual))
        g2.metric("累計推定利益", money(total_estimated))
        g3.metric("累計回収可能利益", money(total_recoverable))


    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 推定利益ランキング")
        st.bar_chart(df_view.set_index("customer")["estimated_profit"])

    with col2:
        st.markdown("### 危険度別件数")
        st.bar_chart(df_view["risk_level"].value_counts())

with tabs[1]:
    st.subheader("🔥 今すぐ返信")
    st.caption("今すぐ対応すべき案件を選び、AI分析・返信生成・送信・営業温度更新まで行います。")

    if df_view.empty:
        st.info("表示できる案件がありません。")
    else:
        priority_sort_col = "opportunity_score" if "opportunity_score" in df_view.columns else "revenue_score"
        dashboard_df = df_view.sort_values(priority_sort_col, ascending=False).copy()

        st.divider()
        st.markdown("### 案件詳細")

        option_labels = {}
        for _, row in dashboard_df.iterrows():
            label = f"ID {int(row.get('id', 0))}｜{row.get('customer', '')}｜{row.get('subject', '')}"
            option_labels[label] = int(row.get("id", 0))

        selected_label = st.selectbox(
            "詳細を見る案件",
            list(option_labels.keys()),
            key="reply_lead_detail_select"
        )

        lead_id = option_labels[selected_label]
        lead = dashboard_df[dashboard_df["id"] == lead_id].iloc[0]

        safe_subject = str(lead.get("subject", "") or "").strip()
        if len(safe_subject) < 3:
            safe_subject = "案件のご確認"

        col_a, col_b = st.columns([2, 1])

        with col_a:
            st.markdown("#### 基本情報")
            st.write("顧客：", lead.get("customer", ""))
            st.write("件名：", safe_subject)
            st.write("分類：", lead.get("category", ""))
            st.write("ステージ：", lead.get("pipeline_stage", ""))
            st.write("受信日：", lead.get("email_date", ""))

            if pd.notna(lead.get("gmail_id", "")):
                gmail_url = f"https://mail.google.com/mail/u/0/#inbox/{lead.get('gmail_id', '')}"
                st.link_button("Gmailで元メールを開く", gmail_url)

            st.markdown("#### メール本文")
            st.text_area(
                "本文",
                str(lead.get("content", "") or ""),
                height=300,
                key=f"reply_content_{lead_id}"
            )

        with col_b:
            st.markdown("#### AI分析")

            try:
                try:
                    st.text(build_openai_advice(lead))
                except Exception as openai_error:
                    st.caption(f"OpenAI未使用: {openai_error}")
                    advice = build_ai_advice(lead)
                    st.text(format_ai_advice(advice))
            except Exception as e:
                st.warning(f"AI分析を生成できませんでした: {e}")
            st.metric("推定利益", money(lead.get("estimated_profit", 0)))
            st.metric("回収可能利益", money(lead.get("recoverable_profit", 0)))
        st.metric("実回収利益", money(lead.get("actual_revenue", 0)))

        actual_revenue_input = st.number_input(
            "実際に回収した金額",
            min_value=0,
            value=int(lead.get("actual_revenue", 0) or 0),
            step=1000,
            key=f"actual_revenue_{lead_id}"
        )

        if st.button("実回収利益を保存", key=f"save_actual_revenue_{lead_id}"):
            update_actual_revenue(lead_id, actual_revenue_input)
            save_action_log(int(lead_id), "actual_revenue_updated", f"実回収利益: {actual_revenue_input}", "done")
            st.success("実回収利益を保存しました。")
            # AI学習UIは app_dev.py に分離済み

            st.metric("Revenue Score", int(lead.get("revenue_score", 0) or 0))
            st.metric("Opportunity Score", int(lead.get("opportunity_score", 0) or 0))
            st.write("危険度：", lead.get("risk_level", ""))
            st.write("放置日数：", f"{int(lead.get('neglected_days', 0) or 0)}日")
            st.write("次の行動：", lead.get("next_action", ""))
            st.info(str(lead.get("reason", "") or "判定理由なし"))

        st.divider()
        st.markdown("### メモ / フォロー")

        memo = lead.get("memo", "") if pd.notna(lead.get("memo", "")) else ""
        memo_text = st.text_area(
            "案件メモ",
            str(memo),
            height=120,
            key=f"reply_memo_{lead_id}"
        )

        if st.button("メモを保存", key=f"reply_save_memo_{lead_id}"):
            update_lead_memo(int(lead_id), memo_text)
            st.success("メモを保存しました。")

        history_text = build_followup_history(lead)

        default_follow = generate_follow_message(
            lead.get("customer", ""),
            safe_subject,
            lead.get("content", ""),
            category=lead.get("category", ""),
            history=history_text
        )

        follow_body = st.text_area(
            "フォロー文",
            default_follow,
            height=240,
            key=f"reply_follow_{lead_id}"
        )

        customer_raw = str(lead.get("customer", "") or "")
        email_match = re.search(r"<([^>]+)>", customer_raw)
        default_to_email = email_match.group(1).strip() if email_match else customer_raw.strip()

        to_email = st.text_input(
            "送信先メールアドレス",
            default_to_email,
            key=f"reply_to_{lead_id}"
        )

        col_save, col_send, col_status = st.columns(3)

        with col_save:
            if st.button("フォロー文を保存", key=f"reply_save_follow_{lead_id}"):
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

        with col_send:
            if st.button("Gmail送信", key=f"reply_send_follow_{lead_id}"):
                try:
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

                    update_lead_status(int(lead_id), "対応済み")
                    st.success(f"Gmail送信完了: {gmail_result_id}")

                except Exception as e:
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
                    st.error(f"Gmail送信エラー: {e}")

        with col_status:
            temp_options = ["未判定", "決裁済み", "発注予定", "稟議中", "検討中", "保留", "失注"]
            current_temp = str(lead.get("sales_temperature", "未判定") or "未判定")
            if current_temp not in temp_options:
                current_temp = "未判定"

            new_temp = st.selectbox(
                "営業温度",
                temp_options,
                index=temp_options.index(current_temp),
                key=f"reply_sales_temp_{lead_id}"
            )

            if st.button("営業温度を保存", key=f"reply_save_sales_temp_{lead_id}"):
                conn = sqlite3.connect(DB)
                c = conn.cursor()
                c.execute("UPDATE profit_leads SET sales_temperature=? WHERE id=?", (new_temp, int(lead_id)))
                conn.commit()
                conn.close()
                save_action_log(int(lead_id), "sales_temperature_update", f"営業温度: {new_temp}", "done")
                st.success("営業温度を保存しました。")

            new_status = st.selectbox(
                "ステータス変更",
                ["未対応", "対応済み", "保留", "返信あり"],
                index=["未対応", "対応済み", "保留"].index(str(lead.get("status", "未対応"))) if str(lead.get("status", "未対応")) in ["未対応", "対応済み", "保留"] else 0,
                key=f"reply_status_{lead_id}"
            )
            if st.button("ステータス保存", key=f"reply_save_status_{lead_id}"):
                update_lead_status(int(lead_id), new_status)
                save_action_log(int(lead_id), "status_update", f"{new_status}に変更", "done")
                st.success("ステータスを保存しました。")

if False:
    st.subheader("回収案件")
    if df_view.empty:
        st.info("表示できる案件がありません。")
    else:
        for _, row in df_view.iterrows():
            lead_card(row)

if False:
    st.subheader("メール詳細")

    lead_id = st.selectbox("確認する案件", df_view["id"].tolist(), key="mail_detail")
    lead = df_view[df_view["id"] == lead_id].iloc[0]

    col_a, col_b = st.columns([2, 1])

    with col_a:
        st.markdown("### 基本情報")
        st.write(f"顧客：{lead['customer']}")
        st.write(f"件名：{lead['subject']}")
        st.write(f"受信日：{lead.get('email_date', '')}")

        if pd.notna(lead.get("gmail_id", "")):
            gmail_url = f"https://mail.google.com/mail/u/0/#inbox/{lead['gmail_id']}"
            st.link_button("Gmailで元メールを開く", gmail_url)

        st.markdown("### メール本文")
        st.text_area("本文", lead["content"], height=360)

    with col_b:
        st.markdown("### AI分析")

        use_openai = st.checkbox(
            "OpenAI案件参謀を使う",
            value=True,
            key=f"use_openai_detail_{lead_id}"
        )

        if use_openai:
            if st.button("AI分析を実行", key=f"run_openai_advice_{lead_id}"):
                with st.spinner("AIが案件を分析しています..."):
                    try:
                        st.text(build_openai_advice(lead))
                    except Exception as openai_error:
                        st.caption(f"OpenAI未使用: {openai_error}")
                        try:
                            advice = build_ai_advice(lead)
                            st.text(format_ai_advice(advice))
                        except Exception as e:
                            st.warning(f"AI分析を生成できませんでした: {e}")
            else:
                st.info("AI分析を実行ボタンを押すと、OpenAI案件参謀がこの案件を分析します。")
        else:
            try:
                advice = build_ai_advice(lead)
                st.text(format_ai_advice(advice))
            except Exception as e:
                st.warning(f"AI分析を生成できませんでした: {e}")
        st.metric("推定利益", money(lead["estimated_profit"]))
        st.metric("回収可能利益", money(lead.get("recoverable_profit", 0)))
        st.metric("Revenue Score", int(lead["revenue_score"]))
        st.metric("Opportunity Score", int(lead.get("opportunity_score", 0)))
        if int(lead.get("hot_lead", 0) or 0) == 1:
            st.warning("HOT LEAD：優先対応候補")
        st.write(f"危険度：{lead['risk_level']}")
        st.write(f"放置日数：{int(lead['neglected_days'])}日")
        st.write(f"次の行動：{lead['next_action']}")
        st.info(lead["reason"] if pd.notna(lead["reason"]) else "判定理由なし")

        st.markdown("### メモ")
        memo = lead["memo"] if "memo" in lead and pd.notna(lead["memo"]) else ""
        memo_text = st.text_area("案件メモ", memo, height=140)

        if st.button("メモを保存"):
            update_lead_memo(int(lead_id), memo_text)
            st.success("保存しました。再読み込みしてください。")

        st.divider()
        st.markdown("### フォロー文")

        safe_subject = str(lead.get("subject", "") or "").strip()
        if len(safe_subject) < 3:
            safe_subject = "契約のご確認"

        history_text = build_followup_history(lead)

        default_follow = generate_follow_message(
            lead["customer"],
            safe_subject,
            lead["content"],
            category=lead.get("category", ""),
            history=history_text
        )

        follow_body = st.text_area(
            "編集して保存・送信できます",
            default_follow,
            height=240,
            key=f"detail_follow_{lead_id}"
        )

        customer_raw = str(lead.get("customer", "") or "")
        email_match = re.search(r"<([^>]+)>", customer_raw)
        default_to_email = email_match.group(1).strip() if email_match else customer_raw.strip()

        to_email = st.text_input(
            "送信先メールアドレス",
            default_to_email,
            key=f"detail_to_{lead_id}"
        )

        col_save, col_send = st.columns(2)

        with col_save:
            if st.button("フォロー文を保存", key=f"save_follow_{lead_id}"):
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

        with col_send:
            if st.button("Gmail送信", key=f"send_follow_{lead_id}"):
                try:
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

                    update_lead_status(int(lead_id), "対応済み")
                    st.success(f"Gmail送信完了: {gmail_result_id}")

                except Exception as e:
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
                    st.error(f"Gmail送信エラー: {e}")


with tabs[4]:
    st.subheader("⚙️ 設定")
    render_gmail_oauth_settings()
    # AI分析履歴 は app_dev.py に分離済み

    st.markdown("### Gmail解析")
    st.caption("Gmailから利益候補を検出します。")

    analysis_limit = st.selectbox("Gmail解析件数", [5, 10, 20, 30, 50], index=2, key="settings_analysis_limit_restored")

    if st.button("Gmailを解析する", key="settings_gmail_scan_restored"):
        try:
            emails = fetch_recent_emails(limit=analysis_limit)
            count = 0
            for email in emails:
                if save_email_as_lead(email):
                    count += 1
            st.success(f"{count}件の利益候補を検出しました。")
        except Exception as e:
            st.error(f"Gmail解析エラー: {e}")

    if st.button("解析データをリセット", key="settings_reset_data_restored"):
        reset_database()
        st.success("解析データをリセットしました。")

    df = get_leads()

    if df.empty:
        st.markdown('<div class="main-title">Profit Radar</div>', unsafe_allow_html=True)
        st.markdown('<div class="sub-title">左の「Gmailを解析する」から利益候補を検出してください。</div>', unsafe_allow_html=True)
        st.stop()

    st.divider()

    st.markdown("### CSV出力")
    st.caption("現在表示中の案件一覧をCSVで保存します。")

    try:
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

