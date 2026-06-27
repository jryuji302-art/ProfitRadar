import streamlit as st
import pandas as pd

def render(df_view, money, lead_card):
    st.subheader("🏠 今日の利益")
    st.caption("今日見るべき利益状況と優先案件を確認します。詳細対応は「🔥 要対応」で行います。")

    if df_view.empty:
        st.info("表示できる案件がありません。")
        return

    priority_sort_col = "opportunity_score" if "opportunity_score" in df_view.columns else "revenue_score"

    dashboard_df = df_view.sort_values(priority_sort_col, ascending=False).copy()

    st.markdown("### 優先案件")
    for _, row in dashboard_df.head(8).iterrows():
        lead_card(row)
