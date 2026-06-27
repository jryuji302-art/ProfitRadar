import pandas as pd
import streamlit as st


def prepare_customer_view(df_view):
    customer_view = df_view.copy()

    for col in [
        "id", "customer", "subject", "status", "category", "risk_level",
        "estimated_profit", "recoverable_profit", "actual_revenue",
        "neglected_days", "revenue_score", "opportunity_score",
        "pipeline_stage", "content", "memo"
    ]:
        if col not in customer_view.columns:
            customer_view[col] = ""

    for col in [
        "estimated_profit", "recoverable_profit", "actual_revenue",
        "neglected_days", "revenue_score", "opportunity_score"
    ]:
        customer_view[col] = pd.to_numeric(customer_view[col], errors="coerce").fillna(0)

    return customer_view


def build_customer_summary(customer_view):
    customer_summary = customer_view.groupby("customer").agg(
        実売上=("actual_revenue", "sum"),
        案件金額候補=("estimated_profit", "sum"),
        回収期待値利益=("recoverable_profit", "sum"),
        最大放置=("neglected_days", "max"),
        案件数=("id", "count"),
        未対応数=("status", lambda x: int((x == "未対応").sum())),
        保留数=("status", lambda x: int((x == "保留").sum())),
        対応済み数=("status", lambda x: int((x == "対応済み").sum())),
    ).reset_index()

    customer_summary["優先度"] = (
        customer_summary["回収期待値利益"].fillna(0)
        + customer_summary["案件金額候補"].fillna(0) * 0.4
        + customer_summary["最大放置"].fillna(0) * 1000
        + customer_summary["未対応数"].fillna(0) * 5000
    )

    return customer_summary


def render_customer_summary(customer_view, money):
    st.markdown("### 顧客サマリー")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("総顧客数", f"{customer_view['customer'].nunique()}件")
    c2.metric("未対応", f"{int((customer_view['status'] == '未対応').sum())}件")
    c3.metric("実売上", money(customer_view["actual_revenue"].sum()))
    c4.metric("回収期待値", money(customer_view["recoverable_profit"].sum()))

    return build_customer_summary(customer_view)


def build_customer_lead_pool(customer_view, customer_summary, view_mode, score_col):
    if view_mode == "今すぐ対応":
        lead_pool = customer_view[
            customer_view["status"].astype(str).isin(["未対応", "返信あり", "フォロー必要"])
        ].copy()
        return lead_pool.sort_values(["recoverable_profit", "neglected_days", score_col], ascending=False)

    if view_mode == "売上順":
        top_customers = customer_summary.sort_values("実売上", ascending=False)["customer"].tolist()
        lead_pool = customer_view[customer_view["customer"].isin(top_customers)].copy()
        lead_pool["customer_rank"] = lead_pool["customer"].apply(
            lambda x: top_customers.index(x) if x in top_customers else 999
        )
        return lead_pool.sort_values(
            ["customer_rank", "actual_revenue", "estimated_profit"],
            ascending=[True, False, False]
        )

    if view_mode == "放置危険":
        lead_pool = customer_view[
            (customer_view["status"].astype(str) == "未対応") &
            (customer_view["neglected_days"] >= 3)
        ].copy()
        return lead_pool.sort_values(["neglected_days", "recoverable_profit"], ascending=False)

    if view_mode == "対応済み・保留":
        lead_pool = customer_view[
            customer_view["status"].astype(str).isin(["対応済み", "保留"])
        ].copy()
        return lead_pool.sort_values("id", ascending=False)

    lead_pool = customer_view.copy()
    return lead_pool.sort_values(["customer", "id"], ascending=[True, False])


def render_customer_selector(customer_view, customer_summary, score_col, money):
    view_mode = st.radio(
        "表示する顧客",
        ["今すぐ対応", "売上順", "放置危険", "対応済み・保留", "全顧客"],
        horizontal=True,
        key="customer_unified_view_mode"
    )

    lead_pool = build_customer_lead_pool(customer_view, customer_summary, view_mode, score_col)

    if lead_pool.empty:
        st.info("該当する顧客・案件はありません。")
        return None, None, None

    st.markdown("### 対象案件を選択")

    lead_options = []
    lead_map = {}

    for _, r in lead_pool.head(50).iterrows():
        lead_id_v = int(r.get("id", 0) or 0)
        label = (
            f"#{lead_id_v}｜{r.get('customer', '不明顧客')}｜"
            f"{r.get('status', '')}｜"
            f"{money(r.get('recoverable_profit', 0))}｜"
            f"{r.get('subject', '件名なし')}"
        )
        lead_options.append(label)
        lead_map[label] = lead_id_v

    selected_label = st.selectbox(
        "確認・対応する案件",
        lead_options,
        key=f"customer_unified_selected_{view_mode}"
    )

    selected_lead_id = lead_map[selected_label]
    selected_rows = customer_view[customer_view["id"].astype(int) == int(selected_lead_id)]

    if selected_rows.empty:
        st.warning("選択した案件が見つかりません。")
        return None, None, None

    lead_row = selected_rows.iloc[0]
    lead_id_v = int(lead_row.get("id", 0) or 0)
    selected_customer = str(lead_row.get("customer", "") or "不明顧客")

    return lead_row, lead_id_v, selected_customer


