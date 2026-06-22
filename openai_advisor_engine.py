import os
import sqlite3
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(".env")

DB = "profit_radar.db"
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def _safe(v, default=""):
    if v is None:
        return default
    return str(v)


def _get(lead, k, d=""):
    try:
        return lead.get(k, d)
    except Exception:
        try:
            return lead[k]
        except Exception:
            return d


def load_customer_history(customer, lead_id=None, limit=5):
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT id, subject, category, pipeline_stage, estimated_profit,
                   recoverable_profit, opportunity_score, risk_level,
                   neglected_days, next_action, reason, created_at
            FROM profit_leads
            WHERE customer = ?
            ORDER BY id DESC
            LIMIT ?
        """, (customer, limit))

        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def load_action_history(lead_id, limit=5):
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT action_type, message, status, sent_at, created_at,
                   safety_ok, safety_errors, safety_warnings
            FROM profit_actions
            WHERE lead_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (lead_id, limit))

        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def format_history(rows):
    if not rows:
        return "履歴なし"

    lines = []
    for r in rows:
        parts = []
        for k, v in r.items():
            if v not in [None, ""]:
                parts.append(f"{k}: {v}")
        lines.append(" / ".join(parts))
    return "\n".join(lines)


def build_openai_advice(lead):
    api_key = os.getenv("OPENAI_API_KEY", "")

    if not api_key or api_key == "ここにOpenAI_APIキー":
        raise RuntimeError("OPENAI_API_KEYが未設定です。.envにAPIキーを入れてください。")

    client = OpenAI(api_key=api_key)

    lead_id = _get(lead, "id", "")
    customer = _safe(_get(lead, "customer", ""))
    subject = _safe(_get(lead, "subject", ""))
    content = _safe(_get(lead, "content", ""))
    category = _safe(_get(lead, "category", ""))
    stage = _safe(_get(lead, "pipeline_stage", ""))
    risk = _safe(_get(lead, "risk_level", ""))
    score = _safe(_get(lead, "opportunity_score", _get(lead, "revenue_score", "")))
    estimated_profit = _safe(_get(lead, "estimated_profit", ""))
    recoverable_profit = _safe(_get(lead, "recoverable_profit", ""))
    days = _safe(_get(lead, "neglected_days", ""))
    next_action = _safe(_get(lead, "next_action", ""))
    reason = _safe(_get(lead, "reason", ""))

    customer_history = load_customer_history(customer, lead_id=lead_id, limit=5)
    action_history = load_action_history(lead_id, limit=5)

    prompt = f"""
あなたはProfit Radarの案件参謀AIです。
顧客向け画面ではRUDIAという名称を絶対に出さず、「AI」として振る舞ってください。

目的:
営業メール・案件情報・顧客履歴・送信履歴を読み、
この案件を追うべきか、失注リスク、次の行動を判断する。

必ず以下の形式だけで回答してください。

成約確率
...%

利益期待値
...円

営業温度
高 / 中 / 低

判断
...

理由
...

リスク
...

推奨返信文
...

次アクション
...

判断基準:
- 相手が質問している場合、質問で返さず、まず回答方針を出す
- 相手が依頼している場合、次に必要な作業を明確化する
- 見積・契約・請求・採用・日程調整を区別する
- 過去履歴がある場合は、それを踏まえて判断する
- 送信履歴がある場合は、重複送信やしつこい追客を避ける
- 未対応日数が長い場合は失注リスクを上げる
- 金額、日程、契約条件が曖昧な場合はリスクに書く
- 成約確率は0〜100%で出す。ただし根拠が弱い場合は断定しすぎない
- 利益期待値は「推定利益 × 成約確率」を目安にする
- 営業温度は 高 / 中 / 低 の3段階にする
- 推奨返信文は、そのまま顧客に送れる自然な日本語に近づける
- 次アクションは「今日やる行動」にする
- 相手が質問している場合、質問返しで逃げず、先に回答方針を出す
- 根拠のない断定は禁止
- 日本語で簡潔に書く
- 顧客にそのまま見せても違和感がない表現にする

現在の案件:
顧客: {customer}
件名: {subject}
分類: {category}
ステージ: {stage}
危険度: {risk}
Score: {score}
推定利益: {estimated_profit}
回収可能利益: {recoverable_profit}
未対応日数: {days}
次の行動: {next_action}
判定理由: {reason}

メール本文:
{content}

顧客の過去案件履歴:
{format_history(customer_history)}

この案件の送信履歴:
{format_history(action_history)}
"""

    res = client.responses.create(
        model=MODEL,
        input=prompt,
    )

    advice = res.output_text.strip()

    save_ai_advice_log(
        lead_id=lead_id,
        customer=customer,
        subject=subject,
        advice=advice
    )

    return advice


def init_ai_advice_db():
    try:
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS ai_advice_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER,
                customer TEXT,
                subject TEXT,
                model TEXT,
                advice TEXT,
                created_at TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        pass


def save_ai_advice_log(lead_id, customer, subject, advice):
    try:
        from datetime import datetime
        init_ai_advice_db()

        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("""
            INSERT INTO ai_advice_logs
            (lead_id, customer, subject, model, advice, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            lead_id,
            customer,
            subject,
            MODEL,
            advice,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()
        conn.close()
    except Exception:
        pass
