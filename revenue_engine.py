import re


EXCLUDE_KEYWORDS = [
    # 認証・セキュリティ
    "security", "alert", "認証", "認証コード", "verification", "verification code",
    "ログイン", "login", "signin", "sign in", "password", "パスワード",
    "2段階認証", "二段階認証", "ワンタイム", "otp", "code",

    # 自動送信
    "no-reply", "noreply", "do-not-reply", "donotreply", "自動送信",
    "配信専用", "返信不可",

    # 大手通知・AI通知
    "google", "gemini", "openai", "chatgpt", "apple", "icloud",
    "microsoft", "github", "notion", "slack", "discord",

    # メルマガ・広告
    "newsletter", "ニュースレター", "メールマガジン", "メルマガ",
    "キャンペーン", "広告", "通知", "お知らせ", "news", "update",
    "アップデート", "セール", "クーポン", "特典", "無料",

    # 決済・領収書系ノイズ
    "receipt", "領収書", "ご利用明細", "明細", "利用明細",
    "決済完了", "購入完了", "注文確認", "注文完了",

    # 既知ノイズ
    "moneyforward", "マネーフォワード", "biz.moneyforward.com", "noreply.biz"
]

CATEGORY_KEYWORDS = {
    "請求・入金": ["請求", "請求書", "支払い", "入金", "未入金", "振込", "報酬"],
    "提案・見積": ["見積", "提案", "再提案", "発注", "受注", "契約", "契約書", "業務委託"],
    "採用・人材": ["採用", "人材", "応募", "面談", "面接", "候補者", "求人", "勤務", "稼働", "スタッフ", "イベント"],
    "休眠顧客": ["以前", "その後", "状況確認", "ご無沙汰", "再開", "検討状況"],
    "フォロー必要": ["確認", "相談", "依頼", "日程", "返信", "ご連絡"]
}

PROFIT_KEYWORDS = [
    # 売上・契約
    "見積", "見積依頼", "お見積り", "請求", "請求書", "契約", "契約書",
    "発注", "ご発注", "受注", "成約", "申込", "申し込み", "業務委託",
    "案件", "案件紹介", "提案", "再提案", "検討状況",

    # お金
    "単価", "日当", "報酬", "支払い", "お支払い", "入金", "未入金",
    "振込", "売上", "料金", "費用", "月額", "年額", "更新", "継続",
    "解約", "キャンセル料",

    # 納品・業務進行
    "納品", "納期", "修正", "追加対応", "作業依頼", "正式依頼",
    "開始日", "実施日", "稼働日", "日程調整",

    # BtoB商談
    "商談", "打ち合わせ", "打合せ", "面談日程", "導入", "導入検討",
    "トライアル", "デモ", "資料請求", "問い合わせ", "お問い合わせ",

    # 人材系も最低限残す
    "採用", "面談", "面接", "応募", "稼働", "求人", "勤務",
    "イベント", "スタッフ", "人材", "候補者", "採用決定", "募集"
]


def normalize_text(text):
    return (text or "").lower()


def contains_any(text, keywords):
    text_l = normalize_text(text)
    return any(k.lower() in text_l for k in keywords)


def count_profit_signals(text):
    text_l = normalize_text(text)
    return sum(1 for k in PROFIT_KEYWORDS if k.lower() in text_l)


def classify_email(text):
    scores = {}

    for category, keywords in CATEGORY_KEYWORDS.items():
        scores[category] = sum(1 for k in keywords if k in text)

    best_category = max(scores, key=scores.get)

    if scores[best_category] == 0:
        return "不明"

    return best_category


def extract_money_numbers(text):
    values = []

    patterns = [
        r"([0-9,]+)\s*円",
        r"単価\s*[:：]?\s*([0-9,]+)",
        r"日当\s*[:：]?\s*([0-9,]+)",
        r"報酬\s*[:：]?\s*([0-9,]+)",
    ]

    for pattern in patterns:
        for m in re.findall(pattern, text):
            try:
                values.append(int(str(m).replace(",", "")))
            except Exception:
                pass

    return values


def extract_count(text, keywords, default=1):
    for key in keywords:
        m = re.search(rf"([0-9]+)\s*{key}", text)
        if m:
            return int(m.group(1))
    return default


