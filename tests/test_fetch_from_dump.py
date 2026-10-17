"""Kiểm thử công cụ lấy dữ liệu từ bản dump Parquet, dùng một tệp Parquet giả cùng cấu trúc.

Cấu trúc giả dựa theo thẻ dữ liệu của openfoodfacts/product-database trên Hugging Face:
product_name, ingredients_text là list {lang, text}; nutriments là list {name, value, 100g, serving, unit}.
"""
import gzip
import json
from collections import Counter

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src import fetch_from_dump as fd
from src import raw_audit, staging
from src.load_raw_to_postgres import iter_records

TEXT = pa.list_(pa.struct([("lang", pa.string()), ("text", pa.string())]))
NUTRI = pa.list_(pa.struct([("name", pa.string()), ("value", pa.float32()), ("100g", pa.float32()),
                            ("serving", pa.float32()), ("unit", pa.string())]))
TAGS = pa.list_(pa.string())

SCHEMA = pa.schema([
    ("code", pa.string()), ("product_name", TEXT), ("brands_tags", TAGS), ("countries_tags", TAGS),
    ("categories_tags", TAGS), ("food_groups_tags", TAGS), ("ingredients_tags", TAGS),
    ("ingredients_text", TEXT), ("ingredients_n", pa.int32()), ("ingredients_from_palm_oil_n", pa.int32()),
    ("ingredients_analysis_tags", TAGS), ("additives_tags", TAGS), ("additives_n", pa.int32()),
    ("allergens_tags", TAGS), ("labels_tags", TAGS), ("nova_group", pa.int32()),
    ("nutriscore_grade", pa.string()), ("nutriscore_score", pa.int32()), ("nutriments", NUTRI),
    ("lang", pa.string()), ("last_modified_t", pa.int64()), ("obsolete", pa.bool_()),
    # cột cá nhân có trong dump thật: công cụ KHÔNG được đọc
    ("creator", pa.string()), ("last_editor", pa.string()), ("editors", TAGS),
])

GRADES = ["a", "b", "c", "d", "e", "unknown", "not-applicable", None]


def make_rows(n=400):
    rows = []
    for i in range(n):
        grade = GRADES[i % len(GRADES)]
        has_ing = i % 7 != 0
        rows.append({
            "code": f"{i:013d}",
            "product_name": [{"lang": "main", "text": f"Sản phẩm {i}"}, {"lang": "en", "text": f"Product {i}"}],
            "brands_tags": [f"brand{i % 25}"],
            "countries_tags": ["en:france"] if i % 3 else ["en:vietnam", "en:france"],
            "categories_tags": ["en:snacks"],
            "food_groups_tags": ["en:sugary-snacks", "en:biscuits-and-cakes"],
            "ingredients_tags": ["en:sugar", "en:wheat-flour"] if has_ing else [],
            "ingredients_text": [{"lang": "fr", "text": "sucre, farine"}],
            "ingredients_n": 2 if has_ing else 0,
            "ingredients_from_palm_oil_n": 0,
            "ingredients_analysis_tags": ["en:vegan"],
            "additives_tags": ["en:e322"] if i % 2 else [],
            "additives_n": 1 if i % 2 else 0,
            "allergens_tags": ["en:gluten"],
            "labels_tags": [],
            "nova_group": (i % 4) + 1,
            "nutriscore_grade": grade.upper() if grade and i % 5 == 0 else grade,
            "nutriscore_score": 10,
            "nutriments": [{"name": "sugars", "value": 30.0, "100g": 30.0, "serving": None, "unit": "g"},
                           {"name": "energy-kcal", "value": 450.0, "100g": 450.0, "serving": None, "unit": "kcal"}],
            "lang": "fr",
            "last_modified_t": 1700000000 + i,
            "obsolete": i % 50 == 1,
            "creator": "someone", "last_editor": "x", "editors": ["a", "b"],
        })
    return rows


def eligible_codes(rows, country=None):
    out = set()
    for r in rows:
        g = r["nutriscore_grade"]
        if g and g.lower() in "abcde" and len(g) == 1 and r["ingredients_tags"] and not r["obsolete"]:
            if country is None or country in r["countries_tags"]:
                out.add(r["code"])
    return out


@pytest.fixture
def dump(tmp_path):
    rows = make_rows()
    path = tmp_path / "food.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path, row_group_size=100)
    return str(path), rows


