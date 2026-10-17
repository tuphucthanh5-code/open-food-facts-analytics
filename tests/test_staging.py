"""Kiểm thử bước staging: ép kiểu, tách bảng, chống rò rỉ nhãn, bảo vệ dữ liệu cá nhân."""
import json
import math
import re

import pandas as pd
import pytest

from src import staging as st
from src.raw_audit import find_leakage_fields, find_pii_fields
from tests.helpers import make_payload as mp


def full_payload(**over):
    p = mp(
        code="0012345678905", grade="B", nova="3",
        ingredients=("en:sugar", "en:cocoa"), countries=("en:france", "en:vietnam"), brand="nutella",
        pnns_groups_1="Sugary snacks", pnns_groups_2="unknown",
        ingredients_n=2, additives_n=1, additives_tags=["en:e322"], allergens_tags=[],
        labels_tags=["en:vegan"], ingredients_from_palm_oil_n=1,
        ingredients_analysis_tags=["en:palm-oil"], categories_tags=["en:spreads"],
        nutriments={"energy-kcal_100g": 539, "sugars_100g": "56.3", "fat_100g": 30.9, "salt_100g": 0.107},
        nutriscore_score=26, nutriscore_version="2023",
        creator="someone", editors_tags=["a", "b"], last_editor="x",
    )
    p.update(over)
    return p


# --------------------------------------------------------------------------- ép kiểu
@pytest.mark.parametrize("v,exp", [("  abc ", "abc"), ("", None), ("   ", None), (None, None),
                                   (5, "5"), (1.5, "1.5"), (True, None), (["x"], None), ({}, None)])
def test_to_str(v, exp):
    assert st.to_str(v) == exp


@pytest.mark.parametrize("v,exp", [(3, 3), ("4", 4), (" 5 ", 5), (2.0, 2), (2.5, None), ("x", None),
                                   (None, None), (True, None), ("", None), (-1, -1)])
def test_to_int(v, exp):
    assert st.to_int(v) == exp


@pytest.mark.parametrize("v,exp", [(1, 1.0), ("2.5", 2.5), (" 3 ", 3.0), ("x", None), (None, None),
                                   (True, None), ("", None), (float("nan"), None), (float("inf"), None),
                                   ("nan", None)])
def test_to_float(v, exp):
    assert st.to_float(v) == exp


def test_to_list_keeps_absent_and_empty_distinct():
    assert st.to_list(None) is None
    assert st.to_list("not a list") is None
    assert st.to_list([]) == []
    assert st.to_list([" a ", "", None, 3, "b"]) == ["a", "b"]


@pytest.mark.parametrize("v,exp", [("Sugary Snacks", "sugary snacks"), ("unknown", None), ("UNKNOWN", None),
                                   ("", None), (None, None)])
def test_to_category(v, exp):
    assert st.to_category(v) == exp


# --------------------------------------------------------------------------- dòng đặc trưng
def test_feature_row_basic_fields():
    r = st.build_feature_row(full_payload(), 7)
    assert r["row_id"] == 7
    assert r["code"] == "0012345678905"            # giữ số 0 đầu
    assert r["brand"] == "nutella"
    assert r["nova_group"] == 3                    # "3" -> 3
    assert r["pnns_groups_1"] == "sugary snacks"
    assert r["pnns_groups_2"] is None              # unknown -> thiếu
    assert r["ingredients_tags"] == ["en:sugar", "en:cocoa"]
    assert r["allergens_tags"] == []               # rỗng không bị đổi thành None
    assert r["additives_n"] == 1


def test_feature_row_handles_garbage_without_raising():
    junk = {"code": None, "brands_tags": "x", "ingredients_tags": "sugar", "nova_group": "abc",
            "ingredients_n": "n/a", "last_modified_t": "yesterday", "countries_tags": {"a": 1}}
    r = st.build_feature_row(junk, 0)
    assert r["code"] is None and r["brand"] is None
    assert r["ingredients_tags"] is None and r["countries_tags"] is None
    assert r["nova_group"] is None and r["ingredients_n"] is None


