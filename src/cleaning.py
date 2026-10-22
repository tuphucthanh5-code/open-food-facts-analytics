"""Bước 4 - Làm sạch (cleaning): biến hai bảng staging thành bộ dữ liệu sẵn sàng cho mô hình.

Đầu vào (tạo bởi python -m src.staging):
    data/processed/staging_features.parquet
    data/processed/staging_audit.parquet

Đầu ra:
    data/final/clean_features.parquet   X: đặc trưng đã chuẩn hóa + group_id + cờ chất lượng (KHÔNG có nhãn)
    data/final/clean_labels.parquet     y: row_id, code, nutriscore_grade
    data/processed/clean_audit.parquet  bảng dinh dưỡng và điểm Nutri-Score của các dòng giữ lại, CHỈ cho EDA
    reports/cleaning_report.md / .json  phễu làm sạch, phân bố sau làm sạch, kiểm tra điểm-hạng

Các bước (theo đúng thứ tự, mỗi bước ghi lại số dòng bị loại vào phễu):
    1. Ghép features và audit theo row_id (bắt buộc khớp 1-1).
    2. Chuẩn hóa: thương hiệu, tên sản phẩm, quốc gia (bỏ en:world), các danh sách thẻ, ngôn ngữ, số đếm.
    3. Lọc: nhãn không hợp lệ, không có thành phần, mã vạch không hợp lệ, số thành phần phi lý.
    4. Loại trùng mã vạch (giữ bản sửa gần nhất).
    5. Loại trùng nội dung (cùng thương hiệu + tên + danh sách thành phần), tránh rò rỉ giữa train và test.
    6. Gắn cờ chất lượng (không loại): ít thành phần, thẻ ngoài taxonomy, thiếu NOVA.
    7. Tạo group_id cho GroupKFold.

Không bước nào dùng bảng dinh dưỡng hay điểm Nutri-Score để quyết định giữ hay loại một dòng:
chúng chỉ được dùng trong phần kiểm tra điểm-hạng (chẩn đoán, không lọc).

Chạy từ thư mục gốc dự án:
    python -m src.cleaning
"""
import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone

import pandas as pd

from src.raw_audit import VALID_GRADES, find_leakage_fields, find_pii_fields

# --- Tham số mặc định (ghi lại trong báo cáo) -------------------------------------------
DEFAULT_MAX_INGREDIENTS = 150      # trên mức này gần như chắc chắn là lỗi nhập liệu
FEW_INGREDIENTS = 1                # <= mức này: gắn cờ (mật ong, dầu ô liu... vẫn hợp lệ nên KHÔNG loại)
NON_COUNTRY_TAGS = frozenset({"en:world"})
TAXONOMY_PREFIX = "en:"
LANG_PREFIX = re.compile(r"^[a-z]{2}:")

LIST_COLUMNS = [
    "brands_tags", "countries_tags", "categories_tags", "ingredients_tags",
    "ingredients_analysis_tags", "additives_tags", "allergens_tags", "labels_tags",
]

CLEAN_FEATURE_COLUMNS = [
    "row_id", "code", "group_id", "product_name", "brand", "brands_tags", "countries_tags", "n_countries",
    "categories_tags", "pnns_groups_1", "pnns_groups_2", "ingredients_tags", "ingredients_text",
    "ingredients_n", "ingredients_from_palm_oil_n", "ingredients_analysis_tags", "additives_tags",
    "additives_n", "allergens_tags", "labels_tags", "nova_group", "lang", "last_modified",
    "share_ingredients_off_taxonomy", "flag_few_ingredients", "flag_missing_nova", "flag_missing_brand",
]
CLEAN_LABEL_COLUMNS = ["row_id", "code", "nutriscore_grade"]

