import pandas as pd
import streamlit as st


def _int(v):
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def build_customer_rank(row):
    actual = _int(row.get("実利益", 0))
    expected = _int(row.get("回収期待値利益", 0))
    open_count = _int(row.get("未対応数", 0))
    pending = _int(row.get("保留数", 0))
    done = _int(row.get("対応済み数", 0))
    max_days = _int(row.get("最大未対応日数", 0))

    score = 0
    score += min(actual // 10000, 40)
    score += min(expected // 10000, 30)
    score += min(open_count * 8, 20)
    score += min(done * 3, 10)
    score -= min(pending * 4, 12)
    score -= min(max_days, 20)

    score = max(0, min(100, score))

    if score >= 80:
        rank = "S"
        label = "最重要顧客"
    elif score >= 60:
        rank = "A"
        label = "優先顧客"
    elif score >= 35:
        rank = "B"
        label = "通常顧客"
    else:
        rank = "C"
        label = "低優先"

    if max_days >= 14:
        risk = "高"
    elif max_days >= 7:
        risk = "中"
    else:
        risk = "低"

    return {
        "rank": rank,
        "label": label,
        "score": score,
        "risk": risk,
    }


def render_customer_rank_summary(customer_summary, money):
    if customer_summary is None or customer_summary.empty:
        return

    df = customer_summary.copy()
    ranks = df.apply(build_customer_rank, axis=1, result_type="expand")
    df = pd.concat([df.reset_index(drop=True), ranks.reset_index(drop=True)], axis=1)

    st.markdown("### 👑 顧客ランク")

    s_count = int((df["rank"] == "S").sum())
    a_count = int((df["rank"] == "A").sum())
    risk_count = int((df["risk"] == "高").sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("S顧客", f"{s_count}件")
    c2.metric("A顧客", f"{a_count}件")
    c3.metric("離脱危険", f"{risk_count}件")

    top_df = df.sort_values(["score", "実利益", "回収期待値利益"], ascending=False).head(5)

    for _, r in top_df.iterrows():
        customer = str(r.get("customer", "") or "不明顧客")
        rank = r.get("rank", "C")
        label = r.get("label", "")
        score = _int(r.get("score", 0))
        risk = r.get("risk", "低")
        actual = _int(r.get("実利益", 0))
        expected = _int(r.get("回収期待値利益", 0))

        with st.container(border=True):
            st.markdown(f"**{rank}ランク｜{label}**")
            st.markdown(f"### {customer}")
            a, b, c = st.columns(3)
            a.metric("実利益", money(actual))
            b.metric("回収期待値", money(expected))
            c.metric("危険度", risk)
            st.caption(f"顧客スコア：{score}/100")
