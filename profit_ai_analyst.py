import os
import sqlite3
from datetime import datetime
from openai import OpenAI

DB = "profit_radar.db"


def ensure_profit_ai_cache_table():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS profit_ai_analysis_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER,
        input_hash TEXT,
        analysis_text TEXT,
        created_at TEXT,
        updated_at TEXT,
        UNIQUE(lead_id, input_hash)
    )
    """)
    conn.commit()
    conn.close()


def _hash_input(*parts):
    import hashlib
    raw = "\n".join(str(p or "") for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fallback_analysis(estimated_profit, recoverable_profit, actual_revenue):
    if int(actual_revenue or 0) > 0:
        return f"""AI利益分析:
・実利益として {int(actual_revenue):,}円 が入力されています。
・この金額はユーザー入力に基づくため、AI推定より優先されます。

不足情報:
・追加確認は任意です。

次に確認:
・入金状況や継続案件の有無を確認してください。"""

    if int(estimated_profit or 0) <= 0 or int(recoverable_profit or 0) <= 0:
        return """AI利益分析:
・この案件は金額未確定です。
・現時点では売上予測ではなく、確認すべき営業案件として扱います。
・メール本文だけでは契約金額や条件を判断できません。

不足情報:
・金額、条件、時期、進行可否。

次に確認:
・相手に金額条件と進行可否を確認してください。"""

    return f"""AI利益分析:
・現在の金額はAI推定またはルール推定による目安です。
・案件金額候補は {int(estimated_profit or 0):,}円、回収期待値は {int(recoverable_profit or 0):,}円です。
・確定売上ではありません。

不足情報:
・契約金額、支払い条件、確定可否。

次に確認:
・相手に金額条件と進行可否を確認してください。"""


def build_profit_ai_analysis(
    lead_id=None,
    customer="",
    subject="",
    content="",
    estimated_profit=0,
    recoverable_profit=0,
    profit_basis="",
    profit_confidence=0,
    actual_revenue=0,
    force_refresh=False,
):
    estimated_profit = int(estimated_profit or 0)
    recoverable_profit = int(recoverable_profit or 0)
    actual_revenue = int(actual_revenue or 0)
    profit_confidence = int(profit_confidence or 0)

    input_hash = _hash_input(
        customer,
        subject,
        content[:2500],
        estimated_profit,
        recoverable_profit,
        profit_basis,
        profit_confidence,
        actual_revenue,
    )

    if lead_id is not None:
        ensure_profit_ai_cache_table()
        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        if not force_refresh:
            cur.execute("""
            SELECT analysis_text
            FROM profit_ai_analysis_cache
            WHERE lead_id=? AND input_hash=?
            ORDER BY id DESC
            LIMIT 1
            """, (int(lead_id), input_hash))
            row = cur.fetchone()
            if row and row[0]:
                conn.close()
                return row[0]

        conn.close()

    prompt = f"""
あなたはProfit RadarのAI利益分析官です。
社長が営業案件を判断するために、金額の根拠を短く正確に説明してください。

重要ルール:
- 確定していない金額を確定売上のように言わない
- メール本文にない金額を断定しない
- 金額根拠が弱い場合は「要確認」と明記する
- 案件金額候補が0円、または信頼度25%以下の場合は「金額未確定」と明記する
- 金額未確定の場合、売上予測ではなく「確認すべき営業案件」として説明する
- 金額未確定の場合、確認項目は「金額・条件・時期・進行可否」を優先する
- 人材派遣専用に寄せない
- 業種を勝手に断定しない
- 社長が次に何を確認すべきかを書く
- 文章は日本語
- 5〜8行以内
- 顧客に送る文ではなく、社内判断用の説明

入力:
顧客: {customer}
件名: {subject}
本文:
{content[:2500]}

案件金額候補: {estimated_profit}円
回収期待値: {recoverable_profit}円
既存推定根拠: {profit_basis}
信頼度: {profit_confidence}%
実利益: {actual_revenue}円

出力形式:
AI利益分析:
・
・
・

不足情報:
・

次に確認:
・
"""

    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY missing")

        client = OpenAI(api_key=api_key)

        res = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            messages=[
                {"role": "system", "content": "あなたは営業CRMの利益分析AIです。誇張せず、根拠と不足情報を明確に説明します。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )

        analysis_text = res.choices[0].message.content.strip()

    except Exception:
        analysis_text = _fallback_analysis(estimated_profit, recoverable_profit, actual_revenue)

    if lead_id is not None:
        try:
            conn = sqlite3.connect(DB)
            cur = conn.cursor()
            now = datetime.now().isoformat()
            cur.execute("""
            INSERT OR REPLACE INTO profit_ai_analysis_cache
            (lead_id, input_hash, analysis_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """, (int(lead_id), input_hash, analysis_text, now, now))
            conn.commit()
            conn.close()
        except Exception:
            pass

    return analysis_text
