"""Kiểm thử Bước 6 (src/features.py): đặc trưng tự tạo, bộ biến đổi học từ train, chống rò rỉ, dòng lệnh."""
import numpy as np
import pandas as pd
import pytest

from src import cleaning as cl
from src import features as fe


def crow(**kw):
    """Một dòng giống clean_features.parquet (đủ CLEAN_FEATURE_COLUMNS)."""
    r = {
        "row_id": 0, "code": "3017620422003", "group_id": "brand:nutella", "product_name": "Sản phẩm thử",
        "brand": "nutella", "brands_tags": ["nutella"], "countries_tags": ["en:france"], "n_countries": 1,
        "categories_tags": ["en:snacks", "en:sweet-snacks"], "pnns_groups_1": "sugary snacks",
        "pnns_groups_2": "sweets", "ingredients_tags": ["en:sugar", "en:added-sugar", "en:palm-oil"],
        "ingredients_text": "sucre, huile de palme", "ingredients_n": 2, "ingredients_from_palm_oil_n": 0,
        "ingredients_analysis_tags": ["en:palm-oil", "en:vegan"], "additives_tags": [], "additives_n": 0,
        "allergens_tags": [], "labels_tags": None, "nova_group": 4, "lang": "fr",
        "last_modified": pd.Timestamp("2026-01-01", tz="UTC"), "share_ingredients_off_taxonomy": 0.0,
        "flag_few_ingredients": False, "flag_missing_nova": False, "flag_missing_brand": False,
    }
    r.update(kw)
    return r


def frame(rows):
    df = pd.DataFrame(rows)
    df["row_id"] = range(len(df))
    return df[cl.CLEAN_FEATURE_COLUMNS]


def rows(n, **kw):
    return [crow(code=str(1000 + i), group_id=f"brand:b{i}", **kw) for i in range(n)]


# --------------------------------------------------------------------------- nhận diện đường/muối/chất béo
@pytest.mark.parametrize("tag, tokens, expected", [
    ("en:sugar", fe.SUGAR_TOKENS, True),
    ("en:glucose-fructose-syrup", fe.SUGAR_TOKENS, True),
    ("en:no-added-sugar", fe.SUGAR_TOKENS, False),
    ("en:lactose", fe.SUGAR_TOKENS, False),
    ("fr:sucre", fe.SUGAR_TOKENS, False),          # chỉ nhận thẻ taxonomy en:
    ("en:sea-salt", fe.SALT_TOKENS, True),
    ("en:unsalted-butter", fe.SALT_TOKENS, False),
    ("en:sunflower-oil", fe.FAT_TOKENS, True),
    ("en:fat-reduced-cocoa", fe.FAT_TOKENS, False),
    ("en:reduced-fat-mayonnaise", fe.FAT_TOKENS, False),
    ("en:non-hydrogenated-palm-oil", fe.FAT_TOKENS, True),   # "non" đi với hydrogenated, không phải với dầu
    ("en:buttermilk", fe.FAT_TOKENS, False),
])
def test_tag_has(tag, tokens, expected):
    assert fe.tag_has(tag, tokens) is expected


def test_relative_position_first_middle_absent():
    tags = ["en:sugar", "en:added-sugar", "en:salt", "en:water"]
    assert fe.relative_position(tags, fe.SUGAR_TOKENS) == 1.0
    assert fe.relative_position(tags, fe.SALT_TOKENS) == 0.5
    assert fe.relative_position(tags, fe.FAT_TOKENS) == 0.0
    assert fe.relative_position(None, fe.SALT_TOKENS) == 0.0
    assert fe.relative_position(np.array(["en:salt"], dtype=object), fe.SALT_TOKENS) == 1.0


def test_count_percentages():
    assert fe.count_percentages("cacao 70 %, sữa 12,5%, đường") == 2
    assert fe.count_percentages(None) == 0


