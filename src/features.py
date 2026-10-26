"""Bước 6 - Feature engineering theo Cách A: biến clean_features thành ma trận đặc trưng cho mô hình.

Đầu vào: data/final/clean_features.parquet (tạo bởi python -m src.cleaning). KHÔNG đọc staging_features (còn thẻ
rò rỉ nhãn) và KHÔNG đọc nhãn: tệp này không cần biết hạng Nutri-Score.

Mọi biến đổi nằm trong một sklearn Pipeline (build_feature_pipeline). Phần nào phải "học" từ dữ liệu
(danh sách thẻ đủ phổ biến, ánh xạ danh mục -> pnns_groups_1, trung vị và độ lệch chuẩn của biến số) chỉ được
fit trên tập huấn luyện của từng fold ở Bước 7-8, nên tệp này KHÔNG lưu ma trận đặc trưng fit trên toàn bộ dữ liệu.

Các nhóm đặc trưng (FEATURE_GROUPS, bật/tắt từng nhóm để làm ablation ở Bước 8):
    numeric      số thành phần, phụ gia, chất gây dị ứng, độ dài chữ thành phần, số tỷ lệ %, dầu cọ
    position     vị trí tương đối của đường/muối/chất béo, thành phần đứng đầu
    ingredients  multi-hot thành phần (ngưỡng min_freq) + số thẻ hiếm
    additives    multi-hot phụ gia + số phụ gia theo nhóm số E (tạo màu, bảo quản, tạo ngọt...)
    categories   pnns_groups_1 (đã bổ sung từ categories_tags), pnns_groups_2, thẻ danh mục, cờ đồ uống/béo/phô mai
    nova         one-hot NOVA 1-4 và "thiếu"
    labels       thẻ nhãn bao bì, ingredients_analysis_tags (thuần chay, dầu cọ), cờ hữu cơ
    countries    thẻ quốc gia + số quốc gia
    flags        cờ chất lượng dữ liệu (ít thành phần, thiếu thương hiệu, tỷ lệ thẻ ngoài taxonomy, pnns đã bổ sung)

Đầu ra của dòng lệnh (chỉ mô tả, không dùng nhãn):
    reports/features_report.md / .json   số đặc trưng theo nhóm và ngưỡng, độ chính xác phép bổ sung pnns_groups_1
    reports/feature_names.txt            danh sách tên đặc trưng ở ngưỡng mặc định

Chạy từ thư mục gốc dự án:
    python -m src.features
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from src.cleaning import as_list, assert_no_leakage, is_fat_oil_nut_seed, is_leaky_label

# --- Tham số mặc định (ghi lại trong báo cáo) -------------------------------------------
DEFAULT_MIN_FREQ = 100             # thẻ phải có ở >= 100 sản phẩm mới thành một cột; chốt ở Bước 8 (thử 20 và 100)
COMPARE_MIN_FREQS = (20, 100)
DEFAULT_MIN_SUPPORT = 5            # thẻ danh mục phải có ở >= 5 sản phẩm đã biết nhóm mới được dùng để bổ sung
DEFAULT_MIN_PURITY = 0.5           # nhóm phổ biến nhất của thẻ phải chiếm > nửa, nếu không thì để "missing"
MISSING = "missing"
SEED = 42

FEATURE_GROUPS = ("numeric", "position", "ingredients", "additives", "categories", "nova", "labels",
                  "countries", "flags")

# Các cột của clean_features mà pipeline đọc. Cố ý KHÔNG dùng: row_id, code, group_id (chỉ để chia dữ liệu),
# brand/brands_tags (thương hiệu là nhóm GroupKFold nên thương hiệu ở test không có trong train),
# product_name, lang, last_modified, flag_missing_nova (trùng nova_missing).
FEATURE_INPUT_COLUMNS = [
    "ingredients_tags", "ingredients_text", "ingredients_n", "ingredients_from_palm_oil_n", "additives_tags",
    "additives_n", "allergens_tags", "categories_tags", "pnns_groups_1", "pnns_groups_2", "nova_group",
    "labels_tags", "ingredients_analysis_tags", "countries_tags", "n_countries",
    "share_ingredients_off_taxonomy", "flag_few_ingredients", "flag_missing_brand",
]

# --- Nhận diện đường, muối, chất béo trong thẻ thành phần ---------------------------------
# So theo từng từ (tách bằng "-") của thẻ taxonomy en:, ví dụ en:glucose-fructose-syrup -> {glucose, fructose, syrup}.
# Không tính lactose (đường tự nhiên của sữa) và maltodextrin.
SUGAR_TOKENS = frozenset({"sugar", "sugars", "syrup", "dextrose", "glucose", "fructose", "sucrose", "honey",
                          "molasses", "maltose"})
SALT_TOKENS = frozenset({"salt"})
FAT_TOKENS = frozenset({"oil", "oils", "fat", "fats", "butter", "lard", "margarine", "shortening", "ghee",
                        "tallow"})
# Thẻ nói về việc GIẢM/KHÔNG CÓ chất đó (en:fat-reduced-cocoa, en:no-added-sugar...) không tính là có chất đó.
NEGATED_PATTERN = re.compile(
    r"(^|-)(low|reduced|free|non|no|no-added|without)-(fat|fats|sugars?|salt|sodium)(-|$)"
    r"|(^|-)(fat|sugars?|salt|sodium)-(free|reduced)(-|$)")
# Đầu từ là đầu chuỗi, dấu ':' của tiền tố ngôn ngữ hoặc dấu '-' (en:palm-oil, en:eu-organic, en:fr-bio-01).
PALM_PATTERN = re.compile(r"(^|[:-])palm(-kernel)?-(oil|fat)")
PERCENT_PATTERN = re.compile(r"\d+(?:[.,]\d+)?\s*%")
ORGANIC_PATTERN = re.compile(r"(^|[:-])(organic|bio)(-|$)|ab-agriculture-biologique")

BEVERAGE_TAG = "en:beverages"
CHEESE_TAG = "en:cheeses"
PNNS_MERGE = {"alcoholic beverages": "beverages"}   # chỉ 4 sản phẩm, gộp để không có nhóm gần như rỗng

# --- Nhóm phụ gia theo số E (hệ thống đánh số của EU) --------------------------------------
SWEETENER_NUMBERS = frozenset({420, 421, 950, 951, 952, 953, 954, 955, 957, 959, 960, 961, 962, 964, 965,
                               966, 967, 968, 969})
ADDITIVE_CLASSES = ["add_colours", "add_preservatives", "add_antioxidants_acids", "add_thickeners_emulsifiers",
                    "add_acidity_anticaking", "add_flavour_enhancers", "add_sweeteners", "add_other"]
E_NUMBER = re.compile(r"^en:e(\d{3,4})")

NOVA_COLUMNS = ["nova_1", "nova_2", "nova_3", "nova_4", "nova_missing"]
NUMERIC_COLUMNS = ["ingredients_n", "additives_n", "ingredients_from_palm_oil_n", "n_allergens",
                   "ingredients_text_len", "n_ingredients_with_percent"]
POSITION_COLUMNS = ["pos_sugar", "pos_salt", "pos_fat"]
CATEGORY_FLAG_COLUMNS = ["is_beverage", "is_fat_oil_nut_seed", "is_cheese"]
FLAG_COLUMNS = ["flag_few_ingredients", "flag_missing_brand", "share_ingredients_off_taxonomy",
                "pnns_groups_1_imputed"]

# Cột do RowFeatures tạo ra (không cần học từ dữ liệu) và cột do bộ bổ sung pnns tạo ra.
ROW_FEATURE_COLUMNS = (["n_allergens", "ingredients_text_len", "n_ingredients_with_percent", "has_palm_oil"]
                       + POSITION_COLUMNS + ["first_ingredient"] + ADDITIVE_CLASSES + CATEGORY_FLAG_COLUMNS
                       + ["pnns_groups_2_filled"] + NOVA_COLUMNS + ["is_organic"])
IMPUTER_COLUMNS = ["pnns_groups_1_filled", "pnns_groups_1_imputed"]


# ======================================================================================
# Hàm nhỏ, thuần (dùng trong RowFeatures)
# ======================================================================================
def tag_tokens(tag):
    """'en:glucose-fructose-syrup' -> {'glucose', 'fructose', 'syrup'}. Chỉ thẻ taxonomy en:, còn lại -> rỗng."""
    if not isinstance(tag, str) or not tag.startswith("en:"):
        return frozenset()
    return frozenset(tag[3:].split("-"))


def tag_has(tag, tokens):
    """True nếu thẻ chứa một trong các từ `tokens` và không phải thẻ phủ định (ít béo, không thêm đường...)."""
    if not (tag_tokens(tag) & tokens):
        return False
    return not NEGATED_PATTERN.search(tag[3:])


def relative_position(tags, tokens):
    """Vị trí tương đối của thẻ ĐẦU TIÊN khớp `tokens`: 1.0 nếu đứng đầu, giảm dần về 0 về cuối, 0.0 nếu không có.

    Dùng vị trí tương đối vì ingredients_tags chèn các thẻ cha ngay sau mỗi thành phần
    (en:sugar, en:added-sugar, en:disaccharide...), nên số thứ tự tuyệt đối bị phóng đại không đều.
    """
    tags = as_list(tags) or []
    for i, t in enumerate(tags):
        if tag_has(t, tokens):
            return 1.0 - i / len(tags)
    return 0.0


def count_percentages(text):
    """Số tỷ lệ phần trăm ghi trong chữ thành phần ('cacao 70 %, sữa 12,5%' -> 2)."""
    return len(PERCENT_PATTERN.findall(text)) if isinstance(text, str) else 0


def has_palm_oil(tags, palm_n):
    if isinstance(palm_n, (int, float, np.integer, np.floating)) and palm_n == palm_n and palm_n > 0:
        return True
    return any(isinstance(t, str) and PALM_PATTERN.search(t) for t in (as_list(tags) or []))


def additive_class(tag):
    """Nhóm của phụ gia theo số E: 'en:e322i' -> 'add_antioxidants_acids'; không phải số E -> 'add_other'."""
    m = E_NUMBER.match(tag) if isinstance(tag, str) else None
    if not m:
        return "add_other"
    n = int(m.group(1))
    if n in SWEETENER_NUMBERS:
        return "add_sweeteners"
    return {1: "add_colours", 2: "add_preservatives", 3: "add_antioxidants_acids", 4: "add_thickeners_emulsifiers",
            5: "add_acidity_anticaking", 6: "add_flavour_enhancers"}.get(n // 100, "add_other")


def additive_class_counts(tags):
    """Đếm phụ gia theo nhóm. e322 và e322i (thẻ cha và con) chỉ tính một lần theo số E gốc."""
    seen = {}
    for t in as_list(tags) or []:
        m = E_NUMBER.match(t) if isinstance(t, str) else None
        seen.setdefault(m.group(1) if m else t, additive_class(t))
    counts = Counter(seen.values())
    return [counts.get(c, 0) for c in ADDITIVE_CLASSES]


def is_organic(labels):
    return any(isinstance(t, str) and ORGANIC_PATTERN.search(t) for t in (as_list(labels) or []))


def has_tag(tags, tag):
    return tag in (as_list(tags) or [])


def clean_pnns(value):
    """Chữ thường, thiếu -> None, gộp nhóm quá nhỏ theo PNNS_MERGE."""
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip().lower()
    return PNNS_MERGE.get(v, v)


def nova_one_hot(value):
    """NOVA là biến phân loại: [nova_1, nova_2, nova_3, nova_4, nova_missing]."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = None
    if v not in (1, 2, 3, 4):
        return [0.0, 0.0, 0.0, 0.0, 1.0]
    return [1.0 if v == k else 0.0 for k in (1, 2, 3, 4)] + [0.0]