def render_customer_panel(
    lead_row,
    lead_id_v,
    selected_customer,
    money,
    safe,
    render_reply_screen,
    reply_ui_deps,
    update_lead_memo,
):
    st.divider()
    st.markdown("## 顧客対応パネル")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("状態", safe(lead_row.get("status", "")))
    c2.metric("実売上", money(lead_row.get("actual_revenue", 0)))
    c3.metric("回収期待値", money(lead_row.get("recoverable_profit", 0)))
    c4.metric("放置", f"{int(lead_row.get('neglected_days', 0) or 0)}日")

    st.markdown(f"### {safe(selected_customer)}")
    st.caption(f"案件ID {lead_id_v}｜{safe(lead_row.get('subject', '件名なし'))}")

    render_reply_screen(
        lead_row,
        context=f"customer_unified_{lead_id_v}",
        deps=reply_ui_deps
    )

    st.divider()
    st.markdown("### メモ")

    memo_key = f"customer_unified_memo_{lead_id_v}"
    memo_value = st.text_area(
        "顧客・案件メモ",
        str(lead_row.get("memo", "") or ""),
        height=120,
        key=memo_key
    )

    if st.button("メモを保存", key=f"customer_unified_save_memo_{lead_id_v}", use_container_width=True):
        update_lead_memo(
            lead_id_v,
            memo_value,
            user_id=st.session_state.get("user_id"),
            company_id=st.session_state.get("company_id")
        )
        st.success("メモを保存しました。")
        st.rerun()


def render_customer_related_and_timeline(
    customer_view,
    selected_customer,
    get_customer_timeline,
    safe,
    safe_text,
    money,
    clean_reply_body,
    log_warning,
):
    st.divider()
    st.markdown("### 同じ顧客の案件")

    same_customer_leads = customer_view[
        customer_view["customer"].astype(str) == selected_customer
    ].copy().sort_values("id", ascending=False)

    for _, same in same_customer_leads.iterrows():
        st.markdown(
            f"- #{int(same.get('id', 0) or 0)}｜"
            f"{safe(same.get('status', ''))}｜"
            f"{money(same.get('estimated_profit', 0))}｜"
            f"{safe(same.get('subject', '件名なし'))}"
        )

    st.divider()
    st.markdown("### タイムライン")

    try:
        timeline_df = get_customer_timeline(same_customer_leads["id"].tolist())

        if timeline_df.empty:
            st.info("タイムラインはまだありません。")
            return

        for _, ev in timeline_df.iterrows():
            event_type = safe_text(ev.get("event_type", ""), "履歴")
            event_time = safe_text(ev.get("event_time", ""), "")
            subject_v = safe_text(ev.get("subject", ""), "件名なし")
            body_v = (
                clean_reply_body(ev.get("body", ""))
                if event_type == "reply"
                else safe_text(ev.get("body", ""), "") or safe_text(ev.get("message", ""), "")
            )

            if event_type == "reply":
                label = "相手から返信"
            elif event_type == "gmail_reply":
                label = "こちらから送信"
            elif event_type == "follow_text_saved":
                label = "送信文を保存"
            elif event_type == "reply_inbox_done":
                label = "対応済み"
            elif event_type == "reply_follow_7days":
                label = "フォロー予定"
            else:
                label = "履歴"

            st.markdown(f"""
            <div style="
                border:1px solid #e5e7eb;
                background:#ffffff;
                border-radius:16px;
                padding:14px 16px;
                margin:10px 0;
            ">
                <div style="font-weight:800; color:#0f172a; font-size:15px;">
                    {safe(label)}
                </div>
                <div style="color:#64748b; font-size:13px; margin-bottom:8px;">
                    {safe(event_time[:16] if event_time else "日時未取得")} ｜ {safe(subject_v)}
                </div>
                <div style="color:#111827; font-size:15px; line-height:1.7; white-space:pre-wrap;">
                    {safe(body_v) if body_v else "本文はありません。"}
                </div>
            </div>
            """, unsafe_allow_html=True)

    except Exception as e:
        log_warning(f"タイムライン表示エラー: {e}")
        st.warning("タイムラインを表示できませんでした。")
