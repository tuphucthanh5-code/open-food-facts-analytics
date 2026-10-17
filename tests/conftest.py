"""Cấu hình dùng chung cho mọi test.

Lưu ý: src/load_raw_to_postgres.py đọc os.environ["DB_PASSWORD"] ngay khi import, nên phải đặt
giá trị giả TRƯỚC khi các test import module đó. Giá trị này chỉ dùng trong tiến trình test.
"""
import gzip
import json
import os
import sys
from pathlib import Path

import pytest

from tests.helpers import make_payload

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DB_PASSWORD", "test-password-not-real")


@pytest.fixture(scope="session")
def root():
    return ROOT


@pytest.fixture
def payload_factory():
    return make_payload


@pytest.fixture
def write_jsonl_gz(tmp_path):
    """Ghi list payload thành tệp .jsonl.gz đúng định dạng của crawler; trả về đường dẫn."""
    def _write(payloads, name="raw_products_test.jsonl.gz", extra_lines=()):
        path = tmp_path / name
        with gzip.open(path, "wt", encoding="utf-8") as f:
            for p in payloads:
                rec = {"_metadata": {"retrieved_at": "2026-01-01T00:00:00+00:00", "http_status": 200, "page": 1},
                       "raw_payload": p}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            for line in extra_lines:
                f.write(line + "\n")
        return path
    return _write
