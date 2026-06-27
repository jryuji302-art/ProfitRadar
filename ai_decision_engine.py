import sqlite3
import streamlit as st

DB = "profit_radar.db"


def _int(v):
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def get_customer_learning_boost(customer):
    """
    顧客ごとの過去実利益・成約履歴から優先度補正を返す。
    初期は軽めに効かせる。
    """
    try:
        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        cur.execute("""
        SELECT
            COUNT(*) AS cnt,
            COALESCE(SUM(actual_revenue), 0) AS total_actual,
            SUM(CASE WHEN status IN ('成約','対応済み') THEN 1 ELSE 0 END) AS success_count
        FROM profit_leads
        WHERE customer = ?
        """, (str(customer or ""),))

        row = cur.fetchone()
        conn.close()

        if not row:
            return 0, "学習データなし"

        cnt = _int(row[0])
        total_actual = _int(row[1])
        success_count = _int(row[2])

        boost = 0
        notes = []

        if total_actual >= 50000:
            boost += 12
            notes.append("過去利益あり")
        elif total_actual > 0:
            boost += 6
            notes.append("小規模実績あり")

        if cnt >= 3:
            boost += 5
            notes.append("接触履歴あり")

        if success_count >= 2:
            boost += 8
            notes.append("対応実績あり")

        return min(boost, 20), "・".join(notes) if notes else "学習データ少"

    except Exception:
        return 0, "学習補正不可"


def build_decision(row):
    customer = str(row.get("customer", "") or "")
    status = str(row.get("status", "") or "")
    score = _int(row.get("opportunity_score", 0) or row.get("revenue_score", 0))
    recoverable = _int(row.get("recoverable_profit", 0))
    estimated = _int(row.get("estimated_profit", 0))
    confidence = _int(row.get("profit_confidence", 0))
    neglected = _int(row.get("neglected_days", 0))

    profit = recoverable if recoverable > 0 else estimated

    reasons = []

    if "返信" in status:
        score += 35
        reasons.append("相手から返信あり")

    if neglected >= 7:
        score += 15
        reasons.append(f"{neglected}日放置")

    if profit >= 30000:
        score += 15
        reasons.append("利益期待が高い")

    if confidence >= 80:
        score += 10
        reasons.append("利益根拠が強い")

    if confidence <= 25 or estimated <= 0:
        score += 8
        reasons.append("金額は未確定")

    boost, boost_reason = get_customer_learning_boost(customer)
    score += boost

    if boost > 0:
        reasons.append(f"学習補正: {boost_reason}")

    score = max(0, min(120, score))

    if score >= 95:
        priority = "★★★★★"
    elif score >= 75:
        priority = "★★★★"
    elif score >= 50:
        priority = "★★★"
    elif score >= 30:
        priority = "★★"
    else:
        priority = "★"

    action = "今日対応"

    if confidence <= 25 or estimated <= 0:
        action = "まず条件確認"

    if "返信" in status:
        action = "本日返信"

    if neglected >= 14:
        action = "失注防止で即確認"

    return {
        "priority": priority,
        "score": score,
        "action": action,
        "reason": "・".join(reasons) if reasons else "通常確認",
        "learning_boost": boost,
        "learning_reason": boost_reason,
    }


def render_decision(row):
    d = build_decision(row)

    st.markdown("### 🧠 AI判断")

    c1, c2 = st.columns(2)
    c1.metric("優先度", d["priority"])
    c2.metric("判断スコア", f"{d['score']}/120")

    st.success(d["action"])
    st.caption(f"理由：{d['reason']}")

    if d.get("learning_boost", 0) > 0:
        st.info(f"過去実績による補正：+{d['learning_boost']} / {d['learning_reason']}")
