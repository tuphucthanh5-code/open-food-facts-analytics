"""Bước 6a - Làm sạch: bảng sản phẩm phẳng (từ sql/extract_products.sql) -> X (đặc trưng) và y (nhãn).

Thứ tự: chuẩn hóa -> lọc -> loại trùng -> gắn cờ -> tạo group_id. Không bước nào dùng bảng dinh dưỡng
để giữ hay loại một dòng (dự án mô phỏng sản phẩm THIẾU dinh dưỡng).
"""
import hashlib
import re
import unicodedata

import pandas as pd

VALID_GRADES = ("a", "b", "c", "d", "e")
MAX_INGREDIENTS = 150        # trên mức này gần như chắc chắn là lỗi nhập liệu
FEW_INGREDIENTS = 1          # <= mức này chỉ gắn cờ (mật ong, dầu ô liu vẫn hợp lệ)

# Trường cá nhân: không bao giờ được thu thập
PII_FIELDS = {"creator", "editors_tags", "last_editor", "correctors_tags", "photographers_tags",
              "informers_tags", "checkers_tags"}
# Thẻ trên bao bì làm lộ đáp án: logo Nutri-Score, Health Star, nhãn cảnh báo "exceso"/"alto en"...
LEAKY_LABEL_PATTERN = re.compile(
    r"nutri[- ]?score|nutrition[- ]?grade|health[- ]?star|keyhole|nutrinform|traffic[- ]?light"
    r"|exceso|alto[- ]en[- ]|sellos?[- ]de[- ]advertencia|(^|:)\d+[- ]sellos?$"
    r"|high[- ]in[- ](sugars?|salt|sodium|saturated|fat|calories|energy)")
LEAKY_TAG_COLUMNS = ("labels_tags", "categories_tags")

LIST_COLUMNS = ["brands_tags", "countries_tags", "categories_tags", "ingredients_tags",
                "ingredients_analysis_tags", "additives_tags", "allergens_tags", "labels_tags"]
FEATURE_COLUMNS = [
    "row_id", "code", "group_id", "product_name", "brand", "brands_tags", "countries_tags", "n_countries",
    "categories_tags", "pnns_groups_1", "pnns_groups_2", "ingredients_tags", "ingredients_text",
    "ingredients_n", "ingredients_from_palm_oil_n", "ingredients_analysis_tags", "additives_tags",
    "additives_n", "allergens_tags", "labels_tags", "nova_group", "lang", "last_modified",
    "share_ingredients_off_taxonomy", "flag_few_ingredients", "flag_missing_nova", "flag_missing_brand",
]


# ---------------------------------------------------------------------------------------
# Hàm nhỏ
# ---------------------------------------------------------------------------------------
def as_list(value):
    """list Python từ list / mảng numpy (đọc từ parquet); None, NaN, chuỗi -> None."""
    if value is None or isinstance(value, (str, bytes, dict, float)):
        return None
    return list(value)


def clean_tags(values, drop=()):
    """Strip, chữ thường, bỏ rỗng, bỏ trùng (giữ thứ tự). None giữ là None (khác với danh sách rỗng)."""
    items = as_list(values)
    if items is None:
        return None
    out = []
    for v in items:
        t = v.strip().lower() if isinstance(v, str) else ""
        if t and t not in drop and t not in out:
            out.append(t)
    return out


def slugify(text):
    """'Nestlé Côte d’Or' -> 'nestle-cote-d-or': bỏ dấu, chữ thường, ký tự lạ thành '-'."""
    if not isinstance(text, str):
        return None
    t = unicodedata.normalize("NFKD", text)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-") or None


def clean_brands(values):
    """'xx:Carrefour', 'Carrefour ' -> ['carrefour']: bỏ tiền tố ngôn ngữ rồi slugify."""
    items = as_list(values)
    if items is None:
        return None
    out = []
    for v in items:
        b = slugify(re.sub(r"^[a-z]{2}:", "", v.strip().lower())) if isinstance(v, str) else None
        if b and b not in out:
            out.append(b)
    return out


def normalize_name(name):
    """Tên dùng để so trùng: bỏ dấu, chữ thường, gộp dấu câu."""
    s = slugify(name)
    return s.replace("-", " ") if s else None


def is_leaky_label(tag):
    return isinstance(tag, str) and bool(LEAKY_LABEL_PATTERN.search(tag.lower()))


def content_key(brand, name, ingredients):
    """Khóa so trùng nội dung; None nếu thiếu tên hoặc thành phần (không đủ căn cứ coi là trùng)."""
    if not isinstance(name, str) or not name or not ingredients:
        return None
    brand = brand if isinstance(brand, str) else ""
    return hashlib.md5("\x1f".join([brand, name, "|".join(ingredients)]).encode("utf-8")).hexdigest()


def make_group_id(brand, name, code):
    """Nhóm cho GroupKFold: thương hiệu; thiếu thương hiệu thì theo tên; thiếu cả hai thì theo mã vạch."""
    if isinstance(brand, str) and brand:
        return f"brand:{brand}"
    if isinstance(name, str) and name:
        return f"name:{name}"
    return f"code:{code}"


def assert_no_leakage(columns):
    """Bảng đặc trưng không được có cột nhãn, điểm, dinh dưỡng hay trường cá nhân (kiểm tra TÊN cột)."""
    bad = [c for c in columns if c in PII_FIELDS or "nutri" in c.lower() or c.endswith("_100g")
           or c in ("nutrient_levels_tags", "misc_tags", "states_tags", "data_quality_tags")]
    if bad:
        raise ValueError(f"Bảng đặc trưng chứa cột bị cấm: {sorted(bad)}")