def test_feature_row_missing_brand_is_none():
    assert st.build_feature_row(mp(brand=None), 0)["brand"] is None


# --------------------------------------------------------------------------- dòng kiểm toán
def test_audit_row_normalizes_grade_and_keeps_raw():
    r = st.build_audit_row(full_payload(), 0)
    assert r["nutriscore_grade"] == "b"
    assert r["nutriscore_grade_raw"] == "B"


def test_audit_row_unknown_grade_becomes_none_but_raw_is_kept():
    r = st.build_audit_row(mp(grade="not-applicable"), 0)
    assert r["nutriscore_grade"] is None
    assert r["nutriscore_grade_raw"] == "not-applicable"


def test_audit_row_flattens_nutriments_and_coerces_strings():
    r = st.build_audit_row(full_payload(), 0)
    assert r["energy-kcal_100g"] == 539.0
    assert r["sugars_100g"] == 56.3                # "56.3" -> 56.3
    assert r["proteins_100g"] is None              # không có trong dữ liệu


def test_audit_row_survives_nutriments_that_is_not_a_dict():
    r = st.build_audit_row(mp(nutriments="oops"), 0)
    assert all(r[k] is None for k in st.NUTRIENT_KEYS)


def test_audit_row_keeps_other_nutriscore_fields():
    r = st.build_audit_row(full_payload(nutriscore_data={"score": 3}), 0)
    assert r["nutriscore_score"] == 26
    assert r["nutriscore_version"] == "2023"
    assert json.loads(r["nutriscore_data"]) == {"score": 3}    # dict được lưu thành chuỗi JSON


# --------------------------------------------------------------------------- stage()
def test_stage_does_not_drop_any_row():
    payloads = [full_payload(), mp(grade=None, ingredients=None), mp(grade="unknown", ingredients=()), {}]
    features, audit = st.stage(payloads)
    assert len(features) == len(audit) == 4


def test_stage_row_ids_align_between_tables():
    features, audit = st.stage([mp(code=f"{i:05d}") for i in range(5)])
    assert list(features["row_id"]) == list(audit["row_id"]) == [0, 1, 2, 3, 4]
    assert list(features["code"]) == list(audit["code"])


def test_features_table_has_no_label_nutrition_or_personal_columns():
    features, _ = st.stage([full_payload()])
    cols = list(features.columns)
    assert find_leakage_fields(cols) == []
    assert find_pii_fields(cols) == []
    assert not [c for c in cols if c.endswith("_100g") or c.endswith("_serving")]


def test_personal_fields_are_in_neither_table():
    features, audit = st.stage([full_payload()])
    for table in (features, audit):
        assert find_pii_fields(list(table.columns)) == []


def test_columns_follow_declared_layout():
    features, audit = st.stage([full_payload()])
    assert list(features.columns) == st.FEATURE_COLUMNS
    assert list(audit.columns)[:len(st.AUDIT_BASE_COLUMNS)] == st.AUDIT_BASE_COLUMNS


def test_dtypes():
    features, audit = st.stage([full_payload(), mp(nova=None)])
    assert str(features["nova_group"].dtype) == "Int64"
    assert str(features["ingredients_n"].dtype) == "Int64"
    assert pd.api.types.is_datetime64_any_dtype(features["last_modified"])
    assert features["last_modified"].dt.tz is not None
    assert audit["sugars_100g"].dtype == "float64"
    assert features["nova_group"].isna().sum() == 1


def test_last_modified_converted_from_epoch_seconds():
    features, _ = st.stage([mp(last_modified_t=1700000000)])
    assert features.loc[0, "last_modified"] == pd.Timestamp("2023-11-14T22:13:20Z")


def test_bad_timestamp_becomes_nat_not_error():
    features, _ = st.stage([mp(last_modified_t="bad")])
    assert features["last_modified"].isna().all()


