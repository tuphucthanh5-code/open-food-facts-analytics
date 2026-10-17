"""Kiểm thử tích hợp với PostgreSQL thật. Tự bỏ qua nếu không kết nối được.

Đọc cấu hình trực tiếp từ tệp .env (không dùng biến môi trường giả của conftest).
Chạy riêng:  pytest -m integration -v
"""
import psycopg2
import pytest
from dotenv import dotenv_values

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def conn(root):
    cfg = dotenv_values(root / ".env")
    if not cfg.get("DB_PASSWORD"):
        pytest.skip("không có .env hoặc thiếu DB_PASSWORD")
    try:
        c = psycopg2.connect(
            host=cfg.get("DB_HOST", "localhost"), port=int(cfg.get("DB_PORT", "5432")),
            dbname=cfg.get("DB_NAME", "food_facts_db"), user=cfg.get("DB_USER", "postgres"),
            password=cfg["DB_PASSWORD"], connect_timeout=3,
        )
    except psycopg2.Error as exc:
        pytest.skip(f"không kết nối được PostgreSQL: {str(exc).splitlines()[0]}")
    yield c
    c.close()


def test_raw_products_table_has_expected_columns(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'raw_products'")
        cols = dict(cur.fetchall())
    assert cols, "chưa có bảng raw_products: chạy sql/init_raw_db.sql"
    assert cols["payload"] == "jsonb"
    assert cols["code"] == "text"
    assert {"retrieved_at", "source_endpoint", "request_url", "http_status", "page", "source_file"} <= set(cols)


def test_unique_constraint_exists(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_indexes WHERE tablename = 'raw_products' AND indexdef ILIKE '%UNIQUE%'")
        assert cur.fetchone()[0] >= 1


def test_loaded_data_keeps_barcode_as_text_with_leading_zeros(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw_products")
        if cur.fetchone()[0] == 0:
            pytest.skip("bảng còn trống: chạy load_raw_to_postgres.py trước")
        cur.execute("SELECT count(*) FROM raw_products WHERE code !~ '^[0-9A-Za-z]+$'")
        assert cur.fetchone()[0] == 0


def test_no_personal_fields_were_stored(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw_products WHERE payload ?| array['creator','editors_tags','last_editor']")
        assert cur.fetchone()[0] == 0
