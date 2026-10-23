"""Kiểm thử Bước 4 - làm sạch (src/cleaning.py). Không cần mạng hay PostgreSQL."""
import json

import numpy as np
import pandas as pd
import pytest

from src import cleaning as cl
from src.staging import stage, write_outputs
from tests.helpers import make_payload as mp


def run(payloads, **kw):
    features, audit = stage(payloads)
    return cl.clean(features, audit, **kw)


# ======================================================================================
# Hàm nhỏ
# ======================================================================================
@pytest.mark.parametrize("v, exp", [
    (["a", "b"], ["a", "b"]), (np.array(["a"]), ["a"]), (None, None),
    ("abc", None), (float("nan"), None), ({"a": 1}, None), (5, None),
])
def test_as_list(v, exp):
    assert cl.as_list(v) == exp


@pytest.mark.parametrize("v, exp", [
    ("xx:Carrefour", "carrefour"), ("xx:carrefour", "carrefour"), ("Nestlé", "nestle"),
    ("fr:Côte d'Or ", "cote-d-or"), ("xx:U", "u"), ("xx:marque-repere", "marque-repere"),
    ("   ", None), (None, None), (42, None), ("xx:!!!", None),
])
def test_normalize_brand(v, exp):
    assert cl.normalize_brand(v) == exp


def test_brand_case_variants_merge():
    assert cl.clean_brands(["xx:Carrefour", "xx:carrefour", "xx:Carrefour Bio"]) == ["carrefour", "carrefour-bio"]


@pytest.mark.parametrize("v, exp", [
    ("  Pâte à   tartiner!! ", "pate a tartiner"), ("NUTELLA", "nutella"), ("", None), (None, None),
])
def test_normalize_name(v, exp):
    assert cl.normalize_name(v) == exp


def test_clean_tags_dedupes_keeps_order_and_absent_vs_empty():
    assert cl.clean_tags([" en:Sugar", "en:sugar", "", "en:salt", 3]) == ["en:sugar", "en:salt"]
    assert cl.clean_tags(None) is None
    assert cl.clean_tags([]) == []
    assert cl.clean_tags(["en:world", "en:france"], drop=cl.NON_COUNTRY_TAGS) == ["en:france"]


def test_off_taxonomy_share():
    assert cl.off_taxonomy_share(["en:a", "fr:b", "en:c", "de:d"]) == 0.5
    assert cl.off_taxonomy_share([]) is None
    assert cl.off_taxonomy_share(None) is None


def test_content_key_requires_name_and_ingredients():
    assert cl.content_key("b", None, ["en:a"]) is None
    assert cl.content_key("b", "x", []) is None
    assert cl.content_key("b", "x", ["en:a"]) == cl.content_key("b", "x", ["en:a"])
    assert cl.content_key("b", "x", ["en:a"]) != cl.content_key(None, "x", ["en:a"])
    assert cl.content_key("b", "x", ["en:a", "en:b"]) != cl.content_key("b", "x", ["en:b", "en:a"])


def test_group_id_never_lumps_missing_brands_together():
    assert cl.make_group_id("nestle", "x", "1") == "brand:nestle"
    assert cl.make_group_id(None, "kit kat", "1") == "name:kit kat"
    assert cl.make_group_id(None, None, "0123") == "code:0123"
    assert cl.make_group_id(None, None, "1") != cl.make_group_id(None, None, "2")


@pytest.mark.parametrize("score, v17, v23", [
    (-5, "a", "a"), (-1, "a", "a"), (0, "b", "a"), (1, "b", "b"), (2, "b", "b"), (3, "c", "c"),
    (10, "c", "c"), (11, "d", "d"), (18, "d", "d"), (19, "e", "e"), (30, "e", "e"),
])
def test_grade_from_score(score, v17, v23):
    assert cl.grade_from_score(score, "2017") == v17
    assert cl.grade_from_score(score, "2023") == v23


@pytest.mark.parametrize("score, grade, exp", [
    (5, "c", "both"), (0, "b", "2017_only"), (0, "a", "2023_only"), (25, "a", "neither"),
    (None, "a", None), (float("nan"), "a", None), (5, None, None), (5, "x", None),
])
def test_score_grade_consistency(score, grade, exp):
    assert cl.score_grade_consistency(score, grade) == exp


