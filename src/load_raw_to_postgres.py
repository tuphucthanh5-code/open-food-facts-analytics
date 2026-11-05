"""Bước 4b - Nạp tệp JSON thô (.jsonl.gz) vào bảng raw_products của PostgreSQL (cột payload kiểu JSONB).

Mỗi dòng giữ nguyên JSON gốc + thời điểm lấy, nguồn, tên tệp (raw layer). Nạp lại cùng tệp không tạo trùng
nhờ ràng buộc UNIQUE (code, source_file).

Chạy từ thư mục gốc dự án (tạo bảng trước bằng sql/init_raw_db.sql):
    python -m src.load_raw_to_postgres data/raw/raw_products_dump_20261017_174142.jsonl.gz
"""
import argparse
import gzip
import json
import os
import sys

INSERT_SQL = """
INSERT INTO raw_products (code, retrieved_at, source_endpoint, request_url, http_status, page, source_file, payload)
VALUES %s
ON CONFLICT (code, source_file) DO NOTHING
"""


def iter_rows(path):
    """Mỗi dòng của tệp -> một bộ giá trị cho câu INSERT."""
    from psycopg2.extras import Json

    name = os.path.basename(path)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            meta, payload = rec.get("_metadata", {}), rec.get("raw_payload", {})
            code = payload.get("code")
            yield (str(code) if code is not None else None, meta.get("retrieved_at"), meta.get("source_endpoint"),
                   meta.get("request_url"), meta.get("http_status"), meta.get("page"), name, Json(payload))


def load(path, batch_size=1000):
    """Nạp một tệp, trả về số dòng đã gửi (dòng trùng bị bỏ qua nhờ ON CONFLICT)."""
    from psycopg2.extras import execute_values

    from src.db import connect

    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            rows = list(iter_rows(path))
            execute_values(cur, INSERT_SQL, rows, page_size=batch_size)
        return len(rows)
    finally:
        conn.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Nạp một tệp .jsonl.gz vào bảng raw_products")
    ap.add_argument("path", help="tệp trong data/raw/, ví dụ data/raw/raw_products_dump_<thời điểm>.jsonl.gz")
    args = ap.parse_args(argv)
    if not os.path.isfile(args.path):
        print(f"Không thấy tệp {args.path}")
        return 1
    print(f"{args.path}: đã gửi {load(args.path)} bản ghi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