def test_has_palm_oil_from_tags_or_count():
    assert fe.has_palm_oil(["en:palm-kernel-oil"], 0)
    assert fe.has_palm_oil(["en:sugar"], 1)
    assert not fe.has_palm_oil(["en:sugar"], float("nan"))
    assert not fe.has_palm_oil(["en:palm-sugar"], None)


@pytest.mark.parametrize("tag, cls", [
    ("en:e102", "add_colours"), ("en:e202", "add_preservatives"), ("en:e322i", "add_antioxidants_acids"),
    ("en:e471", "add_thickeners_emulsifiers"), ("en:e500ii", "add_acidity_anticaking"),
    ("en:e621", "add_flavour_enhancers"), ("en:e951", "add_sweeteners"), ("en:e420", "add_sweeteners"),
    ("en:e1442", "add_other"), ("en:something", "add_other"),
])
def test_additive_class(tag, cls):
    assert fe.additive_class(tag) == cls


def test_additive_class_counts_parent_and_child_counted_once():
    counts = dict(zip(fe.ADDITIVE_CLASSES, fe.additive_class_counts(["en:e322", "en:e322i", "en:e330", "en:e951"])))
    assert counts["add_antioxidants_acids"] == 2
    assert counts["add_sweeteners"] == 1
    assert sum(counts.values()) == 3


@pytest.mark.parametrize("value, expected", [
    (1, [1, 0, 0, 0, 0]), (2, [0, 1, 0, 0, 0]), (4, [0, 0, 0, 1, 0]),
    (None, [0, 0, 0, 0, 1]), (pd.NA, [0, 0, 0, 0, 1]), (7, [0, 0, 0, 0, 1]),
])
def test_nova_one_hot_has_missing_category(value, expected):
    assert fe.nova_one_hot(value) == expected


def test_clean_pnns_merges_alcoholic_beverages():
    assert fe.clean_pnns("Alcoholic beverages") == "beverages"
    assert fe.clean_pnns("sugary snacks") == "sugary snacks"
    assert fe.clean_pnns(None) is None
    assert fe.clean_pnns(" ") is None


@pytest.mark.parametrize("labels, expected", [
    (["en:organic"], True), (["en:fr-bio-01"], True), (["fr:ab-agriculture-biologique"], True),
    (["en:biodynamic-agriculture"], False), (["en:no-gluten"], False), (None, False),
])
def test_is_organic(labels, expected):
    assert fe.is_organic(labels) is expected


# --------------------------------------------------------------------------- RowFeatures
def test_row_features_creates_documented_columns():
    out = fe.RowFeatures().fit_transform(frame([crow(), crow(nova_group=None, pnns_groups_2=None)]))
    for c in fe.ROW_FEATURE_COLUMNS:
        assert c in out.columns
    assert out["nova_missing"].tolist() == [0.0, 1.0]
    assert out["pnns_groups_2_filled"].tolist() == ["sweets", "missing"]
    assert out["pos_sugar"].iloc[0] == 1.0
    assert out["has_palm_oil"].iloc[0] == 1.0
    assert out["first_ingredient"].iloc[0] == ["en:sugar"]


def test_row_features_converts_nullable_numbers_to_float_nan():
    df = frame([crow(ingredients_from_palm_oil_n=None)])
    df["ingredients_from_palm_oil_n"] = df["ingredients_from_palm_oil_n"].astype("Int64")
    out = fe.RowFeatures().transform(df)
    assert out["ingredients_from_palm_oil_n"].dtype == "float64"
    assert np.isnan(out["ingredients_from_palm_oil_n"].iloc[0])


@pytest.mark.parametrize("bad", ["nutriscore_grade", "sugars_100g", "nutriscore_score", "creator"])
def test_row_features_refuses_label_nutrition_or_pii_columns(bad):
    df = frame([crow()])
    df[bad] = 1
    with pytest.raises(ValueError, match="cấm"):
        fe.RowFeatures().transform(df)