@pytest.mark.parametrize("score, v17, v23", [
    (-7, "a", "a"), (-6, "a", "a"), (-5, "a", "b"), (-1, "a", "b"), (0, "b", "b"),
    (2, "b", "b"), (3, "c", "c"), (18, "d", "d"), (19, "e", "e"),
])
def test_grade_from_score_fats_oils_nuts_seeds(score, v17, v23):
    # Ngưỡng riêng chỉ có ở bản 2023 (A <= -6); bản 2017 dùng chung bảng thực phẩm
    assert cl.grade_from_score(score, "2017", is_fat=True) == v17
    assert cl.grade_from_score(score, "2023", is_fat=True) == v23


@pytest.mark.parametrize("score, grade, exp", [
    (-3, "b", "2023_only"), (-3, "a", "2017_only"), (-6, "a", "both"), (0, "a", "neither"), (0, "b", "both"),
])
def test_score_grade_consistency_fats(score, grade, exp):
    assert cl.score_grade_consistency(score, grade, is_fat=True) == exp


@pytest.mark.parametrize("cats, exp", [
    (["en:plant-based-foods", "en:fats", "en:olive-oils"], True), (["en:nuts"], True),
    (np.array(["en:seeds"]), True), (["en:cheeses"], False), ([], False), (None, False), (float("nan"), False),
])
def test_is_fat_oil_nut_seed(cats, exp):
    assert cl.is_fat_oil_nut_seed(cats) is exp


@pytest.mark.parametrize("bad", ["nutriscore_grade", "nutriscore_score", "sugars_100g", "fat_serving",
                                 "nutriments", "creator", "nutrition_label", "nutrient_levels_tags"])
def test_assert_no_leakage_rejects(bad):
    with pytest.raises(ValueError):
        cl.assert_no_leakage(["code", bad])


def test_assert_no_leakage_accepts_clean_columns():
    cl.assert_no_leakage(cl.CLEAN_FEATURE_COLUMNS)


@pytest.mark.parametrize("tag", [
    "en:nutriscore", "en:nutriscore-grade-a", "en:nutriscore-experiment-grade-d", "en:nutri-score-a-b",
    "en:nutriscore-grade-b-new-calculation", "en:health-star-rating-4-5", "en:keyhole",
    "es:exceso-azucares", "es:exceso en calorías", "es:alto-en-sodio", "es:1-sello", "en:high-in-sugars",
    "EN:NUTRISCORE-GRADE-E",
])
def test_leaky_labels_detected(tag):
    assert cl.is_leaky_label(tag)


@pytest.mark.parametrize("tag", [
    "en:organic", "en:no-added-sugar", "en:low-fat", "en:high-in-omega-3", "en:high-in-fibre",
    "en:vegan", "en:fair-trade", "es:sello-de-calidad", None,
])
def test_marketing_claims_are_kept(tag):
    # Lời quảng cáo về một chất có sẵn trên bao bì, không phải điểm tóm tắt dinh dưỡng
    assert not cl.is_leaky_label(tag)


def test_drop_leaky_labels_keeps_others_and_none():
    assert cl.drop_leaky_labels(["en:organic", "en:nutriscore-grade-a", "en:vegan"]) == ["en:organic", "en:vegan"]
    assert cl.drop_leaky_labels(np.array(["en:nutriscore"])) == []
    assert cl.drop_leaky_labels(None) is None


def test_assert_no_leaky_values():
    cl.assert_no_leaky_values(pd.DataFrame({"labels_tags": [["en:organic"], None, []]}))
    with pytest.raises(ValueError, match="rò rỉ"):
        cl.assert_no_leaky_values(pd.DataFrame({"labels_tags": [["en:organic"], ["en:nutriscore-grade-c"]]}))


def test_clean_removes_leaky_labels_but_keeps_row():
    X, *_, rep = run([mp(code="1", labels_tags=["en:organic", "en:nutriscore-grade-c", "en:health-star-rating-4"]),
                      mp(code="2", product_name="b", labels_tags=["en:low-fat"])])
    assert len(X) == 2
    by_code = dict(zip(X["code"], X["labels_tags"]))
    assert list(by_code["1"]) == ["en:organic"]
    assert list(by_code["2"]) == ["en:low-fat"]
    assert rep["normalization"]["rows_with_leaky_labels_removed"] == 1


# ======================================================================================
# Ghép đầu vào
# ======================================================================================
def test_merge_rejects_mismatched_row_ids():
    f, a = stage([mp(code="1"), mp(code="2")])
    with pytest.raises(ValueError, match="không khớp"):
        cl.merge_inputs(f, a.iloc[:1])


