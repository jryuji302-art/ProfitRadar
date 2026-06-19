def _safe(v, default=""):
    if v is None:
        return default
    return str(v)

def _num(v, default=0):
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default

def detect_intent(subject="", content=""):
    text = f"{subject}\n{content}"

    rules = {
        "質問": ["？", "?", "教えて", "確認したい", "可能ですか", "できますか", "どうなって"],
        "依頼": ["お願い", "依頼", "対応", "手配", "送って", "作成"],
        "見積": ["見積", "金額", "費用", "単価", "料金", "いくら"],
        "契約": ["契約", "発注", "決定", "進めたい", "お願いします"],
        "請求": ["請求", "請求書", "入金", "振込", "支払い", "未入金"],
        "採用": ["採用", "面談", "面接", "候補者", "応募", "稼働", "人材"],
        "日程": ["日程", "候補日", "何日", "いつ", "時間", "調整"],
    }

    for name, words in rules.items():
        if any(w in text for w in words):
            return name

    return "不明"

def detect_temperature(subject="", content="", category="", stage=""):
    text = f"{subject}\n{content}\n{category}\n{stage}"

    hot = ["発注", "契約", "決定", "お願いします", "進めたい", "採用決定", "入金しました"]
    warm = ["見積", "検討", "候補", "相談", "比較", "確認します", "前向き"]
    cold = ["保留", "見送り", "失注", "不要", "今回は", "キャンセル"]

    if any(w in text for w in cold):
        return "低"
    if any(w in text for w in hot):
        return "高"
    if any(w in text for w in warm):
        return "中"

    return "中"

def build_ai_advice(lead):
    def get(k, d=""):
        try:
            return lead.get(k, d)
        except Exception:
            try:
                return lead[k]
            except Exception:
                return d

    customer = _safe(get("customer", "顧客"))
    subject = _safe(get("subject", ""))
    content = _safe(get("content", ""))
    category = _safe(get("category", "不明"))
    stage = _safe(get("pipeline_stage", "新規"))
    risk = _safe(get("risk_level", "中"))
    reason = _safe(get("reason", ""))
    next_action = _safe(get("next_action", ""))
    score = _num(get("opportunity_score", get("revenue_score", 0)))
    days = _num(get("neglected_days", 0))
    profit = _num(get("estimated_profit", get("recoverable_profit", 0)))

    intent = detect_intent(subject, content)
    temp = detect_temperature(subject, content, category, stage)

    if risk == "高":
        decision = "慎重に追うべき案件です。送信前に内容確認が必要です。"
    elif score >= 75 or temp == "高":
        decision = "優先して追うべき案件です。早めの対応が利益化につながる可能性があります。"
    elif score >= 45 or temp == "中":
        decision = "追う価値はあります。ただし、温度確認と次アクションの明確化が必要です。"
    else:
        decision = "優先度は低めです。工数をかけすぎず、軽い確認に留めるべきです。"

    reasons = [
        f"分類は「{category}」、ステージは「{stage}」です。",
        f"顧客意図は「{intent}」、営業温度は「{temp}」です。",
    ]

    if profit > 0:
        reasons.append(f"推定利益は約{profit:,}円です。")
    if score > 0:
        reasons.append(f"案件スコアは{score}です。")
    if days > 0:
        reasons.append(f"未対応期間は{days}日です。")
    if reason:
        reasons.append(f"補足理由：{reason}")

    risks = []
    if risk == "高":
        risks.append("条件誤認・誤送信・相手温度の読み違いリスクがあります。")
    if days >= 7:
        risks.append("対応遅れにより、競合流出または失注の可能性があります。")
    if intent == "質問":
        risks.append("相手の質問に回答せず質問で返すと、信頼低下につながります。")
    if category == "不明":
        risks.append("分類が不明のため、判断精度が下がっています。")
    if not risks:
        risks.append("大きなリスクは低めですが、送信前の事実確認は必要です。")

    if intent == "質問":
        action = "相手の質問に直接回答してください。不明点がある場合のみ、最後に1つだけ確認してください。"
    elif intent == "見積":
        action = "見積条件・金額・期限を整理し、相手が判断しやすい形で返信してください。"
    elif intent == "契約":
        action = "契約条件・開始日・請求条件を確認し、次の手続きを提示してください。"
    elif intent == "請求":
        action = "請求書・入金状況・支払期限を確認し、事実ベースで案内してください。"
    elif intent == "採用":
        action = "候補者・日程・稼働条件を整理し、次の面談または紹介導線を提示してください。"
    elif intent == "日程":
        action = "候補日時を2〜3個提示し、相手が選ぶだけの形にしてください。"
    elif next_action:
        action = next_action
    else:
        action = "短文で状況確認し、次に進める条件を明確にしてください。"

    return {
        "判断": decision,
        "理由": " ".join(reasons),
        "リスク": " ".join(risks),
        "推奨アクション": action,
    }

