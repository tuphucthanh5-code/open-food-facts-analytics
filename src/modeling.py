"""Bước 6c-8 - Chia dữ liệu, khóa tập test, bộ chỉ số, đánh giá chéo, đường cơ sở và các mô hình.

Cách chia (chốt ở Bước 7, lưu trong data/final/split.parquet):
    - Test 20%: StratifiedGroupKFold 5 phần theo group_id (seed 42), lấy phần đầu. Một thương hiệu không bao giờ
      nằm ở cả dev lẫn test. Test bị KHÓA: chỉ lấy được bằng select_test(..., final=True) ở bước đánh giá cuối.
    - Dev 80%: chia tiếp 5 fold cùng cách để so sánh và tinh chỉnh mô hình.
"""
import hashlib

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, cohen_kappa_score, f1_score, log_loss, precision_score,
                             recall_score, roc_auc_score)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier

from src.cleaning import as_list
from src.features import make_features

GRADES = ["a", "b", "c", "d", "e"]
SEED = 42


# ---------------------------------------------------------------------------------------
# Chia dữ liệu và khóa test
# ---------------------------------------------------------------------------------------
def make_split(X, y, seed=SEED, holdout_country="en:france"):
    """Bảng chia: row_id, code, group_id, split (dev/test), fold (0-4 trong dev, -1 ở test), country_holdout."""
    y = np.asarray(y, dtype=object)
    groups = X["group_id"].to_numpy(dtype=object)
    sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    _, test_idx = next(sgkf.split(X, y, groups))
    split = np.full(len(X), "dev", dtype=object)
    split[test_idx] = "test"

    dev = np.flatnonzero(split == "dev")
    fold = np.full(len(X), -1)
    for k, (_, va) in enumerate(sgkf.split(dev, y[dev], groups[dev])):
        fold[dev[va]] = k

    # Bài kiểm tra quốc gia (trong dev): đo trên hàng bán ở Pháp, học trên hàng không bán ở Pháp và không cùng nhóm
    in_country = np.array([holdout_country in (as_list(t) or []) for t in X["countries_tags"]])
    eval_groups = set(groups[dev][in_country[dev]])
    role = np.where(in_country, "eval", np.where([g in eval_groups for g in groups], "excluded", "train"))
    role = np.where(split == "test", "test", role).astype(object)
    return pd.DataFrame({"row_id": X["row_id"].to_numpy(), "code": X["code"].astype(str).to_numpy(dtype=object),
                         "group_id": groups, "split": split, "fold": fold, "country_holdout": role})


def check_split(split):
    """Không nhóm nào nằm ở cả dev và test, hay ở nhiều fold."""
    dev, test = split[split["split"] == "dev"], split[split["split"] == "test"]
    shared = set(dev["group_id"]) & set(test["group_id"])
    spread = dev.groupby("group_id")["fold"].nunique()
    if shared or (spread > 1).any():
        raise ValueError(f"Tập chia sai: {len(shared)} nhóm ở cả dev và test, {(spread > 1).sum()} nhóm ở nhiều fold")
    return True


def fingerprint(split):
    """Dấu vân tay tập test: 16 ký tự đầu SHA-256 của các mã vạch test đã sắp xếp. Đổi một mã là đổi vân tay."""
    codes = sorted(split.loc[split["split"] == "test", "code"].astype(str))
    return hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest()[:16]


def _rows(X, y, split, part):
    if not np.array_equal(X["row_id"].to_numpy(), split["row_id"].to_numpy()):
        raise ValueError("Tập chia không khớp dữ liệu (row_id lệch)")
    idx = np.flatnonzero((split["split"] == part).to_numpy())
    return X.iloc[idx].reset_index(drop=True), np.asarray(y, dtype=object)[idx], split.iloc[idx].reset_index(drop=True)


def select_dev(X, y, split):
    """Phần dev (80%): dùng cho mọi việc so sánh, tinh chỉnh mô hình."""
    return _rows(X, y, split, "dev")


def select_test(X, y, split, final=False):
    """Tập test đã khóa. Chỉ gọi MỘT lần, với final=True, sau khi đã chốt mô hình trên dev."""
    if not final:
        raise PermissionError("Tập test bị khóa. Chỉ gọi select_test(..., final=True) ở bước đánh giá cuối.")
    return _rows(X, y, split, "test")


