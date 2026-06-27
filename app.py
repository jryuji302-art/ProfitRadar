import html
import re
import sqlite3
from db_adapter import patch_sqlite_for_database_url
patch_sqlite_for_database_url(sqlite3)
import hashlib
from datetime import datetime
from email.utils import parsedate_to_datetime

import pandas as pd
import altair as alt
from revenue_engine import analyze_email, generate_follow_message as generate_revenue_follow_message
import streamlit as st
from app_logger import get_logger
from error_handler import handle_error, log_info, log_warning, log_error
from utils.formatters import safe as fmt_safe, safe_text as fmt_safe_text, money as fmt_money, money_or_unknown as fmt_money_or_unknown, clean_reply_body as fmt_clean_reply_body
from services import db_service
from services import schema_service

from gmail_reader import fetch_recent_emails
from lead_service import save_email_as_lead
from action_engine import send_gmail_reply, save_action
from reply_ui import render_reply_screen
from ai_home_brief import render_ai_executive_brief
from ceo_daily_mission import render_ceo_daily_mission
from ai_sales_forecast import render_ai_sales_forecast
from ai_roi_engine import render_roi_dashboard
from ai_ceo_judgement import render_ceo_judgement_card
from profit_estimator import estimate_profit_from_text
from profit_ai_analyst import build_profit_ai_analysis, ensure_profit_ai_cache_table
from ai_advisor_engine import build_ai_dashboard_advice, format_ai_dashboard_advice
from openai_sales_engine import build_sales_ai, fallback_sales_ai
from openai_advisor_engine import build_openai_advice
from openai_followup_engine import generate_followup as generate_openai_followup
from reply_detector import detect_replies
from modules.home_dashboard_ui import render_home_dashboard
from modules.auth_ui import ensure_auth_tables as auth_ensure_auth_tables, render_auth_gate as auth_render_auth_gate, render_logout_sidebar as auth_render_logout_sidebar
from modules.gmail_ui import render_gmail_tab
from modules.results_ui import render_results_tab
from modules.customer_ui import prepare_customer_view, render_customer_summary, render_customer_selector, render_customer_panel, render_customer_related_and_timeline

