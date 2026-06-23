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

from gmail_reader import fetch_recent_emails
from lead_service import save_email_as_lead
from action_engine import send_gmail_reply, save_action
from ai_advisor_engine import build_ai_dashboard_advice, format_ai_dashboard_advice
from openai_sales_engine import build_sales_ai, fallback_sales_ai
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

    # Render上の既存SQLiteに actual_revenue 列が無い場合の自動補修
    try:
        c.execute("ALTER TABLE profit_leads ADD COLUMN actual_revenue INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass

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





def ensure_reply_detection_columns():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    for sql in [
        "ALTER TABLE reply_detection_logs ADD COLUMN reply_body TEXT",
        "ALTER TABLE reply_detection_logs ADD COLUMN reply_date TEXT",
    ]:
        try:
            c.execute(sql)
            conn.commit()
        except Exception:
            pass

    conn.close()


def get_customer_timeline(lead_ids):
    ensure_reply_detection_columns()

    import sqlite3
    import pandas as pd

    conn = sqlite3.connect(DB)

    placeholders = ",".join(["?"] * len(lead_ids))

    actions = pd.read_sql_query(
        f"""
        SELECT
            a.lead_id,
            a.created_at AS event_time,
            a.action_type AS event_type,
            a.subject,
            a.body,
            a.message,
            l.estimated_profit,
            l.recoverable_profit,
            l.actual_revenue,
            l.status,
            l.pipeline_stage
        FROM profit_actions a
        LEFT JOIN profit_leads l ON a.lead_id = l.id
        WHERE a.lead_id IN ({placeholders})
        """,
        conn,
        params=lead_ids
    )

    replies = pd.read_sql_query(
        f"""
        SELECT
            r.lead_id,
            r.detected_at AS event_time,
            'reply' AS event_type,
            r.subject,
            r.reply_body AS body,
            r.from_email AS message,
            l.estimated_profit,
            l.recoverable_profit,
            l.actual_revenue,
            l.status,
            l.pipeline_stage
        FROM reply_detection_logs r
        LEFT JOIN profit_leads l ON r.lead_id = l.id
        WHERE r.lead_id IN ({placeholders})
        """,
        conn,
        params=lead_ids
    )

    conn.close()

    timeline = pd.concat(
        [actions, replies],
        ignore_index=True
    )

    if timeline.empty:
        return timeline

    # 表示価値が低い内部ログを除外
    if "event_type" in timeline.columns:
        timeline = timeline[
            ~timeline["event_type"].isin([
                "reply_detected",
                "status_update"
            ])
        ]

    # 本文・件名が両方ないものは除外
    timeline["body"] = timeline["body"].fillna("")
    timeline["message"] = timeline["message"].fillna("")
    timeline["subject"] = timeline["subject"].fillna("")

    timeline = timeline[
        (timeline["body"].astype(str).str.strip() != "") |
        (timeline["message"].astype(str).str.strip() != "") |
        (timeline["subject"].astype(str).str.strip() != "")
    ]

    # 重複削除
    timeline["_dedupe_key"] = (
        timeline["lead_id"].astype(str) + "|" +
        timeline["event_type"].astype(str) + "|" +
        timeline["subject"].astype(str) + "|" +
        timeline["body"].astype(str).str[:120]
    )

    timeline = timeline.drop_duplicates(
        subset=["_dedupe_key"],
        keep="last"
    ).drop(columns=["_dedupe_key"])

    timeline = timeline.sort_values(
        "event_time",
        ascending=True
    )

    return timeline


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
    history_parts.append(f"見込み利益: {clean_history_value(lead.get('estimated_profit', 0))}")
    history_parts.append(f"回収見込み: {clean_history_value(lead.get('recoverable_profit', 0))}")
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


def safe_text(value, default=""):
    if value is None:
        return default

    try:
        import pandas as pd
        if pd.isna(value):
            return default
    except Exception:
        pass

    value = str(value)

    if value.lower() == "nan":
        return default

    return value










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
    body = safe_text(body, "")
    if not body:
        return ""

    cut_patterns = [
        "\r\n\r\n2026年",
        "\n\n2026年",
        "\r\n2026年",
        "\n2026年",
        "\r\n>",
        "\n>",
        "On ",
        " wrote:",
    ]

    cleaned = body

    for p in cut_patterns:
        idx = cleaned.find(p)
        if idx > 0:
            cleaned = cleaned[:idx]
            break

    cleaned = cleaned.strip()

    lines = []
    for line in cleaned.splitlines():
        if line.strip().startswith(">"):
            continue
        lines.append(line)

    return "\n".join(lines).strip()


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
        st.caption("見込み利益: データなし")
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
            st.error(f"OAuth設定エラー: {e}")
            st.info("Render環境変数 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI を確認してください。")

dev_mode = False

tab_names = [
    "🏠 今日の利益",
    "🔥 要対応",
    "👥 顧客",
    "📈 実績",
    "⚙️ Gmail接続",
]

tabs = st.tabs(tab_names)


priority_sort_col = "opportunity_score" if "opportunity_score" in df_view.columns else "revenue_score"
priority_df = df_view[df_view["status"] == "未対応"].sort_values(priority_sort_col, ascending=False).head(5)

with tabs[0]:
    st.subheader("🏠 今日の利益")
    st.caption("今日見るべき利益状況と優先案件を確認します。詳細対応は「🔥 要対応」で行います。")

    if df_view.empty:
        st.info("表示できる案件がありません。")
    else:
        priority_sort_col = "opportunity_score" if "opportunity_score" in df_view.columns else "revenue_score"
        dashboard_df = df_view.sort_values(priority_sort_col, ascending=False).copy()

        st.markdown("### 優先案件")
        for _, row in dashboard_df.head(8).iterrows():
            lead_card(row)





with tabs[1]:
    st.subheader("🔥 要対応")
    st.caption("返信・フォローが必要な案件を確認し、AI文面を編集して送信します。")

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
            st.success("現在、要対応が必要な未対応はありません。")
        else:
            lead_options = []
            lead_map = {}

            for _, r in reply_df.head(20).iterrows():
                lead_id_v = int(r.get("id", 0) or 0)
                label = (
                    f"#{lead_id_v}｜{r.get('customer', '不明顧客')}｜"
                    f"{r.get('subject', '件名なし')}｜"
                    f"回収見込み {money(r.get('recoverable_profit', 0))}｜"
                    f"{int(r.get('neglected_days', 0) or 0)}日放置"
                )
                lead_options.append(label)
                lead_map[label] = lead_id_v

            selected_label = st.selectbox("返信する案件を選択", lead_options, key="hot_reply_select")
            lead_id = lead_map[selected_label]
            lead = reply_df[reply_df["id"] == lead_id].iloc[0]

            st.divider()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("回収見込み", money(lead.get("recoverable_profit", 0)))
            c2.metric("見込み利益", money(lead.get("estimated_profit", 0)))
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
            st.markdown("### AI判断")

            try:
                formatted_ai_advice = build_sales_ai(
                    customer=str(lead.get("customer", "")),
                    subject=str(lead.get("subject", "")),
                    lead_content=str(lead.get("content", "")),
                    last_sent_body="",
                    reply_body="",
                    memo=str(lead.get("memo", "")),
                    estimated_profit=int(lead.get("estimated_profit", 0) or 0),
                    recoverable_profit=int(lead.get("recoverable_profit", 0) or 0),
                    actual_revenue=int(lead.get("actual_revenue", 0) or 0),
                    mode="hot_reply"
                )
            except Exception as e:
                formatted_ai_advice = fallback_sales_ai(
                    reply_body=str(lead.get("content", "")),
                    estimated_profit=int(lead.get("estimated_profit", 0) or 0),
                    recoverable_profit=int(lead.get("recoverable_profit", 0) or 0)
                ) + f"\n\n補足: OpenAI未使用: {e}"

            render_ceo_sales_card(
                formatted_ai_advice,
                fallback_profit=int(lead.get("recoverable_profit", 0) or 0)
            )

            st.divider()
            st.markdown("### 送信文")

            safe_subject = str(lead.get("subject", "") or "").strip()
            if len(safe_subject) < 3:
                safe_subject = "ご確認のお願い"

            try:
                history_text = build_followup_history(lead)
            except Exception:
                history_text = ""

            try:
                ai_follow_advice = build_sales_ai(
                    customer=str(lead.get("customer", "")),
                    subject=safe_subject,
                    lead_content=str(lead.get("content", "")),
                    last_sent_body="",
                    reply_body="",
                    memo=str(lead.get("memo", "")),
                    estimated_profit=int(lead.get("estimated_profit", 0) or 0),
                    recoverable_profit=int(lead.get("recoverable_profit", 0) or 0),
                    actual_revenue=int(lead.get("actual_revenue", 0) or 0),
                    mode="followup"
                )

                default_follow = extract_recommended_reply_from_ai(ai_follow_advice)

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
                "AIが作成した文面。必要なら編集して送信してください。",
                default_follow,
                height=180,
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

            col_save, col_send = st.columns([1, 1])

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
                            status="saved",
                            user_id=st.session_state.get("user_id"),
                            company_id=st.session_state.get("company_id")
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
                            force_send=False,
                            user_id=st.session_state.get("user_id"),
                            company_id=st.session_state.get("company_id")
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
                            gmail_result_id=gmail_result_id,
                            user_id=st.session_state.get("user_id"),
                            company_id=st.session_state.get("company_id")
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
                                safety_errors=str(e),
                                user_id=st.session_state.get("user_id"),
                                company_id=st.session_state.get("company_id")
                            )
                        except Exception:
                            pass
                        st.error(f"Gmail送信エラー: {e}")