# ---------------------------------------------------------------------------------------
# Chỉ số
# ---------------------------------------------------------------------------------------
def metrics(y_true, y_pred, proba=None):
    """Macro-F1 là chỉ số chính (các hạng quan trọng như nhau dù số lượng khác nhau).
    QWK và tỷ lệ lệch <= 1 hạng đo mức sai theo thứ tự A < B < C < D < E. proba: ma trận (n, 5) theo GRADES."""
    t = np.array([GRADES.index(g) for g in y_true])
    p = np.array([GRADES.index(g) for g in y_pred])
    out = {
        "macro_f1": f1_score(y_true, y_pred, labels=GRADES, average="macro", zero_division=0),
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred, labels=GRADES, average="macro", zero_division=0),
        "recall": recall_score(y_true, y_pred, labels=GRADES, average="macro", zero_division=0),
        "qwk": cohen_kappa_score(t, p, weights="quadratic", labels=list(range(5))),
        "within_one": float(np.mean(np.abs(t - p) <= 1)),
    }
    if proba is not None:
        out["roc_auc"] = roc_auc_score(y_true, proba, labels=GRADES, multi_class="ovr")
        out["log_loss"] = log_loss(y_true, proba, labels=GRADES)
    return {k: round(float(v), 4) for k, v in out.items()}


def cross_validate(make_model, X, y, folds):
    """Đánh giá chéo: với mỗi fold k, tạo mô hình MỚI, học trên các fold còn lại, dự đoán fold k.
    Trả về (bảng chỉ số từng fold, dự đoán ngoài fold, xác suất ngoài fold)."""
    y = np.asarray(y, dtype=object)
    folds = np.asarray(folds)
    pred = np.empty(len(y), dtype=object)
    proba = np.zeros((len(y), len(GRADES)))
    rows = []
    for k in sorted(set(folds)):
        tr, va = folds != k, folds == k
        model = make_model().fit(X[tr], y[tr])
        pred[va] = model.predict(X[va])
        proba[va] = model.predict_proba(X[va])
        rows.append({"fold": k, **metrics(y[va], pred[va], proba[va])})
    return pd.DataFrame(rows).set_index("fold"), pred, proba


def summarize(per_fold):
    """'trung bình ± độ lệch chuẩn' giữa các fold cho từng chỉ số."""
    return per_fold.mean().round(3).astype(str) + " ± " + per_fold.std().round(3).astype(str)


# ---------------------------------------------------------------------------------------
# Đường cơ sở và mô hình
# ---------------------------------------------------------------------------------------
class CategoryBaseline(ClassifierMixin, BaseEstimator):
    """Đường cơ sở: đoán hạng phổ biến nhất của nhóm pnns_groups_2 trong tập huấn luyện ("missing" cũng là một nhóm)."""

    def fit(self, X, y):
        table = pd.crosstab(X["pnns_groups_2"].fillna("missing").to_numpy(), np.asarray(y)).reindex(
            columns=GRADES, fill_value=0)
        self.classes_ = np.array(GRADES, dtype=object)
        self.prior_ = table.sum().to_numpy() / table.to_numpy().sum()
        self.proba_ = {g: (row.to_numpy() + self.prior_) / (row.sum() + 1) for g, row in table.iterrows()}
        return self

    def predict_proba(self, X):
        return np.array([self.proba_.get(g, self.prior_) for g in X["pnns_groups_2"].fillna("missing")])

    def predict(self, X):
        return self.classes_[self.predict_proba(X).argmax(axis=1)]


def make_model(kind, min_freq=100, groups=None, **params):
    """Mô hình hoàn chỉnh = Pipeline(đặc trưng, bộ phân loại). Nhận thẳng DataFrame clean_features.
    Mọi bộ phân loại dùng class_weight="balanced" để hạng ít (B) không bị lấn át."""
    if kind == "majority":
        return DummyClassifier(strategy="prior")
    if kind == "category":
        return CategoryBaseline()
    if kind == "logreg":
        clf = LogisticRegression(class_weight="balanced", max_iter=2000, **params)
    elif kind == "tree":
        clf = DecisionTreeClassifier(class_weight="balanced", random_state=SEED, **params)
    elif kind == "forest":
        clf = RandomForestClassifier(class_weight="balanced", n_jobs=-1, random_state=SEED, **params)
    elif kind == "lgbm":
        from lightgbm import LGBMClassifier
        clf = LGBMClassifier(class_weight="balanced", random_state=SEED, verbose=-1, **params)
    else:
        raise ValueError(f"Không có loại mô hình {kind!r}")
    features = make_features(min_freq) if groups is None else make_features(min_freq, groups)
    return Pipeline([("features", features), ("model", clf)])