# ======================================================================================
# Bộ biến đổi sklearn
# ======================================================================================
class RowFeatures(BaseEstimator, TransformerMixin):
    """Tạo các cột tính được từ riêng từng dòng (không học gì từ dữ liệu, nên không thể rò rỉ giữa train và test).

    Từ chối bảng đầu vào có cột nhãn, dinh dưỡng hay trường cá nhân.
    """

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        assert_no_leakage(list(X.columns))
        missing = [c for c in FEATURE_INPUT_COLUMNS if c not in X.columns]
        if missing:
            raise ValueError(f"Thiếu cột đầu vào: {missing}. Hãy đọc data/final/clean_features.parquet")
        df = X[FEATURE_INPUT_COLUMNS].copy()
        for col in ("ingredients_n", "additives_n", "ingredients_from_palm_oil_n", "n_countries",
                    "share_ingredients_off_taxonomy"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")   # pd.NA -> NaN cho sklearn
        for col in ("flag_few_ingredients", "flag_missing_brand"):
            df[col] = df[col].astype(bool).astype("float64")

        ing = df["ingredients_tags"]
        df["n_allergens"] = df["allergens_tags"].map(lambda v: float(len(as_list(v) or [])))
        df["ingredients_text_len"] = df["ingredients_text"].map(lambda s: float(len(s)) if isinstance(s, str) else 0.0)
        df["n_ingredients_with_percent"] = df["ingredients_text"].map(count_percentages).astype("float64")
        df["has_palm_oil"] = [float(has_palm_oil(t, n)) for t, n in zip(ing, df["ingredients_from_palm_oil_n"])]
        df["pos_sugar"] = ing.map(lambda t: relative_position(t, SUGAR_TOKENS))
        df["pos_salt"] = ing.map(lambda t: relative_position(t, SALT_TOKENS))
        df["pos_fat"] = ing.map(lambda t: relative_position(t, FAT_TOKENS))
        df["first_ingredient"] = ing.map(lambda t: (as_list(t) or [])[:1])

        add = np.array([additive_class_counts(t) for t in df["additives_tags"]], dtype="float64").reshape(-1, len(ADDITIVE_CLASSES))
        for i, c in enumerate(ADDITIVE_CLASSES):
            df[c] = add[:, i]

        cats = df["categories_tags"]
        df["is_beverage"] = cats.map(lambda t: float(has_tag(t, BEVERAGE_TAG)))
        df["is_fat_oil_nut_seed"] = cats.map(lambda t: float(is_fat_oil_nut_seed(as_list(t) or [])))
        df["is_cheese"] = cats.map(lambda t: float(has_tag(t, CHEESE_TAG)))
        df["pnns_groups_1"] = df["pnns_groups_1"].map(clean_pnns)
        df["pnns_groups_2_filled"] = df["pnns_groups_2"].map(lambda v: clean_pnns(v) or MISSING)

        nova = np.array([nova_one_hot(v) for v in df["nova_group"]], dtype="float64").reshape(-1, len(NOVA_COLUMNS))
        for i, c in enumerate(NOVA_COLUMNS):
            df[c] = nova[:, i]
        df["is_organic"] = df["labels_tags"].map(lambda t: float(is_organic(t)))
        return df


class CategoryGroupImputer(BaseEstimator, TransformerMixin):
    """Bổ sung nhóm thiếu (pnns_groups_1) từ thẻ danh mục, học CHỈ từ các dòng đã biết nhóm của tập fit.

    Với mỗi thẻ danh mục có ở >= min_support sản phẩm đã biết nhóm, ghi lại nhóm phổ biến nhất và độ thuần
    (tỷ lệ sản phẩm thuộc nhóm đó). Sản phẩm thiếu nhóm lấy nhóm của thẻ thuần nhất mà nó có (hòa thì thẻ phổ
    biến hơn); nếu độ thuần cao nhất không vượt min_purity thì để "missing". Không dùng nhãn Nutri-Score.

    Thêm hai cột: <target>_filled (nhóm gốc hoặc nhóm bổ sung hoặc "missing") và <target>_imputed (1 nếu đã bổ sung).
    """

    def __init__(self, target="pnns_groups_1", source="categories_tags", min_support=DEFAULT_MIN_SUPPORT,
                 min_purity=DEFAULT_MIN_PURITY):
        self.target = target
        self.source = source
        self.min_support = min_support
        self.min_purity = min_purity

    def fit(self, X, y=None):
        counts = {}
        for group, tags in zip(X[self.target], X[self.source]):
            if not isinstance(group, str):
                continue
            for t in set(as_list(tags) or []):
                counts.setdefault(t, Counter())[group] += 1
        self.mapping_ = {}
        for t, c in counts.items():
            support = sum(c.values())
            if support < self.min_support:
                continue
            group, n = max(c.items(), key=lambda kv: (kv[1], kv[0]))
            self.mapping_[t] = (group, n / support, support)
        return self

    def impute_one(self, tags):
        """Nhóm suy ra từ danh sách thẻ, hoặc None nếu không đủ căn cứ."""
        best = None
        for t in as_list(tags) or []:
            m = self.mapping_.get(t)
            if m and (best is None or (m[1], m[2], t) > (best[1], best[2], best[3])):
                best = (m[0], m[1], m[2], t)
        if best is None or best[1] <= self.min_purity:
            return None
        return best[0]

    def transform(self, X):
        df = X.copy()
        known = df[self.target].map(lambda v: isinstance(v, str))
        guessed = [None if k else self.impute_one(t) for k, t in zip(known, df[self.source])]
        df[f"{self.target}_filled"] = [v if k else (g or MISSING) for v, k, g in zip(df[self.target], known, guessed)]
        df[f"{self.target}_imputed"] = [0.0 if k else float(g is not None) for k, g in zip(known, guessed)]
        return df


class TagVectorizer(BaseEstimator, TransformerMixin):
    """Multi-hot cho một cột danh sách thẻ, dạng ma trận thưa.

    fit: giữ các thẻ có ở >= min_freq sản phẩm (đếm mỗi thẻ một lần mỗi sản phẩm). Từ chối thẻ rò rỉ nhãn.
    transform: 1 nếu sản phẩm có thẻ; nếu rare_count, thêm cột n_rare = log(1 + số thẻ không được giữ),
    kể cả thẻ chưa từng gặp lúc fit.
    """

    def __init__(self, min_freq=DEFAULT_MIN_FREQ, rare_count=True):
        self.min_freq = min_freq
        self.rare_count = rare_count

    @staticmethod
    def _lists(X):
        col = X.iloc[:, 0] if isinstance(X, pd.DataFrame) else pd.Series(list(X))
        return [list(dict.fromkeys(t for t in (as_list(v) or []) if isinstance(t, str))) for v in col]

    def fit(self, X, y=None):
        doc_freq = Counter(t for tags in self._lists(X) for t in tags)
        self.vocabulary_ = sorted(t for t, n in doc_freq.items() if n >= self.min_freq)
        leaky = [t for t in self.vocabulary_ if is_leaky_label(t)]
        if leaky:
            raise ValueError(f"Thẻ rò rỉ nhãn lọt vào đặc trưng: {leaky[:10]}. Hãy dùng clean_features.parquet")
        self.index_ = {t: i for i, t in enumerate(self.vocabulary_)}
        return self

    def transform(self, X):
        lists = self._lists(X)
        rows, cols, rare = [], [], []
        for r, tags in enumerate(lists):
            n_rare = 0
            for t in tags:
                j = self.index_.get(t)
                if j is None:
                    n_rare += 1
                else:
                    rows.append(r)
                    cols.append(j)
            rare.append(np.log1p(n_rare))
        m = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(lists), len(self.vocabulary_)))
        if self.rare_count:
            m = sparse.hstack([m, sparse.csr_matrix(np.array(rare).reshape(-1, 1))], format="csr")
        return m

    def get_feature_names_out(self, input_features=None):
        return np.array(self.vocabulary_ + (["n_rare"] if self.rare_count else []), dtype=object)