# --- Ngưỡng điểm -> hạng, CHỈ dùng để chẩn đoán phiên bản công thức ---------------------
# Nguồn: mã tính nhãn của Open Food Facts (openfoodfacts-server, lib/ProductOpener/Nutriscore.pm,
# hàm compute_nutriscore_grade_2021 và compute_nutriscore_grade_2023), đối chiếu ngày 23/10/2026.
# Phô mai và thịt đỏ KHÔNG có ngưỡng riêng (chỉ khác cách tính điểm). Đồ uống có bảng riêng
# (bản 2023 coi cả sữa uống là đồ uống) nên bị bỏ qua ở bước chẩn đoán này.
GRADE_THRESHOLDS = {
    "2017": [(-1, "a"), (2, "b"), (10, "c"), (18, "d")],      # A <= -1, B 0..2, C 3..10, D 11..18, E >= 19
    "2023": [(0, "a"), (2, "b"), (10, "c"), (18, "d")],       # A <= 0,  B 1..2, C 3..10, D 11..18, E >= 19
    "2023_fat": [(-6, "a"), (2, "b"), (10, "c"), (18, "d")],  # chất béo/dầu/hạt: A <= -6, B -5..2
}
BEVERAGE_TAG = "en:beverages"
# OFF xác định nhóm chất béo/dầu/hạt qua thuộc tính của cây danh mục; ở đây xấp xỉ bằng các thẻ cha.
FAT_OIL_NUT_SEED_TAGS = {"en:fats", "en:vegetable-oils", "en:nuts", "en:nuts-and-their-products",
                         "en:seeds", "en:oilseeds"}


# ======================================================================================
# Hàm chuẩn hóa nhỏ, thuần
# ======================================================================================
def as_list(value):
    """Đổi giá trị đọc từ parquet (list, mảng numpy, None) thành list Python; còn lại -> None."""
    if value is None or isinstance(value, (str, bytes, dict)):
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    try:
        return list(value)
    except TypeError:
        return None


def slugify(text):
    """'Nestlé Côte d’Or ' -> 'nestle-cote-d-or'. Bỏ dấu, chữ thường, ký tự lạ thành '-'."""
    if not isinstance(text, str):
        return None
    t = unicodedata.normalize("NFKD", text)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
    return t or None


def normalize_brand(tag):
    """'xx:Carrefour' và 'xx:carrefour' -> 'carrefour'. Bỏ tiền tố ngôn ngữ rồi slugify."""
    if not isinstance(tag, str):
        return None
    return slugify(LANG_PREFIX.sub("", tag.strip().lower()))


def normalize_name(name):
    """Tên sản phẩm dùng làm khóa so trùng: bỏ dấu, chữ thường, gộp khoảng trắng và dấu câu."""
    s = slugify(name)
    return s.replace("-", " ") if s else None


def clean_tags(values, lowercase=True, drop=frozenset()):
    """Strip, chữ thường, bỏ rỗng, bỏ giá trị trong `drop`, bỏ trùng nhưng giữ thứ tự.
    Vắng (None) giữ là None để phân biệt với danh sách rỗng []."""
    items = as_list(values)
    if items is None:
        return None
    out, seen = [], set()
    for v in items:
        if not isinstance(v, str):
            continue
        t = v.strip()
        t = t.lower() if lowercase else t
        if not t or t in drop or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def clean_brands(values):
    items = as_list(values)
    if items is None:
        return None
    out = []
    for v in items:
        b = normalize_brand(v)
        if b and b not in out:
            out.append(b)
    return out


def off_taxonomy_share(tags):
    """Tỷ lệ thẻ thành phần KHÔNG có tiền tố en: (chưa ánh xạ được vào taxonomy)."""
    if not tags:
        return None
    return sum(1 for t in tags if not t.startswith(TAXONOMY_PREFIX)) / len(tags)


