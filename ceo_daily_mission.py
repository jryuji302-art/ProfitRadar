import pandas as pd
import streamlit as st


def _int(v):
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def _customer(v):
    return str(v or "").split("<")[0].strip() or "不明顧客"


def _mission_reason(row):
    status = str(row.get("status", "") or "")
    conf = _int(row.get("profit_confidence", 0))
    days = _int(row.get("neglected_days", 0))
    subject = str(row.get("subject", "") or "")
    category = str(row.get("category", "") or "")

    if "返信" in status:
        return "相手から返信あり。今日中に返す価値が高い。"
    if conf <= 25:
        return "金額未確定。まず条件・金額・進行可否を確認。"
    if days >= 7:
        return f"{days}日放置。失注リスクが上がっている。"
    if any(k in subject + category for k in ["契約", "請求", "見積", "発注"]):
        return "契約・金額に近い内容。優先処理。"
    return "短い確認で案件を前に進められる。"


def render_ceo_daily_mission(top_df, money):
    st.markdown("### 🚀 CEO Daily Mission")

    if top_df is None or top_df.empty:
        st.success("本日の指令：対応すべき営業案件はありません。")
        return

    df = top_df.copy()

    if "profit_for_today" not in df.columns:
        df["profit_for_today"] = df.get("recoverable_profit", 0)

    df["profit_for_today"] = pd.to_numeric(df["profit_for_today"], errors="coerce").fillna(0)

    total_profit = _int(df["profit_for_today"].sum())
    total_minutes = max(5, len(df) * 6)

    st.info(
        f"本日の指令：**上位{len(df)}件だけ処理**。"
        f"期待回収は **{money(total_profit)}**、想定作業時間は **約{total_minutes}分** です。"
    )

    for idx, (_, row) in enumerate(df.iterrows(), start=1):
        customer = _customer(row.get("customer", ""))
        profit = _int(row.get("profit_for_today", 0))
        reason = _mission_reason(row)

        with st.container(border=True):
            st.markdown(f"**Mission {idx}**")
            st.markdown(f"### {customer}")
            c1, c2 = st.columns(2)
            c1.metric("期待回収", money(profit) if profit > 0 else "金額未確定")
            c2.metric("目安時間", "6分")
            st.caption(f"理由：{reason}")

    st.caption("完了後は必ず「対応済み」「保留」「成約」のどれかに更新してください。")
