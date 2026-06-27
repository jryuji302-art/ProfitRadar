import re


def _to_int(text):
    if not text:
        return 0

    raw = str(text).replace(",", "").replace("，", "").strip()

    try:
        if "万円" in raw or "万" in raw:
            num = re.sub(r"[^0-9.]", "", raw)
            return int(float(num) * 10000)

        num = re.sub(r"[^0-9.]", "", raw)
        if not num:
            return 0

        return int(float(num))
    except Exception:
        return 0


def extract_money_values(text):
    text = str(text or "")

    patterns = [
        r"(?:税込|税抜|合計|総額|金額|費用|料金|見積|請求|報酬|単価|日当|月額|年額)?\s*([0-9,\.]+)\s*万円",
        r"(?:税込|税抜|合計|総額|金額|費用|料金|見積|請求|報酬|単価|日当|月額|年額)?\s*([0-9,\.]+)\s*万",
        r"(?:税込|税抜|合計|総額|金額|費用|料金|見積|請求|報酬|単価|日当|月額|年額)?\s*([0-9,\.]+)\s*円",
    ]

    values = []

    for pat in patterns:
        for m in re.finditer(pat, text):
            raw = m.group(0).strip()
            val = _to_int(raw)
            if val > 0:
                values.append({"raw": raw, "value": val})

    # 小さすぎる数字・日付っぽい数字を除外しすぎない範囲で整理
    clean = []
    seen = set()

    for v in values:
        val = int(v["value"])
        if val in seen:
            continue
        seen.add(val)

        # 100円未満は利益予測として使わない
        if val < 100:
            continue

        clean.append(v)

    return clean


def estimate_profit_from_text(subject="", content="", category="", actual_revenue=0):
    """
    汎用・控えめ利益推定。
    業種ごとの人数×日数計算はしない。
    明記された金額だけを根拠にする。
    """
    text = f"{subject}\n{content}\n{category}"

    if int(actual_revenue or 0) > 0:
        return {
            "estimated_profit": int(actual_revenue),
            "recoverable_profit": int(actual_revenue),
            "confidence": 95,
            "basis": f"実利益入力済み: {int(actual_revenue):,}円",
            "unit_price": int(actual_revenue),
            "people": 0,
            "days": 0,
            "gross_amount": int(actual_revenue),
            "profit_rate": 1.0,
        }

    money_values = extract_money_values(text)

    if not money_values:
        return {
            "estimated_profit": 0,
            "recoverable_profit": 0,
            "confidence": 20,
            "basis": "明記金額なし。金額確認が必要。",
            "unit_price": 0,
            "people": 0,
            "days": 0,
            "gross_amount": 0,
            "profit_rate": 0.0,
        }

    # メール内の最大金額を採用。ただし「利益」ではなく「明記金額ベースの見込み」として扱う
    amount = max(v["value"] for v in money_values)

    # 確定ではないため、回収可能は控えめに50%
    recoverable = int(amount * 0.5)

    basis_items = [f"{v['raw']}→{int(v['value']):,}円" for v in money_values[:3]]
    basis = "明記金額ベース: " + " / ".join(basis_items)

    confidence = 65
    if any(k in text for k in ["契約", "発注", "請求", "請求書", "入金", "振込", "確定", "合意"]):
        confidence += 15
    if any(k in text for k in ["相談", "可能でしょうか", "検討", "予定", "概算"]):
        confidence -= 10

    confidence = max(30, min(90, confidence))

    return {
        "estimated_profit": int(amount),
        "recoverable_profit": int(recoverable),
        "confidence": confidence,
        "basis": basis,
        "unit_price": int(amount),
        "people": 0,
        "days": 0,
        "gross_amount": int(amount),
        "profit_rate": 0.0,
    }