# ======================================================================================
# Pipeline
# ======================================================================================
def _numeric():
    """Biến đếm lệch phải: điền trung vị (của tập fit) -> log(1 + x) -> chuẩn hóa."""
    return Pipeline([
        ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("log", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),
        ("scale", StandardScaler()),
    ])


def group_parts(group, min_freq=DEFAULT_MIN_FREQ):
    """Các phần (tên, bộ biến đổi, cột) của một nhóm đặc trưng. Tên phần có dạng '<nhóm>-<phần>'."""
    tags = lambda rare=True: TagVectorizer(min_freq=min_freq, rare_count=rare)   # noqa: E731
    parts = {
        "numeric": [("numeric-counts", _numeric(), NUMERIC_COLUMNS),
                    ("numeric-palm", "passthrough", ["has_palm_oil"])],
        "position": [("position-pos", "passthrough", POSITION_COLUMNS),
                     ("position-first", tags(rare=False), ["first_ingredient"])],
        "ingredients": [("ingredients", tags(), ["ingredients_tags"])],
        "additives": [("additives-tags", tags(), ["additives_tags"]),
                      ("additives-classes", _numeric(), ADDITIVE_CLASSES)],
        "categories": [("categories-pnns", OneHotEncoder(handle_unknown="ignore"),
                        ["pnns_groups_1_filled", "pnns_groups_2_filled"]),
                       ("categories-tags", tags(), ["categories_tags"]),
                       ("categories-flags", "passthrough", CATEGORY_FLAG_COLUMNS)],
        "nova": [("nova", "passthrough", NOVA_COLUMNS)],
        "labels": [("labels-tags", tags(), ["labels_tags"]),
                   ("labels-analysis", tags(rare=False), ["ingredients_analysis_tags"]),
                   ("labels-organic", "passthrough", ["is_organic"])],
        "countries": [("countries-tags", tags(), ["countries_tags"]),
                      ("countries-n", _numeric(), ["n_countries"])],
        "flags": [("flags", "passthrough", FLAG_COLUMNS)],
    }
    if group not in parts:
        raise ValueError(f"Nhóm đặc trưng không tồn tại: {group}. Các nhóm: {FEATURE_GROUPS}")
    return parts[group]