DB = "profit_radar.db"
logger = get_logger("profit_radar.app")


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
        profit_basis TEXT,
        profit_confidence INTEGER DEFAULT 0,
        unit_price_detected INTEGER DEFAULT 0,
        people_detected REAL DEFAULT 1,
        days_detected REAL DEFAULT 1,
            note TEXT,
            created_at TEXT
        )
    """)

    c.execute("""
        INSERT INTO ai_learning
        (lead_id, customer, subject, ai_decision, result, actual_revenue, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        int(lead_id or 0),
        str(customer or ""),
        str(subject or ""),
        str(ai_decision or ""),
        str(result or ""),
        int(actual_revenue or 0),
        str(note or ""),
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

def get_revenue_chart_data():
    return db_service.get_revenue_chart_data(DB)


def get_customer_revenue_summary(customer):
    return db_service.get_customer_revenue_summary(DB, customer)


def update_actual_revenue(lead_id, actual_revenue, user_id=None, company_id=None):
    return db_service.update_actual_revenue(
        DB,
        lead_id,
        actual_revenue,
        user_id=user_id,
        company_id=company_id
    )


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
        "AI",
        "AI",
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
    return db_service.get_ai_advice_logs(DB, limit)


def init_db():
    return schema_service.init_db(DB)


def repair_profit_leads_schema():
    return schema_service.repair_profit_leads_schema(DB)


def ensure_columns():
    return schema_service.ensure_columns(DB)


def get_leads(user_id=None, company_id=None):
    return db_service.get_leads(
        DB,
        user_id=user_id,
        company_id=company_id,
        score_func=calc_revenue_score
    )


def ensure_reply_detection_columns():
    return schema_service.ensure_reply_detection_columns(DB)


def get_customer_timeline(lead_ids):
    return db_service.get_customer_timeline(DB, lead_ids)


def get_actions(user_id=None, company_id=None):
    return db_service.get_actions(
        DB,
        user_id=user_id,
        company_id=company_id
    )


def reset_database(user_id=None, company_id=None):
    return db_service.reset_database(
        DB,
        user_id=user_id,
        company_id=company_id
    )


def update_lead_status(lead_id, status, user_id=None, company_id=None):
    return db_service.update_lead_status(
        DB,
        lead_id,
        status,
        user_id=user_id,
        company_id=company_id
    )


def update_lead_memo(lead_id, memo, user_id=None, company_id=None):
    return db_service.update_lead_memo(
        DB,
        lead_id,
        memo,
        user_id=user_id,
        company_id=company_id
    )


def save_action_log(lead_id, action_type, message, result, user_id=None, company_id=None):
    return db_service.save_action_log(
        DB,
        lead_id,
        action_type,
        message,
        result,
        user_id=user_id,
        company_id=company_id
    )


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
    history_parts.append(f"案件金額候補: {clean_history_value(lead.get('estimated_profit', 0))}")
    history_parts.append(f"回収期待値: {clean_history_value(lead.get('recoverable_profit', 0))}")
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





def inject_profit_radar_ui_css():
    st.markdown("""
    <style>
    .block-container {
        max-width: 1180px;
        padding-top: 2rem;
        padding-bottom: 4rem;
    }

    section[data-testid="stSidebar"] {
        background: #f3f6f8;
        border-right: 1px solid #e5e7eb;
    }

    section[data-testid="stSidebar"] * {
        font-size: 14px !important;
    }

    h1 {
        font-size: 2.2rem !important;
        letter-spacing: -0.03em;
        margin-bottom: .4rem !important;
    }

    h2 {
        font-size: 1.65rem !important;
        margin-top: 1.4rem !important;
    }

    h3 {
        font-size: 1.25rem !important;
        margin-top: 1.1rem !important;
    }

    [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 10px 25px rgba(15, 23, 42, .04);
    }

    [data-testid="stMetricLabel"] {
        color: #64748b;
        font-size: 13px !important;
    }

    [data-testid="stMetricValue"] {
        font-size: 1.7rem !important;
        line-height: 1.25 !important;
        white-space: normal !important;
        overflow-wrap: anywhere !important;
    }

    div[data-testid="stExpander"] {
        border-radius: 14px !important;
        overflow: hidden;
    }

    textarea {
        font-size: 15px !important;
        line-height: 1.7 !important;
        border-radius: 14px !important;
    }

    button {
        border-radius: 12px !important;
        font-weight: 700 !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        border-bottom: 1px solid #e5e7eb;
    }

    .stTabs [data-baseweb="tab"] {
        padding: 12px 16px;
        border-radius: 14px 14px 0 0;
        font-weight: 800;
    }

    .stAlert {
        border-radius: 14px !important;
    }

    @media (max-width: 768px) {
        .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
        }

        h1 {
            font-size: 1.8rem !important;
        }

        [data-testid="stMetricValue"] {
            font-size: 1.35rem !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)



def money_or_unknown(value):
    return fmt_money_or_unknown(value)


def safe_text(value, default=""):
    return fmt_safe_text(value, default)


def extract_recommended_reply_from_ai(text):
    text = safe_text(text, "")
    if not text:
        return ""

    markers = [
        "推奨返信文:",
        "推奨返信文：",
        "返信文:",
        "返信文：",
    ]

    for marker in markers:
        if marker in text:
            return text.split(marker, 1)[1].strip()

    return text.strip()


def build_reply_ai_summary(reply_body, last_sent_body="", estimated_profit=0, recoverable_profit=0):
    body = clean_reply_body(reply_body)
    sent = safe_text(last_sent_body, "")

    body_l = body.lower()

    positive_words = [
        "お願いします", "お願い致します", "進めてください", "承知しました",
        "承知いたしました", "問題ありません", "大丈夫です", "それで進めて",
        "よろしくお願いします", "ok", "OK"
    ]

    question_words = [
        "どうでしょう", "どうですか", "確認", "質問", "教えて", "可能ですか",
        "いつ", "どこ", "いくら", "何名", "日程"
    ]

    pending_words = [
        "検討", "確認します", "社内確認", "また連絡", "保留", "一旦"
    ]

    negative_words = [
        "難しい", "キャンセル", "見送り", "不要", "今回はなし", "厳しい"
    ]

    if any(w in body for w in positive_words):
        judgement = "成約目前"
        reason = "相手が進行に前向きで、否定表現がありません。条件了承または進行承認に近い返信です。"
        risk = "日程・場所・請求条件などの確定項目が未確認の場合、後で認識ズレが起きる可能性があります。"
        action = "日程・場所・人数・単価・請求条件を確認し、確定連絡へ進めてください。"
    elif any(w in body for w in question_words):
        judgement = "要回答"
        reason = "相手が確認・質問を返しており、こちらの回答待ち状態です。"
        risk = "回答が遅れると商談温度が下がり、案件が止まる可能性があります。"
        action = "質問に明確に回答し、次の確定条件を提示してください。"
    elif any(w in body for w in pending_words):
        judgement = "検討中"
        reason = "相手は拒否していませんが、まだ意思決定前です。"
        risk = "放置すると自然消滅する可能性があります。"
        action = "3〜7日後に短く確認フォローを送ってください。"
    elif any(w in body for w in negative_words):
        judgement = "失注リスク高"
        reason = "否定・見送りに近い表現が含まれています。"
        risk = "無理に追うと関係悪化や工数過多になります。"
        action = "条件変更の余地だけ確認し、反応が薄ければ優先度を下げてください。"
    else:
        judgement = "要確認"
        reason = "返信内容だけでは成約確度を断定できません。"
        risk = "判断が曖昧なまま放置すると機会損失になります。"
        action = "相手の意図を確認し、次に進める条件を1つだけ聞いてください。"

    profit = int(recoverable_profit or estimated_profit or 0)

    return f"""
**判断:** {judgement}

**理由:** {reason}

**リスク:** {risk}

**推奨アクション:** {action}

**利益予測:** {profit:,}円
"""




def parse_sales_ai_text(text):
    text = safe_text(text, "")

    def pick(*labels):
        import re
        for label in labels:
            patterns = [
                rf"{label}[:：]\s*(.*?)(?=\n\S+[:：]|$)",
                rf"\*\*{label}[:：]?\*\*\s*(.*?)(?=\n\*\*|$)",
            ]
            for pat in patterns:
                m = re.search(pat, text, re.S)
                if m:
                    return m.group(1).strip()
        return ""

    return {
        "state": pick("案件状態", "判断") or "要確認",
        "probability": pick("成約確率") or "-",
        "profit": pick("想定利益", "利益予測") or "-",
        "todo": pick("今やること", "推奨アクション", "推奨") or "次に進める条件を確認",
        "risk": pick("放置リスク", "リスク") or "放置による機会損失",
        "reply": pick("推奨返信文", "返信文") or "",
    }




def render_ceo_sales_card(advice_text, fallback_profit=0):
    data = parse_sales_ai_text(advice_text)

    state = safe_text(data.get("state", ""), "要確認")
    probability = safe_text(data.get("probability", ""), "-")
    profit = safe_text(data.get("profit", ""), "") or money(fallback_profit)
    todo = safe_text(data.get("todo", ""), "次に進める条件を確認")
    risk = safe_text(data.get("risk", ""), "要注意")

    st.markdown("### AI案件参謀")

    st.markdown(f"""
    <div style="border:1px solid #e5e7eb; border-radius:16px; padding:16px; background:#fff; margin:10px 0;">
        <div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:10px;">
            <div style="background:#f8fafc; border-radius:12px; padding:12px;">
                <div style="font-size:13px; color:#64748b;">案件状態</div>
                <div style="font-size:20px; font-weight:800; color:#0f172a; word-break:break-word;">{safe(state)}</div>
            </div>
            <div style="background:#f8fafc; border-radius:12px; padding:12px;">
                <div style="font-size:13px; color:#64748b;">成約確率</div>
                <div style="font-size:20px; font-weight:800; color:#0f172a;">{safe(probability)}</div>
            </div>
            <div style="background:#f8fafc; border-radius:12px; padding:12px;">
                <div style="font-size:13px; color:#64748b;">想定利益</div>
                <div style="font-size:20px; font-weight:800; color:#0f172a;">{safe(profit)}</div>
            </div>
            <div style="background:#f8fafc; border-radius:12px; padding:12px;">
                <div style="font-size:13px; color:#64748b;">リスク</div>
                <div style="font-size:20px; font-weight:800; color:#0f172a;">{safe(risk[:18])}</div>
            </div>
        </div>
        <div style="margin-top:12px; background:#ecfdf5; border:1px solid #bbf7d0; border-radius:12px; padding:12px;">
            <div style="font-size:13px; color:#047857; font-weight:700;">今やること</div>
            <div style="font-size:16px; color:#064e3b; font-weight:700; line-height:1.6;">{safe(todo)}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_ai_advisor_card(advice_text):
    text = safe_text(advice_text, "")

    def pick(label):
        import re
        patterns = [
            rf"\*\*{label}:\*\*(.*?)(?=\n\*\*|$)",
            rf"{label}[:：](.*?)(?=\n|$)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.S)
            if m:
                return m.group(1).strip()
        return ""

    judgement = pick("判断") or "要確認"
    reason = pick("理由") or "返信内容と案件情報を確認してください。"
    risk = pick("リスク") or "放置による機会損失。"
    action = pick("推奨アクション") or pick("推奨") or "次の返信内容を確認してください。"

    c1, c2 = st.columns(2)
    c1.metric("AI判断", judgement[:20])
    c2.metric("次アクション", action[:20])

    st.markdown("**理由**")
    st.info(reason)

    st.markdown("**リスク**")
    st.warning(risk)

    st.markdown("**推奨**")
    st.success(action)


def clean_reply_body(body):
    return fmt_clean_reply_body(body)


def safe(v):
    return fmt_safe(v)


def money(v):
    return fmt_money(v)


def inject_css():
    st.markdown("""
<style>
.block-container {
    padding-top: 2.4rem;
    padding-left: 3.6rem;
    padding-right: 3.6rem;
    max-width: 1320px;
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
        <div class="lead-score">期待度 {int(row.get("revenue_score", 0) or 0)} / Opp {int(row.get("opportunity_score", 0) or 0)}</div>
    </div>
    """, unsafe_allow_html=True)


# =========================
# App
# =========================





init_db()
ensure_columns()
auth_ensure_auth_tables(DB)
auth_render_auth_gate(DB)
auth_render_logout_sidebar()

# Render旧DB対策：profit_actions不足カラム補修
def repair_profit_actions_schema():
    return schema_service.repair_profit_actions_schema(DB)


repair_profit_actions_schema()

inject_css()







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

with st.sidebar.expander("詳細フィルタ", expanded=False):
    selected_status = st.selectbox("ステータス", status_options)
    selected_risk = st.selectbox("危険度", risk_options)
    selected_pipeline = st.selectbox("案件ステージ", pipeline_options)
    selected_category = st.selectbox("分類", category_options)

# データ取得：サイドバー整理時のdf未定義対策
try:
    try:
        ensure_profit_ai_cache_table()
    except Exception as cache_e:
        log_warning(f"AI利益分析キャッシュ初期化エラー: {cache_e}")
        st.warning("AI利益分析キャッシュの初期化に失敗しました。")

    df = get_leads(
        user_id=st.session_state.get("user_id"),
        company_id=st.session_state.get("company_id")
    )
except Exception as e:
    handle_error(e, "案件データの取得に失敗しました。時間をおいて再読み込みしてください。")
    df = pd.DataFrame()

if "revenue_score" not in df.columns:
    df["revenue_score"] = 0

df["revenue_score"] = df["revenue_score"].fillna(0)
max_score_value = df["revenue_score"].max()

if pd.isna(max_score_value):
    max_score_value = 0

max_score = int(max_score_value)

max_profit_value = df["estimated_profit"].fillna(0).max() if "estimated_profit" in df.columns else 0
max_profit = int(max_profit_value) if not pd.isna(max_profit_value) else 0

with st.sidebar.expander("詳細条件", expanded=False):
    if max_score <= 0:
        min_score = 0
        st.caption("期待度: データなし")
    else:
        min_score = st.slider("期待度下限", 0, max_score, 0)

    if max_profit <= 0:
        min_profit = 0
        st.caption("案件金額候補: データなし")
    else:
        min_profit = st.slider("利益下限", 0, max_profit, 0)

    only_open = st.checkbox("未対応のみ", value=False)
    only_hot = st.checkbox("優先案件のみ", value=False)

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

# Profit Estimator v1：金額根拠ベースで過大評価を抑制
try:
    if not df_view.empty:
        def _estimate_row_profit(row):
            est = estimate_profit_from_text(
                subject=row.get("subject", ""),
                content=row.get("content", ""),
                category=row.get("category", ""),
                actual_revenue=row.get("actual_revenue", 0)
            )
            return est

        _profit_estimates = df_view.apply(_estimate_row_profit, axis=1)
        df_view["profit_basis"] = _profit_estimates.apply(lambda x: x.get("basis", ""))
        df_view["profit_confidence"] = _profit_estimates.apply(lambda x: int(x.get("confidence", 0) or 0))
        df_view["unit_price_detected"] = _profit_estimates.apply(lambda x: int(x.get("unit_price", 0) or 0))
        df_view["people_detected"] = _profit_estimates.apply(lambda x: x.get("people", 1))
        df_view["days_detected"] = _profit_estimates.apply(lambda x: x.get("days", 1))

        # 既存推定が明らかに過大な場合だけ、控えめ推定で補正
        df_view["estimated_profit_v1"] = _profit_estimates.apply(lambda x: int(x.get("estimated_profit", 0) or 0))
        df_view["recoverable_profit_v1"] = _profit_estimates.apply(lambda x: int(x.get("recoverable_profit", 0) or 0))

        over_mask = (
            (df_view["estimated_profit_v1"] > 0) &
            (
                (df_view["estimated_profit"].fillna(0) <= 0) |
                (df_view["estimated_profit"].fillna(0) > df_view["estimated_profit_v1"] * 3)
            )
        )

        df_view.loc[over_mask, "estimated_profit"] = df_view.loc[over_mask, "estimated_profit_v1"]
        df_view.loc[over_mask, "recoverable_profit"] = df_view.loc[over_mask, "recoverable_profit_v1"]
except Exception as e:
    log_warning(f"利益推定補正エラー: {e}")
    st.warning("利益推定補正を実行できませんでした。")


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
        <div class="hero-label">今日の確認対象</div>
        <div class="hero-value">{open_count}件</div>
        <div class="hero-sub">見込み {money(recoverable_total)} / 放置注意 {danger_count}件</div>
    </div>
</div>
""", unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
with c1:
    metric_card("今日見る利益", money(recoverable_total), "対応すべき見込み")
with c2:
    metric_card("未対応", f"{open_count}件", "返信・確認が必要")
with c3:
    metric_card("放置注意", f"{danger_count}件", "放置注意")

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
            handle_error(e, "OAuth設定に問題があります。環境変数を確認してください。")
            st.info("Render環境変数 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI を確認してください。")

dev_mode = False

tab_names = [
    "今日の利益",
    "今すぐ返信",
    "顧客",
    "実績",
    "Gmail接続",
]

tabs = st.tabs(tab_names)


priority_sort_col = "opportunity_score" if "opportunity_score" in df_view.columns else "revenue_score"
priority_df = df_view[df_view["status"] == "未対応"].sort_values(priority_sort_col, ascending=False).head(5)

reply_ui_deps = {
    "money": money,
    "money_or_unknown": money_or_unknown,
    "safe_text": safe_text,
    "clean_customer_name": lambda v: (str(v or "").split("<")[0].strip() or "不明顧客"),
    "build_sales_ai": build_sales_ai,
    "fallback_sales_ai": fallback_sales_ai,
    "render_ceo_sales_card": render_ceo_sales_card,
    "extract_recommended_reply_from_ai": extract_recommended_reply_from_ai,
    "validate_send_body": validate_send_body,
    "send_gmail_reply": send_gmail_reply,
    "save_action": save_action,
    "save_action_log": save_action_log,
    "update_lead_status": update_lead_status,
    "update_actual_revenue": update_actual_revenue,
    "build_profit_ai_analysis": build_profit_ai_analysis,
    "save_ai_learning": save_ai_learning,
}



with tabs[0]:
    render_home_dashboard(
        df_view=df_view,
        money=money,
        money_or_unknown=money_or_unknown,
        safe_text=safe_text,
        render_ceo_judgement_card=render_ceo_judgement_card,
        render_ceo_daily_mission=render_ceo_daily_mission,
        render_ai_executive_brief=render_ai_executive_brief,
        render_ai_sales_forecast=render_ai_sales_forecast,
        render_roi_dashboard=render_roi_dashboard,
        fetch_recent_emails=fetch_recent_emails,
        save_email_as_lead=save_email_as_lead,
        update_actual_revenue=update_actual_revenue,
        update_lead_status=update_lead_status,
        save_action_log=save_action_log,
        generate_openai_followup=generate_openai_followup,
        save_action=save_action,
        send_gmail_reply=send_gmail_reply,
        validate_send_body=validate_send_body,
    )


with tabs[1]:
    st.subheader("今すぐ返信")
    st.caption("AIが選んだ案件を、返信・保存・送信まで処理します。")

    if df_view.empty:
        st.info("対応できる案件がありません。")
    else:
        reply_df = df_view.copy()

        for col in [
            "id", "customer", "subject", "status", "recoverable_profit",
            "estimated_profit", "actual_revenue", "neglected_days",
            "opportunity_score", "revenue_score", "content", "memo"
        ]:
            if col not in reply_df.columns:
                reply_df[col] = ""

        for col in [
            "recoverable_profit", "estimated_profit", "actual_revenue",
            "neglected_days", "opportunity_score", "revenue_score"
        ]:
            reply_df[col] = pd.to_numeric(reply_df[col], errors="coerce").fillna(0)

        work_df = reply_df[
            ~reply_df["status"].astype(str).isin(["対応済み", "成約", "失注", "除外", "完了"])
        ].copy()

        if work_df.empty:
            st.success("今すぐ返信が必要な案件はありません。")
        else:
            sort_col = "opportunity_score" if "opportunity_score" in work_df.columns else "revenue_score"
            work_df = work_df.sort_values(
                ["recoverable_profit", "neglected_days", sort_col],
                ascending=False
            )

            lead_options = []
            lead_map = {}

            selected_from_home = st.session_state.get("home_selected_lead_id")

            default_index = 0
            for i, (_, r) in enumerate(work_df.head(50).iterrows()):
                lead_id_v = int(r.get("id", 0) or 0)
                label = (
                    f"#{lead_id_v}｜{safe(r.get('customer', '不明顧客'))}｜"
                    f"{safe(r.get('status', ''))}｜"
                    f"{money(r.get('recoverable_profit', 0))}｜"
                    f"{safe(r.get('subject', '件名なし'))}"
                )
                lead_options.append(label)
                lead_map[label] = lead_id_v

                if selected_from_home and int(selected_from_home) == lead_id_v:
                    default_index = i

            selected_label = st.selectbox(
                "対応する案件",
                lead_options,
                index=default_index,
                key="reply_tab_selected_lead"
            )

            selected_lead_id = lead_map[selected_label]
            selected_rows = reply_df[reply_df["id"].astype(int) == int(selected_lead_id)]

            if selected_rows.empty:
                st.warning("選択した案件が見つかりません。")
            else:
                lead_row = selected_rows.iloc[0]

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("状態", safe(lead_row.get("status", "")))
                c2.metric("回収期待値", money(lead_row.get("recoverable_profit", 0)))
                c3.metric("案件金額", money(lead_row.get("estimated_profit", 0)))
                c4.metric("放置", f"{int(lead_row.get('neglected_days', 0) or 0)}日")

                st.divider()

                render_reply_screen(
                    lead_row,
                    context=f"reply_tab_{selected_lead_id}",
                    deps=reply_ui_deps
                )


with tabs[2]:
    st.subheader("顧客")
    st.caption("顧客を選び、1つの統合画面で売上・対応・状態・履歴を管理します。")

    if df_view.empty:
        st.info("顧客データはありません。")
    else:
        customer_view = prepare_customer_view(df_view)
        score_col = "opportunity_score" if "opportunity_score" in customer_view.columns else "revenue_score"
        customer_summary = render_customer_summary(customer_view, money)

        lead_row, lead_id_v, selected_customer = render_customer_selector(
            customer_view=customer_view,
            customer_summary=customer_summary,
            score_col=score_col,
            money=money,
        )

        if lead_row is not None:
            render_customer_panel(
                lead_row=lead_row,
                lead_id_v=lead_id_v,
                selected_customer=selected_customer,
                money=money,
                safe=safe,
                render_reply_screen=render_reply_screen,
                reply_ui_deps=reply_ui_deps,
                update_lead_memo=update_lead_memo,
            )

            render_customer_related_and_timeline(
                customer_view=customer_view,
                selected_customer=selected_customer,
                get_customer_timeline=get_customer_timeline,
                safe=safe,
                safe_text=safe_text,
                money=money,
                clean_reply_body=clean_reply_body,
                log_warning=log_warning,
            )


with tabs[3]:
    render_results_tab(
        get_revenue_chart_data=get_revenue_chart_data,
        money=money,
        safe=safe,
    )

with tabs[4]:
    st.subheader("Gmail接続")
    render_gmail_tab(
        db_path=DB,
        safe=safe,
        render_gmail_oauth_settings=render_gmail_oauth_settings,
        fetch_recent_emails=fetch_recent_emails,
        save_email_as_lead=save_email_as_lead,
        detect_replies=detect_replies,
        ensure_reply_detection_columns=ensure_reply_detection_columns,
    )

