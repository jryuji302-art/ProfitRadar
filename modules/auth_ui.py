import hashlib
import sqlite3
import streamlit as st
from error_handler import handle_error


def ensure_auth_tables(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        name TEXT,
        password_hash TEXT,
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        company_name TEXT,
        plan TEXT,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()


def hash_password(password):
    return hashlib.sha256(str(password or "").encode("utf-8")).hexdigest()


def create_user_and_company(db_path, email, name, password, company_name):
    from datetime import datetime

    email = str(email or "").strip().lower()
    name = str(name or "").strip()
    company_name = str(company_name or "").strip() or "未設定"

    if not email or not password:
        raise ValueError("メールアドレスとパスワードは必須です。")

    password_hash = hash_password(password)
    created_at = datetime.now().isoformat(timespec="seconds")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
        INSERT INTO users (email, name, password_hash, created_at)
        VALUES (?, ?, ?, ?)
    """, (email, name, password_hash, created_at))

    user_id = c.lastrowid

    c.execute("""
        INSERT INTO companies (user_id, company_name, plan, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, company_name, "beta", created_at))

    company_id = c.lastrowid

    conn.commit()
    conn.close()

    return user_id, company_id


def authenticate_user(db_path, email, password):
    email = str(email or "").strip().lower()
    password_hash = hash_password(password)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT id, email, name
        FROM users
        WHERE email = ? AND password_hash = ?
    """, (email, password_hash))

    user = c.fetchone()

    if not user:
        conn.close()
        return None

    c.execute("""
        SELECT id, company_name, plan
        FROM companies
        WHERE user_id = ?
        ORDER BY id ASC
        LIMIT 1
    """, (user["id"],))

    company = c.fetchone()
    conn.close()

    if not company:
        return None

    return {
        "user_id": int(user["id"]),
        "email": user["email"],
        "name": user["name"],
        "company_id": int(company["id"]),
        "company_name": company["company_name"],
        "plan": company["plan"],
    }


def render_auth_gate(db_path):
    if st.session_state.get("logged_in"):
        return

    st.title("Profit Radar")
    st.caption("ログインまたは新規登録してください。")

    login_tab, register_tab = st.tabs(["ログイン", "新規登録"])

    with login_tab:
        login_email = st.text_input("メールアドレス", key="login_email")
        login_password = st.text_input("パスワード", type="password", key="login_password")

        if st.button("ログイン", key="login_button"):
            user = authenticate_user(db_path, login_email, login_password)
            if user:
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = user["user_id"]
                st.session_state["company_id"] = user["company_id"]
                st.session_state["user_email"] = user["email"]
                st.session_state["user_name"] = user["name"]
                st.session_state["company_name"] = user["company_name"]
                st.session_state["plan"] = user["plan"]
                st.success("ログインしました。")
                st.rerun()
            else:
                st.error("メールアドレスまたはパスワードが違います。")

    with register_tab:
        reg_name = st.text_input("名前", key="register_name")
        reg_company = st.text_input("会社名・屋号", key="register_company")
        reg_email = st.text_input("メールアドレス", key="register_email")
        reg_password = st.text_input("パスワード", type="password", key="register_password")

        if st.button("新規登録", key="register_button"):
            try:
                user_id, company_id = create_user_and_company(
                    db_path,
                    reg_email,
                    reg_name,
                    reg_password,
                    reg_company
                )

                st.session_state["logged_in"] = True
                st.session_state["user_id"] = user_id
                st.session_state["company_id"] = company_id
                st.session_state["user_email"] = reg_email.strip().lower()
                st.session_state["user_name"] = reg_name.strip()
                st.session_state["company_name"] = reg_company.strip()
                st.session_state["plan"] = "beta"

                st.success("登録しました。")
                st.rerun()
            except Exception as e:
                handle_error(e, "登録に失敗しました。入力内容を確認してください。")

    st.stop()


def render_logout_sidebar():
    st.sidebar.caption(f"ログイン中: {st.session_state.get('user_email', '')}")
    st.sidebar.caption(f"会社: {st.session_state.get('company_name', '')}")

    if st.sidebar.button("ログアウト"):
        for key in ["logged_in", "user_id", "company_id", "user_email", "user_name", "company_name", "plan"]:
            st.session_state.pop(key, None)
        st.rerun()
