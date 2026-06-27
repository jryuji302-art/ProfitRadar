import sqlite3
from datetime import datetime

DB = "profit_radar.db"

PIPELINE_STAGES = [
    "新規",
    "提案",
    "交渉",
    "請求",
    "回収",
    "入金",
    "失注",
]

def init_recovery_crm():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS recovery_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER,
        note TEXT,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()

def update_pipeline_stage(lead_id, stage, reason="manual"):
    if stage not in PIPELINE_STAGES:
        raise ValueError("Invalid pipeline stage")

    init_pipeline_history()

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    SELECT COALESCE(pipeline_stage, '新規'), estimated_profit
    FROM profit_leads
    WHERE id=?
    """, (lead_id,))
    row = c.fetchone()
    from_stage = row[0] if row else "新規"
    estimated_profit = row[1] if row else 0

    c.execute("""
    UPDATE profit_leads
    SET pipeline_stage=?
    WHERE id=?
    """, (stage, lead_id))

    conn.commit()
    conn.close()

    if from_stage != stage:
        add_pipeline_history(lead_id, from_stage, stage, reason)

    # Learning Engineへ自動連携
    if stage in ["入金", "失注"]:
        try:
            from learning_engine import record_learning_event

            if stage == "入金":
                record_learning_event(
                    lead_id=lead_id,
                    action_id=None,
                    event_type="CRMステージ更新",
                    result="入金確認",
                    profit_amount=int(estimated_profit or 0),
                    note="Recovery CRMで入金ステージに更新"
                )

            elif stage == "失注":
                record_learning_event(
                    lead_id=lead_id,
                    action_id=None,
                    event_type="CRMステージ更新",
                    result="失注",
                    profit_amount=0,
                    note="Recovery CRMで失注ステージに更新"
                )

        except Exception:
            pass

def add_recovery_note(lead_id, note):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    INSERT INTO recovery_notes
    (lead_id, note, created_at)
    VALUES (?, ?, ?)
    """, (
        lead_id,
        note,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

def get_recovery_notes(lead_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT *
    FROM recovery_notes
    WHERE lead_id=?
    ORDER BY created_at DESC
    """, (lead_id,))

    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_recovery_pipeline():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT
        id,
        customer,
        subject,
        category,
        opportunity_score,
        hot_lead,
        estimated_profit,
        recoverable_profit,
        pipeline_stage,
        status,
        created_at
    FROM profit_leads
    WHERE category != 'ノイズ'
    ORDER BY
        CASE
            WHEN pipeline_stage='回収' THEN 1
            WHEN pipeline_stage='請求' THEN 2
            WHEN pipeline_stage='交渉' THEN 3
            WHEN pipeline_stage='提案' THEN 4
            WHEN pipeline_stage='新規' THEN 5
            WHEN pipeline_stage='入金' THEN 6
            WHEN pipeline_stage='失注' THEN 7
            ELSE 8
        END,
        opportunity_score DESC,
        recoverable_profit DESC
    """)

    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_pipeline_summary():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT
        COALESCE(pipeline_stage, '新規') as pipeline_stage,
        COUNT(*) as lead_count,
        SUM(COALESCE(estimated_profit, 0)) as total_estimated_profit,
        SUM(COALESCE(recoverable_profit, 0)) as total_recoverable_profit,
        AVG(COALESCE(opportunity_score, 0)) as avg_opportunity_score,
        SUM(COALESCE(hot_lead, 0)) as hot_lead_count
    FROM profit_leads
    WHERE category != 'ノイズ'
    GROUP BY COALESCE(pipeline_stage, '新規')
    ORDER BY
        CASE
            WHEN pipeline_stage='新規' THEN 1
            WHEN pipeline_stage='提案' THEN 2
            WHEN pipeline_stage='交渉' THEN 3
            WHEN pipeline_stage='請求' THEN 4
            WHEN pipeline_stage='回収' THEN 5
            WHEN pipeline_stage='入金' THEN 6
            WHEN pipeline_stage='失注' THEN 7
            ELSE 8
        END
    """)

    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def init_pipeline_history():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS pipeline_stage_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER,
        from_stage TEXT,
        to_stage TEXT,
        reason TEXT,
        created_at TEXT
    )
    """)
    conn.commit()
    conn.close()