def build_feature_pipeline(min_freq=DEFAULT_MIN_FREQ, groups=FEATURE_GROUPS, min_support=DEFAULT_MIN_SUPPORT,
                           min_purity=DEFAULT_MIN_PURITY):
    """Pipeline chưa fit: clean_features (DataFrame) -> ma trận thưa. Ở Bước 7-8 chỉ gọi fit trên tập huấn luyện."""
    if not groups:
        raise ValueError("Cần ít nhất một nhóm đặc trưng")
    parts = [p for g in groups for p in group_parts(g, min_freq)]
    return Pipeline([
        ("rows", RowFeatures()),
        ("pnns", CategoryGroupImputer(min_support=min_support, min_purity=min_purity)),
        ("columns", ColumnTransformer(parts, remainder="drop", sparse_threshold=1.0)),
    ])


def feature_group(name):
    """'categories-tags__en:snacks' -> 'categories'."""
    return name.split("__", 1)[0].split("-", 1)[0]


def assert_feature_names_clean(names):
    """Ma trận đặc trưng không được có cột nhãn, dinh dưỡng hay thẻ rò rỉ (tiêu chí hoàn thành của Bước 6)."""
    bases = [n.split("__", 1)[-1] for n in names]
    leaky = [n for n, b in zip(names, bases) if is_leaky_label(b)]
    if leaky:
        raise ValueError(f"Đặc trưng rò rỉ nhãn: {leaky[:10]}")
    # Tên thẻ (có dấu ':') có thể chứa 'nutri' một cách hợp lệ (en:nutritional-yeast) nên chỉ kiểm tra theo mẫu trên.
    assert_no_leakage([b for b in bases if ":" not in b])
    if len(set(names)) != len(names):
        raise ValueError("Tên đặc trưng bị trùng")