def test_merge_rejects_duplicate_row_ids():
    f, a = stage([mp(code="1"), mp(code="2")])
    f.loc[1, "row_id"] = 0
    with pytest.raises(ValueError, match="trùng"):
        cl.merge_inputs(f, a)


# ======================================================================================
# Pipeline: lọc
# ======================================================================================
def test_clean_happy_path_keeps_valid_rows():
    X, y, audit, rep = run([mp(code="0001", brand="b1"), mp(code="0002", brand="b2", grade="A")])
    assert len(X) == len(y) == len(audit) == 2
    assert list(X["row_id"]) == list(y["row_id"]) == list(audit["row_id"])
    assert list(y["nutriscore_grade"]) == ["c", "a"]
    assert rep["funnel"][-1]["remaining"] == 2


@pytest.mark.parametrize("grade", ["unknown", "not-applicable", "", None, "f"])
def test_invalid_label_is_dropped(grade):
    X, y, _, rep = run([mp(code="1"), mp(code="2", grade=grade, brand="z")])
    assert list(X["code"]) == ["1"]
    assert rep["funnel"][1]["dropped"] == 1


@pytest.mark.parametrize("ing", [None, ()])
def test_no_ingredients_is_dropped(ing):
    X, *_ = run([mp(code="1"), mp(code="2", ingredients=ing, brand="z")])
    assert list(X["code"]) == ["1"]


@pytest.mark.parametrize("code", ["12a3", None, "  "])
def test_bad_barcode_is_dropped(code):
    X, *_ = run([mp(code="1"), mp(code=code, brand="z")])
    assert list(X["code"]) == ["1"]


def test_leading_zero_barcode_is_kept_as_string():
    X, *_ = run([mp(code="0001234567890")])
    assert X.loc[0, "code"] == "0001234567890"


def test_absurd_ingredient_count_is_dropped_and_threshold_is_configurable():
    payloads = [mp(code="1", ingredients_n=5), mp(code="2", ingredients_n=500, brand="z")]
    X, *_ = run(payloads)
    assert list(X["code"]) == ["1"]
    X2, *_ = run(payloads, max_ingredients=1000)
    assert len(X2) == 2


def test_duplicate_barcode_keeps_most_recent_edit():
    old = mp(code="1", grade="e", last_modified_t=1_600_000_000)
    new = mp(code="1", grade="b", last_modified_t=1_700_000_000, product_name="Tên mới")
    X, y, _, rep = run([old, new])
    assert len(X) == 1 and y.loc[0, "nutriscore_grade"] == "b"
    assert any(f["step"].startswith("Trùng mã vạch") and f["dropped"] == 1 for f in rep["funnel"])


def test_content_duplicate_across_barcodes_is_removed():
    a = mp(code="1", brand="xx:Nutella", product_name="Nutella 400g", last_modified_t=1_600_000_000)
    b = mp(code="2", brand="xx:nutella", product_name="NUTELLA 400G", last_modified_t=1_700_000_000)
    X, *_ = run([a, b])
    assert list(X["code"]) == ["2"]


def test_conflicting_grades_in_content_duplicates_are_counted():
    a = mp(code="1", grade="a", product_name="X")
    b = mp(code="2", grade="e", product_name="X")
    *_, rep = run([a, b])
    assert rep["duplicates"]["content_duplicate_groups_with_conflicting_grades"] == 1


def test_different_ingredients_are_not_content_duplicates():
    a = mp(code="1", product_name="X", ingredients=("en:sugar",))
    b = mp(code="2", product_name="X", ingredients=("en:salt",))
    X, *_ = run([a, b])
    assert len(X) == 2


def test_missing_name_is_never_treated_as_duplicate():
    X, *_ = run([mp(code="1", product_name=None), mp(code="2", product_name=None)])
    assert len(X) == 2


def test_funnel_is_consistent():
    payloads = [mp(code=str(i), brand=f"b{i}", product_name=f"p{i}") for i in range(10)]
    payloads += [mp(code="x1"), mp(code="20", grade="unknown"), mp(code="0", brand="b0", product_name="p0")]
    *_, rep = run(payloads)
    f = rep["funnel"]
    assert f[0]["remaining"] == len(payloads)
    for prev, cur in zip(f, f[1:]):
        assert prev["remaining"] - cur["dropped"] == cur["remaining"]
    assert f[-1]["remaining"] == rep["rows"] == 10