def content_key(brand, name, ingredients):
    """Khóa so trùng nội dung. None nếu thiếu tên hoặc thành phần (không đủ căn cứ để coi là trùng)."""
    brand = brand if isinstance(brand, str) else ""   # pandas có thể trả NaN thay cho None
    if not isinstance(name, str) or not name or not ingredients:
        return None
    raw = "\x1f".join([brand, name, "|".join(ingredients)])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def make_group_id(brand, name, code):
    """Nhóm cho GroupKFold. Sản phẩm thiếu thương hiệu KHÔNG bị gộp chung vào một nhóm khổng lồ."""
    if isinstance(brand, str) and brand:
        return f"brand:{brand}"
    if isinstance(name, str) and name:
        return f"name:{name}"
    return f"code:{code}"


def grade_from_score(score, version, is_fat=False):
    """Hạng suy ra từ điểm (thực phẩm, không phải đồ uống); None nếu không có điểm.

    Nhóm chất béo/dầu/hạt chỉ có ngưỡng riêng ở bản 2023; bản 2017 dùng chung bảng thực phẩm.
    """
    if score is None or score != score:
        return None
    key = "2023_fat" if is_fat and version == "2023" else version
    for upper, grade in GRADE_THRESHOLDS[key]:
        if score <= upper:
            return grade
    return "e"


def is_fat_oil_nut_seed(categories):
    """True nếu danh mục thuộc nhóm chất béo/dầu/hạt (xấp xỉ, xem FAT_OIL_NUT_SEED_TAGS)."""
    try:
        return any(t in FAT_OIL_NUT_SEED_TAGS for t in categories)
    except TypeError:  # None / NaN: không có danh mục
        return False


def score_grade_consistency(score, grade, is_fat=False):
    """'both' | '2017_only' | '2023_only' | 'neither' | None (thiếu điểm/hạng)."""
    if grade not in VALID_GRADES or score is None or score != score:
        return None
    ok17 = grade_from_score(score, "2017") == grade
    ok23 = grade_from_score(score, "2023", is_fat) == grade
    if ok17 and ok23:
        return "both"
    if ok17:
        return "2017_only"
    if ok23:
        return "2023_only"
    return "neither"


def assert_no_leakage(columns):
    """Bảng đặc trưng sạch không được chứa nhãn, dinh dưỡng, điểm hay trường cá nhân."""
    bad = set(find_leakage_fields(columns)) | set(find_pii_fields(columns))
    bad |= {c for c in columns if c.endswith("_100g") or c.endswith("_serving") or "nutri" in c.lower()}
    if bad:
        raise ValueError(f"Bảng đặc trưng sạch chứa cột bị cấm: {sorted(bad)}")


# ======================================================================================
# Pipeline
# ======================================================================================
def merge_inputs(features, audit):
    """Ghép theo row_id, bắt buộc 1-1. Chỉ lấy từ audit các cột cần cho nhãn và chẩn đoán."""
    if features["row_id"].duplicated().any() or audit["row_id"].duplicated().any():
        raise ValueError("row_id bị trùng trong staging: hãy chạy lại python -m src.staging")
    if set(features["row_id"]) != set(audit["row_id"]):
        raise ValueError("staging_features và staging_audit không khớp row_id: hãy chạy lại staging")
    keep = [c for c in ("row_id", "nutriscore_grade", "nutriscore_score") if c in audit.columns]
    return features.merge(audit[keep], on="row_id", how="inner", validate="one_to_one")


