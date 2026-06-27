import pandas as pd
import streamlit as st


def render_results_tab(get_revenue_chart_data, money, safe):
    st.subheader("実績")
    st.caption("売上の現在地だけを確認します。")

    chart_df = get_revenue_chart_data()

    if chart_df.empty:
        st.info("実績データがまだありません。Gmail解析・売上保存後に表示されます。")
        return

    chart_df["actual_revenue"] = pd.to_numeric(
        chart_df.get("actual_revenue", 0),
        errors="coerce"
    ).fillna(0)

    for col in ["customer", "subject", "created_at"]:
        if col not in chart_df.columns:
            chart_df[col] = ""

    chart_df["customer"] = (
        chart_df["customer"]
        .fillna("不明顧客")
        .astype(str)
        .replace("", "不明顧客")
    )
    chart_df["created_at_dt"] = pd.to_datetime(chart_df["created_at"], errors="coerce")

    today = pd.Timestamp.now().date()
    this_month = pd.Timestamp.now().month
    this_year = pd.Timestamp.now().year

    today_revenue = int(
        chart_df[chart_df["created_at_dt"].dt.date == today]["actual_revenue"].sum()
    )

    month_revenue = int(
        chart_df[
            (chart_df["created_at_dt"].dt.year == this_year) &
            (chart_df["created_at_dt"].dt.month == this_month)
        ]["actual_revenue"].sum()
    )

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
        return

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