def estimate_profit(text, category):
    money_values = extract_money_numbers(text)

    people = extract_count(text, ["名", "人"], 1)
    days = extract_count(text, ["日"], 1)
    cases = extract_count(text, ["件"], 1)

    if money_values:
        base = max(money_values)

        if people > 1 or days > 1:
            return base * people * days

        if cases > 1:
            return base * cases

        return base

    if category == "請求・入金":
        return 150000
    if category == "提案・見積":
        return 200000
    if category == "採用・人材":
        return 120000
    if category == "休眠顧客":
        return 80000
    if category == "フォロー必要":
        return 70000

    return 0


def risk_from_days_and_category(neglected_days, category):
    if category in ["提案・見積", "請求・入金"] and neglected_days >= 7:
        return "高"
    if neglected_days >= 14:
        return "高"
    if neglected_days <= 3:
        return "低"
    return "中"


def next_action_for_category(category):
    return {
        "請求・入金": "入金・請求状況を確認",
        "提案・見積": "検討状況を確認",
        "採用・人材": "候補者・稼働状況を確認",
        "休眠顧客": "再提案",
        "フォロー必要": "フォロー確認",
        "不明": "内容確認",
    }.get(category, "内容確認")



def calculate_opportunity_score(text, category, estimated_profit, neglected_days, subject=""):
    score = 0

    subject_bonus_keywords = [
        "見積", "見積依頼", "請求", "請求書", "契約", "契約書",
        "発注", "受注", "成約", "申込", "採用決定", "入金", "未入金"
    ]

    if contains_any(subject, subject_bonus_keywords):
        score += 20

    signal_points = {
        "契約": 40,
        "発注": 35,
        "受注": 35,
        "請求": 30,
        "請求書": 30,
        "入金": 30,
        "採用決定": 30,
        "面談日程": 20,
        "面談": 18,
        "面接": 18,
        "候補者": 15,
        "スタッフ": 15,
        "人材": 15,
        "稼働": 15,
        "見積": 20,
        "提案": 18,
    }

    for keyword, point in signal_points.items():
        if keyword in text:
            score += point

    category_points = {
        "請求・入金": 25,
        "提案・見積": 22,
        "採用・人材": 20,
        "休眠顧客": 12,
        "フォロー必要": 10,
        "不明": 0,
    }
    score += category_points.get(category, 0)

    if estimated_profit >= 300000:
        score += 20
    elif estimated_profit >= 150000:
        score += 15
    elif estimated_profit >= 70000:
        score += 8

    if neglected_days >= 30:
        score += 40
    elif neglected_days >= 14:
        score += 20
    elif neglected_days >= 7:
        score += 10

    return max(0, min(score, 100))


def calculate_recoverable_profit(estimated_profit, opportunity_score):
    if opportunity_score >= 85:
        rate = 0.75
    elif opportunity_score >= 70:
        rate = 0.60
    elif opportunity_score >= 50:
        rate = 0.40
    elif opportunity_score >= 30:
        rate = 0.25
    else:
        rate = 0.10

    return int(estimated_profit * rate)


def analyze_email(subject, body, neglected_days=7):
    text = f"{subject or ''} {body or ''}"

    if contains_any(text, EXCLUDE_KEYWORDS):
        return {
            "is_profit_lead": False,
            "category": "ノイズ",
            "estimated_profit": 0,
            "risk_level": "低",
            "next_action": "保存不要",
            "reason": "除外キーワードを検出"
        }

    signal_count = count_profit_signals(text)

    strong_keywords = [
        "契約", "契約書", "請求", "請求書", "発注", "受注",
        "成約", "採用決定", "入金", "未入金", "振込"
    ]

    if signal_count < 2 and not contains_any(text, strong_keywords):
        return {
            "is_profit_lead": False,
            "category": "ノイズ",
            "estimated_profit": 0,
            "risk_level": "低",
            "next_action": "保存不要",
            "reason": "利益シグナル不足"
        }

    category = classify_email(text)
    estimated_profit = estimate_profit(text, category)

    if estimated_profit <= 0:
        return {
            "is_profit_lead": False,
            "category": "不明",
            "estimated_profit": 0,
            "risk_level": "低",
            "next_action": "保存不要",
            "reason": "利益推定不可"
        }

    opportunity_score = calculate_opportunity_score(text, category, estimated_profit, neglected_days, subject)
    opportunity_score = apply_learning_boost(category, opportunity_score)
    hot_lead = 1 if opportunity_score >= 80 else 0
    recoverable_profit = calculate_recoverable_profit(estimated_profit, opportunity_score)

    return {
        "is_profit_lead": True,
        "category": category,
        "estimated_profit": int(estimated_profit),
        "risk_level": risk_from_days_and_category(neglected_days, category),
        "next_action": next_action_for_category(category),
        "reason": f"{category}として分類。Opportunity Score {opportunity_score}。利益候補として保存",
        "opportunity_score": opportunity_score,
        "hot_lead": hot_lead,
        "recoverable_profit": recoverable_profit
    }


