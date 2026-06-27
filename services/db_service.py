import sqlite3
import pandas as pd
from db_adapter import patch_sqlite_for_database_url

patch_sqlite_for_database_url(sqlite3)


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def require_user_company(user_id, company_id):
    if user_id is None or company_id is None:
        raise ValueError("user_id / company_id がありません。")
    return int(user_id), int(company_id)


def get_revenue_chart_data(db_path):
    conn = connect(db_path)
    try:
        return pd.read_sql_query("""
            SELECT
                id,
                customer,
                subject,
                estimated_profit,
                recoverable_profit,
                actual_revenue,
                status,
                created_at,
                user_id,
                company_id
            FROM profit_leads
            ORDER BY created_at DESC
        """, conn)
    finally:
        conn.close()


def update_actual_revenue(db_path, lead_id, actual_revenue, user_id=None, company_id=None):
    user_id, company_id = require_user_company(user_id, company_id)
    conn = connect(db_path)
    c = conn.cursor()
    c.execute("""
        UPDATE profit_leads
        SET actual_revenue=?
        WHERE id=? AND user_id=? AND company_id=?
    """, (int(actual_revenue or 0), int(lead_id), user_id, company_id))
    conn.commit()
    conn.close()


def update_lead_status(db_path, lead_id, status, user_id=None, company_id=None):
    user_id, company_id = require_user_company(user_id, company_id)
    conn = connect(db_path)
    c = conn.cursor()
    c.execute("""
        UPDATE profit_leads
        SET status=?
        WHERE id=? AND user_id=? AND company_id=?
    """, (status, int(lead_id), user_id, company_id))
    conn.commit()
    conn.close()


def update_lead_memo(db_path, lead_id, memo, user_id=None, company_id=None):
    user_id, company_id = require_user_company(user_id, company_id)
    conn = connect(db_path)
    c = conn.cursor()
    c.execute("""
        UPDATE profit_leads
        SET memo=?
        WHERE id=? AND user_id=? AND company_id=?
    """, (memo, int(lead_id), user_id, company_id))
    conn.commit()
    conn.close()


def save_action_log(db_path, lead_id, action_type, message, result, user_id=None, company_id=None):
    user_id, company_id = require_user_company(user_id, company_id)
    from datetime import datetime

    conn = connect(db_path)
    c = conn.cursor()
    c.execute("""
        INSERT INTO profit_actions
        (lead_id, action_type, body, status, sent_at, user_id, company_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        int(lead_id),
        action_type,
        message,
        result,
        datetime.now().isoformat(timespec="seconds"),
        user_id,
        company_id
    ))
    conn.commit()
    conn.close()


def get_customer_timeline(db_path, lead_ids):
    if not lead_ids:
        return pd.DataFrame()

    conn = connect(db_path)
    try:
        placeholders = ",".join(["?"] * len(lead_ids))

        action_df = pd.read_sql_query(f"""
            SELECT
                lead_id,
                action_type AS event_type,
                sent_at AS event_time,
                subject,
                body,
                status,
                to_email,
                '' AS from_email
            FROM profit_actions
            WHERE lead_id IN ({placeholders})
        """, conn, params=list(lead_ids))

        reply_df = pd.read_sql_query(f"""
            SELECT
                lead_id,
                'reply' AS event_type,
                reply_date AS event_time,
                subject,
                reply_body AS body,
                '' AS status,
                '' AS to_email,
                from_email
            FROM reply_detection_logs
            WHERE lead_id IN ({placeholders})
        """, conn, params=list(lead_ids))

        timeline_df = pd.concat([action_df, reply_df], ignore_index=True)
        if timeline_df.empty:
            return timeline_df

        timeline_df["event_time"] = pd.to_datetime(timeline_df["event_time"], errors="coerce")
        timeline_df = timeline_df.sort_values("event_time", ascending=False)
        return timeline_df
    finally:
        conn.close()


def get_customer_revenue_summary(db_path, customer):
    conn = connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT
            COALESCE(SUM(actual_revenue), 0) AS total_actual_revenue,
            COALESCE(SUM(recoverable_profit), 0) AS total_recoverable_profit,
            COALESCE(SUM(estimated_profit), 0) AS total_estimated_profit,
            COUNT(*) AS lead_count
        FROM profit_leads
        WHERE customer = ?
    """, (customer,))

    row = c.fetchone()
    conn.close()

    if not row:
        return {
            "total_actual_revenue": 0,
            "total_recoverable_profit": 0,
            "total_estimated_profit": 0,
            "lead_count": 0,
        }

    return dict(row)


def get_ai_advice_logs(db_path, limit=50):
    conn = connect(db_path)
    try:
        return pd.read_sql_query("""
            SELECT *
            FROM ai_self_evaluation
            ORDER BY id DESC
            LIMIT ?
        """, conn, params=(int(limit),))
    finally:
        conn.close()


def get_actions(db_path, user_id=None, company_id=None):
    conn = connect(db_path)
    try:
        if user_id is not None and company_id is not None:
            return pd.read_sql_query("""
                SELECT *
                FROM profit_actions
                WHERE user_id=? AND company_id=?
                ORDER BY id DESC
            """, conn, params=(int(user_id), int(company_id)))

        return pd.read_sql_query("""
            SELECT *
            FROM profit_actions
            ORDER BY id DESC
        """, conn)
    finally:
        conn.close()


def reset_database(db_path, user_id=None, company_id=None):
    conn = connect(db_path)
    c = conn.cursor()

    if user_id is not None and company_id is not None:
        for table in ["profit_leads", "profit_actions", "reply_detection_logs"]:
            c.execute(
                f"DELETE FROM {table} WHERE user_id=? AND company_id=?",
                (int(user_id), int(company_id))
            )
    else:
        for table in ["profit_leads", "profit_actions", "reply_detection_logs"]:
            c.execute(f"DELETE FROM {table}")

    conn.commit()
    conn.close()


def get_leads(db_path, user_id=None, company_id=None, score_func=None):
    conn = connect(db_path)
    try:
        if user_id is not None and company_id is not None:
            df = pd.read_sql_query(
                "SELECT * FROM profit_leads WHERE user_id = ? AND company_id = ?",
                conn,
                params=(int(user_id), int(company_id))
            )
        else:
            df = pd.read_sql_query("SELECT * FROM profit_leads WHERE 1=0", conn)
    finally:
        conn.close()

    if not df.empty and score_func:
        df["revenue_score"] = df.apply(score_func, axis=1)

    if not df.empty:
        sort_col = "opportunity_score" if "opportunity_score" in df.columns else "revenue_score"
        if sort_col in df.columns:
            df = df.sort_values(sort_col, ascending=False)

    return df