def feature_names(pipe):
    """Tên đặc trưng của pipeline đã fit (lấy từ bước ColumnTransformer cuối cùng)."""
    return list(pipe[-1].get_feature_names_out())


def fit_feature_pipeline(X, **kwargs):
    """Fit pipeline trên X (tập huấn luyện) và kiểm tra tên đặc trưng. Trả về pipeline đã fit."""
    pipe = build_feature_pipeline(**kwargs).fit(X)
    assert_feature_names_clean(feature_names(pipe))
    return pipe


# ======================================================================================
# Báo cáo (chỉ mô tả, không dùng nhãn)
# ======================================================================================
def _pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


def count_by_group(names):
    counts = Counter(feature_group(n) for n in names)
    return {g: counts.get(g, 0) for g in FEATURE_GROUPS}


def evaluate_pnns_imputation(X, seed=SEED, test_size=0.2, min_support=DEFAULT_MIN_SUPPORT,
                             min_purity=DEFAULT_MIN_PURITY):
    """Đo phép bổ sung pnns_groups_1: giấu nhóm của 20% sản phẩm đã biết (chia theo group_id), suy lại rồi so.

    Kết quả hơi lạc quan: sản phẩm thật sự thiếu nhóm thường có thẻ danh mục chung chung hoặc chưa dịch.
    """
    rows = RowFeatures().transform(X)
    rows["group_id"] = X["group_id"].values
    known = rows[rows["pnns_groups_1"].map(lambda v: isinstance(v, str))]
    split = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    tr, te = next(split.split(known, groups=known["group_id"]))
    imp = CategoryGroupImputer(min_support=min_support, min_purity=min_purity).fit(known.iloc[tr])
    test = known.iloc[te]
    guess = [imp.impute_one(t) for t in test["categories_tags"]]
    covered = [(g, true) for g, true in zip(guess, test["pnns_groups_1"]) if g is not None]
    correct = sum(g == true for g, true in covered)

    full_imp = CategoryGroupImputer(min_support=min_support, min_purity=min_purity).fit(rows)
    full = full_imp.transform(rows)
    was_missing = ~rows["pnns_groups_1"].map(lambda v: isinstance(v, str))
    filled = full.loc[was_missing, "pnns_groups_1_filled"]
    return {
        "holdout_rows": int(len(test)),
        "holdout_coverage": round(len(covered) / len(test), 4) if len(test) else 0.0,
        "holdout_accuracy": round(correct / len(covered), 4) if covered else 0.0,
        "missing_rows": int(was_missing.sum()),
        "imputed_rows": int((filled != MISSING).sum()),
        "still_missing_rows": int((filled == MISSING).sum()),
        "imputed_groups": {k: int(v) for k, v in filled[filled != MISSING].value_counts().items()},
        "mapping_tags": len(full_imp.mapping_),
    }