def generate_follow_message(customer, subject, content, category="フォロー必要"):
    customer = str(customer or "ご担当者様").strip()
    subject = str(subject or "先日の件").strip()
    content = str(content or "")

    # 本文から状況ワードを拾う
    has_money = any(k in content for k in ["見積", "お見積", "請求", "入金", "未入金", "振込", "支払い"])
    has_schedule = any(k in content for k in ["日程", "稼働日", "面談", "面接", "予定", "候補日"])
    has_people = any(k in content for k in ["人材", "スタッフ", "候補者", "採用", "募集", "人数"])
    has_contract = any(k in content for k in ["契約", "発注", "受注", "業務委託", "契約書"])
    has_adjust = any(k in content for k in ["条件", "単価", "日当", "報酬", "調整", "変更"])

    if category == "請求・入金":
        main = "ご請求・お支払い状況について、現在の確認状況を伺いたくご連絡いたしました。"
        sub = "入金予定日や確認中の点があれば、ご共有いただけますと幸いです。"

    elif category == "提案・見積":
        main = "以前ご提案・お見積りさせていただいた件について、現在のご検討状況を確認したくご連絡いたしました。"
        sub = "条件の調整や再見積りが必要であれば、改めて整理いたします。"

    elif category == "採用・人材":
        main = "候補者様・稼働予定・採用進捗について、現在の状況を確認したくご連絡いたしました。"
        sub = "必要人数・稼働日・条件に変更があれば、再度調整いたします。"

    elif category == "休眠顧客":
        main = "以前のご相談内容を踏まえ、現在の募集状況やお困りごとがないか確認したくご連絡いたしました。"
        sub = "再開予定や新しい案件があれば、すぐ対応できるよう準備いたします。"

    else:
        main = "以前ご連絡いただいていた件について、現在のご状況を確認したくご連絡いたしました。"
        sub = "必要であれば、内容を整理したうえで次の対応をご提案いたします。"

    # 本文特徴で一文追加
    detail_lines = []

    if has_schedule:
        detail_lines.append("日程や進行予定に変更がないかも、あわせて確認できればと思います。")
    if has_people:
        detail_lines.append("必要人数や候補者条件が変わっている場合も、再調整可能です。")
    if has_contract:
        detail_lines.append("契約・発注に進める場合は、必要事項をこちらで整理いたします。")
    if has_adjust:
        detail_lines.append("単価・条件面の調整が必要な場合も、遠慮なくお知らせください。")
    if has_money and category != "請求・入金":
        detail_lines.append("金額面についても、必要であれば再確認いたします。")

    detail = "\n".join(detail_lines[:2])

    if detail:
        detail_block = f"\n{detail}\n"
    else:
        detail_block = ""

    return f"""件名：{subject}のご確認

{customer} 様

いつもお世話になっております。

{main}

{sub}
{detail_block}
ご確認よろしくお願いいたします。
"""

# =========================
# Learning Score Boost
# =========================
def apply_learning_boost(category, base_score):
    """
    learning_patterns の成功率を使って Opportunity Score を補正する。
    強く効かせすぎると危険なので、初期は ±10点まで。
    """
    import sqlite3

    try:
        conn = sqlite3.connect("profit_radar.db")
        c = conn.cursor()

        c.execute("""
        SELECT success_count, failure_count
        FROM learning_patterns
        WHERE category=?
        """, (category,))

        rows = c.fetchall()
        conn.close()

        success = sum(r[0] or 0 for r in rows)
        failure = sum(r[1] or 0 for r in rows)
        total = success + failure

        if total < 3:
            return base_score

        success_rate = success / total

        if success_rate >= 0.7:
            base_score += 10
        elif success_rate >= 0.55:
            base_score += 5
        elif success_rate <= 0.25:
            base_score -= 10
        elif success_rate <= 0.4:
            base_score -= 5

        return max(0, min(100, int(base_score)))

    except Exception:
        return base_score
