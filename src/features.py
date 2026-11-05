"""Bước 6b - Đặc trưng: clean_features (DataFrame) -> ma trận thưa cho mô hình, gói trong một sklearn Pipeline.

Phần nào "học" từ dữ liệu (danh sách thẻ đủ phổ biến, trung vị, độ lệch chuẩn) chỉ được fit trên tập huấn luyện
của từng fold, nên Pipeline này luôn nằm TRONG mô hình (src.modeling.make_model), không fit trên toàn bộ dữ liệu.

Nhóm đặc trưng (bật/tắt từng nhóm để làm ablation):
    numeric      số thành phần, số phụ gia, số thành phần từ dầu cọ, số quốc gia (log + chuẩn hóa)
    position     vị trí tương đối của đường/muối/chất béo trong danh sách thành phần + thành phần đứng đầu
    ingredients  multi-hot thành phần
    additives    multi-hot phụ gia
    categories   pnns_groups_1/2 (one-hot) + multi-hot thẻ danh mục
    nova         one-hot NOVA 1-4 và "missing"
    labels       multi-hot nhãn bao bì + ingredients_analysis_tags (thuần chay, dầu cọ...)
    countries    multi-hot quốc gia
"""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from src.cleaning import as_list, assert_no_leakage, is_leaky_label

MIN_FREQ = 100     # thẻ phải có ở >= 100 sản phẩm của tập huấn luyện mới thành một cột
GROUPS = ("numeric", "position", "ingredients", "additives", "categories", "nova", "labels", "countries")
NUMERIC_COLUMNS = ["ingredients_n", "additives_n", "ingredients_from_palm_oil_n", "n_countries"]
POSITION_COLUMNS = ["pos_sugar", "pos_salt", "pos_fat"]

# Từ khóa nhận diện đường/muối/chất béo trong thẻ thành phần en: (en:glucose-fructose-syrup -> glucose, fructose, syrup)
SUGAR_WORDS = {"sugar", "sugars", "syrup", "dextrose", "glucose", "fructose", "sucrose", "honey", "molasses", "maltose"}
SALT_WORDS = {"salt"}
FAT_WORDS = {"oil", "oils", "fat", "fats", "butter", "lard", "margarine", "shortening", "ghee", "tallow"}


def tag_list(value):
    """Danh sách thẻ của một ô (list, mảng numpy hoặc None). Dùng làm analyzer cho CountVectorizer."""
    return [t for t in (as_list(value) or []) if isinstance(t, str)]


def relative_position(tags, words):
    """Vị trí tương đối của thành phần ĐẦU TIÊN chứa một từ trong `words`: 1.0 nếu đứng đầu, gần 0 nếu ở cuối,
    0.0 nếu không có. Dùng vị trí tương đối vì thành phần được ghi theo khối lượng giảm dần."""
    tags = tag_list(tags)
    for i, t in enumerate(tags):
        if t.startswith("en:") and set(t[3:].split("-")) & words:
            return 1.0 - i / len(tags)
    return 0.0


def row_features(X):
    """Các cột tính được từ riêng từng dòng (không học gì từ dữ liệu nên không thể rò rỉ giữa train và test)."""
    assert_no_leakage(X.columns)
    df = pd.DataFrame(index=X.index)
    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(X[col], errors="coerce").astype("float64")
    ing = X["ingredients_tags"]
    df["pos_sugar"] = ing.map(lambda t: relative_position(t, SUGAR_WORDS))
    df["pos_salt"] = ing.map(lambda t: relative_position(t, SALT_WORDS))
    df["pos_fat"] = ing.map(lambda t: relative_position(t, FAT_WORDS))
    df["first_ingredient"] = ing.map(lambda t: tag_list(t)[:1])
    for col in ("pnns_groups_1", "pnns_groups_2"):
        df[col] = X[col].map(lambda v: v if isinstance(v, str) and v else "missing")
    df["nova"] = pd.to_numeric(X["nova_group"], errors="coerce").map(lambda v: "missing" if pd.isna(v) else str(int(v)))
    for col in ("ingredients_tags", "additives_tags", "categories_tags", "labels_tags",
                "ingredients_analysis_tags", "countries_tags"):
        df[col] = X[col]
    return df


def multi_hot(min_freq):
    """1 nếu sản phẩm có thẻ; chỉ giữ thẻ có ở >= min_freq sản phẩm của tập fit."""
    return CountVectorizer(analyzer=tag_list, min_df=min_freq, binary=True)


def make_features(min_freq=MIN_FREQ, groups=GROUPS):
    """Pipeline chưa fit: clean_features -> ma trận thưa. groups: các nhóm đặc trưng được dùng."""
    numeric = Pipeline([("fill", SimpleImputer(strategy="median")),          # thiếu -> trung vị của tập fit
                        ("log", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),
                        ("scale", StandardScaler())])                          # chuẩn hóa: trung bình 0, độ lệch 1
    onehot = OneHotEncoder(handle_unknown="ignore")
    parts = {
        "numeric": [("numeric", numeric, NUMERIC_COLUMNS)],
        "position": [("position", "passthrough", POSITION_COLUMNS),
                     ("first", multi_hot(min_freq), "first_ingredient")],
        "ingredients": [("ingredients", multi_hot(min_freq), "ingredients_tags")],
        "additives": [("additives", multi_hot(min_freq), "additives_tags")],
        "categories": [("pnns", onehot, ["pnns_groups_1", "pnns_groups_2"]),
                       ("categories", multi_hot(min_freq), "categories_tags")],
        "nova": [("nova", onehot, ["nova"])],
        "labels": [("labels", multi_hot(min_freq), "labels_tags"),
                   ("analysis", multi_hot(min_freq), "ingredients_analysis_tags")],
        "countries": [("countries", multi_hot(min_freq), "countries_tags")],
    }
    columns = ColumnTransformer([p for g in groups for p in parts[g]], sparse_threshold=1.0)
    return Pipeline([("rows", FunctionTransformer(row_features)), ("columns", columns)])


def feature_names(pipe):
    """Tên đặc trưng của pipeline đã fit, dạng '<phần>__<tên>' (vd. 'ingredients__en:sugar')."""
    return list(pipe["columns"].get_feature_names_out())


def check_feature_names(names):
    """Sau khi fit: không đặc trưng nào là thẻ rò rỉ nhãn (logo Nutri-Score...) hay cột dinh dưỡng."""
    bad = [n for n in names if is_leaky_label(n.split("__", 1)[-1]) or n.endswith("_100g")]
    if bad:
        raise ValueError(f"Đặc trưng rò rỉ nhãn: {bad[:10]}")
    return True