def describe_rows(X):
    """Tỷ lệ sản phẩm có từng đặc trưng tự tạo (để kiểm tra quy tắc nhận diện có hợp lý không)."""
    r = RowFeatures().transform(X)
    n = len(r)
    share = lambda mask: _pct(int(mask.sum()), n)   # noqa: E731
    return {
        "rows": n,
        "has_sugar": share(r["pos_sugar"] > 0),
        "sugar_first": share(r["pos_sugar"] == 1.0),
        "has_salt": share(r["pos_salt"] > 0),
        "has_fat": share(r["pos_fat"] > 0),
        "fat_first": share(r["pos_fat"] == 1.0),
        "has_palm_oil": share(r["has_palm_oil"] > 0),
        "with_percentages": share(r["n_ingredients_with_percent"] > 0),
        "is_organic": share(r["is_organic"] > 0),
        "is_beverage": share(r["is_beverage"] > 0),
        "is_fat_oil_nut_seed": share(r["is_fat_oil_nut_seed"] > 0),
        "is_cheese": share(r["is_cheese"] > 0),
        "additive_classes": {c: share(r[c] > 0) for c in ADDITIVE_CLASSES},
        "nova": {c: int(r[c].sum()) for c in NOVA_COLUMNS},
    }


def build_report(X, min_freqs=COMPARE_MIN_FREQS, default_min_freq=DEFAULT_MIN_FREQ):
    """Fit trên TOÀN BỘ dữ liệu chỉ để đếm số đặc trưng; đánh giá mô hình phải fit lại trong từng fold."""
    by_threshold, names = {}, None
    for mf in sorted(set(min_freqs) | {default_min_freq}):
        n = feature_names(fit_feature_pipeline(X, min_freq=mf))
        by_threshold[mf] = {"total": len(n), "groups": count_by_group(n)}
        if mf == default_min_freq:
            names = n
    return {
        "params": {"default_min_freq": default_min_freq, "compare_min_freqs": sorted(set(min_freqs)),
                   "min_support": DEFAULT_MIN_SUPPORT, "min_purity": DEFAULT_MIN_PURITY, "seed": SEED,
                   "pnns_merge": PNNS_MERGE},
        "rows": len(X),
        "by_threshold": by_threshold,
        "pnns_imputation": evaluate_pnns_imputation(X),
        "row_features": describe_rows(X),
    }, names


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in rows]
    return "\n".join(out)


