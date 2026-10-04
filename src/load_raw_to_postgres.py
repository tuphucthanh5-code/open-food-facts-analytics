import glob
import gzip
import json
import os

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import Json, execute_values

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "food_facts_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.environ["DB_PASSWORD"],
}

INSERT_SQL = """
INSERT INTO raw_products
    (code, retrieved_at, source_endpoint, request_url, http_status, page, source_file, payload)
VALUES %s
ON CONFLICT (code, source_file) DO NOTHING
"""


def iter_records(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def main(pattern="data/raw/*.jsonl.gz", batch_size=1000):
    files = sorted(glob.glob(pattern))
    if not files:
        print("Không tìm thấy file trong data/raw/")
        return
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn, conn.cursor() as cur:
            for path in files:
                name = os.path.basename(path)
                rows, total = [], 0
                for rec in iter_records(path):
                    meta = rec.get("_metadata", {})
                    payload = rec.get("raw_payload", {})
                    code = payload.get("code")
                    rows.append((
                        str(code) if code is not None else None,
                        meta.get("retrieved_at"),
                        meta.get("source_endpoint"),
                        meta.get("request_url"),
                        meta.get("http_status"),
                        meta.get("page"),
                        name,
                        Json(payload),
                    ))
                    if len(rows) >= batch_size:
                        execute_values(cur, INSERT_SQL, rows)
                        total += len(rows)
                        rows = []
                if rows:
                    execute_values(cur, INSERT_SQL, rows)
                    total += len(rows)
                print(f"{name}: đã xử lý {total} bản ghi")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
