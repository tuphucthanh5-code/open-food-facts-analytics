"""Bước 6a - làm sạch: chuẩn hóa, lọc, loại trùng, chống rò rỉ nhãn."""
import pandas as pd
import pytest

from src import cleaning as c
from tests.conftest import frame, product


def test_slugify_and_brands():
    assert c.slugify("Nestlé Côte d’Or ") == "nestle-cote-d-or"
    assert c.clean_brands(["xx:Carrefour", "Carrefour ", "fr:carrefour"]) == ["carrefour"]
    assert c.clean_brands(None) is None


def test_clean_tags_keeps_order_and_none():
    assert c.clean_tags([" EN:Sugar", "en:sugar", "", "en:salt"]) == ["en:sugar", "en:salt"]
    assert c.clean_tags(["en:france", "en:world"], drop={"en:world"}) == ["en:france"]
    assert c.clean_tags(None) is None          # vắng khác với danh sách rỗng
    assert c.clean_tags([]) == []


@pytest.mark.parametrize("tag", ["en:nutriscore-grade-a", "en:nutriscore", "en:health-star-rating-4",
                                 "es:exceso-sodio", "fr:nutri score a", "en:keyhole", "es:alto-en-azucares"])
def test_leaky_labels_detected(tag):
    assert c.is_leaky_label(tag)


@pytest.mark.parametrize("tag", ["en:low-fat", "en:organic", "en:no-added-sugar", "en:nutritional-yeast", "en:vegan"])
def test_normal_labels_kept(tag):
    assert not c.is_leaky_label(tag)


def test_normalize_removes_leaky_tags_but_keeps_row():
    out = c.normalize(frame(product()))
    assert len(out) == 1
    assert out.loc[0, "labels_tags"] == ["en:green-dot"]
    assert out.loc[0, "countries_tags"] == ["en:france"]          # en:world bị bỏ
    assert out.loc[0, "brand"] == "nutella"
    assert out.loc[0, "n_countries"] == 1


def test_normalize_negative_counts_and_fill_ingredients_n():
    out = c.normalize(frame(product(additives_n=-1.0, ingredients_n=None)))
    assert pd.isna(out.loc[0, "additives_n"])
    assert out.loc[0, "ingredients_n"] == 3                      # lấy theo số thẻ thành phần


def test_filters_funnel_and_never_use_nutrition():
    df = c.normalize(frame(
        product(code="1"),
        product(code="2", nutriscore_grade=None),                 # thiếu nhãn -> loại
        product(code="3", ingredients_tags=[]),                   # không thành phần -> loại
        product(code="4a"),                                       # mã có chữ -> loại
        product(code="5", ingredients_n=151.0),                   # > 150 thành phần -> loại
        product(code="6", sugars_100g=1110.0, product_name="Khác"),  # dinh dưỡng phi lý -> VẪN GIỮ
    ))
    out, funnel = c.apply_filters(df)
    assert set(out["code"]) == {"1", "6"}
    assert funnel["Còn lại"].iloc[-1] == 2
    assert list(funnel["Loại bỏ"][1:5]) == [1, 1, 1, 1]


def test_duplicate_code_keeps_newest():
    old = product(code="1", nutriscore_grade="c", last_modified=pd.Timestamp("2020-01-01", tz="UTC"))
    new = product(code="1", nutriscore_grade="d", last_modified=pd.Timestamp("2024-01-01", tz="UTC"))
    out, _ = c.apply_filters(c.normalize(frame(old, new)))
    assert list(out["nutriscore_grade"]) == ["d"]


def test_content_duplicates_removed():
    out, funnel = c.apply_filters(c.normalize(frame(product(code="1"), product(code="2"))))
    assert len(out) == 1
    assert funnel["Loại bỏ"].iloc[-1] == 1


def test_few_ingredients_flagged_not_removed_and_group_id():
    df = frame(product(code="1", ingredients_tags=["en:honey"], ingredients_n=1.0, product_name="Mật ong"),
               product(code="2", brands_tags=None, product_name="Dầu Ô liu", nova_group=None))
    X, y, _ = c.clean(df)
    assert len(X) == 2
    assert X.loc[0, "flag_few_ingredients"]
    assert list(X["group_id"]) == ["brand:nutella", "name:dau o liu"]
    assert X.loc[1, "flag_missing_brand"] and X.loc[1, "flag_missing_nova"]


def test_clean_output_has_no_label_or_nutrition():
    X, y, _ = c.clean(frame(product(code="0012345678905")))
    assert list(X.columns) == c.FEATURE_COLUMNS
    assert not [col for col in X.columns if "nutri" in col or col.endswith("_100g")]
    assert list(y.columns) == ["row_id", "code", "nutriscore_grade"]
    assert X.loc[0, "code"] == "0012345678905"                    # mã vạch giữ số 0 đầu


def test_leakage_guards_raise():
    with pytest.raises(ValueError):
        c.assert_no_leakage(["code", "sugars_100g"])
    with pytest.raises(ValueError):
        c.assert_no_leakage(["nutriscore_score"])
    with pytest.raises(ValueError):
        c.assert_no_leakage(["creator"])
    bad = pd.DataFrame({"labels_tags": [["en:nutriscore-grade-a"]], "categories_tags": [[]]})
    with pytest.raises(ValueError):
        c.assert_no_leaky_values(bad)


def test_every_clean_column_is_documented(root):
    text = (root / "docs" / "data_dictionary.md").read_text(encoding="utf-8")
    missing = [col for col in c.FEATURE_COLUMNS if f"`{col}`" not in text]
    assert not missing, f"docs/data_dictionary.md thiếu cột: {missing}"