def test_row_features_requires_clean_columns():
    with pytest.raises(ValueError, match="clean_features"):
        fe.RowFeatures().transform(frame([crow()]).drop(columns=["ingredients_tags"]))


def test_feature_inputs_are_clean_columns_and_not_forbidden():
    assert set(fe.FEATURE_INPUT_COLUMNS) <= set(cl.CLEAN_FEATURE_COLUMNS)
    cl.assert_no_leakage(fe.FEATURE_INPUT_COLUMNS)
    for unused in ("code", "group_id", "brand", "brands_tags", "row_id"):
        assert unused not in fe.FEATURE_INPUT_COLUMNS


# --------------------------------------------------------------------------- TagVectorizer
def test_tag_vectorizer_keeps_only_frequent_tags_and_counts_rare():
    X = pd.DataFrame({"t": [["a", "b"], ["a", "c"], ["a"], None]})
    v = fe.TagVectorizer(min_freq=2).fit(X)
    assert v.vocabulary_ == ["a"]
    m = v.transform(X).toarray()
    assert m[:, 0].tolist() == [1, 1, 1, 0]
    assert m[:, 1].tolist() == pytest.approx([np.log1p(1), np.log1p(1), 0, 0])
    assert list(v.get_feature_names_out()) == ["a", "n_rare"]


def test_tag_vectorizer_counts_each_tag_once_per_product():
    X = pd.DataFrame({"t": [["a", "a", "a"], ["b"]]})
    assert fe.TagVectorizer(min_freq=2).fit(X).vocabulary_ == []


def test_tag_vectorizer_learns_vocabulary_from_fit_data_only():
    train = pd.DataFrame({"t": [["a"], ["a"]]})
    test = pd.DataFrame({"t": [["z"], ["z"], ["a", "z"]]})
    v = fe.TagVectorizer(min_freq=2).fit(train)
    m = v.transform(test).toarray()
    assert v.vocabulary_ == ["a"]
    assert m.shape == (3, 2)
    assert m[:, 1].tolist() == pytest.approx([np.log1p(1)] * 3)   # "z" chưa gặp lúc fit -> thẻ hiếm


def test_tag_vectorizer_without_rare_column():
    v = fe.TagVectorizer(min_freq=1, rare_count=False).fit(pd.DataFrame({"t": [["a"], ["b"]]}))
    assert list(v.get_feature_names_out()) == ["a", "b"]
    assert v.transform(pd.DataFrame({"t": [["b"]]})).toarray().tolist() == [[0, 1]]


def test_tag_vectorizer_refuses_leaky_tags():
    X = pd.DataFrame({"t": [["en:nutriscore-grade-a"], ["en:nutriscore-grade-a"]]})
    with pytest.raises(ValueError, match="rò rỉ"):
        fe.TagVectorizer(min_freq=1).fit(X)


def test_tag_vectorizer_reads_numpy_arrays_from_parquet():
    X = pd.DataFrame({"t": [np.array(["a", "b"], dtype=object), np.array(["a"], dtype=object)]})
    assert fe.TagVectorizer(min_freq=2).fit(X).vocabulary_ == ["a"]


# --------------------------------------------------------------------------- CategoryGroupImputer
def imputer_frame(pairs):
    return pd.DataFrame({"pnns_groups_1": [g for g, _ in pairs], "categories_tags": [t for _, t in pairs]})


def test_imputer_fills_missing_group_from_purest_tag():
    train = imputer_frame([("sugary snacks", ["en:snacks", "en:biscuits"])] * 3
                          + [("salty snacks", ["en:snacks", "en:chips"])] * 2
                          + [(None, ["en:biscuits"]), (None, ["en:chips", "en:snacks"])])
    imp = fe.CategoryGroupImputer(min_support=2, min_purity=0.5).fit(train)
    out = imp.transform(train)
    assert out["pnns_groups_1_filled"].tolist()[-2:] == ["sugary snacks", "salty snacks"]
    assert out["pnns_groups_1_imputed"].tolist() == [0.0] * 5 + [1.0, 1.0]
    assert out["pnns_groups_1_filled"].tolist()[:5] == train["pnns_groups_1"].tolist()[:5]   # nhóm gốc giữ nguyên


