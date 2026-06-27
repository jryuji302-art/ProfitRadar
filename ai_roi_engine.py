import pandas as pd
import streamlit as st


def _int(v):
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def render_roi_dashboard(active_df, money):
    st.markdown("### 💰 AI ROI")

    if active_df is None or active_df.empty:
        st.info("ROI分析対象の未対応案件がありません。")
        return

    df = active_df.copy()

    for col in ["recoverable_profit", "estimated_profit", "actual_revenue"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["roi_value"] = df["recoverable_profit"]
    df.loc[df["roi_value"] <= 0, "roi_value"] = df["estimated_profit"]

    total_open_value = _int(df["roi_value"].sum())
    today_value = _int(total_open_value * 0.25)
    week_value = _int(total_open_value * 0.60)
    month_value = total_open_value

    c1, c2, c3 = st.columns(3)
    c1.metric("今日対応価値", money(today_value))
    c2.metric("今週回収余地", money(week_value))
    c3.metric("今月回収余地", money(month_value))

    if total_open_value > 0:
        st.success("AI判断：上位案件から処理すると、回収期待値を最大化できます。")
    else:
        st.info("AI判断：金額未確定案件が中心です。まず条件確認を優先してください。")
