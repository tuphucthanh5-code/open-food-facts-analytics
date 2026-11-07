"""src/predict.py: tạo dòng từ dữ liệu nhập, dự đoán, "tắt thẻ", gợi ý sản phẩm tốt hơn (dùng trong dashboard)."""
import numpy as np
import pytest

from src.cleaning import FEATURE_COLUMNS, assert_no_leakage
from src.modeling import GRADES, make_model
from src.predict import alternatives, explain, ingredient_matrix, make_row, predict, pretty, to_tags


@pytest.fixture
def fitted(clean_data):
    X, y = clean_data
    return make_model("lgbm", min_freq=2, n_estimators=30, min_child_samples=5).fit(X, y), X, y


def test_to_tags_keeps_order_and_prefix():
    assert to_tags("Sugar, whole milk powder , E322,, fr:Sucre de canne") == \
        ["en:sugar", "en:whole-milk-powder", "en:e322", "fr:sucre-de-canne"]
    assert to_tags("") == [] and to_tags(None) == []


def test_make_row_has_model_columns_and_no_leakage():
    row = make_row(["en:sugar", "en:palm-oil"], additives=["en:e322"], countries=["en:france"], nova=4)
    assert list(row.columns) == FEATURE_COLUMNS and len(row) == 1
    assert_no_leakage(row.columns)
    r = row.iloc[0]
    assert r["ingredients_n"] == 2 and r["additives_n"] == 1 and r["n_countries"] == 1
    assert r["ingredients_from_palm_oil_n"] == 1


def test_predict_returns_probabilities_for_every_grade(fitted):
    model, X, _ = fitted
    p = predict(model, make_row(["en:sugar", "en:cocoa-butter"], pnns_groups_2="sweets"))
    assert list(p.index) == GRADES and np.isclose(p.sum(), 1)


def test_explain_only_switches_off_tags_the_product_has(fitted):
    model, X, _ = fitted
    row = make_row(["en:sugar", "en:cocoa-butter", "en:salt"], categories=["en:snacks"], countries=["en:france"])
    grade = predict(model, row).idxmax()
    effect = explain(model, row, grade)
    assert set(effect.index) <= {"thành phần: sugar", "thành phần: cocoa-butter", "thành phần: salt",
                                 "đứng đầu: sugar", "danh mục: snacks", "quốc gia: france"}
    assert len(effect) > 0 and effect.abs().is_monotonic_decreasing
    assert explain(model, make_row([]), grade).empty                      # không có thẻ thì không có gì để tắt


def test_alternatives_same_group_and_better_grade(fitted):
    model, X, y = fitted
    row = X[(X["pnns_groups_2"] == "sweets").to_numpy() & (y == "e")].head(1)
    out = alternatives(model, row, "e", X, y, ingredient_matrix(model, X), top=3)
    assert 0 < len(out) <= 3
    assert set(out["hạng"]) <= {"A", "B", "C", "D"}
    assert set(X.set_index("code").loc[out["code"], "pnns_groups_2"]) == {"sweets"}
    assert row["code"].iloc[0] not in set(out["code"])
    assert alternatives(model, make_row(["en:sugar"]), "e", X, y, ingredient_matrix(model, X)).empty  # thiếu nhóm


def test_pretty_names():
    assert pretty("ingredients__en:palm-oil") == "thành phần: palm-oil"
    assert pretty("additives__en:e322") == "phụ gia: e322"
