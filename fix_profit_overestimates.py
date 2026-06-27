import sqlite3
from profit_estimator import estimate_profit_from_text

DB = "profit_radar.db"
DEFAULT_OVER_ESTIMATES = {70000, 80000, 120000, 150000, 200000}

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

rows = cur.execute("""
SELECT id, subject, content, category, estimated_profit, recoverable_profit,
       actual_revenue, profit_basis, profit_confidence
FROM profit_leads
""").fetchall()

fixed = 0
updated_basis = 0

for r in rows:
    actual = int(r["actual_revenue"] or 0)
    old_est = int(r["estimated_profit"] or 0)
    old_basis = str(r["profit_basis"] or "")
    old_conf = int(r["profit_confidence"] or 0)

    est = estimate_profit_from_text(
        subject=r["subject"] or "",
        content=r["content"] or "",
        category=r["category"] or "",
        actual_revenue=actual
    )

    new_est = int(est.get("estimated_profit", 0) or 0)
    new_rec = int(est.get("recoverable_profit", 0) or 0)
    new_basis = str(est.get("basis", "") or "")
    new_conf = int(est.get("confidence", 0) or 0)

    # 実利益入力済みは実利益優先
    if actual > 0:
        cur.execute("""
        UPDATE profit_leads
        SET estimated_profit=?,
            recoverable_profit=?,
            profit_basis=?,
            profit_confidence=?,
            unit_price_detected=?,
            people_detected=?,
            days_detected=?
        WHERE id=?
        """, (
            actual,
            actual,
            f"実利益入力済み: {actual:,}円",
            95,
            actual,
            0,
            0,
            int(r["id"])
        ))
        updated_basis += 1
        continue

    # 明記金額がないのに固定高額が残っている場合は未確定化
    is_old_human_basis = any(k in old_basis for k in ["人数", "日数", "単価根拠"])
    is_low_conf_default = old_conf <= 25 and old_est in DEFAULT_OVER_ESTIMATES

    if new_est <= 0 and (is_old_human_basis or is_low_conf_default):
        cur.execute("""
        UPDATE profit_leads
        SET estimated_profit=0,
            recoverable_profit=0,
            profit_basis=?,
            profit_confidence=20,
            unit_price_detected=0,
            people_detected=0,
            days_detected=0
        WHERE id=?
        """, (
            "明記金額なし。金額未確定。相手に金額・条件確認が必要。",
            int(r["id"])
        ))
        fixed += 1
        continue

    # 明記金額がある場合のみ金額を更新
    if new_est > 0:
        cur.execute("""
        UPDATE profit_leads
        SET estimated_profit=?,
            recoverable_profit=?,
            profit_basis=?,
            profit_confidence=?,
            unit_price_detected=?,
            people_detected=?,
            days_detected=?
        WHERE id=?
        """, (
            new_est,
            new_rec,
            new_basis,
            new_conf,
            int(est.get("unit_price", 0) or 0),
            float(est.get("people", 0) or 0),
            float(est.get("days", 0) or 0),
            int(r["id"])
        ))
        updated_basis += 1

conn.commit()
conn.close()

print(f"未確定化: {fixed}件")
print(f"根拠更新: {updated_basis}件")
