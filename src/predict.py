"""Bước 9 - Dự đoán và giải thích cho MỘT sản phẩm (dùng trong dashboard).

Mô hình đã đóng băng sau notebook 06: chỉ nạp artifacts/best_model.joblib, không học lại.
Giải thích bằng "tắt thẻ" (giống notebook 06 mục 8.15): bỏ một thẻ khỏi sản phẩm, dự đoán lại, xem xác suất đổi bao
nhiêu. Không dùng SHAP vì TreeSHAP của LightGBM sai số học trên các cây rất sâu của mô hình này.
"""
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity

from src.cleaning import FEATURE_COLUMNS, slugify
from src.features import feature_names
from src.modeling import GRADES

MODEL_PATH = "artifacts/best_model.joblib"
# Các phần đặc trưng dạng thẻ 0/1: tắt được từng thẻ để giải thích
TAG_PARTS = {"ingredients": "thành phần", "first": "đứng đầu", "additives": "phụ gia", "categories": "danh mục",
             "labels": "nhãn", "analysis": "phân tích", "countries": "quốc gia"}


def load_model(path=MODEL_PATH):
    """Pipeline (đặc trưng + LightGBM) đã học trên toàn bộ dev ở notebook 05."""
    return joblib.load(path)["model"]


def to_tags(text):
    """'Sugar, whole milk powder, E322' -> ['en:sugar', 'en:whole-milk-powder', 'en:e322'], giữ thứ tự.
    Thẻ đã có tiền tố ngôn ngữ ('fr:sucre') giữ nguyên tiền tố."""
    tags = []
    for part in str(text or "").split(","):
        part = part.strip().lower()
        prefix, name = (part[:3], part[3:]) if len(part) > 3 and part[2] == ":" else ("en:", part)
        if slugify(name):
            tags.append(prefix + slugify(name))
    return tags


def make_row(ingredients, additives=(), categories=(), pnns_groups_1=None, pnns_groups_2=None, nova=None,
             countries=(), labels=()):
    """Một dòng DataFrame cùng cột với clean_features, từ thông tin người dùng nhập.
    Số đếm tính từ danh sách; cột mô hình không dùng (tên, thương hiệu...) để trống."""
    ingredients = list(ingredients)
    row = dict.fromkeys(FEATURE_COLUMNS)
    row.update({
        "ingredients_tags": ingredients, "ingredients_n": len(ingredients),
        "ingredients_from_palm_oil_n": sum("palm" in t for t in ingredients),
        "additives_tags": list(additives), "additives_n": len(additives),
        "categories_tags": list(categories), "pnns_groups_1": pnns_groups_1, "pnns_groups_2": pnns_groups_2,
        "nova_group": nova, "countries_tags": list(countries), "n_countries": len(countries),
        "labels_tags": list(labels), "ingredients_analysis_tags": [],
    })
    return pd.DataFrame([row])


def predict(model, row):
    """Xác suất 5 hạng (Series a..e) của một sản phẩm."""
    return pd.Series(model.predict_proba(row)[0], index=model.classes_).reindex(GRADES)


def pretty(name):
    """'ingredients__en:palm-oil' -> 'thành phần: palm-oil'."""
    part, tag = name.split("__", 1)
    return f"{TAG_PARTS.get(part, part)}: {tag.split(':', 1)[-1]}"


def explain(model, row, grade, top=10):
    """'Tắt thẻ': nhân bản sản phẩm, mỗi bản tắt một thẻ nó có, dự đoán lại.
    Giá trị = xác suất hạng `grade` giảm bao nhiêu khi tắt thẻ: dương là thẻ ủng hộ hạng đó, âm là thẻ kéo đi chỗ khác."""
    features, clf = model["features"], model["model"]
    M = features.transform(row).tocsr()
    names = feature_names(features)
    cols = [j for j in M.indices if names[j].split("__")[0] in TAG_PARTS]
    if not cols:
        return pd.Series(dtype=float)
    k = list(clf.classes_).index(grade)
    copies = M[np.zeros(len(cols), dtype=int)].tolil()          # len(cols) bản sao của dòng M
    for i, j in enumerate(cols):
        copies[i, j] = 0                                         # bản thứ i tắt thẻ thứ i
    drop = clf.predict_proba(M)[0, k] - clf.predict_proba(copies.tocsr())[:, k]
    s = pd.Series(drop, index=[pretty(names[j]) for j in cols])
    return s.reindex(s.abs().sort_values(ascending=False).index).head(top)


def ingredient_matrix(model, X):
    """Ma trận 0/1 thành phần (đúng các thẻ mô hình biết) của nhiều sản phẩm, để so độ giống nhau."""
    features = model["features"]
    cols = [j for j, n in enumerate(feature_names(features)) if n.startswith("ingredients__")]
    return features.transform(X).tocsr()[:, cols]


def alternatives(model, row, grade, X, y, M_ing, top=5):
    """Sản phẩm cùng nhóm pnns_groups_2 có hạng thật TỐT HƠN `grade`, thành phần giống nhất (cosine).
    X, y: dữ liệu sạch (clean_features, nhãn); M_ing = ingredient_matrix(model, X), tính sẵn một lần."""
    empty = pd.DataFrame(columns=["code", "product_name", "hạng", "độ giống"])
    group = row["pnns_groups_2"].iloc[0]
    if not isinstance(group, str):                               # không biết nhóm thì không so được
        return empty
    rank = np.array([GRADES.index(g) for g in y])
    ok = (X["pnns_groups_2"].to_numpy() == group) & (rank < GRADES.index(grade))
    ok &= X["code"].to_numpy() != row["code"].iloc[0]           # bỏ chính sản phẩm đang xem
    if not ok.any():
        return empty
    sim = cosine_similarity(M_ing[ok], ingredient_matrix(model, row)).ravel()
    best = np.argsort(-sim)[:top]
    out = X.loc[ok, ["code", "product_name"]].iloc[best].reset_index(drop=True)
    return out.assign(**{"hạng": [g.upper() for g in y[ok][best]], "độ giống": sim[best].round(2)})
