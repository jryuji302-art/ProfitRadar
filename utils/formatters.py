import html
import re


def safe(v):
    return html.escape(str(v or ""))


def safe_text(value, default=""):
    try:
        if value is None:
            return default
        text = str(value)
        if text.strip() == "":
            return default
        return text
    except Exception:
        return default


def money(v):
    try:
        return f"¥{int(float(v or 0)):,}"
    except Exception:
        return "¥0"


def money_or_unknown(value):
    """
    金額表示用。
    None/空/0/低信頼の金額は「金額未確定」と表示する。
    """
    try:
        if value is None:
            return "金額未確定"
        s = str(value).strip()
        if s == "" or s.lower() in ["nan", "none", "null"]:
            return "金額未確定"
        n = int(float(s))
        if n <= 0:
            return "金額未確定"
        return f"¥{n:,}"
    except Exception:
        return "金額未確定"


def clean_reply_body(body):
    if not body:
        return ""

    text = str(body)

    # Gmail引用を軽く除去
    text = re.split(r"\n\d{4}年.*? wrote:", text)[0]
    text = re.split(r"\nOn .* wrote:", text)[0]
    text = re.split(r"\n>+", text)[0]

    return text.strip()
