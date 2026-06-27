import pandas as pd
import streamlit as st
from datetime import datetime


def _int(v):
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def render_ai_sales_forecast(home_df, active_df, money):
    st.markdown("### 💰 AI売上予測")

    if home_df is None or home_df.empty:
        st.info("売上予測に使える案件データがありません。")
        return

    df = home_df.copy()

    for col in ["actual_revenue", "recoverable_profit", "estimated_profit"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "created_at" in df.columns:
        created = pd.to_datetime(df["created_at"], errors="coerce")
        now = pd.Timestamp(datetime.now())
        month_df = df[(created.dt.year == now.year) & (created.dt.month == now.month)].copy()
    else:
        month_df = df.copy()

    monthly_actual = _int(month_df["actual_revenue"].sum())

    if active_df is not None and not active_df.empty:
        adf = active_df.copy()
        for col in ["recoverable_profit", "estimated_profit"]:
            if col not in adf.columns:
                adf[col] = 0
            adf[col] = pd.to_numeric(adf[col], errors="coerce").fillna(0)

        adf["forecast_value"] = adf["recoverable_profit"]
        adf.loc[adf["forecast_value"] <= 0, "forecast_value"] = adf["estimated_profit"]
        open_expected = _int(adf["forecast_value"].sum())
    else:
        open_expected = 0

    forecast_total = monthly_actual + open_expected

    monthly_target = st.number_input(
        "今月の目標売上",
        min_value=0,
        step=10000,
        value=300000,
        key="ai_monthly_sales_target"
    )

    shortage = max(0, int(monthly_target) - forecast_total)
    achievement = 0
    if int(monthly_target) > 0:
        achievement = min(999, int((forecast_total / int(monthly_target)) * 100))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("今月実利益", money(monthly_actual))
    c2.metric("未対応期待値", money(open_expected))
    c3.metric("着地予測", money(forecast_total))
    c4.metric("達成率", f"{achievement}%")

    if shortage > 0:
        st.warning(f"AI判断：今月目標まで **{money(shortage)}** 足りません。高期待値案件を優先して処理してください。")
    else:
        st.success("AI判断：現時点の着地予測では、今月目標を超える可能性があります。")

    with st.expander("AI売上予測の見方", expanded=False):
        st.write("・今月実利益：実利益として保存済みの金額")
        st.write("・未対応期待値：まだ対応可能な案件の回収期待値")
        st.write("・着地予測：今月実利益 + 未対応期待値")
        st.write("・不足額が出ている場合は、AIホーム上位案件から処理してください。")
