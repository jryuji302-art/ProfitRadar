import sqlite3
import pandas as pd
import streamlit as st

from error_handler import handle_error


def render_gmail_tab(
    db_path,
    safe,
    render_gmail_oauth_settings,
    fetch_recent_emails,
    save_email_as_lead,
    detect_replies,
    ensure_reply_detection_columns,
):
    render_gmail_oauth_settings()

    st.divider()

    st.markdown("### メール解析")
    st.caption("Gmailから利益候補を探します。")

    analysis_limit = st.slider("確認するメール数", 10, 100, 30)

    if st.button("Gmailを解析する"):
        try:
            emails = fetch_recent_emails(
                limit=analysis_limit,
                user_id=st.session_state.get("user_id"),
                company_id=st.session_state.get("company_id")
            )

            count = 0
            for email in emails:
                if save_email_as_lead(
                    email,
                    user_id=st.session_state.get("user_id"),
                    company_id=st.session_state.get("company_id")
                ):
                    count += 1

            st.success(f"{count}件の利益候補を検出しました。")

        except Exception as e:
            handle_error(e, "Gmail解析に失敗しました。接続状態または認証情報を確認してください。")

    st.divider()

    st.markdown("### 返信チェック")
    st.caption("送信済みメールに返信が来ているか確認します。")

    if st.button("返信をチェックする"):
        try:
            results = detect_replies(
                limit=30,
                user_id=st.session_state.get("user_id"),
                company_id=st.session_state.get("company_id")
            )

            ok_results = [r for r in results if not r.get("error")]
            error_results = [r for r in results if r.get("error")]

            if ok_results:
                st.success(f"{len(ok_results)}件の返信を検知しました。")
                for r in ok_results[:5]:
                    st.markdown(f"""
                    <div class="lead-card">
                        <div>
                            <div class="lead-title">返信あり</div>
                            <div class="lead-sub">{safe(r.get("from_email", ""))}</div>
                        </div>
                        <div class="lead-money">{safe(r.get("subject", "件名なし"))}</div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("新しい返信はありません。")

            if error_results:
                st.warning("一部の返信確認に失敗しました。時間をおいて再実行してください。")

        except Exception as e:
            handle_error(e, "返信チェックに失敗しました。時間をおいて再実行してください。")

    st.divider()

    st.markdown("### 最近の返信")
    try:
        ensure_reply_detection_columns()

        conn = sqlite3.connect(db_path)
        recent_replies = pd.read_sql_query("""
            SELECT from_email, subject, detected_at
            FROM reply_detection_logs
            ORDER BY id DESC
            LIMIT 5
        """, conn)
        conn.close()

        if recent_replies.empty:
            st.info("返信確認履歴はまだありません。")
        else:
            for _, r in recent_replies.iterrows():
                st.markdown(f"""
                <div class="lead-card">
                    <div>
                        <div class="lead-title">{safe(r.get("subject", "件名なし"))}</div>
                        <div class="lead-sub">From: {safe(r.get("from_email", ""))}</div>
                    </div>
                    <div class="lead-days">{safe(str(r.get("detected_at", ""))[:16])}</div>
                </div>
                """, unsafe_allow_html=True)

    except Exception as e:
        handle_error(e, "最近の返信履歴を表示できませんでした。")