def normalize(df):
    """Bước 2: chuẩn hóa từng cột. Không loại dòng nào. Trả về (df, thống kê chuẩn hóa)."""
    df = df.copy()
    stats = {}

    before_brands = df["brand"].dropna().nunique()
    df["brands_tags"] = df["brands_tags"].map(clean_brands)
    df["brand"] = df["brands_tags"].map(lambda b: b[0] if b else None)
    stats["brand_unique_before"] = int(before_brands)
    stats["brand_unique_after"] = int(df["brand"].dropna().nunique())

    world = df["countries_tags"].map(lambda v: bool(as_list(v)) and "en:world" in as_list(v))
    stats["rows_with_en_world"] = int(world.sum())
    df["countries_tags"] = df["countries_tags"].map(lambda v: clean_tags(v, drop=NON_COUNTRY_TAGS))
    df["n_countries"] = df["countries_tags"].map(lambda v: len(v) if v is not None else 0).astype("Int64")
    stats["rows_without_country_after"] = int((df["n_countries"] == 0).sum())

    for col in LIST_COLUMNS:
        if col in ("brands_tags", "countries_tags"):
            continue
        df[col] = df[col].map(clean_tags)

    df["product_name"] = df["product_name"].map(
        lambda s: re.sub(r"\s+", " ", s).strip() or None if isinstance(s, str) else None)
    df["lang"] = df["lang"].map(lambda s: s.strip().lower() or None if isinstance(s, str) else None)
    df["ingredients_text"] = df["ingredients_text"].map(
        lambda s: s.strip() or None if isinstance(s, str) else None)

    for col in ("ingredients_n", "ingredients_from_palm_oil_n", "additives_n"):
        s = pd.to_numeric(df[col], errors="coerce").astype("Float64")
        neg = s < 0
        stats[f"{col}_negative_to_null"] = int(neg.fillna(False).sum())
        df[col] = s.mask(neg).round().astype("Int64")

    # ingredients_n thiếu -> lấy độ dài danh sách thẻ
    filled = df["ingredients_n"].isna() & df["ingredients_tags"].map(bool)
    df.loc[filled, "ingredients_n"] = df.loc[filled, "ingredients_tags"].map(len)
    stats["ingredients_n_filled_from_tags"] = int(filled.sum())

    df["nutriscore_grade"] = df["nutriscore_grade"].map(
        lambda g: g.strip().lower() if isinstance(g, str) and g.strip().lower() in VALID_GRADES else None)
    return df, stats


def apply_filters(df, max_ingredients=DEFAULT_MAX_INGREDIENTS):
    """Bước 3-5: lọc và loại trùng. Trả về (df, phễu). Phễu là list (tên bước, số loại, còn lại)."""
    funnel = [("Đầu vào (sau staging)", 0, len(df))]

    def step(name, mask_drop):
        nonlocal df
        n = int(mask_drop.sum())
        df = df[~mask_drop].copy()
        funnel.append((name, n, len(df)))

    step("Nhãn không phải A-E", df["nutriscore_grade"].isna())
    step("Không có danh sách thành phần", ~df["ingredients_tags"].map(bool))
    step("Mã vạch thiếu hoặc chứa ký tự không phải số",
         ~df["code"].map(lambda c: isinstance(c, str) and c.strip().isdigit()))
    step(f"Số thành phần > {max_ingredients} (lỗi nhập liệu)",
         (df["ingredients_n"] > max_ingredients).fillna(False))

    # Thứ tự ưu tiên: bản sửa gần nhất; hòa thì mã vạch nhỏ hơn; vẫn hòa thì row_id lớn hơn.
    # Nhờ vậy kết quả không phụ thuộc thứ tự đọc dữ liệu.
    df = df.sort_values(["last_modified", "code", "row_id"], ascending=[False, True, False],
                        na_position="last", kind="mergesort")
    step("Trùng mã vạch (giữ bản sửa gần nhất)", df["code"].duplicated(keep="first"))

    # Loại trùng nội dung
    names = df["product_name"].map(normalize_name)
    keys = pd.Series([content_key(b, n, i) for b, n, i in zip(df["brand"], names, df["ingredients_tags"])],
                     index=df.index)
    dup_groups = keys[keys.notna() & keys.duplicated(keep=False)]
    conflicting = 0
    if not dup_groups.empty:
        grades = df.loc[dup_groups.index, "nutriscore_grade"]
        conflicting = int(grades.groupby(dup_groups).nunique().gt(1).sum())
    step("Trùng nội dung: cùng thương hiệu + tên + thành phần", keys.notna() & keys.duplicated(keep="first"))

    df = df.sort_values("row_id").reset_index(drop=True)
    return df, funnel, {"content_duplicate_groups_with_conflicting_grades": conflicting}


