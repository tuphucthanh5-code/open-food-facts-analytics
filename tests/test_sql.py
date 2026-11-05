"""Tệp SQL (raw layer, kiểm toán, trích xuất), nạp dữ liệu vào PostgreSQL và kiểm tra tích hợp với CSDL thật."""
import gzip
import json

import pytest

from src import load_raw_to_postgres as loader
from src.cleaning import PII_FIELDS
from src.db import load_queries

AUDIT_QUERIES = {"tong_quan", "nhan_goc", "dung_duoc", "hang_theo_nova", "ty_le_thieu", "so_thanh_phan",
                 "the_taxonomy", "thuong_hieu", "quoc_gia", "truong_nhay_cam", "ma_trung_join"}
WRITE_WORDS = ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "TRUNCATE ")


def sql_body(query):
    """Bỏ các dòng chú thích '--' ở đầu câu SQL."""
    return " ".join(line for line in query.splitlines() if not line.lstrip().startswith("--")).strip()


def test_load_queries_splits_by_name(tmp_path):
    p = tmp_path / "q.sql"
    p.write_text("-- chú thích\n-- name: a\nSELECT 1;\n\n-- name: b\nSELECT 2\nFROM t;\n", encoding="utf-8")
    assert load_queries(p) == {"a": "SELECT 1;", "b": "SELECT 2\nFROM t;"}


def test_audit_file_has_every_check_and_only_reads(root):
    queries = load_queries(root / "sql" / "audit_queries.sql")
    assert set(queries) == AUDIT_QUERIES
    for q in queries.values():
        body = sql_body(q).upper()
        assert body.startswith(("SELECT", "WITH"))
        assert not [w for w in WRITE_WORDS if w in body]
    assert "JOIN" in queries["ma_trung_join"] and "GROUP BY" in queries["hang_theo_nova"]


def test_extract_query_is_read_only_and_has_no_personal_fields(root):
    sql = load_queries(root / "sql" / "extract_products.sql")["products"]
    assert sql_body(sql).upper().startswith("SELECT") and "ORDER BY id" in sql
    assert not [f for f in PII_FIELDS if f in sql]
    assert "AS row_id" in sql and "AS nutriscore_grade" in sql


def test_raw_table_schema(root):
    sql = (root / "sql" / "init_raw_db.sql").read_text(encoding="utf-8")
    assert "payload          JSONB NOT NULL" in sql
    assert "UNIQUE (code, source_file)" in sql


def test_loader_reads_rows(tmp_path, monkeypatch):
    monkeypatch.setattr("psycopg2.extras.Json", lambda x: x)
    path = tmp_path / "raw.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps({"_metadata": {"retrieved_at": "2026-01-01"}, "raw_payload": {"code": 123}}) + "\n\n")
    rows = list(loader.iter_rows(path))
    assert len(rows) == 1
    assert rows[0][0] == "123" and rows[0][6] == "raw.jsonl.gz" and rows[0][7] == {"code": 123}


def test_loader_main_missing_file(tmp_path):
    assert loader.main([str(tmp_path / "missing.jsonl.gz")]) == 1


# ------------------------------------------------------------------ tích hợp: cần PostgreSQL thật (tự bỏ qua)
@pytest.fixture(scope="module")
def db():
    from src import db

    try:
        db.connect().close()
    except Exception as exc:          # không có .env, chưa cài PostgreSQL, sai mật khẩu...
        pytest.skip(f"không kết nối được PostgreSQL: {type(exc).__name__}")
    return db


@pytest.mark.integration
def test_audit_queries_run_on_real_db(db, root):
    queries = load_queries(root / "sql" / "audit_queries.sql")
    for name, sql in queries.items():
        assert db.query(sql) is not None, name
    keys = db.query(queries["truong_nhay_cam"])
    assert not keys["loai"].str.startswith("CÁ NHÂN").any()


@pytest.mark.integration
def test_extract_query_on_real_db(db, root):
    products = db.query(load_queries(root / "sql" / "extract_products.sql")["products"])
    assert len(products) > 0 and products["row_id"].is_unique
    assert products["code"].map(lambda c: isinstance(c, str)).all()