def test_never_filters_on_nutrition():
    """Giá trị dinh dưỡng phi lý KHÔNG được làm mất dòng: lọc dựa vào nhãn/dinh dưỡng là rò rỉ."""
    X, *_ = run([mp(code="1", nutriments={"sugars_100g": 9999, "salt_100g": -5})])
    assert len(X) == 1


# ======================================================================================
# Pipeline: chuẩn hóa, cờ, nhóm
# ======================================================================================
def test_brands_are_normalized():
    X, *_ = run([mp(code="1", brand="xx:Carrefour", product_name="a"),
                 mp(code="2", brand="xx:carrefour", product_name="b")])
    assert set(X["brand"]) == {"carrefour"}
    assert list(X.loc[0, "brands_tags"]) == ["carrefour"]


def test_en_world_is_removed_from_countries():
    X, *_, rep = run([mp(code="1", countries=("en:world",), product_name="a"),
                      mp(code="2", countries=("en:world", "en:france"), product_name="b")])
    assert list(X.loc[0, "countries_tags"]) == []
    assert list(X.loc[1, "countries_tags"]) == ["en:france"]
    assert list(X["n_countries"]) == [0, 1]
    assert rep["normalization"]["rows_with_en_world"] == 2


def test_all_countries_are_kept():
    X, *_ = run([mp(code=str(i), countries=(c,), product_name=c)
                 for i, c in enumerate(["en:france", "en:vietnam", "en:united-states", "en:peru"])])
    assert len(X) == 4


def test_negative_counts_become_null():
    X, *_, rep = run([mp(code="1", additives_n=-1)])
    assert pd.isna(X.loc[0, "additives_n"])
    assert rep["normalization"]["additives_n_negative_to_null"] == 1


def test_missing_ingredients_n_is_filled_from_tags():
    X, *_ = run([mp(code="1", ingredients=("en:a", "en:b", "en:c"))])  # make_payload không có ingredients_n
    assert X.loc[0, "ingredients_n"] == 3


def test_flags():
    X, *_ = run([
        mp(code="1", ingredients=("en:honey",), ingredients_n=1, nova=None, brand=None, product_name="mat ong"),
        mp(code="2", ingredients=("en:a", "fr:b"), ingredients_n=2, product_name="x"),
    ])
    r0, r1 = X.iloc[0], X.iloc[1]
    assert r0["flag_few_ingredients"] and r0["flag_missing_nova"] and r0["flag_missing_brand"]
    assert not r1["flag_few_ingredients"] and not r1["flag_missing_nova"] and not r1["flag_missing_brand"]
    assert r0["share_ingredients_off_taxonomy"] == 0.0
    assert r1["share_ingredients_off_taxonomy"] == 0.5


def test_single_ingredient_products_are_kept():
    X, *_ = run([mp(code="1", ingredients=("en:olive-oil",), ingredients_n=1)])
    assert len(X) == 1


def test_group_ids_in_pipeline():
    X, *_ = run([mp(code="1", brand="xx:Nestle", product_name="a"),
                 mp(code="2", brand="xx:nestle", product_name="b"),
                 mp(code="3", brand=None, product_name="Bánh A"),
                 mp(code="4", brand=None, product_name="Bánh B")])
    g = list(X["group_id"])
    assert g[0] == g[1] == "brand:nestle"
    assert g[2] == "name:banh a" and g[3] == "name:banh b"


def test_output_layout_and_no_leakage():
    X, y, audit, _ = run([mp(code="1")])
    assert list(X.columns) == cl.CLEAN_FEATURE_COLUMNS
    assert list(y.columns) == cl.CLEAN_LABEL_COLUMNS
    assert not any("nutri" in c or c.endswith("_100g") for c in X.columns)
    assert "sugars_100g" in audit.columns


def test_dtypes():
    X, *_ = run([mp(code="1"), mp(code="2", nova=None, brand="z")])
    for col in ("ingredients_n", "additives_n", "nova_group", "n_countries"):
        assert str(X[col].dtype) == "Int64", col
    for col in ("flag_few_ingredients", "flag_missing_nova", "flag_missing_brand"):
        assert X[col].dtype == bool, col


