import os
from openai import OpenAI

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def _client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY が設定されていません。")
    return OpenAI(api_key=api_key)


def build_sales_ai(
    customer="",
    subject="",
    lead_content="",
    last_sent_body="",
    reply_body="",
    memo="",
    estimated_profit=0,
    recoverable_profit=0,
    actual_revenue=0,
    mode="reply"
):
    prompt = f"""
あなたは中小企業・個人事業主向けのトップ営業責任者です。
目的は、相手との関係を壊さず、案件を前進させ、利益回収確率を上げることです。

以下の営業情報を読み、意味を理解して判断してください。

【顧客】
{customer}

【件名】
{subject}

【元メール・案件内容】
{lead_content}

【最後にこちらが送った内容】
{last_sent_body}

【相手の返信】
{reply_body}

【メモ】
{memo}

【利益情報】
推定利益: {estimated_profit}円
回収可能利益: {recoverable_profit}円
実利益: {actual_revenue}円

出力は必ず以下の形式にしてください。
長文禁止。社長が3秒で判断できるように短く具体的に出してください。
推奨返信文は100〜180文字程度。署名・[あなたの名前]・[会社名]・[連絡先]は禁止。

案件状態:
成約確率:
想定利益:
今やること:
放置リスク:
推奨返信文:
"""

    res = _client().responses.create(
        model=MODEL,
        input=prompt,
        temperature=0.2,
    )

    return res.output_text.strip()


def fallback_sales_ai(reply_body="", estimated_profit=0, recoverable_profit=0):
    body = reply_body or ""
    profit = int(recoverable_profit or estimated_profit or 0)

    if "お願いします" in body or "お願い致します" in body or "進めてください" in body:
        return f"""案件状態: 成約目前
成約確率: 85%
想定利益: {profit:,}円
今やること: 日程・場所・人数・単価・請求条件を確認
放置リスク: 条件認識ズレで後から揉める可能性
推奨返信文: ありがとうございます。それでは進行いたします。念のため、日程・場所・人数・単価・請求条件だけ確認させてください。"""

    return f"""案件状態: 要確認
成約確率: 50%
想定利益: {profit:,}円
今やること: 相手の意図と次に進む条件を確認
放置リスク: 案件が止まり自然消滅する可能性
推奨返信文: ご返信ありがとうございます。次に進めるため、条件面について確認させてください。"""