GROUP_LABELS = {
    "numeric": "Số đếm (thành phần, phụ gia, dị ứng, độ dài chữ, %, dầu cọ)",
    "position": "Vị trí đường/muối/chất béo, thành phần đầu tiên",
    "ingredients": "Multi-hot thành phần + số thẻ hiếm",
    "additives": "Multi-hot phụ gia + số phụ gia theo nhóm số E",
    "categories": "pnns_groups_1/2, thẻ danh mục, cờ đồ uống/béo/phô mai",
    "nova": "NOVA 1-4 và thiếu",
    "labels": "Nhãn bao bì, thuần chay/dầu cọ, hữu cơ",
    "countries": "Quốc gia",
    "flags": "Cờ chất lượng dữ liệu",
}


def render_report(r, generated_at):
    thresholds = sorted(r["by_threshold"])
    p = r["pnns_imputation"]
    f = r["row_features"]
    lines = [
        "# Báo cáo đặc trưng (Bước 6)", "",
        f"- Thời điểm: {generated_at}",
        f"- Đầu vào: `data/final/clean_features.parquet`, **{r['rows']}** dòng. Không đọc nhãn.",
        f"- Ngưỡng mặc định: thẻ có ở ≥ {r['params']['default_min_freq']} sản phẩm; "
        f"chốt ngưỡng ở Bước 8 bằng F1 trung bình theo lớp (GroupKFold).",
        "- Số đặc trưng dưới đây do fit trên toàn bộ dữ liệu, CHỈ để mô tả. Ở Bước 7-8 pipeline được fit lại trên "
        "tập huấn luyện của từng fold, nên số cột mỗi fold có thể chênh vài cột.",
        "", "## 1. Số đặc trưng theo nhóm và ngưỡng", "",
        _table(["Nhóm", "Nội dung"] + [f"min_freq = {t}" for t in thresholds],
               [[g, GROUP_LABELS[g]] + [r["by_threshold"][t]["groups"][g] for t in thresholds]
                for g in FEATURE_GROUPS]
               + [["**Tổng**", ""] + [f"**{r['by_threshold'][t]['total']}**" for t in thresholds]]),
        "", "## 2. Bổ sung `pnns_groups_1` từ `categories_tags`", "",
        f"- Thẻ danh mục dùng được: có ở ≥ {r['params']['min_support']} sản phẩm đã biết nhóm; "
        f"chỉ bổ sung khi nhóm phổ biến nhất của thẻ chiếm > {r['params']['min_purity']:.0%}. Không dùng nhãn.",
        f"- Gộp nhóm: {', '.join(f'{k} -> {v}' for k, v in r['params']['pnns_merge'].items())}.",
        f"- Thử trên {p['holdout_rows']} sản phẩm đã biết nhóm (giấu nhóm, chia theo `group_id`, seed {r['params']['seed']}): "
        f"bổ sung được {100 * p['holdout_coverage']:.1f}%, đúng {100 * p['holdout_accuracy']:.1f}% trong số đó. "
        "Con số hơi lạc quan vì sản phẩm thật sự thiếu nhóm thường có thẻ danh mục chung chung hoặc chưa dịch.",
        f"- Áp dụng cho {p['missing_rows']} sản phẩm thiếu nhóm: bổ sung {p['imputed_rows']} "
        f"({_pct(p['imputed_rows'], p['missing_rows'])}%), còn {p['still_missing_rows']} để `missing`.", "",
        _table(["Nhóm bổ sung", "Số sản phẩm"], list(p["imputed_groups"].items())),
        "", "## 3. Đặc trưng tự tạo: tỷ lệ sản phẩm có đặc trưng", "",
        _table(["Đặc trưng", "% sản phẩm"], [
            ["Có đường (thẻ en: chứa sugar, syrup, glucose...)", f["has_sugar"]],
            ["Đường là thành phần đầu tiên", f["sugar_first"]],
            ["Có muối", f["has_salt"]],
            ["Có chất béo/dầu", f["has_fat"]],
            ["Chất béo/dầu là thành phần đầu tiên", f["fat_first"]],
            ["Có dầu cọ", f["has_palm_oil"]],
            ["Chữ thành phần có ghi tỷ lệ %", f["with_percentages"]],
            ["Hữu cơ (nhãn organic/bio)", f["is_organic"]],
            ["Đồ uống (en:beverages)", f["is_beverage"]],
            ["Chất béo/dầu/hạt (danh mục)", f["is_fat_oil_nut_seed"]],
            ["Phô mai (en:cheeses)", f["is_cheese"]],
        ]),
        "", "## 4. Phụ gia theo nhóm số E (% sản phẩm có ít nhất một)", "",
        _table(["Nhóm", "% sản phẩm"], list(f["additive_classes"].items())),
        "", "## 5. NOVA (one-hot)", "",
        _table(["Cột", "Số sản phẩm"], list(f["nova"].items())),
        "", "## 6. Kiểm tra chống rò rỉ", "",
        "- `RowFeatures` từ chối bảng đầu vào có cột nhãn, dinh dưỡng hay trường cá nhân (`assert_no_leakage`).",
        "- `TagVectorizer` từ chối thẻ rò rỉ (logo Nutri-Score, Health Star...) lọt vào danh sách cột.",
        "- `assert_feature_names_clean` kiểm tra mọi tên đặc trưng sau khi fit: không có cột bị cấm.",
        "- Phần cần học (ngưỡng thẻ, ánh xạ danh mục, trung vị, chuẩn hóa) chỉ fit trên tập huấn luyện.",
    ]
    return "\n".join(lines) + "\n"