def assert_no_leaky_values(X):
    """Kiểm tra GIÁ TRỊ: labels_tags và categories_tags không còn thẻ rò rỉ nhãn."""
    for col in LEAKY_TAG_COLUMNS:
        found = sorted({t for tags in X[col] for t in (as_list(tags) or []) if is_leaky_label(t)})
        if found:
            raise ValueError(f"{col} còn thẻ rò rỉ nhãn: {found[:10]}")


# ---------------------------------------------------------------------------------------
# Các bước làm sạch
# ---------------------------------------------------------------------------------------
def normalize(df):
    """Chuẩn hóa từng cột. Không loại dòng nào."""
    df = df.copy()
    df["brands_tags"] = df["brands_tags"].map(clean_brands)
    df["brand"] = df["brands_tags"].map(lambda b: b[0] if b else None)
    df["countries_tags"] = df["countries_tags"].map(lambda v: clean_tags(v, drop={"en:world"}))
    df["n_countries"] = df["countries_tags"].map(lambda v: len(v) if v else 0).astype("Int64")
    for col in LIST_COLUMNS[2:]:
        df[col] = df[col].map(clean_tags)
    for col in LEAKY_TAG_COLUMNS:   # bỏ thẻ rò rỉ nhãn, giữ dòng
        df[col] = df[col].map(lambda v: None if v is None else [t for t in v if not is_leaky_label(t)])
    df["product_name"] = df["product_name"].map(lambda s: re.sub(r"\s+", " ", s).strip() or None
                                                if isinstance(s, str) else None)
    for col in ("ingredients_n", "ingredients_from_palm_oil_n", "additives_n"):
        s = pd.to_numeric(df[col], errors="coerce").astype("Float64")
        df[col] = s.mask(s < 0).round().astype("Int64")       # số âm là lỗi -> thiếu
    missing_n = df["ingredients_n"].isna() & df["ingredients_tags"].map(bool)
    df.loc[missing_n, "ingredients_n"] = df.loc[missing_n, "ingredients_tags"].map(len)
    df["nova_group"] = pd.to_numeric(df["nova_group"], errors="coerce").astype("Int64")
    df["last_modified"] = pd.to_datetime(df["last_modified"], utc=True)
    return df


def apply_filters(df, max_ingredients=MAX_INGREDIENTS):
    """Lọc và loại trùng. Trả về (df, phễu) với phễu là DataFrame: bước, số dòng loại, còn lại."""
    funnel = [("Đầu vào", 0, len(df))]

    def drop(name, mask):
        nonlocal df
        df = df[~mask]
        funnel.append((name, int(mask.sum()), len(df)))

    drop("Nhãn không phải A-E", df["nutriscore_grade"].isna())
    drop("Không có danh sách thành phần", ~df["ingredients_tags"].map(bool))
    drop("Mã vạch thiếu hoặc có ký tự không phải số", ~df["code"].map(lambda c: isinstance(c, str) and c.isdigit()))
    drop(f"Số thành phần > {max_ingredients}", (df["ingredients_n"] > max_ingredients).fillna(False))

    # Trùng mã vạch: giữ bản sửa gần nhất (hòa thì mã nhỏ hơn, rồi row_id lớn hơn) để kết quả không phụ thuộc thứ tự
    df = df.sort_values(["last_modified", "code", "row_id"], ascending=[False, True, False],
                        na_position="last", kind="mergesort")
    drop("Trùng mã vạch", df["code"].duplicated())

    # Trùng nội dung: cùng thương hiệu + tên + danh sách thành phần (tránh cùng một sản phẩm ở cả train và test)
    names = df["product_name"].map(normalize_name)
    keys = pd.Series([content_key(b, n, i) for b, n, i in zip(df["brand"], names, df["ingredients_tags"])],
                     index=df.index)
    drop("Trùng nội dung (thương hiệu + tên + thành phần)", keys.notna() & keys.duplicated())

    funnel = pd.DataFrame(funnel, columns=["Bước", "Loại bỏ", "Còn lại"])
    return df.sort_values("row_id").reset_index(drop=True), funnel


def add_flags_and_groups(df):
    """Cờ chất lượng (chỉ gắn cờ, không loại dòng) và group_id."""
    df = df.copy()
    df["share_ingredients_off_taxonomy"] = df["ingredients_tags"].map(
        lambda t: sum(not x.startswith("en:") for x in t) / len(t)).astype("Float64")
    df["flag_few_ingredients"] = (df["ingredients_n"] <= FEW_INGREDIENTS).fillna(False).astype(bool)
    df["flag_missing_nova"] = df["nova_group"].isna()
    df["flag_missing_brand"] = df["brand"].isna()
    names = df["product_name"].map(normalize_name)
    df["group_id"] = [make_group_id(b, n, c) for b, n, c in zip(df["brand"], names, df["code"])]
    return df


def clean(products, max_ingredients=MAX_INGREDIENTS):
    """Toàn bộ bước làm sạch. Trả về (X, y, phễu). X không có nhãn; y có row_id, code, nutriscore_grade."""
    df, funnel = apply_filters(normalize(products), max_ingredients)
    df = add_flags_and_groups(df)
    X = df[FEATURE_COLUMNS].copy()
    assert_no_leakage(X.columns)
    assert_no_leaky_values(X)
    y = df[["row_id", "code", "nutriscore_grade"]].copy()
    return X, y, funnel
