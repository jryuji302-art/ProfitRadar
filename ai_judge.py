import os
import json
from pathlib import Path
from dotenv import load_dotenv
from google import genai

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def judge_email(subject, sender, body):
    if not GEMINI_API_KEY or GEMINI_API_KEY == "ここにGeminiAPIキー":
        return fallback_judge(subject, body)

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
あなたはProfit RadarのRUDIA Revenue Judgeです。
以下のGmailが売上・案件・請求・営業フォローに関係するか判定してください。

必ずJSONだけで返してください。

形式：
{{
  "is_lead": true,
  "customer": "相手名または会社名",
  "estimated_profit": 100000,
  "risk_level": "低/中/高",
  "neglected_days": 7,
  "next_action": "次にやるべき行動",
  "reason": "判定理由"
}}

From:
{sender}

Subject:
{subject}

Body:
{body[:3000]}
"""

    try:
        res = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        text = res.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        data = fallback_judge(subject, body)
        data["reason"] = f"Gemini判定失敗のため簡易判定: {e}"
        return data

def fallback_judge(subject, body):
    text = f"{subject} {body}"
    keywords = ["見積", "請求", "契約", "提案", "発注", "案件", "紹介", "採用", "面談", "依頼", "支払い", "入金"]
    is_lead = any(k in text for k in keywords)

    return {
        "is_lead": is_lead,
        "customer": "",
        "estimated_profit": 100000,
        "risk_level": "中",
        "neglected_days": 7,
        "next_action": "フォロー確認",
        "reason": "売上関連キーワードを検出"
    }
