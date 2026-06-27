import sqlite3
from profit_estimator import estimate_profit_from_text

DB = "profit_radar.db"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 補助カラム追加
for sql in [
    "ALTER TABLE profit_leads ADD COLUMN profit_basis TEXT",
    "ALTER TABLE profit_leads ADD COLUMN profit_confidence INTEGER DEFAULT 0",
    "ALTER TABLE profit_leads ADD COLUMN unit_price_detected INTEGER DEFAULT 0",
    "ALTER TABLE profit_leads ADD COLUMN people_detected REAL DEFAULT 1",
    "ALTER TABLE profit_leads ADD COLUMN days_detected REAL DEFAULT 1",
]:
    try:
        cur.execute(sql)
    except Exception:
        pass

rows = cur.execute("""
SELECT
    id, subject, content, category,
    estimated_profit, recoverable_profit, actual_revenue
FROM profit_leads
""").fetchall()

updated = 0

for r in rows:
    est = estimate_profit_from_text(
        subject=r["subject"] or "",
        content=r["content"] or "",
        category=r["category"] or "",
        actual_revenue=r["actual_revenue"] or 0
    )

    new_estimated = int(est.get("estimated_profit", 0) or 0)
    new_recoverable = int(est.get("recoverable_profit", 0) or 0)
    old_estimated = int(r["estimated_profit"] or 0)

    # 金額根拠がある場合だけ補正
    # 既存値が新推定の3倍超なら過大評価として補正
    should_fix = new_estimated > 0 and (
        old_estimated <= 0 or old_estimated > new_estimated * 3
    )

    if should_fix:
        cur.execute("""
        UPDATE profit_leads
        SET
            estimated_profit=?,
            recoverable_profit=?,
            profit_basis=?,
            profit_confidence=?,
            unit_price_detected=?,
            people_detected=?,
            days_detected=?
        WHERE id=?
        """, (
            new_estimated,
            new_recoverable,
            est.get("basis", ""),
            int(est.get("confidence", 0) or 0),
            int(est.get("unit_price", 0) or 0),
            float(est.get("people", 1) or 1),
            float(est.get("days", 1) or 1),
            int(r["id"])
        ))
        updated += 1
    else:
        cur.execute("""
        UPDATE profit_leads
        SET
            profit_basis=?,
            profit_confidence=?,
            unit_price_detected=?,
            people_detected=?,
            days_detected=?
        WHERE id=?
        """, (
            est.get("basis", ""),
            int(est.get("confidence", 0) or 0),
            int(est.get("unit_price", 0) or 0),
            float(est.get("people", 1) or 1),
            float(est.get("days", 1) or 1),
            int(r["id"])
        ))

conn.commit()

print(f"再計算完了: {len(rows)}件確認 / {updated}件補正")

for r in cur.execute("""
SELECT id, subject, estimated_profit, recoverable_profit, profit_basis, profit_confidence
FROM profit_leads
ORDER BY id DESC
LIMIT 10
""").fetchall():
    print(dict(r))

conn.close()