def test_parquet_roundtrip(tmp_path):
    X, y, *_ = run([mp(code="0007")])
    X.to_parquet(tmp_path / "x.parquet", index=False)
    back = pd.read_parquet(tmp_path / "x.parquet")
    assert back.loc[0, "code"] == "0007"
    assert list(back.loc[0, "ingredients_tags"]) == ["en:sugar", "en:palm-oil"]
    # chạy lại cleaning trên dữ liệu đọc từ parquet (list thành mảng numpy) không được lỗi
    f, a = stage([mp(code="0007")])
    write_outputs(f, a, tmp_path)
    X2, *_ = cl.clean(pd.read_parquet(tmp_path / "staging_features.parquet"),
                      pd.read_parquet(tmp_path / "staging_audit.parquet"))
    assert len(X2) == 1


def test_clean_is_deterministic():
    payloads = [mp(code=str(i), brand=f"b{i % 3}", product_name=f"p{i % 4}") for i in range(20)]
    X1, *_ = run(payloads)
    X2, *_ = run(list(reversed(payloads)))
    assert sorted(X1["code"]) == sorted(X2["code"])


# ======================================================================================
# Báo cáo và dòng lệnh
# ======================================================================================
def test_consistency_report_skips_beverages():
    payloads = [mp(code="1", nutriscore_score=5, grade="c"),
                mp(code="2", nutriscore_score=0, grade="b", product_name="b"),
                mp(code="3", nutriscore_score=0, grade="b", product_name="c", categories_tags=["en:beverages"])]
    *_, rep = run(payloads)
    c = rep["score_grade_consistency"]
    assert c["available"] and c["beverages_skipped"] == 1
    assert c["foods"] == {"both": 1, "2017_only": 1}


def test_consistency_report_uses_fat_thresholds():
    # Dầu điểm -3 hạng B: sai với bảng thực phẩm thường, nhưng đúng ngưỡng chất béo bản 2023
    payloads = [mp(code="1", nutriscore_score=-3, grade="b", categories_tags=["en:fats", "en:vegetable-oils"]),
                mp(code="2", nutriscore_score=-3, grade="b", product_name="b")]
    *_, rep = run(payloads)
    c = rep["score_grade_consistency"]
    assert c["fats_oils_nuts_seeds"] == 1
    assert c["foods"] == {"2023_only": 1, "neither": 1}


def test_report_renders(tmp_path):
    *_, rep = run([mp(code="1", nutriscore_score=5)])
    md = cl.render_report(rep, "2026-01-01")
    for heading in ("Phễu làm sạch", "Phân bố hạng", "GroupKFold", "Kiểm tra điểm - hạng"):
        assert heading in md
    json.dumps(rep, ensure_ascii=False)  # phải tuần tự hóa được


def test_main_end_to_end(tmp_path, capsys):
    f, a = stage([mp(code="0001"), mp(code="0002", grade="unknown", brand="z")])
    write_outputs(f, a, tmp_path / "processed")
    rc = cl.main(["--in-dir", str(tmp_path / "processed"), "--final-dir", str(tmp_path / "final"),
                  "--audit-out", str(tmp_path / "processed" / "clean_audit.parquet"),
                  "--report", str(tmp_path / "reports" / "cleaning_report.md")])
    assert rc == 0
    X = pd.read_parquet(tmp_path / "final" / "clean_features.parquet")
    y = pd.read_parquet(tmp_path / "final" / "clean_labels.parquet")
    assert list(X["code"]) == list(y["code"]) == ["0001"]
    assert (tmp_path / "reports" / "cleaning_report.json").is_file()
    assert "còn 1" in capsys.readouterr().out


def test_main_without_staging_returns_error(tmp_path, capsys):
    assert cl.main(["--in-dir", str(tmp_path)]) == 1
    assert "src.staging" in capsys.readouterr().out


def test_data_dictionary_documents_every_clean_column(root):
    doc = (root / "docs" / "data_dictionary.md").read_text(encoding="utf-8")
    missing = [c for c in cl.CLEAN_FEATURE_COLUMNS + cl.CLEAN_LABEL_COLUMNS if f"`{c}`" not in doc]
    assert not missing, f"data_dictionary.md thiếu cột: {missing}"


def test_report_does_not_count_missing_brand_as_a_brand():
    """Lỗi từng gặp: NaN là truthy nên 'nan' xuất hiện như một thương hiệu có 4556 dòng."""
    *_, rep = run([mp(code="1", brand=None, product_name="a"), mp(code="2", brand=None, product_name="b"),
                   mp(code="3", brand="xx:Nestle", product_name="c")])
    assert rep["brands_unique"] == 1
    assert rep["brands_top"] == [("nestle", 1)]
    assert "nan" not in cl.render_report(rep, "t").lower().split("## 6.")[1].split("## 7.")[0]
