"""Kết nối PostgreSQL và chạy câu SQL, trả về DataFrame.

Mật khẩu đọc từ tệp .env (biến DB_PASSWORD), không bao giờ viết trong mã.
Các câu SQL nằm trong thư mục sql/, mỗi câu mở đầu bằng dòng "-- name: <tên>".
"""
import os
import re

import pandas as pd
from dotenv import load_dotenv


def connect():
    import psycopg2

    load_dotenv()
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "food_facts_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.environ["DB_PASSWORD"],
    )


def query(sql, params=None):
    """Chạy một câu SELECT, trả về DataFrame (cột JSONB tự đổi thành list/dict của Python)."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=columns)
    finally:
        conn.close()


def load_queries(path):
    """Đọc tệp .sql có nhiều câu, trả về dict {tên: câu SQL} theo các dòng '-- name: <tên>'."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    parts = re.split(r"^-- name: *(\w+) *$", text, flags=re.M)
    return {name: body.strip() for name, body in zip(parts[1::2], parts[2::2])}
