import sqlite3
from db_adapter import patch_sqlite_for_database_url
patch_sqlite_for_database_url(sqlite3)
from datetime import datetime
from email.utils import parsedate_to_datetime

from revenue_engine import analyze_email

DB = "profit_radar.db"

def estimate_neglected_days(email_date):
    try:
        if not email_date:
            return 7

        dt = parsedate_to_datetime(email_date)

        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)

        return max(0, (datetime.now() - dt).days)
    except Exception:
        return 7

def save_email_as_lead(email, user_id=None, company_id=None):
    if user_id is None or company_id is None:
        raise ValueError("user_id / company_id がないため利益候補を保存できません。")
    subject = email.get("subject", "")
    body = email.get("body", "")
    sender = email.get("sender", "")
    email_date = email.get("date", "")
    neglected_days = estimate_neglected_days(email_date)

    analysis = analyze_email(f"{sender} {subject}", body, neglected_days)

    if not analysis.get("is_profit_lead"):
        return False

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    gmail_id = email.get("gmail_id", "")

    c.execute("SELECT COUNT(*) FROM profit_leads WHERE gmail_id = ? AND user_id = ? AND company_id = ?", (gmail_id, user_id, company_id))
    if c.fetchone()[0] > 0:
        conn.close()
        return False

    estimated_profit = analysis.get("estimated_profit", 0)
    risk_level = analysis.get("risk_level", "中")
    next_action = analysis.get("next_action", "フォロー確認")
    reason = analysis.get("reason", "")
    category = analysis.get("category", "不明")
    opportunity_score = analysis.get("opportunity_score", 0)
    hot_lead = analysis.get("hot_lead", 0)
    recoverable_profit = analysis.get("recoverable_profit", 0)
    pipeline_stage = analysis.get("pipeline_stage", "新規")

    customer = email.get("sender", "")[:80]

    c.execute("""
    INSERT INTO profit_leads
    (gmail_id, customer, subject, content, estimated_profit, risk_level,
     neglected_days, next_action, status, created_at, reason, email_date, memo,
     category, opportunity_score, hot_lead, recoverable_profit, pipeline_stage,
     user_id, company_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        gmail_id,
        customer,
        email.get("subject", ""),
        email.get("body", "")[:3000],
        estimated_profit,
        risk_level,
        neglected_days,
        next_action,
        "未対応",
        datetime.now().isoformat(),
        reason,
        email_date,
        "",
        category,
        opportunity_score,
        hot_lead,
        recoverable_profit,
        pipeline_stage,
        user_id,
        company_id
    ))

    conn.commit()
    conn.close()
    return True