# ======================================================================================
# Dòng lệnh
# ======================================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="Bước 6: tạo và mô tả bộ đặc trưng (Cách A)")
    ap.add_argument("--in", dest="in_path", default="data/final/clean_features.parquet")
    ap.add_argument("--report", default="reports/features_report.md")
    ap.add_argument("--names-out", default="reports/feature_names.txt")
    ap.add_argument("--min-freq", type=int, default=DEFAULT_MIN_FREQ)
    ap.add_argument("--compare-min-freq", type=int, nargs="+", default=list(COMPARE_MIN_FREQS))
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if not os.path.isfile(args.in_path):
        print(f"Không tìm thấy {args.in_path}. Hãy chạy python -m src.cleaning trước.")
        return 1
    X = pd.read_parquet(args.in_path)
    if X.empty:
        print("Bảng đặc trưng sạch rỗng.")
        return 1

    report, names = build_report(X, min_freqs=args.compare_min_freq, default_min_freq=args.min_freq)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(render_report(report, stamp))
    with open(os.path.splitext(args.report)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump({"generated_at": stamp, **report}, f, ensure_ascii=False, indent=2,
                  default=lambda o: int(o) if isinstance(o, np.integer) else str(o))
    os.makedirs(os.path.dirname(args.names_out) or ".", exist_ok=True)
    with open(args.names_out, "w", encoding="utf-8") as f:
        f.write("\n".join(names) + "\n")

    for t, v in sorted(report["by_threshold"].items()):
        print(f"min_freq = {t:<4} tổng {v['total']:>5} đặc trưng  " +
              ", ".join(f"{g} {c}" for g, c in v["groups"].items()))
    p = report["pnns_imputation"]
    print(f"pnns_groups_1: bổ sung {p['imputed_rows']}/{p['missing_rows']}, "
          f"thử trên dữ liệu đã biết: phủ {p['holdout_coverage']:.1%}, đúng {p['holdout_accuracy']:.1%}")
    print(f"Đã ghi: {args.report}, {args.names_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
