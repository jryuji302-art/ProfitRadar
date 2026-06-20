import re

NG_WORDS = [
    "絶対儲かる",
    "必ず稼げる",
    "100%保証",
    "違法",
    "脱税",
    "詐欺",
]

def validate_email_address(email):
    if not email:
        return False
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None

def check_message_safety(to_email, subject, body):
    errors = []
    warnings = []

    if not validate_email_address(to_email):
        errors.append("送信先メールアドレスが不正です。")

    if not subject or len(subject.strip()) < 2:
        errors.append("件名が空、または短すぎます。")

    if not body or len(body.strip()) < 20:
        errors.append("本文が短すぎます。")

    if len(body) > 3000:
        warnings.append("本文が長すぎます。簡潔化推奨。")

    for word in NG_WORDS:
        if word in body:
            errors.append(f"危険表現を検出: {word}")

    if "様" not in body and "お世話になっております" not in body:
        warnings.append("ビジネスメールとして宛名・挨拶が弱い可能性があります。")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings
    }

def check_duplicate_send(lead_id, action_type="reply", days=3):
    import sqlite3
    from datetime import datetime, timedelta

    conn = sqlite3.connect("profit_radar.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    since = (datetime.now() - timedelta(days=days)).isoformat()

    c.execute("""
    SELECT id, created_at, status
    FROM profit_actions
    WHERE lead_id=?
      AND action_type=?
      AND status IN ('sent', 'draft')
      AND created_at >= ?
    ORDER BY created_at DESC
    LIMIT 1
    """, (lead_id, action_type, since))

    row = c.fetchone()
    conn.close()

    if row:
        return {
            "ok": False,
            "message": f"重複送信リスク: 過去{days}日以内に同じLeadへ {action_type} 履歴があります。",
            "last_action_id": row["id"],
            "last_created_at": row["created_at"],
            "last_status": row["status"],
        }

    return {
        "ok": True,
        "message": "重複送信リスクなし",
    }
