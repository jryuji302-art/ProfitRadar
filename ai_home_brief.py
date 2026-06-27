import pandas as pd
import streamlit as st


def _safe_int(v):
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def render_ai_executive_brief(active_df, top_df, home_df, money):
    """
    社長向けAI経営ブリーフ。
    朝30秒で今日の営業判断を終わらせるための要約。
    """
    if active_df is None or active_df.empty:
        st.success("AI経営ブリーフ：本日対応が必要な案件はありません。")
        return

    today_expected = _safe_int(top_df["profit_for_today"].sum()) if "profit_for_today" in top_df.columns else 0
    active_count = len(active_df)
    top_count = len(top_df)

    reply_count = 0
    if "status" in active_df.columns:
        reply_count = int(active_df["status"].astype(str).str.contains("返信").sum())

    low_conf_count = 0
    if "profit_confidence" in active_df.columns:
        low_conf_count = int((pd.to_numeric(active_df["profit_confidence"], errors="coerce").fillna(0) <= 25).sum())

    danger_count = 0
    if "neglected_days" in active_df.columns:
        danger_count = int((pd.to_numeric(active_df["neglected_days"], errors="coerce").fillna(0) >= 7).sum())

    actual_total = 0
    if home_df is not None and not home_df.empty and "actual_revenue" in home_df.columns:
        actual_total = _safe_int(pd.to_numeric(home_df["actual_revenue"], errors="coerce").fillna(0).sum())

    first = top_df.iloc[0] if top_df is not None and not top_df.empty else None
    first_customer = "なし"
    first_profit = 0
    first_reason = "本日優先案件はありません。"

    if first is not None:
        first_customer = str(first.get("customer", "") or "不明顧客").split("<")[0].strip() or "不明顧客"
        first_profit = _safe_int(first.get("profit_for_today", 0))
        status = str(first.get("status", "") or "")
        conf = _safe_int(first.get("profit_confidence", 0))
        days = _safe_int(first.get("neglected_days", 0))

        if "返信" in status:
            first_reason = "相手から返信があります。今日中に返すと案件が前に進みやすい状態です。"
        elif conf <= 25:
            first_reason = "金額根拠が弱いため、まず条件確認で精度を上げるべき案件です。"
        elif days >= 7:
            first_reason = "放置日数が長く、失注リスクが上がっています。"
        else:
            first_reason = "期待値と優先度が高いため、今日処理すべき案件です。"

    st.markdown("### 🧠 AI経営ブリーフ")

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("今日の期待利益", money(today_expected))
    b2.metric("今日やる件数", f"{top_count}件")
    b3.metric("返信あり", f"{reply_count}件")
    b4.metric("実利益累計", money(actual_total))

    st.info(
        f"本日は **{top_count}件だけ対応**してください。"
        f"最優先は **{first_customer}**。"
        f"期待値は **{money(first_profit)}** です。"
    )

    st.caption(f"AI理由：{first_reason}")

    alerts = []
    if low_conf_count > 0:
        alerts.append(f"金額根拠が弱い案件 {low_conf_count}件")
    if danger_count > 0:
        alerts.append(f"放置リスク案件 {danger_count}件")
    if active_count > top_count:
        alerts.append(f"後回し可能案件 {active_count - top_count}件")

    if alerts:
        st.warning(" / ".join(alerts))

    with st.expander("AIの今日の作戦を見る", expanded=False):
        st.write("1. まず返信あり案件を処理")
        st.write("2. 次に回収期待値が高い案件を処理")
        st.write("3. 金額根拠が弱い案件は、返信より先に条件確認")
        st.write("4. 対応後は必ず「対応済み」または「保留」に変更")