def test_imputer_leaves_missing_when_no_known_tag_or_low_purity():
    train = imputer_frame([("a", ["en:x"]), ("b", ["en:x"]), ("a", ["en:y"]), ("a", ["en:y"])])
    imp = fe.CategoryGroupImputer(min_support=2, min_purity=0.5).fit(train)
    out = imp.transform(imputer_frame([(None, ["en:x"]), (None, ["en:unknown"]), (None, None)]))
    assert out["pnns_groups_1_filled"].tolist() == ["missing"] * 3
    assert out["pnns_groups_1_imputed"].tolist() == [0.0] * 3


def test_imputer_learns_only_from_fit_rows():
    """Nhóm của dòng ở tập test không được dùng để bổ sung (chống rò rỉ giữa train và test)."""
    train = imputer_frame([("a", ["en:x"])] * 3)
    test = imputer_frame([("b", ["en:z"])] * 5 + [(None, ["en:z"])])
    out = fe.CategoryGroupImputer(min_support=2).fit(train).transform(test)
    assert out["pnns_groups_1_filled"].iloc[-1] == "missing"


def test_imputer_ignores_tags_below_min_support():
    train = imputer_frame([("a", ["en:x"])])
    imp = fe.CategoryGroupImputer(min_support=2).fit(train)
    assert imp.mapping_ == {}


# --------------------------------------------------------------------------- pipeline
def sample_frame():
    data = (rows(6) +
            rows(6, ingredients_tags=["en:water", "en:salt"], pnns_groups_1="beverages", pnns_groups_2=None,
                 categories_tags=["en:beverages", "en:waters"], nova_group=1, labels_tags=["en:organic"],
                 additives_tags=["en:e330"], countries_tags=["en:united-states"], flag_missing_brand=True) +
            [crow(code="9", pnns_groups_1=None, pnns_groups_2=None, categories_tags=["en:waters"], nova_group=None)])
    return frame(data)


def test_pipeline_outputs_one_row_per_product_with_unique_names():
    X = sample_frame()
    pipe = fe.fit_feature_pipeline(X, min_freq=2, min_support=2)
    m = pipe.transform(X)
    names = fe.feature_names(pipe)
    assert m.shape == (len(X), len(names))
    assert len(set(names)) == len(names)
    assert not np.isnan(m.toarray()).any()
    assert {fe.feature_group(n) for n in names} == set(fe.FEATURE_GROUPS)


def test_pipeline_imputes_pnns_and_sets_flag():
    X = sample_frame()
    pipe = fe.fit_feature_pipeline(X, min_freq=2, min_support=2)
    names = fe.feature_names(pipe)
    m = pipe.transform(X).toarray()
    last = dict(zip(names, m[-1]))
    assert last["categories-pnns__pnns_groups_1_filled_beverages"] == 1.0
    assert last["flags__pnns_groups_1_imputed"] == 1.0
    assert last["nova__nova_missing"] == 1.0


def test_pipeline_group_selection_for_ablation():
    X = sample_frame()
    pipe = fe.fit_feature_pipeline(X, min_freq=2, min_support=2, groups=("nova",))
    assert fe.feature_names(pipe) == [f"nova__{c}" for c in fe.NOVA_COLUMNS]
    without_nova = fe.feature_names(fe.fit_feature_pipeline(
        X, min_freq=2, min_support=2, groups=[g for g in fe.FEATURE_GROUPS if g != "nova"]))
    assert not any(fe.feature_group(n) == "nova" for n in without_nova)


def test_pipeline_rejects_unknown_or_empty_groups():
    with pytest.raises(ValueError):
        fe.build_feature_pipeline(groups=("nutrition",))
    with pytest.raises(ValueError):
        fe.build_feature_pipeline(groups=())


