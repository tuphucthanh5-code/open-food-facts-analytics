"""Kiểm thử script nạp PostgreSQL bằng đối tượng giả (không cần máy chủ thật)."""
import gzip
import json
from unittest.mock import MagicMock

import pytest
from psycopg2.extras import Json

import src.load_raw_to_postgres as loader


def write_gz(path, records, blank_line=False):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            if blank_line:
                f.write("\n")


def rec(code, **payload):
    return {"_metadata": {"retrieved_at": "2026-01-01T00:00:00+00:00", "source_endpoint": "ep",
                          "request_url": "u", "http_status": 200, "page": 1},
            "raw_payload": {"code": code, **payload}}


@pytest.fixture
def fake_db(monkeypatch):
    conn = MagicMock(name="conn")
    monkeypatch.setattr(loader.psycopg2, "connect", MagicMock(return_value=conn))
    batches = []
    monkeypatch.setattr(loader, "execute_values", lambda cur, sql, rows: batches.append(list(rows)))
    return conn, batches


# --------------------------------------------------------------------------- cấu hình
def test_db_config_reads_environment(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "x")
    # DB_CONFIG được tạo lúc import; kiểm tra cấu trúc và kiểu
    cfg = loader.DB_CONFIG
    assert set(cfg) == {"host", "port", "dbname", "user", "password"}
    assert isinstance(cfg["port"], int)
    assert cfg["password"]


def test_insert_sql_is_idempotent_and_matches_schema(root):
    assert "ON CONFLICT (code, source_file) DO NOTHING" in loader.INSERT_SQL
    schema = (root / "sql" / "init_raw_db.sql").read_text(encoding="utf-8")
    for col in ("code", "retrieved_at", "source_endpoint", "request_url",
                "http_status", "page", "source_file", "payload"):
        assert col in loader.INSERT_SQL
        assert col in schema


# --------------------------------------------------------------------------- iter_records
def test_iter_records_skips_blank_lines(tmp_path):
    p = tmp_path / "a.jsonl.gz"
    write_gz(p, [rec("1"), rec("2")], blank_line=True)
    assert [r["raw_payload"]["code"] for r in loader.iter_records(p)] == ["1", "2"]


def test_iter_records_reads_unicode(tmp_path):
    p = tmp_path / "a.jsonl.gz"
    write_gz(p, [rec("1", product_name="Bánh mì")])
    assert next(loader.iter_records(p))["raw_payload"]["product_name"] == "Bánh mì"


# --------------------------------------------------------------------------- main
def test_main_with_no_files_does_not_connect(tmp_path, monkeypatch, capsys):
    connect = MagicMock()
    monkeypatch.setattr(loader.psycopg2, "connect", connect)
    loader.main(pattern=str(tmp_path / "*.jsonl.gz"))
    connect.assert_not_called()
    assert "Không tìm thấy" in capsys.readouterr().out


def test_main_inserts_in_batches(tmp_path, fake_db):
    conn, batches = fake_db
    write_gz(tmp_path / "raw_a.jsonl.gz", [rec("1"), rec("2"), rec("3")])
    loader.main(pattern=str(tmp_path / "*.jsonl.gz"), batch_size=2)
    assert [len(b) for b in batches] == [2, 1]
    conn.close.assert_called_once()


def test_main_keeps_barcode_as_string_with_leading_zero(tmp_path, fake_db):
    _, batches = fake_db
    write_gz(tmp_path / "raw_a.jsonl.gz", [rec("0012345678905")])
    loader.main(pattern=str(tmp_path / "*.jsonl.gz"))
    row = batches[0][0]
    assert row[0] == "0012345678905"
    assert isinstance(row[0], str)


def test_main_row_layout_matches_insert_columns(tmp_path, fake_db):
    _, batches = fake_db
    write_gz(tmp_path / "raw_x.jsonl.gz", [rec("9", nutriscore_grade="a")])
    loader.main(pattern=str(tmp_path / "*.jsonl.gz"))
    code, retrieved_at, endpoint, url, status, page, source_file, payload = batches[0][0]
    assert (code, endpoint, url, status, page) == ("9", "ep", "u", 200, 1)
    assert retrieved_at == "2026-01-01T00:00:00+00:00"
    assert source_file == "raw_x.jsonl.gz"          # chỉ tên tệp, không kèm thư mục
    assert isinstance(payload, Json)
    assert payload.adapted["nutriscore_grade"] == "a"


def test_main_record_without_code_gets_none(tmp_path, fake_db):
    _, batches = fake_db
    write_gz(tmp_path / "raw_a.jsonl.gz", [{"_metadata": {}, "raw_payload": {"product_name": "x"}}])
    loader.main(pattern=str(tmp_path / "*.jsonl.gz"))
    assert batches[0][0][0] is None


def test_main_processes_every_file(tmp_path, fake_db):
    _, batches = fake_db
    write_gz(tmp_path / "raw_a.jsonl.gz", [rec("1")])
    write_gz(tmp_path / "raw_b.jsonl.gz", [rec("2")])
    loader.main(pattern=str(tmp_path / "*.jsonl.gz"))
    assert {b[0][6] for b in batches} == {"raw_a.jsonl.gz", "raw_b.jsonl.gz"}


def test_connection_closed_even_when_insert_fails(tmp_path, monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(loader.psycopg2, "connect", MagicMock(return_value=conn))

    def boom(cur, sql, rows):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(loader, "execute_values", boom)
    write_gz(tmp_path / "raw_a.jsonl.gz", [rec("1")])
    with pytest.raises(RuntimeError):
        loader.main(pattern=str(tmp_path / "*.jsonl.gz"))
    conn.close.assert_called_once()