def add_flags_and_groups(df):
    """Bước 6-7: cờ chất lượng (không loại dòng) và group_id."""
    df = df.copy()
    df["share_ingredients_off_taxonomy"] = df["ingredients_tags"].map(off_taxonomy_share).astype("Float64")
    df["flag_few_ingredients"] = (df["ingredients_n"] <= FEW_INGREDIENTS).fillna(False).astype(bool)
    df["flag_missing_nova"] = df["nova_group"].isna()
    df["flag_missing_brand"] = df["brand"].isna()
    names = df["product_name"].map(normalize_name)
    df["group_id"] = [make_group_id(b, n, c) for b, n, c in zip(df["brand"], names, df["code"])]
    return df


def clean(features, audit, max_ingredients=DEFAULT_MAX_INGREDIENTS):
    """Toàn bộ Bước 4. Trả về (clean_features, clean_labels, clean_audit, report_dict)."""
    merged = merge_inputs(features, audit)
    normed, norm_stats = normalize(merged)
    filtered, funnel, dup_stats = apply_filters(normed, max_ingredients=max_ingredients)
    final = add_flags_and_groups(filtered)

    X = final[CLEAN_FEATURE_COLUMNS].copy()
    assert_no_leakage(list(X.columns))
    y = final[CLEAN_LABEL_COLUMNS].copy()
    kept = set(final["row_id"])
    clean_audit = audit[audit["row_id"].isin(kept)].sort_values("row_id").reset_index(drop=True)

    report = build_report(X, y, final, funnel, norm_stats, dup_stats, max_ingredients)
    return X, y, clean_audit, report


# ======================================================================================
# Báo cáo
# ======================================================================================
def _pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


def consistency_table(final):
    """Đếm mức khớp điểm-hạng, tách đồ uống ra vì đồ uống dùng bảng ngưỡng khác."""
    if "nutriscore_score" not in final.columns:
        return {"available": False}
    bev = final["categories_tags"].map(lambda t: bool(t) and BEVERAGE_TAG in t)
    fat = final["categories_tags"].map(is_fat_oil_nut_seed)
    res = [score_grade_consistency(s, g, f)
           for s, g, f in zip(final["nutriscore_score"], final["nutriscore_grade"], fat)]
    res = pd.Series(res, index=final.index)
    foods = res[~bev]
    return {
        "available": True,
        "beverages_skipped": int(bev.sum()),
        "fats_oils_nuts_seeds": int((fat & ~bev).sum()),
        "foods_without_score": int(foods.isna().sum()),
        "foods": {k: int(v) for k, v in foods.value_counts().items()},
    }


def build_report(X, y, final, funnel, norm_stats, dup_stats, max_ingredients):
    n = len(X)
    countries = Counter(c for tags in X["countries_tags"] if tags for c in tags)
    brands = Counter(b for b in X["brand"] if isinstance(b, str) and b)   # NaN là truthy: phải kiểm tra kiểu
    groups = X["group_id"].value_counts()
    return {
        "params": {"max_ingredients": max_ingredients, "few_ingredients": FEW_INGREDIENTS,
                   "non_country_tags": sorted(NON_COUNTRY_TAGS)},
        "funnel": [{"step": s, "dropped": d, "remaining": r} for s, d, r in funnel],
        "normalization": norm_stats,
        "duplicates": dup_stats,
        "rows": n,
        "grades": {g: int((y["nutriscore_grade"] == g).sum()) for g in VALID_GRADES},
        "flags": {
            "few_ingredients": int(X["flag_few_ingredients"].sum()),
            "missing_nova": int(X["flag_missing_nova"].sum()),
            "missing_brand": int(X["flag_missing_brand"].sum()),
            "any_off_taxonomy_ingredient": int((X["share_ingredients_off_taxonomy"] > 0).fillna(False).sum()),
        },
        "countries_unique": len(countries),
        "countries_top": countries.most_common(15),
        "brands_unique": len(brands),
        "brands_top": brands.most_common(15),
        "groups": {"unique": int(groups.size), "largest": int(groups.iloc[0]) if n else 0,
                   "largest_share": round(float(groups.iloc[0]) / n, 4) if n else 0.0,
                   "largest_id": str(groups.index[0]) if n else None},
        "ingredients_n": {
            "median": float(X["ingredients_n"].median()) if n else None,
            "p99": float(X["ingredients_n"].quantile(0.99)) if n else None,
            "max": int(X["ingredients_n"].max()) if n else None,
        },
        "score_grade_consistency": consistency_table(final),
    }


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in rows]
    return "\n".join(out)


