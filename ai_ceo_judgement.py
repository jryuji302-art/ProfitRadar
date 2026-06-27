import streamlit as st


def _int(v):
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def build_ceo_judgement(row, money):
    status = str(row.get("status", "") or "")
    profit = _int(row.get("recoverable_profit", 0))
    if profit <= 0:
        profit = _int(row.get("estimated_profit", 0))

    confidence = _int(row.get("profit_confidence", 0))
    days = _int(row.get("neglected_days", 0))
    score = _int(row.get("home_priority_score", 0))

    probability = 40

    if "返信" in status:
        probability += 25
    if confidence >= 75:
        probability += 20
    elif confidence >= 45:
        probability += 10
    else:
        probability -= 5

    if days >= 7:
        probability -= 8
    elif days <= 2:
        probability += 5

    if score >= 80:
        probability += 10

    probability = max(5, min(95, probability))

    loss_risk = int(profit * min(0.7, max(0.15, days * 0.06 + 0.2)))

    if "返信" in status:
        action = "今すぐ返信"
        reason = "相手が反応しているため、今日返すと案件が進みやすい状態です。"
    elif confidence <= 25:
        action = "金額確認"
        reason = "金額根拠が弱いため、条件確認で精度を上げる必要があります。"
    elif days >= 7:
        action = "放置回収"
        reason = "放置日数が長く、失注リスクが上がっています。"
    elif profit >= 30000:
        action = "優先対応"
        reason = "回収期待値が高いため、今日処理する価値があります。"
    else:
        action = "確認連絡"
        reason = "短い確認で案件を前に進められます。"

    return {
        "probability": probability,
        "loss_risk": loss_risk,
        "action": action,
        "reason": reason,
    }


def render_ceo_judgement_card(row, money):
    j = build_ceo_judgement(row, money)

    c1, c2, c3 = st.columns(3)
    c1.metric("成功確率", f"{j['probability']}%")
    c2.metric("放置損失", money(j["loss_risk"]))
    c3.metric("AI判断", j["action"])

    st.caption(f"判断理由：{j['reason']}")
