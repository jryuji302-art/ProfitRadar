import traceback
import streamlit as st
from app_logger import get_logger

logger = get_logger("profit_radar.error")


def handle_error(exc, user_message="処理中にエラーが発生しました。"):
    """
    ユーザーには簡潔なメッセージ、
    ログには詳細スタックトレースを残す。
    """
    logger.exception(str(exc))
    st.error(user_message)


def log_info(message):
    logger.info(message)


def log_warning(message):
    logger.warning(message)


def log_error(message):
    logger.error(message)
