import pandas as pd
import streamlit as st


def _num(v):
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def _clean_customer(v):
    return str(v or "").split("<")[0].strip() or "不明顧客"


def render_home_dashboard(
    df_view,
    money,
    money_or_unknown,
    safe_text,
    render_ceo_judgement_card=None,
    render_ceo_daily_mission=None,
    render_ai_executive_brief=None,
    render_ai_sales_forecast=None,
    render_roi_dashboard=None,
    **kwargs,
):
    st.markdown("""
    <style>
    .pr-title h1 {
        font-size: 34px;
        font-weight: 900;
        color: #111827;
        margin-bottom: 4px;
        letter-spacing: -0.04em;
    }
    .pr-title p {
        color: #64748B;
        font-size: 14px;
        font-weight: 600;
        margin-top: 0;
        margin-bottom: 22px;
    }
    .pr-kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(180px, 1fr));
        gap: 16px;
        margin-bottom: 18px;
    }
    .pr-card {
        background: #ffffff;
        border: 1px solid #E4EAF2;
        border-radius: 20px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.055);
        padding: 20px;
        box-sizing: border-box;
    }
    .pr-kpi-label {
        font-size: 13px;
        color: #64748B;
        font-weight: 800;
        margin-bottom: 8px;
    }
    .pr-kpi-value {
        font-size: 28px;
        color: #111827;
        font-weight: 950;
        line-height: 1.15;
        word-break: keep-all;
    }
    .pr-kpi-sub {
        font-size: 12px;
        color: #94A3B8;
        font-weight: 600;
        margin-top: 8px;
    }
    .pr-command {
        border: 1px solid #BFDBFE;
        background: linear-gradient(180deg, #EFF6FF, #EAF3FF);
        border-radius: 22px;
        padding: 24px;
        margin: 18px 0 22px 0;
    }
    .pr-command-badge {
        display: inline-block;
        background: #0B66D8;
        color: #ffffff;
        border-radius: 999px;
        padding: 6px 12px;
        font-size: 12px;
        font-weight: 900;
        margin-bottom: 12px;
    }
    .pr-command-title {
        font-size: 24px;
        font-weight: 950;
        color: #0F3F7A;
        line-height: 1.35;
        letter-spacing: -0.03em;
    }
    .pr-command-sub {
        margin-top: 12px;
        background: rgba(255, 255, 255, 0.75);
        border-radius: 14px;
        padding: 12px 14px;
        color: #334155;
        font-size: 14px;
        font-weight: 650;
    }
    .pr-layout {
        display: grid;
        grid-template-columns: minmax(0, 1.8fr) minmax(280px, 0.9fr);
        gap: 18px;
        align-items: start;
    }
    .pr-section-title {
        font-size: 22px;
        font-weight: 950;
        color: #111827;
        margin-bottom: 4px;
    }
    .pr-section-sub {
        font-size: 13px;
        color: #64748B;
        font-weight: 650;
        margin-bottom: 16px;
    }
    .pr-lead-card {
        border: 1px solid #E4EAF2;
        border-radius: 18px;
        padding: 18px;
        margin-bottom: 14px;
        background: #ffffff;
    }
    .pr-rank {
        display: inline-block;
        background: #0B66D8;
        color: white;
        border-radius: 10px;
        padding: 5px 10px;
        font-size: 13px;
        font-weight: 900;
        margin-right: 8px;
    }
    .pr-status {
        display: inline-block;
        background: #EFF6FF;
        color: #1D4ED8;
        border-radius: 999px;
        padding: 5px 10px;
        font-size: 12px;
        font-weight: 850;
    }
    .pr-customer {
        font-size: 21px;
        font-weight: 950;
        color: #111827;
        margin-top: 12px;
    }
    .pr-subject {
        font-size: 13px;
        color: #64748B;
        font-weight: 650;
        margin-top: 3px;
    }
    .pr-lead-main {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 14px;
        align-items: start;
        border-bottom: 1px solid #EDF2F7;
        padding-bottom: 14px;
        margin-bottom: 14px;
    }
    .pr-profit-label {
        font-size: 12px;
        color: #64748B;
        font-weight: 800;
        text-align: right;
    }
    .pr-profit {
        font-size: 25px;
        font-weight: 950;
        color: #0B66D8;
        white-space: nowrap;
        text-align: right;
    }
    .pr-mini-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin: 12px 0;
    }
    .pr-mini {
        background: #F8FAFC;
        border-radius: 12px;
        padding: 11px;
        font-size: 12px;
        color: #334155;
        font-weight: 750;
    }
    .pr-ai {
        background: #F1F7FF;
        border: 1px solid #D7E8FF;
        border-radius: 14px;
        padding: 13px 15px;
        color: #0F3F7A;
        font-size: 14px;
        font-weight: 750;
        line-height: 1.7;
        margin-top: 12px;
    }
    .pr-side-row {
        border-bottom: 1px solid #EDF2F7;
        padding: 13px 0;
        color: #334155;
        font-size: 14px;
        line-height: 1.6;
    }
    .pr-side-row:last-child {
        border-bottom: none;
    }
    .pr-alert {
        background: #FFF7ED;
        border: 1px solid #FED7AA;
        color: #9A3412;
        border-radius: 18px;
        padding: 18px;
        font-weight: 800;
        margin-top: 16px;
    }
    @media (max-width: 980px) {
        .pr-kpi-grid { grid-template-columns: 1fr 1fr; }
        .pr-layout { grid-template-columns: 1fr; }
        .pr-mini-grid { grid-template-columns: 1fr; }
        .pr-lead-main { grid-template-columns: 1fr; }
        .pr-profit, .pr-profit-label { text-align: left; }
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="pr-title">
        <h1>今日の利益</h1>
        <p>社長が朝見るだけで、今日やるべき案件が分かるAI司令塔</p>
    </div>
    """, unsafe_allow_html=True)

    if df_view.empty:
        st.info("表示できる案件がありません。Gmail接続タブで解析してください。")
        return

    home_df = df_view.copy()

    required_cols = [
        "id", "customer", "subject", "status", "pipeline_stage",
        "next_action", "recoverable_profit", "estimated_profit",
        "actual_revenue", "profit_confidence", "profit_basis",
        "neglected_days", "opportunity_score", "revenue_score",
        "category", "content", "memo"
    ]

    for col in required_cols:
        if col not in home_df.columns:
            home_df[col] = ""

    for col in [
        "recoverable_profit", "estimated_profit", "actual_revenue",
        "profit_confidence", "neglected_days", "opportunity_score", "revenue_score"
    ]:
        home_df[col] = pd.to_numeric(home_df[col], errors="coerce").fillna(0)

    def ai_action_text(row):
        status = str(row.get("status", "") or "")
        profit = _num(row.get("recoverable_profit")) or _num(row.get("estimated_profit"))
        days = _num(row.get("neglected_days"))
        conf = _num(row.get("profit_confidence"))
        subject = str(row.get("subject", "") or "")
        category = str(row.get("category", "") or "")
        next_action = str(row.get("next_action", "") or "")

        if "返信" in status:
            return "相手から返信があります。今日中に内容確認して、止めずに返してください。"
        if conf <= 25 or _num(row.get("estimated_profit")) <= 0:
            return "金額未確定です。まず金額・条件・進行可否を確認してください。"
        if days >= 7 and profit >= 30000:
            return "放置リスクがあります。今日中に返信して、案件を前に進めてください。"
        if "契約" in subject or "契約" in category:
            return "契約条件を確認し、進行できるか今日中に返してください。"
        if next_action and len(next_action) >= 4:
            return next_action
        return "今日中に短く確認連絡を入れてください。"

    def priority_score(row):
        base = _num(row.get("opportunity_score")) or _num(row.get("revenue_score"))
        recoverable = _num(row.get("recoverable_profit"))
        estimated = _num(row.get("estimated_profit"))
        actual = _num(row.get("actual_revenue"))
        conf = _num(row.get("profit_confidence"))
        days = _num(row.get("neglected_days"))
        status = str(row.get("status", "") or "")
        profit = recoverable if recoverable > 0 else estimated

        score = base
        score += min(profit // 5000, 30)
        score += min(days * 2, 20)

        if "返信" in status:
            score += 45
        if status == "未対応":
            score += 20
        if status == "保留":
            score -= 10
        if status in ["対応済み", "成約", "失注", "除外", "完了"]:
            score -= 200

        text = str(row.get("subject", "")) + str(row.get("category", "")) + str(row.get("next_action", ""))
        if conf <= 25 or estimated <= 0:
            if any(k in text for k in ["契約", "条件", "見積", "請求", "発注", "確認"]):
                score += 18
            if days <= 3:
                score += 8

        if actual > 0:
            score -= 80

        return int(score)

    active_df = home_df[
        ~home_df["status"].astype(str).isin(["対応済み", "成約", "失注", "除外", "完了"])
    ].copy()

    if active_df.empty:
        st.success("今日対応すべき案件はありません。")
        return

    active_df["home_priority_score"] = active_df.apply(priority_score, axis=1)
    active_df["profit_for_today"] = active_df["recoverable_profit"]
    active_df.loc[active_df["profit_for_today"] <= 0, "profit_for_today"] = active_df["estimated_profit"]

    active_df = active_df.sort_values(
        ["home_priority_score", "profit_for_today", "neglected_days"],
        ascending=False
    )

    top_df = active_df.head(3).copy()
    today_expected_profit = _num(top_df["profit_for_today"].sum())
    actual_total = _num(home_df["actual_revenue"].sum())
    reply_count = int(active_df["status"].astype(str).str.contains("返信").sum())
    danger_count = int((active_df["neglected_days"] >= 7).sum())

    first = top_df.iloc[0]
    first_id = _num(first.get("id"))
    first_customer = _clean_customer(first.get("customer"))
    first_profit = _num(first.get("profit_for_today"))

    st.markdown(f"""
    <div class="pr-kpi-grid">
        <div class="pr-card">
            <div class="pr-kpi-label">今日の回収期待値</div>
            <div class="pr-kpi-value">{money(today_expected_profit)}</div>
            <div class="pr-kpi-sub">上位案件を処理した場合の期待値</div>
        </div>
        <div class="pr-card">
            <div class="pr-kpi-label">今日やる件数</div>
            <div class="pr-kpi-value">{len(top_df)}件</div>
            <div class="pr-kpi-sub">AIが絞り込んだ優先案件</div>
        </div>
        <div class="pr-card">
            <div class="pr-kpi-label">返信あり</div>
            <div class="pr-kpi-value">{reply_count}件</div>
            <div class="pr-kpi-sub">止めると機会損失になる案件</div>
        </div>
        <div class="pr-card">
            <div class="pr-kpi-label">実利益累計</div>
            <div class="pr-kpi-value">{money(actual_total)}</div>
            <div class="pr-kpi-sub">保存済みの実回収額</div>
        </div>
    </div>

    <div class="pr-command">
        <div class="pr-command-badge">AIの結論</div>
        <div class="pr-command-title">今日は「{first_customer}」を最優先で対応してください。</div>
        <div class="pr-command-sub">期待値は {money(first_profit)}。返信状況・利益期待値・放置日数から、今日もっとも動かす価値が高い案件です。</div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("最優先案件を今すぐ対応する", key="home_go_reply_primary", use_container_width=True):
        st.session_state["home_selected_lead_id"] = first_id
        st.session_state["selected_lead_id"] = first_id
        st.success("今すぐ返信タブに案件を反映しました。上部の「今すぐ返信」を開いてください。")

    st.markdown('<div class="pr-layout">', unsafe_allow_html=True)

    st.markdown("""
    <div class="pr-card">
        <div class="pr-section-title">今日やること</div>
        <div class="pr-section-sub">AIが選んだ優先案件です。処理は「今すぐ返信」タブで行います。</div>
    """, unsafe_allow_html=True)

    for idx, (_, row) in enumerate(top_df.iterrows(), start=1):
        lead_id = _num(row.get("id"))
        customer = _clean_customer(row.get("customer"))
        subject = safe_text(row.get("subject", ""), "件名なし")
        status = str(row.get("status", "") or "要確認")
        profit = _num(row.get("profit_for_today"))
        recoverable = _num(row.get("recoverable_profit"))
        conf = _num(row.get("profit_confidence"))
        days = _num(row.get("neglected_days"))
        action = ai_action_text(row)

        st.markdown(f"""
        <div class="pr-lead-card">
            <div class="pr-lead-main">
                <div>
                    <span class="pr-rank">#{idx}</span>
                    <span class="pr-status">{status}</span>
                    <div class="pr-customer">{customer}</div>
                    <div class="pr-subject">{subject}</div>
                </div>
                <div>
                    <div class="pr-profit-label">期待回収</div>
                    <div class="pr-profit">{money_or_unknown(profit)}</div>
                </div>
            </div>
            <div class="pr-mini-grid">
                <div class="pr-mini">信頼度　{conf}%</div>
                <div class="pr-mini">回収期待　{money_or_unknown(recoverable)}</div>
                <div class="pr-mini">放置日数　{days}日</div>
            </div>
            <div class="pr-ai">AI指示：{action}</div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("この案件を今すぐ返信で開く", key=f"home_open_reply_{lead_id}", use_container_width=True):
            st.session_state["home_selected_lead_id"] = lead_id
            st.session_state["selected_lead_id"] = lead_id
            st.success("今すぐ返信タブに案件を反映しました。上部の「今すぐ返信」を開いてください。")

    st.markdown("</div>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("### 社長への判断材料")
        st.caption("細かい処理ではなく、判断だけを表示します。")

        st.markdown("**最優先**")
        st.write(f"{first_customer}を今日中に対応")
        st.divider()

        st.markdown("**返信あり**")
        st.write(f"{reply_count}件。放置すると成約率が落ちます。")
        st.divider()

        st.markdown("**放置注意**")
        st.write(f"{danger_count}件。3日以上止まっている案件を確認してください。")
        st.divider()

        st.markdown("**今日の方針**")
        st.write("新規作業より、上位案件の返信・条件確認を優先。")

    if danger_count > 0:
        st.markdown(f"""
        <div class="pr-alert">
            注意：放置リスクがある案件が {danger_count} 件あります。今日中に返信または状態更新してください。
        </div>
        """, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("AI経営ブリーフを見る", expanded=False):
        if render_ai_executive_brief:
            render_ai_executive_brief(
                active_df=active_df,
                top_df=top_df,
                home_df=home_df,
                money=money,
            )

    with st.expander("AI売上予測を見る", expanded=False):
        if render_ai_sales_forecast:
            render_ai_sales_forecast(
                home_df=home_df,
                active_df=active_df,
                money=money,
            )