def read_out(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run(dump_path, tmp_path, **kw):
    out = str(tmp_path / "raw" / "raw_products_dump_test.jsonl.gz")
    summary = fd.extract(dump_path, out, log=lambda *_: None, **kw)
    return summary, read_out(out), out


# --------------------------------------------------------------------------- hàm chuyển đổi
def test_select_columns_never_include_personal_fields():
    assert not set(fd.SELECT_COLUMNS) & set(raw_audit.PII_FIELDS)
    assert "editors" not in fd.SELECT_COLUMNS


@pytest.mark.parametrize("entries,lang,exp", [
    ([{"lang": "fr", "text": "Pain"}, {"lang": "main", "text": "Pain main"}], "fr", "Pain main"),
    ([{"lang": "fr", "text": "Pain"}, {"lang": "en", "text": "Bread"}], "fr", "Pain"),
    ([{"lang": "de", "text": "Brot"}, {"lang": "en", "text": "Bread"}], "fr", "Bread"),
    ([{"lang": "de", "text": "Brot"}], "fr", "Brot"),
    ([{"lang": "main", "text": "  "}], "fr", None),
    ("  Chuỗi  ", None, "Chuỗi"), (None, None, None), ([], None, None),
])
def test_pick_text(entries, lang, exp):
    assert fd.pick_text(entries, lang) == exp


def test_nutriments_to_dict():
    entries = [{"name": "sugars", "100g": 5.5}, {"name": "salt", "100g": None}, {"name": None, "100g": 1}, "x"]
    assert fd.nutriments_to_dict(entries) == {"sugars_100g": 5.5}
    assert fd.nutriments_to_dict(None) == {}
    assert fd.nutriments_to_dict({"sugars_100g": 1}) == {"sugars_100g": 1}


@pytest.mark.parametrize("tag,exp", [("en:sugary-snacks", "sugary snacks"), ("fruits", "fruits"),
                                     ("", None), (None, None), ("en:", None)])
def test_food_group_label(tag, exp):
    assert fd.food_group_label(tag) == exp


def test_row_to_payload_matches_api_shape():
    row = make_rows(1)[0]
    row = {k: v for k, v in row.items() if k in fd.SELECT_COLUMNS}
    p = fd.row_to_payload(row)
    assert p["product_name"] == "Sản phẩm 0"
    assert p["ingredients_text"] == "sucre, farine"
    assert p["nutriments"] == {"sugars_100g": 30.0, "energy-kcal_100g": 450.0}
    assert (p["pnns_groups_1"], p["pnns_groups_2"]) == ("sugary snacks", "biscuits and cakes")
    assert p["code"] == "0000000000000"


# --------------------------------------------------------------------------- truy vấn
def test_describe_and_plan_columns(dump):
    path, _ = dump
    con = fd.connect(path)
    available = fd.describe(con, path)
    con.close()
    selected, missing = fd.plan_columns(available)
    assert selected == list(fd.SELECT_COLUMNS) and missing == []


def test_plan_columns_requires_core_columns():
    with pytest.raises(ValueError):
        fd.plan_columns({"code": "VARCHAR", "nutriscore_grade": "VARCHAR"})


def test_natural_sample_size_and_eligibility(dump, tmp_path):
    path, rows = dump
    summary, recs, _ = run(path, tmp_path, n=100)
    assert summary["written"] == len(recs) == 100
    eligible = eligible_codes(rows)
    for r in recs:
        p = r["raw_payload"]
        assert p["code"] in eligible
        assert p["nutriscore_grade"].lower() in "abcde"
        assert p["ingredients_tags"]


def test_obsolete_and_invalid_grades_excluded(dump, tmp_path):
    path, rows = dump
    _, recs, _ = run(path, tmp_path, n=10_000)
    assert {r["raw_payload"]["code"] for r in recs} == eligible_codes(rows)


def test_eligible_counts_reported_per_grade(dump, tmp_path):
    path, rows = dump
    summary, _, _ = run(path, tmp_path, n=10)
    expected = Counter(r["nutriscore_grade"].lower() for r in rows if r["code"] in eligible_codes(rows))
    assert summary["eligible"] == {g: expected[g] for g in "abcde"}


def test_stratified_caps_each_grade(dump, tmp_path):
    path, _ = dump
    _, recs, _ = run(path, tmp_path, strategy="stratified", per_grade=20)
    counts = Counter(r["raw_payload"]["nutriscore_grade"].lower() for r in recs)
    assert set(counts) == set("abcde")
    assert all(v == 20 for v in counts.values())


def test_country_filter(dump, tmp_path):
    path, rows = dump
    _, recs, _ = run(path, tmp_path, n=10_000, country="en:vietnam")
    assert recs
    assert {r["raw_payload"]["code"] for r in recs} == eligible_codes(rows, "en:vietnam")


def test_same_seed_same_sample_different_seed_different_sample(dump, tmp_path):
    path, _ = dump
    a = [r["raw_payload"]["code"] for r in run(path, tmp_path, n=50, seed="1")[1]]
    b = [r["raw_payload"]["code"] for r in run(path, tmp_path, n=50, seed="1")[1]]
    c = [r["raw_payload"]["code"] for r in run(path, tmp_path, n=50, seed="2")[1]]
    assert a == b
    assert set(a) != set(c)


def test_duplicate_codes_in_dump_are_written_once(tmp_path):
    rows = make_rows(40)
    rows += [dict(rows[1]), dict(rows[2])]          # trùng mã
    path = tmp_path / "dup.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path)
    _, recs, _ = run(str(path), tmp_path, n=1000)
    codes = [r["raw_payload"]["code"] for r in recs]
    assert len(codes) == len(set(codes))


def test_missing_optional_column_is_tolerated(tmp_path):
    rows = make_rows(60)
    schema = pa.schema([f for f in SCHEMA if f.name != "food_groups_tags"])
    path = tmp_path / "nofg.parquet"
    pq.write_table(pa.Table.from_pylist([{k: v for k, v in r.items() if k != "food_groups_tags"} for r in rows],
                                        schema=schema), path)
    summary, recs, _ = run(str(path), tmp_path, n=5)
    assert "food_groups_tags" in summary["missing_optional"]
    assert recs and recs[0]["raw_payload"]["pnns_groups_1"] is None


# --------------------------------------------------------------------------- đầu ra dùng được cho các bước sau
def test_output_has_no_personal_fields(dump, tmp_path):
    path, _ = dump
    _, recs, _ = run(path, tmp_path, n=50)
    for r in recs:
        assert raw_audit.find_pii_fields(r["raw_payload"].keys()) == []
        assert "editors" not in r["raw_payload"]


def test_output_metadata_records_sampling_settings(dump, tmp_path):
    path, _ = dump
    _, recs, _ = run(path, tmp_path, n=5, seed="7")
    meta = recs[0]["_metadata"]
    assert meta["source_endpoint"] == path
    assert meta["filters"]["seed"] == "7" and meta["filters"]["strategy"] == "natural"
    assert meta["retrieved_at"]


def test_output_works_with_loader_audit_and_staging(dump, tmp_path):
    path, _ = dump
    _, _, out = run(path, tmp_path, n=80)
    assert len(list(iter_records(out))) == 80                       # load_raw_to_postgres
    summary = raw_audit.audit_records(raw_audit.iter_jsonl(out))       # raw_audit
    assert summary["usable"] == 80
    assert summary["pii_fields_present"] == []
    assert summary["code"]["duplicate_records"] == 0
    features, audit = staging.stage(raw_audit.iter_jsonl(out))         # staging
    assert len(features) == 80
    assert features["pnns_groups_1"].eq("sugary snacks").all()
    assert audit["sugars_100g"].eq(30.0).all()


# --------------------------------------------------------------------------- dòng lệnh
def test_main_missing_file_explains_how_to_download(tmp_path, capsys):
    rc = fd.main(["--source", str(tmp_path / "none.parquet")])
    assert rc == 1
    assert "huggingface.co" in capsys.readouterr().out


def test_main_describe(dump, capsys):
    path, _ = dump
    assert fd.main(["--source", path, "--describe"]) == 0
    out = capsys.readouterr().out
    assert "nutriscore_grade" in out and "Cột cần mà không có: không" in out


def test_main_writes_file_into_out_dir(dump, tmp_path):
    path, _ = dump
    out_dir = tmp_path / "raw"
    assert fd.main(["--source", path, "--n", "30", "--out-dir", str(out_dir)]) == 0
    files = list(out_dir.glob("raw_products_dump_*.jsonl.gz"))
    assert len(files) == 1 and len(read_out(files[0])) == 30
