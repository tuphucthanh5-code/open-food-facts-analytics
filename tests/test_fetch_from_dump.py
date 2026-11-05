"""Bước 4a - lấy mẫu từ bản dump Parquet bằng DuckDB, chạy trên một tệp Parquet nhỏ tự tạo."""
import gzip
import json

import duckdb
import pytest

from src import fetch_from_dump as fd
from src.cleaning import PII_FIELDS


def test_pick_text_preference():
    entries = [{"lang": "fr", "text": "Pâte"}, {"lang": "main", "text": " Spread "}, {"lang": "en", "text": "X"}]
    assert fd.pick_text(entries, "fr") == "Spread"
    assert fd.pick_text(entries[:1] + entries[2:], "fr") == "Pâte"
    assert fd.pick_text([{"lang": "de", "text": "A"}, {"lang": "it", "text": "B"}], "fr") == "A"
    assert fd.pick_text(None) is None


def test_nutriments_and_food_groups():
    assert fd.nutriments_to_dict([{"name": "sugars", "100g": 5.0}, {"name": "salt", "100g": None}]) == {"sugars_100g": 5.0}
    assert fd.food_group_label("en:sugary-snacks") == "sugary snacks"
    assert fd.food_group_label("") is None


def test_no_personal_fields_are_read():
    assert not set(fd.COLUMNS) & PII_FIELDS


ROWS = [
    # code, grade, ingredients, last_modified_t, obsolete
    ("001", "e", ["en:sugar"], 100, False),
    ("002", "c", ["en:water"], 100, False),     # mã lặp: bản cũ
    ("002", "b", ["en:water"], 200, False),     # mã lặp: bản mới hơn -> phải được chọn
    ("003", "a", ["en:carrot"], 100, False),    # mã lặp: bản đủ điều kiện
    ("003", "unknown", ["en:carrot"], 300, False),  # bản mới hơn nhưng không có nhãn -> không được chọn
    ("004", "a", [], 100, False),               # không có thành phần -> loại
    ("005", "a", ["en:salt"], 100, True),       # lỗi thời -> loại
]


@pytest.fixture
def tiny_dump(tmp_path):
    path = (tmp_path / "food.parquet").as_posix()
    con = duckdb.connect()
    con.execute("""CREATE TABLE food (code VARCHAR, product_name STRUCT(lang VARCHAR, "text" VARCHAR)[],
        brands_tags VARCHAR[], countries_tags VARCHAR[], categories_tags VARCHAR[], food_groups_tags VARCHAR[],
        ingredients_tags VARCHAR[], ingredients_text STRUCT(lang VARCHAR, "text" VARCHAR)[], ingredients_n INTEGER,
        ingredients_from_palm_oil_n INTEGER, ingredients_analysis_tags VARCHAR[], additives_tags VARCHAR[],
        additives_n INTEGER, allergens_tags VARCHAR[], labels_tags VARCHAR[], nova_group INTEGER,
        nutriscore_grade VARCHAR, nutriscore_score INTEGER, nutriments STRUCT(name VARCHAR, "100g" FLOAT)[],
        lang VARCHAR, last_modified_t BIGINT, obsolete BOOLEAN, creator VARCHAR)""")
    for code, grade, ing, t, obsolete in ROWS:
        con.execute("""INSERT INTO food VALUES (?, [{'lang': 'main', 'text': 'Tên'}], ['xx:b'], ['en:france'],
            ['en:snacks'], ['en:sugary-snacks', 'en:sweets'], ?, [{'lang': 'main', 'text': 'sugar'}], ?, 0, [], [],
            0, [], [], 4, ?, 10, [{'name': 'sugars', '100g': 50.0}], 'fr', ?, ?, 'người dùng X')""",
                    [code, ing, len(ing), grade, t, obsolete])
    con.execute(f"COPY food TO '{path}' (FORMAT parquet)")
    con.close()
    return path


def read(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def test_fetch_picks_eligible_newest_rows(tiny_dump, tmp_path):
    out = tmp_path / "raw.jsonl.gz"
    assert fd.fetch(tiny_dump, str(out), n=10) == 3
    records = read(out)
    payloads = {r["raw_payload"]["code"]: r["raw_payload"] for r in records}
    assert set(payloads) == {"001", "002", "003"}
    assert payloads["002"]["nutriscore_grade"] == "b"            # bản sửa gần nhất
    assert payloads["003"]["nutriscore_grade"] == "a"            # không lấy bản thiếu nhãn
    assert payloads["001"]["pnns_groups_2"] == "sweets"
    assert payloads["001"]["nutriments"] == {"sugars_100g": 50.0}
    assert "creator" not in payloads["001"]                      # trường cá nhân không được đọc
    assert records[0]["_metadata"]["retrieved_at"] and records[0]["_metadata"]["source_endpoint"] == tiny_dump


def test_fetch_is_reproducible_and_respects_n(tiny_dump, tmp_path):
    a, b, c = tmp_path / "a.jsonl.gz", tmp_path / "b.jsonl.gz", tmp_path / "c.jsonl.gz"
    fd.fetch(tiny_dump, str(a), n=10)
    fd.fetch(tiny_dump, str(b), n=10)
    assert [r["raw_payload"]["code"] for r in read(a)] == [r["raw_payload"]["code"] for r in read(b)]
    assert fd.fetch(tiny_dump, str(c), n=2) == 2


def test_main_without_source_file(tmp_path):
    assert fd.main(["--source", str(tmp_path / "missing.parquet")]) == 1