NORM_LABELS = {
    "brand_unique_before": "Số thương hiệu khác nhau trước chuẩn hóa",
    "brand_unique_after": "Số thương hiệu khác nhau sau chuẩn hóa",
    "rows_with_en_world": "Dòng có thẻ en:world (đã bỏ thẻ)",
    "rows_without_country_after": "Dòng không còn quốc gia nào",
    "ingredients_n_negative_to_null": "ingredients_n âm -> thiếu",
    "ingredients_from_palm_oil_n_negative_to_null": "ingredients_from_palm_oil_n âm -> thiếu",
    "additives_n_negative_to_null": "additives_n âm -> thiếu",
    "ingredients_n_filled_from_tags": "ingredients_n thiếu, lấy theo số thẻ",
}

CONSISTENCY_LABELS = {
    "both": "Khớp cả hai bảng ngưỡng",
    "2017_only": "Chỉ khớp ngưỡng cũ (2017)",
    "2023_only": "Chỉ khớp ngưỡng mới (2023)",
    "neither": "Không khớp bảng nào",
}


def render_report(r, generated_at):
    n = r["rows"]
    start = r["funnel"][0]["remaining"]
    lines = [
        "# Báo cáo làm sạch dữ liệu (Bước 4)", "",
        f"- Thời điểm: {generated_at}",
        f"- Đầu vào: **{start}** dòng; giữ lại: **{n}** dòng ({_pct(n, start)}%)",
        f"- Tham số: số thành phần tối đa {r['params']['max_ingredients']}; "
        f"gắn cờ khi ≤ {r['params']['few_ingredients']} thành phần; bỏ thẻ quốc gia {', '.join(r['params']['non_country_tags'])}",
        "", "## 1. Phễu làm sạch", "",
        _table(["Bước", "Loại bỏ", "Còn lại"], [[f["step"], f["dropped"], f["remaining"]] for f in r["funnel"]]),
        "",
        f"- Nhóm trùng nội dung có nhãn mâu thuẫn: {r['duplicates']['content_duplicate_groups_with_conflicting_grades']}",
        "", "## 2. Chuẩn hóa", "",
        _table(["Mục", "Giá trị"], [[NORM_LABELS.get(k, k), v] for k, v in r["normalization"].items()]),
        "", "## 3. Phân bố hạng sau làm sạch", "",
        _table(["Hạng", "Số dòng", "%"], [[g.upper(), c, _pct(c, n)] for g, c in r["grades"].items()]),
        "", "## 4. Cờ chất lượng (giữ dòng, chỉ gắn cờ)", "",
        _table(["Cờ", "Số dòng", "%"], [[k, v, _pct(v, n)] for k, v in r["flags"].items()]),
        "", "## 5. Nhóm cho GroupKFold", "",
        f"- Số nhóm: {r['groups']['unique']}; nhóm lớn nhất `{r['groups']['largest_id']}` "
        f"có {r['groups']['largest']} dòng ({100 * r['groups']['largest_share']:.1f}%)",
        "- Sản phẩm thiếu thương hiệu được nhóm theo tên chuẩn hóa, không gộp chung.",
        "", f"## 6. Thương hiệu sau chuẩn hóa ({r['brands_unique']} thương hiệu)", "",
        _table(["Thương hiệu", "Số dòng"], r["brands_top"]),
        "", f"## 7. Quốc gia ({r['countries_unique']} quốc gia, giữ toàn bộ theo phương án a)", "",
        _table(["Quốc gia", "Số dòng"], r["countries_top"]),
        "", "## 8. Số thành phần", "",
        f"- Trung vị {r['ingredients_n']['median']}; phân vị 99: {r['ingredients_n']['p99']}; "
        f"lớn nhất: {r['ingredients_n']['max']}",
        "", "## 9. Kiểm tra điểm - hạng Nutri-Score (chẩn đoán phiên bản công thức, KHÔNG dùng để lọc)", "",
    ]
    c = r["score_grade_consistency"]
    if not c.get("available"):
        lines.append("- Không có cột nutriscore_score trong staging_audit.")
    else:
        foods = c["foods"]
        total = sum(foods.values())
        lines += [
            f"- Bỏ qua {c['beverages_skipped']} đồ uống (bảng ngưỡng khác); "
            f"{c['foods_without_score']} thực phẩm không có điểm.",
            f"- {c.get('fats_oils_nuts_seeds', 0)} thực phẩm thuộc nhóm chất béo/dầu/hạt dùng ngưỡng riêng "
            "của bản 2023 (A ≤ -6). Phô mai và thịt đỏ không có ngưỡng riêng.",
            "- Nguồn ngưỡng: mã tính nhãn của Open Food Facts (`Nutriscore.pm`). Phần lớn dòng 'không khớp' "
            "còn lại là sữa uống (bản 2023 tính là đồ uống) mà danh mục không gắn `en:beverages`.", "",
            _table(["Kết quả", "Số dòng", "%"],
                   [[CONSISTENCY_LABELS[k], foods.get(k, 0), _pct(foods.get(k, 0), total)]
                    for k in CONSISTENCY_LABELS]),
        ]
    return "\n".join(lines) + "\n"


