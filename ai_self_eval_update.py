import sqlite3

DB = "profit_radar.db"


def update_self_eval_results():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    UPDATE ai_self_evaluation
    SET actual_revenue = COALESCE((
        SELECT MAX(actual_revenue)
        FROM profit_leads l
        WHERE l.customer = ai_self_evaluation.customer
          AND l.subject = ai_self_evaluation.subject
    ), 0)
    WHERE ai_type='followup'
    """)

    c.execute("""
    UPDATE ai_self_evaluation
    SET result_status =
        CASE
            WHEN actual_revenue > 0 THEN '利益発生'
            ELSE '未成果'
        END
    WHERE ai_type='followup'
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    update_self_eval_results()
    print("AI自己評価結果を更新しました。")