def test_extra_nutriscore_columns_appear_only_in_audit():
    features, audit = st.stage([full_payload()])
    assert "nutriscore_version" in audit.columns
    assert "nutriscore_version" not in features.columns


def test_empty_input_gives_empty_tables_with_columns():
    features, audit = st.stage([])
    assert features.empty and audit.empty
    assert list(features.columns) == st.FEATURE_COLUMNS


# --------------------------------------------------------------------------- chốt chặn rò rỉ
@pytest.mark.parametrize("bad", ["nutriscore_grade", "nutriments", "sugars_100g", "salt_serving",
                                 "creator", "editors_tags", "nutrient_levels_tags", "misc_tags"])
def test_assert_features_are_clean_rejects_forbidden_columns(bad):
    with pytest.raises(ValueError):
        st.assert_features_are_clean(["code", bad])


def test_assert_features_are_clean_accepts_declared_columns():
    st.assert_features_are_clean(st.FEATURE_COLUMNS)


# --------------------------------------------------------------------------- tệp parquet
def test_parquet_roundtrip_keeps_types_and_leading_zero(tmp_path):
    features, audit = st.stage([full_payload(), mp(code="0000000000017", nova=None)])
    f_path, a_path = st.write_outputs(features, audit, str(tmp_path / "processed"))
    f2, a2 = pd.read_parquet(f_path), pd.read_parquet(a_path)
    assert list(f2["code"]) == ["0012345678905", "0000000000017"]
    assert str(f2["nova_group"].dtype) == "Int64"
    assert list(f2.loc[0, "ingredients_tags"]) == ["en:sugar", "en:cocoa"]
    assert a2.loc[0, "sugars_100g"] == pytest.approx(56.3)
    assert len(f2) == len(a2) == 2


def test_summary_counts():
    features, audit = st.stage([full_payload(), mp(grade=None), mp(ingredients=(), nova=None), mp(grade="e")])
    s = st.summarize(features, audit)
    assert s["rows"] == 4
    assert s["with_valid_grade"] == 3
    assert s["with_ingredients"] == 3
    assert s["with_nova"] == 3
    assert 0 <= s["missing_pct_features"]["nova_group"] <= 100


def test_report_lists_every_column():
    features, audit = st.stage([full_payload()])
    md = st.render_report(st.summarize(features, audit), "t", "src")
    for c in st.FEATURE_COLUMNS:
        assert f"`{c}`" in md


# --------------------------------------------------------------------------- dòng lệnh
def test_main_end_to_end(tmp_path, write_jsonl_gz, capsys):
    write_jsonl_gz([full_payload(), mp(grade=None), mp(code="0000000000999")])
    out = tmp_path / "processed"
    rc = st.main(["--pattern", str(tmp_path / "*.jsonl.gz"), "--out-dir", str(out),
                  "--report", str(tmp_path / "rep" / "staging.md")])
    assert rc == 0
    assert (out / "staging_features.parquet").exists()
    assert (out / "staging_audit.parquet").exists()
    assert (tmp_path / "rep" / "staging.md").read_text(encoding="utf-8").startswith("# Báo cáo staging")
    assert "Staging 3 dòng" in capsys.readouterr().out
    assert len(pd.read_parquet(out / "staging_features.parquet")) == 3


def test_main_without_files_returns_error(tmp_path, capsys):
    rc = st.main(["--pattern", str(tmp_path / "x*.jsonl.gz"), "--out-dir", str(tmp_path / "o"),
                  "--report", str(tmp_path / "r.md")])
    assert rc == 1
    assert "Không tìm thấy" in capsys.readouterr().out
    assert not (tmp_path / "o").exists()


# --------------------------------------------------------------------------- từ điển dữ liệu
def test_data_dictionary_documents_every_column(root):
    doc = (root / "docs" / "data_dictionary.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"`([^`]+)`", doc))
    missing = [c for c in st.FEATURE_COLUMNS + st.AUDIT_BASE_COLUMNS if c not in documented]
    assert not missing, f"data_dictionary.md thiếu cột: {missing}"
