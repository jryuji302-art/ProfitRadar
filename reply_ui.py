import re
import streamlit as st
from error_handler import handle_error, log_info, log_warning, log_error


def build_unknown_amount_confirm_message(customer, subject):
    customer = str(customer or "").split("<")[0].strip() or "ご担当者"
    subject = str(subject or "先日の件").strip()

    return f"""お世話になっております。

下記の件について、進行条件を確認させてください。

件名：{subject}

現時点で、金額・条件・進行可否について確認できればと思っております。

差し支えなければ、以下をご共有いただけますでしょうか。

・ご依頼内容
・ご予算または想定金額
・進行時期
・次に必要な対応

ご確認よろしくお願いいたします。"""


def render_reply_screen(lead, context="reply", deps=None):
    """
    共通返信画面。
    Home / 要対応 / 顧客 から同じUIを呼ぶための部品。
    app.py側の既存関数は deps で受け取る。
    """
    deps = deps or {}

    money = deps["money"]
    money_or_unknown = deps.get("money_or_unknown", money)
    safe_text = deps["safe_text"]
    clean_customer_name = deps.get("clean_customer_name", lambda v: str(v or "不明顧客"))
    build_sales_ai = deps["build_sales_ai"]
    fallback_sales_ai = deps["fallback_sales_ai"]
    render_ceo_sales_card = deps["render_ceo_sales_card"]
    extract_recommended_reply_from_ai = deps["extract_recommended_reply_from_ai"]
    validate_send_body = deps["validate_send_body"]
    send_gmail_reply = deps["send_gmail_reply"]
    save_action = deps["save_action"]
    save_action_log = deps["save_action_log"]
    update_lead_status = deps["update_lead_status"]
    update_actual_revenue = deps.get("update_actual_revenue")
    save_ai_learning = deps.get("save_ai_learning")
    build_profit_ai_analysis = deps.get("build_profit_ai_analysis")

    lead_id = int(lead.get("id", 0) or 0)
    customer = clean_customer_name(lead.get("customer", ""))
    subject = str(lead.get("subject", "") or "").strip() or "ご確認のお願い"

    def safe_action_log(action_type, message, result):
        try:
            save_action_log(lead_id, action_type, message, result)
        except Exception:
            pass

    c1, c2 = st.columns([1, 1])
    c1.metric("回収期待値", money_or_unknown(lead.get("recoverable_profit", 0)))
    c2.metric("案件金額候補", money_or_unknown(lead.get("estimated_profit", 0)))

    profit_basis = str(lead.get("profit_basis", "") or "")
    profit_confidence = int(lead.get("profit_confidence", 0) or 0)

    if build_profit_ai_analysis is not None:
        with st.expander("AI利益分析を見る", expanded=True):
            try:
                force_refresh_profit_ai = st.button(
                    "AI利益分析を再生成",
                    key=f"{context}_refresh_profit_ai_{lead_id}",
                    use_container_width=True
                )

                profit_ai_text = build_profit_ai_analysis(
                    lead_id=lead_id,
                    customer=str(lead.get("customer", "")),
                    subject=subject,
                    content=str(lead.get("content", "")),
                    estimated_profit=int(lead.get("estimated_profit", 0) or 0),
                    recoverable_profit=int(lead.get("recoverable_profit", 0) or 0),
                    profit_basis=profit_basis,
                    profit_confidence=profit_confidence,
                    actual_revenue=int(lead.get("actual_revenue", 0) or 0),
                    force_refresh=force_refresh_profit_ai,
                )
                st.markdown(profit_ai_text)
            except Exception as e:
                log_warning(f"AI利益分析表示エラー: {e}")
                st.warning("AI利益分析を表示できませんでした。")
    elif profit_basis:
        st.caption(f"推定根拠：{profit_basis}")
        st.caption(f"信頼度：{profit_confidence}%")

    st.markdown(f"### {customer}")
    st.caption(safe_text(lead.get("subject", ""), "件名なし"))

    with st.expander("元メールを見る"):
        st.text_area(
            "メール本文",
            str(lead.get("content", "") or ""),
            height=180,
            key=f"{context}_body_{lead_id}"
        )

    st.markdown("### AI判断")

    try:
        ai_advice = build_sales_ai(
            customer=str(lead.get("customer", "")),
            subject=subject,
            lead_content=str(lead.get("content", "")),
            last_sent_body="",
            reply_body="",
            memo=str(lead.get("memo", "")),
            estimated_profit=int(lead.get("estimated_profit", 0) or 0),
            recoverable_profit=int(lead.get("recoverable_profit", 0) or 0),
            actual_revenue=int(lead.get("actual_revenue", 0) or 0),
            mode=context
        )
    except Exception as e:
        ai_advice = fallback_sales_ai(
            reply_body=str(lead.get("content", "")),
            estimated_profit=int(lead.get("estimated_profit", 0) or 0),
            recoverable_profit=int(lead.get("recoverable_profit", 0) or 0)
        ) + f"\n\n補足: OpenAI未使用: {e}"

    render_ceo_sales_card(
        ai_advice,
        fallback_profit=int(lead.get("recoverable_profit", 0) or 0)
    )

    st.markdown("### 返信文")

    try:
        default_follow = extract_recommended_reply_from_ai(ai_advice)
    except Exception:
        default_follow = ""

    if not default_follow or len(default_follow) < 10:
        default_follow = f"""お世話になっております。

下記の件について、進行状況を確認させてください。

件名：{subject}

ご確認いただき、進められそうであれば次の流れをご相談できればと思います。
よろしくお願いいたします。"""

    follow_body = st.text_area(
        "必要なら編集してください。",
        default_follow,
        height=180,
        key=f"{context}_follow_{lead_id}"
    )

    customer_raw = str(lead.get("customer", "") or "")
    email_match = re.search(r"<([^>]+)>", customer_raw)
    default_to_email = email_match.group(1).strip() if email_match else ""

    to_email = st.text_input(
        "送信先メールアドレス",
        default_to_email,
        key=f"{context}_to_{lead_id}"
    )

    st.markdown("### 実利益")

    current_actual = int(lead.get("actual_revenue", 0) or 0)
    actual_value = st.number_input(
        "実際に回収できた利益",
        min_value=0,
        step=1000,
        value=current_actual,
        key=f"{context}_actual_revenue_{lead_id}"
    )

    if st.button("実利益を保存", key=f"{context}_save_actual_revenue_{lead_id}", use_container_width=True):
        if update_actual_revenue is None:
            st.error("実利益保存関数が読み込まれていません。")
        else:
            update_actual_revenue(
                lead_id,
                int(actual_value or 0),
                user_id=st.session_state.get("user_id"),
                company_id=st.session_state.get("company_id")
            )

            if save_ai_learning is not None:
                try:
                    save_ai_learning(
                        lead_id=lead_id,
                        customer=str(lead.get("customer", "")),
                        subject=subject,
                        ai_decision="共通返信画面から実利益保存",
                        result="成約" if int(actual_value or 0) > 0 else "実利益更新",
                        actual_revenue=int(actual_value or 0),
                        note="reply_ui.pyから実利益を保存"
                    )
                except Exception:
                    pass

            st.success("実利益を保存しました。")
            st.rerun()

    st.divider()

    st.markdown("### 案件状態")

    col_done, col_pending, col_open = st.columns(3)

    with col_done:
        if st.button("対応済みにする", key=f"{context}_mark_done_{lead_id}", use_container_width=True):
            update_lead_status(
                lead_id,
                "対応済み",
                user_id=st.session_state.get("user_id"),
                company_id=st.session_state.get("company_id")
            )
            safe_action_log("status_update", "対応済みに変更", "done")
            st.success("対応済みにしました。")
            st.rerun()

    with col_pending:
        if st.button("保留にする", key=f"{context}_mark_pending_{lead_id}", use_container_width=True):
            update_lead_status(
                lead_id,
                "保留",
                user_id=st.session_state.get("user_id"),
                company_id=st.session_state.get("company_id")
            )
            safe_action_log("status_update", "保留に変更", "pending")
            st.warning("保留にしました。")
            st.rerun()

    with col_open:
        if st.button("未対応に戻す", key=f"{context}_mark_open_{lead_id}", use_container_width=True):
            update_lead_status(
                lead_id,
                "未対応",
                user_id=st.session_state.get("user_id"),
                company_id=st.session_state.get("company_id")
            )
            safe_action_log("status_update", "未対応に変更", "open")
            st.info("未対応に戻しました。")
            st.rerun()

    st.divider()

    col_save, col_send = st.columns([1, 1])

    with col_save:
        if st.button("フォロー文を保存", key=f"{context}_save_follow_{lead_id}", use_container_width=True):
            try:
                save_action(
                    lead_id=lead_id,
                    gmail_id=str(lead.get("gmail_id", "")),
                    action_type="follow_text_saved",
                    to_email=to_email,
                    subject=subject,
                    body=follow_body,
                    status="saved",
                    user_id=st.session_state.get("user_id"),
                    company_id=st.session_state.get("company_id")
                )
                st.success("フォロー文を保存しました。")
            except Exception as e:
                safe_action_log("follow_text_saved", follow_body, "saved")
                log_warning(f"返信文保存フォールバック: {e}")
                st.warning("返信文を簡易保存しました。")

    with col_send:
        if st.button("Gmail送信", key=f"{context}_send_follow_{lead_id}", use_container_width=True):
            try:
                if not to_email:
                    st.error("送信先メールアドレスを入力してください。")
                    raise RuntimeError("送信先メールアドレス未入力")

                send_errors = validate_send_body(follow_body)
                if send_errors:
                    st.error("送信停止：本文に問題があります。")
                    for err in send_errors:
                        st.warning(err)
                    raise RuntimeError("送信前安全チェックで停止しました。")

                result = send_gmail_reply(
                    gmail_id=str(lead.get("gmail_id", "")),
                    to_email=to_email,
                    subject=subject,
                    body=follow_body,
                    lead_id=lead_id,
                    action_type="gmail_reply",
                    force_send=False,
                    user_id=st.session_state.get("user_id"),
                    company_id=st.session_state.get("company_id")
                )

                gmail_result_id = result.get("id", "")

                save_action(
                    lead_id=lead_id,
                    gmail_id=str(lead.get("gmail_id", "")),
                    action_type="gmail_reply",
                    to_email=to_email,
                    subject=subject,
                    body=follow_body,
                    status="sent",
                    safety_ok=1,
                    gmail_result_id=gmail_result_id,
                    user_id=st.session_state.get("user_id"),
                    company_id=st.session_state.get("company_id")
                )

                update_lead_status(
                    lead_id,
                    "対応済み",
                    user_id=st.session_state.get("user_id"),
                    company_id=st.session_state.get("company_id")
                )

                st.success(f"Gmail送信完了: {gmail_result_id}")
                st.rerun()

            except Exception as e:
                try:
                    save_action(
                        lead_id=lead_id,
                        gmail_id=str(lead.get("gmail_id", "")),
                        action_type="gmail_reply_failed",
                        to_email=to_email,
                        subject=subject,
                        body=follow_body,
                        status="failed",
                        safety_ok=0,
                        safety_errors=str(e),
                        user_id=st.session_state.get("user_id"),
                        company_id=st.session_state.get("company_id")
                    )
                except Exception:
                    pass

                handle_error(e, "Gmail送信に失敗しました。送信先・Gmail接続状態を確認してください。")