def test_pipeline_transform_handles_unseen_categories():
    X = sample_frame()
    pipe = fe.fit_feature_pipeline(X, min_freq=2, min_support=2)
    new = frame([crow(pnns_groups_1="fish meat eggs", pnns_groups_2="fish and seafood",
                      ingredients_tags=["en:tuna"], categories_tags=["en:fish"], countries_tags=["en:japan"])])
    assert pipe.transform(new).shape == (1, len(fe.feature_names(pipe)))


def test_pipeline_refuses_staging_style_leaky_values():
    """staging_features còn logo Nutri-Score trong labels_tags: pipeline phải dừng lại."""
    X = frame(rows(4, labels_tags=["en:nutriscore-grade-a"]))
    with pytest.raises(ValueError, match="rò rỉ"):
        fe.fit_feature_pipeline(X, min_freq=2, min_support=2)


@pytest.mark.parametrize("names", [
    ["nova__nova_1", "labels-tags__en:nutriscore-grade-a"],
    ["numeric-counts__sugars_100g"],
    ["numeric-counts__nutriscore_score"],
    ["nova__nova_1", "nova__nova_1"],
])
def test_assert_feature_names_clean_rejects(names):
    with pytest.raises(ValueError):
        fe.assert_feature_names_clean(names)


def test_assert_feature_names_clean_allows_ingredient_with_nutri_in_name():
    fe.assert_feature_names_clean(["ingredients__en:nutritional-yeast", "nova__nova_1"])


def test_feature_group():
    assert fe.feature_group("categories-tags__en:snacks") == "categories"
    assert fe.feature_group("nova__nova_1") == "nova"


# --------------------------------------------------------------------------- báo cáo và dòng lệnh
def test_evaluate_pnns_imputation_reports_coverage_and_accuracy():
    X = frame(rows(10) + rows(10, pnns_groups_1="beverages", categories_tags=["en:beverages"])
              + [crow(code="99", group_id="name:x", pnns_groups_1=None, categories_tags=["en:beverages"])])
    X["group_id"] = [f"g{i}" for i in range(len(X))]
    r = fe.evaluate_pnns_imputation(X, min_support=2)
    assert r["missing_rows"] == 1
    assert r["imputed_rows"] == 1
    assert r["imputed_groups"] == {"beverages": 1}
    assert r["holdout_accuracy"] == 1.0


def test_main_writes_report_and_feature_names(tmp_path):
    src = tmp_path / "clean_features.parquet"
    frame(rows(30) + rows(30, pnns_groups_1=None, pnns_groups_2=None)).assign(
        group_id=[f"g{i}" for i in range(60)]).to_parquet(src, index=False)
    report = tmp_path / "features_report.md"
    names = tmp_path / "feature_names.txt"
    code = fe.main(["--in", str(src), "--report", str(report), "--names-out", str(names),
                    "--min-freq", "5", "--compare-min-freq", "5", "20"])
    assert code == 0
    text = report.read_text(encoding="utf-8")
    assert "## 1. Số đặc trưng theo nhóm và ngưỡng" in text
    assert "min_freq = 20" in text
    assert (tmp_path / "features_report.json").is_file()
    lines = names.read_text(encoding="utf-8").split()
    assert "nova__nova_4" in lines


def test_main_returns_1_when_input_missing(tmp_path):
    assert fe.main(["--in", str(tmp_path / "none.parquet"), "--report", str(tmp_path / "r.md")]) == 1


# --------------------------------------------------------------------------- tài liệu
def test_data_dictionary_documents_every_engineered_column(root):
    doc = (root / "docs" / "data_dictionary.md").read_text(encoding="utf-8")
    cols = fe.ROW_FEATURE_COLUMNS + fe.IMPUTER_COLUMNS + list(fe.FEATURE_GROUPS) + ["n_rare"]
    missing = [c for c in cols if f"`{c}`" not in doc]
    assert not missing, f"data_dictionary.md thiếu cột: {missing}"