def format_ai_advice(advice):
    return f"""判断
{advice.get("判断", "")}

理由
{advice.get("理由", "")}

リスク
{advice.get("リスク", "")}

推奨アクション
{advice.get("推奨アクション", "")}
"""


def build_ai_dashboard_advice(leads):
    """
    複数案件からAI案件参謀の全体判断を作る
    leads: list[dict] / pandas DataFrame
    """
    try:
        if hasattr(leads, "to_dict"):
            rows = leads.to_dict("records")
        else:
            rows = list(leads)
    except Exception:
        rows = []

    if not rows:
        return {
            "最優先案件": "未対応案件はありません。",
            "理由": "分析対象の案件データがありません。",
            "リスク案件": "なし",
            "今日の推奨アクション": "Gmail解析を実行して、利益候補を検出してください。",
        }

    def get(row, key, default=""):
        try:
            return row.get(key, default)
        except Exception:
            return default

    def num(v, default=0):
        try:
            if v is None or v == "":
                return default
            return int(float(v))
        except Exception:
            return default

    sorted_rows = sorted(
        rows,
        key=lambda r: (
            num(get(r, "opportunity_score", get(r, "revenue_score", 0))),
            num(get(r, "estimated_profit", get(r, "recoverable_profit", 0))),
            num(get(r, "neglected_days", 0)),
        ),
        reverse=True
    )

    top = sorted_rows[0]
    top_customer = get(top, "customer", "顧客不明")
    top_subject = get(top, "subject", "件名なし")
    top_score = num(get(top, "opportunity_score", get(top, "revenue_score", 0)))
    top_profit = num(get(top, "estimated_profit", get(top, "recoverable_profit", 0)))
    top_days = num(get(top, "neglected_days", 0))
    top_category = get(top, "category", "不明")

    risk_rows = [
        r for r in rows
        if str(get(r, "risk_level", "")) == "高" or num(get(r, "neglected_days", 0)) >= 7
    ]

    if risk_rows:
        risk_top = sorted(
            risk_rows,
            key=lambda r: (
                num(get(r, "neglected_days", 0)),
                num(get(r, "opportunity_score", get(r, "revenue_score", 0))),
            ),
            reverse=True
        )[0]
        risk_text = f"{get(risk_top, 'customer', '顧客不明')} / 未対応{num(get(risk_top, 'neglected_days', 0))}日 / {get(risk_top, 'subject', '件名なし')}"
    else:
        risk_text = "重大なリスク案件は検出されていません。"

    if top_score >= 75:
        action = "最優先案件に本日中に返信してください。送信前に条件・金額・宛先を確認してください。"
    elif risk_rows:
        action = "未対応日数が長い案件から処理してください。失注防止を優先します。"
    else:
        action = "上位案件から順番に状況確認し、次のアクションを明確にしてください。"

    return {
        "最優先案件": f"{top_customer} / {top_subject}",
        "理由": f"分類は「{top_category}」、Scoreは{top_score}、推定利益は約{top_profit:,}円、未対応は{top_days}日です。",
        "リスク案件": risk_text,
        "今日の推奨アクション": action,
    }

def format_ai_dashboard_advice(advice):
    return f"""最優先案件
{advice.get("最優先案件", "")}

理由
{advice.get("理由", "")}

リスク案件
{advice.get("リスク案件", "")}

今日の推奨アクション
{advice.get("今日の推奨アクション", "")}
"""
