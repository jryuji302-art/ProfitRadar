import os
import sqlite3
import re
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(".env")

DB = "profit_radar.db"
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def init_followup_ai_logs():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_followup_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer TEXT,
            subject TEXT,
            category TEXT,
            model TEXT,
            generated_text TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_followup_ai_log(customer, subject, category, generated_text):
    try:
        init_followup_ai_logs()
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("""
            INSERT INTO ai_followup_logs
            (customer, subject, category, model, generated_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            customer,
            subject,
            category,
            MODEL,
            generated_text,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()
        conn.close()
    except Exception:
        pass


def extract_body_only(text):
    """
    AI出力から送信用本文だけを抽出する。
    送る理由・期待結果・判断材料は絶対に送信本文へ入れない。
    """
    if not text:
        return ""

    # 本文: 以降を取得
    m = re.search(r"本文\s*[:：]\s*(.*)", text, re.S)
    if m:
        body = m.group(1).strip()
    else:
        body = text.strip()

    # 送信用でない項目を削除
    stop_labels = [
        "送る理由", "期待結果", "理由", "リスク", "推奨アクション", "判断"
    ]

    for label in stop_labels:
        pattern = rf"\n\s*{label}\s*[:：].*"
        body = re.sub(pattern, "", body, flags=re.S).strip()

    # 件名が混ざった場合も削除
    body = re.sub(r"^件名\s*[:：].*\n", "", body).strip()

    return body


def generate_followup(customer, subject, content, category="", history=""):
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEYが未設定です。")

    client = OpenAI(api_key=api_key)

    prompt = f"""
あなたはProfit Radarの営業返信AIです。

目的:
受信メールの意味を読み取り、相手にそのまま送れる返信本文だけを作る。

重要:
出力は送信本文のみ。
「件名」「送る理由」「期待結果」「判断」「リスク」「推奨アクション」は絶対に出力しない。
顧客に送ってはいけない内部説明を入れない。

返信ルール:
- 相手が質問している場合、質問で返さず、まず回答する
- 不明点がある場合だけ、最後に1つだけ確認する
- 押し売り感を出さない
- 日本語は自然にする
- 短く読みやすくする
- 根拠のない約束は禁止
- 金額、日程、契約条件が不明な場合は断定しない
- そのままGmail送信できる本文だけを書く

顧客:
{customer}

件名:
{subject}

カテゴリ:
{category}

履歴:
{history}

受信内容:
{content}
"""

    res = client.responses.create(
        model=MODEL,
        input=prompt,
    )

    full_text = res.output_text.strip()
    save_followup_ai_log(customer, subject, category, full_text)

    return extract_body_only(full_text)