# ======================================================================================
# Dòng lệnh
# ======================================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="Bước 4: làm sạch dữ liệu staging")
    ap.add_argument("--in-dir", default="data/processed")
    ap.add_argument("--final-dir", default="data/final")
    ap.add_argument("--audit-out", default="data/processed/clean_audit.parquet")
    ap.add_argument("--report", default="reports/cleaning_report.md")
    ap.add_argument("--max-ingredients", type=int, default=DEFAULT_MAX_INGREDIENTS)
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    f_in = os.path.join(args.in_dir, "staging_features.parquet")
    a_in = os.path.join(args.in_dir, "staging_audit.parquet")
    for p in (f_in, a_in):
        if not os.path.isfile(p):
            print(f"Không tìm thấy {p}. Hãy chạy python -m src.staging trước.")
            return 1

    X, y, clean_audit, report = clean(pd.read_parquet(f_in), pd.read_parquet(a_in),
                                      max_ingredients=args.max_ingredients)
    if X.empty:
        print("Không còn dòng nào sau khi làm sạch.")
        return 1

    os.makedirs(args.final_dir, exist_ok=True)
    x_path = os.path.join(args.final_dir, "clean_features.parquet")
    y_path = os.path.join(args.final_dir, "clean_labels.parquet")
    X.to_parquet(x_path, index=False)
    y.to_parquet(y_path, index=False)
    os.makedirs(os.path.dirname(args.audit_out) or ".", exist_ok=True)
    clean_audit.to_parquet(args.audit_out, index=False)

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(render_report(report, stamp))
    with open(os.path.splitext(args.report)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump({"generated_at": stamp, **report}, f, ensure_ascii=False, indent=2)

    for f in report["funnel"]:
        print(f"{f['step']:<55} -{f['dropped']:>6}  còn {f['remaining']}")
    print(f"Đã ghi: {x_path}, {y_path}, {args.audit_out}, {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