with tabs[2]:
    st.subheader("👥 顧客")

    customer_df = df_view.groupby("customer").agg(
        案件数=("id", "count"),
        累計見込み利益=("estimated_profit", "sum"),
        最大未対応日数=("neglected_days", "max"),
        平均期待=("revenue_score", "mean")
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
                <div class="lead-money">{money(row['累計見込み利益'])}</div>
                <div class="risk-mid">累計売上</div>
                <div class="lead-days">{int(row['最大未対応日数'])}日</div>
                <div class="lead-score">期待度 {int(row['平均期待'])}</div>
            </div>
            """, unsafe_allow_html=True)

        st.divider()
        st.markdown("### 顧客詳細")

        selected_customer = st.selectbox(
            "詳細を見る顧客",
            customer_df["customer"].tolist(),
            key="customer_detail_select"
        )

        customer_leads = df_view[df_view["customer"] == selected_customer].copy()

        try:
            customer_summary = get_customer_revenue_summary(selected_customer)

            open_count = len(
                customer_leads[customer_leads["status"] == "未対応"]
            ) if "status" in customer_leads.columns else 0

            c1, c2, c3 = st.columns(3)

            c1.metric(
                "累計売上",
                money(customer_summary.get("total_actual_revenue", 0))
            )

            c2.metric(
                "案件数",
                int(customer_summary.get("lead_count", 0) or 0)
            )

            c3.metric(
                "未対応",
                f"{open_count}件"
            )

        except Exception as e:
            st.warning(f"顧客収益サマリーを表示できませんでした: {e}")

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
                <div class="lead-score">期待度 {int(lead_row.get('revenue_score', 0) or 0)}</div>
            </div>
            """, unsafe_allow_html=True)

            with st.expander(f"本文・メモを見る｜案件ID {int(lead_row.get('id', 0))}"):
                st.write("件名：", lead_row.get("subject", ""))
                st.write("ステージ：", lead_row.get("pipeline_stage", ""))
                st.text_area("メール本文", str(lead_row.get("content", "") or ""), height=180, key=f"cust_body_{lead_row.get('id')}")
                memo_key = f"cust_memo_{lead_row.get('id')}"
                memo_value = st.text_area(
                    "メモ",
                    str(lead_row.get("memo", "") or ""),
                    height=100,
                    key=memo_key
                )

                if st.button("メモを保存", key=f"save_cust_memo_{lead_row.get('id')}"):
                    update_lead_memo(
                        int(lead_row.get("id")),
                        memo_value,
                        user_id=st.session_state.get("user_id"),
                        company_id=st.session_state.get("company_id")
                    )
                    st.success("メモを保存しました。")
                    st.rerun()

                st.markdown("#### 実利益")
                actual_key = f"cust_actual_revenue_{lead_row.get('id')}"
                actual_value = st.number_input(
                    "実回収利益",
                    min_value=0,
                    step=1000,
                    value=int(lead_row.get("actual_revenue", 0) or 0),
                    key=actual_key
                )

                if st.button("実利益を保存", key=f"save_cust_actual_revenue_{lead_row.get('id')}"):
                    update_actual_revenue(
                        int(lead_row.get("id")),
                        actual_value,
                        user_id=st.session_state.get("user_id"),
                        company_id=st.session_state.get("company_id")
                    )
                    save_ai_learning(
                        lead_id=int(lead_row.get("id")),
                        customer=str(lead_row.get("customer", "")),
                        subject=str(lead_row.get("subject", "")),
                        ai_decision="顧客タブから実利益保存",
                        result="成約" if int(actual_value or 0) > 0 else "実利益更新",
                        actual_revenue=int(actual_value or 0),
                        note="顧客CRMから実利益を保存"
                    )
                    st.success("実利益を保存しました。")
                    st.rerun()



        st.markdown("### 顧客タイムライン")

        try:
            customer_lead_ids = customer_leads["id"].tolist()

            if not customer_lead_ids:
                st.info("タイムラインはまだありません。")
            else:
                timeline_df = get_customer_timeline(customer_lead_ids)

                if timeline_df.empty:
                    st.info("タイムラインはまだありません。")
                else:
                    for _, ev in timeline_df.iterrows():
                        event_type = safe_text(ev.get("event_type", ""), "履歴")
                        event_time = safe_text(ev.get("event_time", ""), "")
                        subject_v = safe_text(ev.get("subject", ""), "件名なし")
                        body_v = clean_reply_body(ev.get("body", "")) if event_type == "reply" else safe_text(ev.get("body", ""), "") or safe_text(ev.get("message", ""), "")

                        if event_type == "reply":
                            label = "📩 相手から返信"
                        elif event_type == "gmail_reply":
                            label = "📤 こちらから送信"
                        elif event_type == "follow_text_saved":
                            label = "📝 送信文を保存"
                        elif event_type == "reply_inbox_done":
                            label = "✅ 対応済み"
                        elif event_type == "reply_follow_7days":
                            label = "⏳ フォロー予定"
                        else:
                            continue

                        display_subject = subject_v if subject_v and subject_v != "件名なし" else "件名未取得"
                        display_time = event_time[:16] if event_time else "日時未取得"

                        bubble_bg = "#eff6ff" if event_type == "gmail_reply" else "#ecfdf5"
                        bubble_border = "#bfdbfe" if event_type == "gmail_reply" else "#bbf7d0"

                        st.markdown(f"""
                        <div style="
                            border:1px solid {bubble_border};
                            background:{bubble_bg};
                            border-radius:16px;
                            padding:14px 16px;
                            margin:10px 0;
                        ">
                            <div style="font-weight:800; color:#0f172a; font-size:15px;">
                                {safe(label)}
                            </div>
                            <div style="color:#64748b; font-size:13px; margin-bottom:8px;">
                                {safe(display_time)} ｜ {safe(display_subject)}
                            </div>
                            <div style="color:#111827; font-size:15px; line-height:1.7; white-space:pre-wrap;">
                                {safe(body_v) if body_v else "本文はありません。"}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

        except Exception as e:
            st.warning(f"顧客タイムライン表示エラー: {e}")



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
    st.caption("売上の現在地だけを確認します。")

    chart_df = get_revenue_chart_data()

    if chart_df.empty:
        st.info("実績データがまだありません。Gmail解析・売上保存後に表示されます。")
    else:
        chart_df["actual_revenue"] = pd.to_numeric(chart_df.get("actual_revenue", 0), errors="coerce").fillna(0)

        for col in ["customer", "subject", "created_at"]:
            if col not in chart_df.columns:
                chart_df[col] = ""

        chart_df["customer"] = chart_df["customer"].fillna("不明顧客").astype(str).replace("", "不明顧客")
        chart_df["created_at_dt"] = pd.to_datetime(chart_df["created_at"], errors="coerce")

        today = pd.Timestamp.now().date()
        this_month = pd.Timestamp.now().month
        this_year = pd.Timestamp.now().year

        today_revenue = int(chart_df[chart_df["created_at_dt"].dt.date == today]["actual_revenue"].sum())
        month_revenue = int(chart_df[
            (chart_df["created_at_dt"].dt.year == this_year) &
            (chart_df["created_at_dt"].dt.month == this_month)
        ]["actual_revenue"].sum())
        total_revenue = int(chart_df["actual_revenue"].sum())

        st.markdown("### 売上")
        k1, k2, k3 = st.columns(3)
        k1.metric("今日", money(today_revenue))
        k2.metric("今月", money(month_revenue))
        k3.metric("累計", money(total_revenue))

        st.divider()

        st.markdown("### 売上上位顧客")

        revenue_df = chart_df[chart_df["actual_revenue"] > 0].copy()

        if revenue_df.empty:
            st.info("売上がある顧客はまだありません。")
        else:
            top_customers = (
                revenue_df.groupby("customer", as_index=False)["actual_revenue"]
                .sum()
                .sort_values("actual_revenue", ascending=False)
                .head(5)
            )

            for i, row in top_customers.reset_index(drop=True).iterrows():
                customer_name = str(row["customer"])
                amount = int(row["actual_revenue"])

                st.markdown(f"""
                <div class="lead-card">
                    <div>
                        <div class="lead-title">{i + 1}. {safe(customer_name)}</div>
                        <div class="lead-sub">累計売上</div>
                    </div>
                    <div class="lead-money">{money(amount)}</div>
                </div>
                """, unsafe_allow_html=True)

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
            from reply_detector import detect_replies, get_sent_gmail_replies

            current_user_id = st.session_state.get("user_id")
            current_company_id = st.session_state.get("company_id")

            st.caption("Gmailの返信を確認します。")

            sent_actions = get_sent_gmail_replies(
                limit=30,
                user_id=current_user_id,
                company_id=current_company_id
            )

            st.markdown("#### 送信済みGmail履歴")
            if not sent_actions:
                st.warning("返信検知対象の送信履歴がありません。Gmail送信が profit_actions に保存されていない可能性があります。")
            else:
                st.dataframe(pd.DataFrame(sent_actions), use_container_width=True)

            results = detect_replies(
                limit=30,
                user_id=current_user_id,
                company_id=current_company_id
            )

            st.markdown("#### 返信検知結果")
            if not results:
                st.info("新しい返信は検知されませんでした。")
            else:
                st.success(f"{len(results)}件の返信を検知しました。")
                st.dataframe(pd.DataFrame(results), use_container_width=True)

        except Exception as e:
            st.error(f"返信検知エラー: {e}")

    st.markdown("### 返信確認履歴")

    try:
        conn = sqlite3.connect(DB)
        reply_logs = pd.read_sql_query(
            """
            SELECT from_email AS 送信者, subject AS 件名, detected_at AS 検知日時
            FROM reply_detection_logs
            ORDER BY id DESC
            LIMIT 10
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


