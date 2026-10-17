"""Kiểm thử tĩnh các tệp SQL (không cần máy chủ PostgreSQL)."""
import re

import pytest


@pytest.fixture
def schema(root):
    return (root / "sql" / "init_raw_db.sql").read_text(encoding="utf-8")


@pytest.fixture
def audit_sql(root):
    return (root / "sql" / "audit_queries.sql").read_text(encoding="utf-8")


def test_schema_is_rerunnable(schema):
    assert "CREATE TABLE IF NOT EXISTS raw_products" in schema
    assert "CREATE INDEX IF NOT EXISTS" in schema


def test_payload_is_jsonb_not_null(schema):
    assert re.search(r"payload\s+JSONB\s+NOT\s+NULL", schema)


def test_barcode_is_text_not_number(schema):
    assert re.search(r"\bcode\s+TEXT\b", schema)
    assert not re.search(r"\bcode\s+(INT|INTEGER|BIGINT|NUMERIC)", schema, re.IGNORECASE)


def test_unique_constraint_enables_idempotent_load(schema):
    assert re.search(r"UNIQUE\s*\(\s*code\s*,\s*source_file\s*\)", schema)


def test_source_file_is_required(schema):
    assert re.search(r"source_file\s+TEXT\s+NOT\s+NULL", schema)


def test_timestamp_has_timezone(schema):
    assert "TIMESTAMPTZ" in schema


def test_audit_queries_are_terminated_statements(audit_sql):
    body = "\n".join(ln for ln in audit_sql.splitlines() if not ln.strip().startswith("--"))
    statements = [s for s in body.split(";") if s.strip()]
    assert len(statements) >= 8
    assert all("raw_products" in s for s in statements)


def test_audit_queries_are_read_only(audit_sql):
    body = "\n".join(ln for ln in audit_sql.splitlines() if not ln.strip().startswith("--")).upper()
    for forbidden in ("DELETE", "UPDATE ", "DROP ", "INSERT ", "TRUNCATE", "ALTER "):
        assert forbidden not in body


def test_audit_queries_never_touch_nutriments(audit_sql):
    # Kiểm toán không cần (và không nên) dùng bảng dinh dưỡng làm đặc trưng
    assert "nutriments" not in audit_sql
