import sqlite3
import pandas as pd
import streamlit as st

DB = "profit_radar.db"

st.set_page_config(page_title="Profit Radar Developer", layout="wide")

st.title("Profit Radar Developer")
st.caption("内部ログ・AI学習・RUDIA同期確認用。販売画面には出さない。")

def read_table(table, limit=100):
    try:
        conn = sqlite3.connect(DB)
        df = pd.read_sql_query(f"SELECT * FROM {table} ORDER BY id DESC LIMIT {int(limit)}", conn)
        conn.close()
        return df
    except Exception as e:
        st.warning(f"{table} を読み込めません: {e}")
        return pd.DataFrame()

tables = [
    "ai_advice_logs",
    "ai_followup_logs",
    "ai_learning",
    "profit_actions",
    "profit_leads",
]

selected = st.sidebar.selectbox("確認するテーブル", tables)
limit = st.sidebar.slider("表示件数", 10, 300, 100)

df = read_table(selected, limit)

st.subheader(selected)

if df.empty:
    st.info("データがありません。")
else:
    st.dataframe(df, use_container_width=True)