def add_pipeline_history(lead_id, from_stage, to_stage, reason="manual"):
    init_pipeline_history()
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
    INSERT INTO pipeline_stage_history
    (lead_id, from_stage, to_stage, reason, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (
        lead_id,
        from_stage,
        to_stage,
        reason,
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

def get_pipeline_history(lead_id=None):
    init_pipeline_history()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if lead_id:
        c.execute("""
        SELECT *
        FROM pipeline_stage_history
        WHERE lead_id=?
        ORDER BY created_at DESC
        """, (lead_id,))
    else:
        c.execute("""
        SELECT
            h.*,
            l.customer,
            l.subject,
            l.category,
            l.opportunity_score
        FROM pipeline_stage_history h
        LEFT JOIN profit_leads l ON h.lead_id = l.id
        ORDER BY h.created_at DESC
        LIMIT 200
        """)

    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_stale_pipeline_alerts():
    """
    Pipeline Stage Historyから、同一ステージで滞留している案件を検出。
    履歴がない案件は created_at を基準に見る。
    """
    init_pipeline_history()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT
        l.id,
        l.customer,
        l.subject,
        l.category,
        COALESCE(l.pipeline_stage, '新規') as pipeline_stage,
        l.opportunity_score,
        l.recoverable_profit,
        l.created_at,
        MAX(h.created_at) as last_stage_changed_at
    FROM profit_leads l
    LEFT JOIN pipeline_stage_history h ON l.id = h.lead_id
    WHERE COALESCE(l.pipeline_stage, '新規') NOT IN ('入金', '失注')
      AND l.category != 'ノイズ'
    GROUP BY l.id
    ORDER BY l.opportunity_score DESC, l.recoverable_profit DESC
    """)

    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    from datetime import datetime

    alerts = []
    now = datetime.now()

    thresholds = {
        "新規": 3,
        "提案": 5,
        "交渉": 7,
        "請求": 5,
        "回収": 3,
    }

    for r in rows:
        stage = r.get("pipeline_stage") or "新規"
        base_date = r.get("last_stage_changed_at") or r.get("created_at")

        if not base_date:
            continue

        try:
            dt = datetime.fromisoformat(base_date)
        except Exception:
            continue

        days = (now - dt).days
        limit = thresholds.get(stage, 7)

        if days >= limit:
            r["stale_days"] = days
            r["threshold_days"] = limit
            r["alert_reason"] = f"{stage}ステージで{days}日滞留"
            alerts.append(r)

    return alerts

def recommend_pipeline_action(stage, stale_days, category, subject):
    if stage == "新規":
        return "初回確認メールを送る。見積・請求・採用など利益化できる要素を確認する。"

    if stage == "提案":
        return "提案後の検討状況を確認する。条件変更・再見積・日程調整の余地を聞く。"

    if stage == "交渉":
        return "意思決定の障害を確認する。金額・日程・人数・条件のどこで止まっているか聞く。"

    if stage == "請求":
        return "請求書の確認状況と支払予定日を確認する。行き違い防止の文面にする。"

    if stage == "回収":
        return "入金予定日を確認する。強すぎず、支払確認ベースで連絡する。"

    return "状況確認メールを送る。次の判断材料を取得する。"

def get_stale_pipeline_recommendations():
    alerts = get_stale_pipeline_alerts()

    for a in alerts:
        a["recommended_action"] = recommend_pipeline_action(
            a.get("pipeline_stage"),
            a.get("stale_days"),
            a.get("category"),
            a.get("subject")
        )

    return alerts

def generate_stale_followup_message(stage, customer, subject, category, stale_days):
    customer = customer or "ご担当者様"
    subject = subject or ""

    if stage == "提案":
        return f"""{customer}

お世話になっております。

以前ご提案させていただいた下記の件について、
その後のご検討状況を確認したくご連絡いたしました。

件名：{subject}

条件面・日程・内容の調整が必要であれば、改めて整理可能です。
現在の状況だけでもご共有いただけますと幸いです。

よろしくお願いいたします。
"""

    if stage == "交渉":
        return f"""{customer}

お世話になっております。

下記の件について、現在どの部分で調整が必要か確認させてください。

件名：{subject}

金額・日程・人数・条件など、止まっている点があればこちらで再整理いたします。
ご確認よろしくお願いいたします。
"""

    if stage == "請求":
        return f"""{customer}

お世話になっております。

下記の請求関連の件について、確認のためご連絡いたしました。

件名：{subject}

請求内容のご確認状況、またはお支払い予定日についてご共有いただけますでしょうか。
行き違いでしたら申し訳ございません。

よろしくお願いいたします。
"""

    if stage == "回収":
        return f"""{customer}

お世話になっております。

下記の件について、入金状況の確認でご連絡いたしました。

件名：{subject}

お支払い予定日、または現在の確認状況をご共有いただけますと幸いです。
よろしくお願いいたします。
"""

    return f"""{customer}

お世話になっております。

下記の件について、現在のご状況を確認したくご連絡いたしました。

件名：{subject}

対応が必要であれば、こちらで次の対応を進めます。
ご確認よろしくお願いいたします。
"""

def get_stale_pipeline_messages():
    recs = get_stale_pipeline_recommendations()

    for r in recs:
        r["recommended_message"] = generate_stale_followup_message(
            r.get("pipeline_stage"),
            r.get("customer"),
            r.get("subject"),
            r.get("category"),
            r.get("stale_days")
        )

    return recs
