"""Bước 7 - Chia dữ liệu và thiết lập đánh giá dùng chung cho mọi mô hình.

Đầu vào: data/final/clean_features.parquet (X) và data/final/clean_labels.parquet (y), ghép theo row_id.

Cách chia (chốt 04/11/2026, lý do trong docs/scope_decision.md):
    1. Tập test 20%: StratifiedGroupKFold 5 phần theo group_id (seed 42), lấy phần đầu tiên làm test.
       Một nhóm (thương hiệu) không bao giờ nằm ở cả dev lẫn test; tỷ lệ hạng A-E của test gần bằng toàn bộ.
       Test bị KHÓA đến Bước 9: chỉ lấy được bằng select_test(..., final=True).
    2. 80% còn lại (dev) chia tiếp 5 fold bằng StratifiedGroupKFold (seed 42) để so sánh mô hình ở Bước 8.
    3. Bài kiểm tra giữ lại Pháp (chỉ trong dev): đo trên sản phẩm bán ở Pháp, huấn luyện trên sản phẩm không bán ở
       Pháp, và bỏ khỏi phần huấn luyện mọi sản phẩm thuộc nhóm có hàng bán ở Pháp.

evaluate() huấn luyện một mô hình MỚI trên từng fold rồi đo trên fold còn lại, nên mọi phần cần học (ngưỡng thẻ,
ánh xạ danh mục, chuẩn hóa...) chỉ học từ phần huấn luyện. Bộ chỉ số: macro-F1 (chính), weighted-F1, accuracy,
QWK, tỷ lệ lệch tối đa 1 hạng, MAE trên thang 0-4, log-loss.

Hai đường cơ sở: luôn đoán hạng phổ biến nhất; đoán hạng phổ biến nhất của từng nhóm pnns_groups_2.

Đầu ra của dòng lệnh:
    data/final/split.parquet                 tập chia: row_id, code, group_id, split, fold, country_holdout
    reports/evaluation_setup.md / .json      cách chia, các kiểm tra, kết quả đường cơ sở

Chạy từ thư mục gốc dự án:
    python -m src.models.evaluate
"""
import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator
from sklearn.metrics import accuracy_score, cohen_kappa_score, f1_score, log_loss
from sklearn.model_selection import StratifiedGroupKFold

from src.cleaning import as_list
from src.features import MISSING, clean_pnns

# --- Tham số mặc định (ghi lại trong báo cáo) -------------------------------------------
GRADES = ("a", "b", "c", "d", "e")
GRADE_INDEX = {g: i for i, g in enumerate(GRADES)}
SEED = 42
TEST_SPLITS = 5                    # chia 5 phần, lấy 1 phần làm test -> 20%
N_FOLDS = 5                        # số fold trong dev
HOLDOUT_COUNTRY = "en:france"
SEGMENT_COUNTRIES = {"france": "en:france", "united_states": "en:united-states"}
CATEGORY_BASELINE_COLUMN = "pnns_groups_2"
PROBA_SMOOTHING = 1.0              # làm trơn xác suất của đường cơ sở theo nhóm (chỉ ảnh hưởng log-loss)

PRIMARY_METRIC = "macro_f1"
METRICS = ("macro_f1", "weighted_f1", "accuracy", "qwk", "within_one", "mae", "log_loss")
CLASS_METRICS = tuple(f"f1_{g}" for g in GRADES)
SPLIT_COLUMNS = ["row_id", "code", "group_id", "split", "fold", "country_holdout"]
HOLDOUT_ROLES = ("train", "eval", "excluded")


# ======================================================================================
# Đọc dữ liệu
# ======================================================================================
def check_alignment(X, labels):
    """X và nhãn phải có cùng row_id, cùng thứ tự, và nhãn chỉ gồm a-e."""
    if len(X) != len(labels) or not np.array_equal(X["row_id"].to_numpy(), labels["row_id"].to_numpy()):
        raise ValueError("clean_features và clean_labels lệch row_id. Hãy chạy lại python -m src.cleaning")
    bad = sorted(set(labels["nutriscore_grade"].astype(str)) - set(GRADES))
    if bad:
        raise ValueError(f"Nhãn ngoài a-e: {bad[:5]}")


def load_xy(features_path, labels_path):
    """Đọc X (DataFrame, không có nhãn) và y (mảng hạng a-e cùng thứ tự với X)."""
    X = pd.read_parquet(features_path)
    labels = pd.read_parquet(labels_path)
    check_alignment(X, labels)
    return X, labels["nutriscore_grade"].to_numpy(dtype=object)


def grade_to_int(grades):
    """'a'..'e' -> 0..4 (thang có thứ tự, dùng cho QWK và MAE)."""
    try:
        return np.array([GRADE_INDEX[g] for g in grades], dtype=int)
    except KeyError as e:
        raise ValueError(f"Hạng không hợp lệ: {e.args[0]!r}; chỉ nhận {GRADES}") from None


# ======================================================================================
# Chia dữ liệu
# ======================================================================================
def make_test_mask(y, groups, seed=SEED, n_splits=TEST_SPLITS):
    """True cho các dòng thuộc tập test: phần đầu tiên của StratifiedGroupKFold(n_splits)."""
    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    _, test_idx = next(sgkf.split(np.zeros(len(y)), y, groups=groups))
    mask = np.zeros(len(y), dtype=bool)
    mask[test_idx] = True
    return mask


def make_folds(y, groups, n_folds=N_FOLDS, seed=SEED):
    """Số fold 0..n_folds-1 cho từng dòng; cùng nhóm luôn cùng fold, tỷ lệ hạng mỗi fold gần như nhau."""
    folds = np.full(len(y), -1, dtype=int)
    sgkf = StratifiedGroupKFold(n_splits=n_folds, shuffle=True, random_state=seed)
    for k, (_, va) in enumerate(sgkf.split(np.zeros(len(y)), y, groups=groups)):
        folds[va] = k
    return folds


def has_country(tags, country):
    return country in (as_list(tags) or [])


def country_holdout_roles(countries, groups, country=HOLDOUT_COUNTRY):
    """Vai trò của từng dòng trong bài kiểm tra giữ lại một quốc gia.

    eval: sản phẩm bán ở `country` (kể cả bán thêm nước khác). train: sản phẩm không bán ở đó.
    excluded: không bán ở đó nhưng cùng nhóm với một sản phẩm eval -> bỏ để thương hiệu không lọt từ train sang eval.
    """
    groups = np.asarray(groups, dtype=object)
    in_country = np.array([has_country(t, country) for t in countries], dtype=bool)
    eval_groups = set(groups[in_country])
    overlap = np.array([g in eval_groups for g in groups], dtype=bool)
    return np.where(in_country, "eval", np.where(overlap, "excluded", "train")).astype(object)


def build_split(X, y, seed=SEED, n_folds=N_FOLDS, test_splits=TEST_SPLITS, holdout_country=HOLDOUT_COUNTRY):
    """Bảng chia cho mọi dòng của X: split (dev/test), fold (0..n_folds-1 trong dev, -1 ở test), country_holdout."""
    y = np.asarray(y, dtype=object)
    groups = X["group_id"].to_numpy(dtype=object)
    test = make_test_mask(y, groups, seed, test_splits)
    dev = np.flatnonzero(~test)
    fold = np.full(len(X), -1, dtype=int)
    fold[dev] = make_folds(y[dev], groups[dev], n_folds, seed)
    role = np.full(len(X), "test", dtype=object)
    role[dev] = country_holdout_roles(X["countries_tags"].to_numpy(dtype=object)[dev], groups[dev], holdout_country)
    return pd.DataFrame({
        "row_id": X["row_id"].to_numpy(),
        "code": X["code"].astype(str).to_numpy(dtype=object),
        "group_id": groups,
        "split": np.where(test, "test", "dev").astype(object),
        "fold": fold,
        "country_holdout": role,
    })


def assert_split_valid(split, n_folds=N_FOLDS):
    """Kiểm tra quy tắc chia: không nhóm nào vượt qua ranh giới dev/test, giữa các fold, hay train/eval."""
    problems = []
    if list(split.columns) != SPLIT_COLUMNS:
        problems.append(f"cột phải là {SPLIT_COLUMNS}")
    if not split["row_id"].is_unique:
        problems.append("row_id bị trùng")
    if set(split["split"]) - {"dev", "test"}:
        problems.append("split chỉ nhận dev/test")
    dev, test = split[split["split"] == "dev"], split[split["split"] == "test"]
    shared = set(dev["group_id"]) & set(test["group_id"])
    if shared:
        problems.append(f"{len(shared)} nhóm nằm ở cả dev và test (vd. {sorted(shared)[:3]})")
    if (test["fold"] != -1).any() or set(test["country_holdout"]) - {"test"}:
        problems.append("dòng test không được có fold hay vai trò trong bài kiểm tra quốc gia")
    if not dev["fold"].between(0, n_folds - 1).all():
        problems.append(f"dòng dev phải có fold 0..{n_folds - 1}")
    spread = dev.groupby("group_id")["fold"].nunique()
    if (spread > 1).any():
        problems.append(f"{int((spread > 1).sum())} nhóm nằm ở nhiều fold")
    if set(dev["country_holdout"]) - set(HOLDOUT_ROLES):
        problems.append(f"country_holdout trong dev chỉ nhận {HOLDOUT_ROLES}")
    both = (set(dev.loc[dev["country_holdout"] == "train", "group_id"])
            & set(dev.loc[dev["country_holdout"] == "eval", "group_id"]))
    if both:
        problems.append(f"{len(both)} nhóm nằm ở cả train và eval của bài kiểm tra quốc gia")
    if problems:
        raise ValueError("Tập chia không hợp lệ: " + "; ".join(problems))


def same_split(a, b):
    """Hai bảng chia giống hệt nhau (dùng để khóa: chạy lại không được làm đổi tập test)."""
    if list(a.columns) != SPLIT_COLUMNS or list(b.columns) != SPLIT_COLUMNS or len(a) != len(b):
        return False
    return all(np.array_equal(a[c].astype(str).to_numpy(), b[c].astype(str).to_numpy()) for c in SPLIT_COLUMNS)


def fingerprint_test_codes(split):
    """16 ký tự đầu của SHA-256 trên danh sách mã vạch test đã sắp xếp: ghi vào báo cáo để đối chiếu khi chạy lại."""
    codes = sorted(split.loc[split["split"] == "test", "code"].astype(str))
    return hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest()[:16]


def _check_split_matches(X, split):
    if len(X) != len(split) or not np.array_equal(X["row_id"].to_numpy(), split["row_id"].to_numpy()):
        raise ValueError("Tập chia không khớp dữ liệu (row_id lệch). Dữ liệu sạch đã đổi sau khi chia?")


def select_dev(X, y, split):
    """Phần dev (80%) dùng ở Bước 8: (X_dev, y_dev, split_dev). Cột fold/country_holdout nằm trong split_dev."""
    _check_split_matches(X, split)
    idx = np.flatnonzero((split["split"] == "dev").to_numpy())
    return X.iloc[idx].reset_index(drop=True), np.asarray(y, dtype=object)[idx], split.iloc[idx].reset_index(drop=True)


def select_test(X, y, split, final=False):
    """Tập test đã khóa. Chỉ gọi MỘT lần ở Bước 9, với final=True, sau khi đã chốt mô hình trên dev."""
    if not final:
        raise PermissionError("Tập test bị khóa đến Bước 9. Bước 8 chỉ dùng select_dev(). "
                              "Khi đã chốt mô hình, gọi select_test(..., final=True).")
    _check_split_matches(X, split)
    idx = np.flatnonzero((split["split"] == "test").to_numpy())
    return X.iloc[idx].reset_index(drop=True), np.asarray(y, dtype=object)[idx], split.iloc[idx].reset_index(drop=True)


# ======================================================================================
# Chỉ số đánh giá
# ======================================================================================
def _clean_number(v):
    if v is None:
        return None
    v = float(v)
    return round(v, 4) if math.isfinite(v) else None


def compute_metrics(y_true, y_pred, proba=None):
    """Bộ chỉ số của Bước 7. proba: ma trận (n, 5) theo thứ tự GRADES, hoặc None (khi đó log_loss = None)."""
    y_true = np.asarray(y_true, dtype=object)
    y_pred = np.asarray(y_pred, dtype=object)
    t, p = grade_to_int(y_true), grade_to_int(y_pred)
    labels = list(GRADES)
    gap = np.abs(t - p)
    out = {
        "macro_f1": f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0),
        "weighted_f1": f1_score(y_true, y_pred, labels=labels, average="weighted", zero_division=0),
        "accuracy": accuracy_score(y_true, y_pred),
        "qwk": cohen_kappa_score(t, p, weights="quadratic", labels=list(range(len(GRADES)))),
        "within_one": float(np.mean(gap <= 1)),
        "mae": float(np.mean(gap)),
        "log_loss": log_loss(y_true, proba, labels=labels) if proba is not None else None,
    }
    per_class = f1_score(y_true, y_pred, labels=labels, average=None, zero_division=0)
    out.update({f"f1_{g}": v for g, v in zip(GRADES, per_class)})
    return {k: _clean_number(v) for k, v in out.items()}


def predict_proba_grades(model, X):
    """Xác suất theo thứ tự GRADES (hạng mô hình chưa từng thấy = 0), hoặc None nếu mô hình không có predict_proba."""
    if not hasattr(model, "predict_proba"):
        return None
    raw = np.asarray(model.predict_proba(X), dtype=float)
    out = np.zeros((raw.shape[0], len(GRADES)))
    for j, c in enumerate(model.classes_):
        out[:, GRADE_INDEX[c]] = raw[:, j]
    return out


def country_segments(countries):
    """Mặt nạ cho từng nhóm quốc gia: bán ở Pháp, bán ở Mỹ, còn lại (không Pháp, không Mỹ)."""
    masks = {name: np.array([has_country(t, tag) for t in countries], dtype=bool)
             for name, tag in SEGMENT_COUNTRIES.items()}
    masks["other"] = ~np.logical_or.reduce(list(masks.values()))
    return masks


def fit_model(make_model, X, y):
    """Tạo mô hình mới bằng make_model() rồi fit; trả về (mô hình, số giây fit)."""
    model = make_model()
    start = time.perf_counter()
    model.fit(X, y)
    return model, time.perf_counter() - start


def _summary(rows, keys, fn):
    return {k: _clean_number(fn([r[k] for r in rows if r[k] is not None])) if any(r[k] is not None for r in rows)
            else None for k in keys}


def evaluate(make_model, X, y, folds, segments=None):
    """Đánh giá chéo dùng chung cho MỌI mô hình (đường cơ sở, Logistic Regression, LightGBM...).

    make_model: hàm không tham số, mỗi lần gọi trả về một mô hình MỚI chưa fit (có fit/predict, nên có predict_proba).
                Nếu mô hình là Pipeline(build_feature_pipeline(), bộ phân loại) thì đặc trưng cũng được fit lại trong
                từng fold, đúng yêu cầu của Bước 6.
    X: DataFrame clean_features của tập dev.  y: hạng a-e cùng thứ tự.  folds: số fold của từng dòng.
    segments: dict tên -> mặt nạ bool (vd. country_segments) để đo riêng trên dự đoán ngoài fold.

    Trả về dict: folds (chỉ số từng fold), mean, std (giữa các fold), oof (chỉ số trên toàn bộ dự đoán ngoài fold),
    segments, predictions (DataFrame row_id, fold, y_true, y_pred, p_a..p_e để phân tích lỗi ở Bước 9).
    """
    y = np.asarray(y, dtype=object)
    folds = np.asarray(folds)
    if not (len(X) == len(y) == len(folds)):
        raise ValueError("X, y và folds phải cùng số dòng")
    fold_ids = sorted(set(folds.tolist()))
    if len(fold_ids) < 2:
        raise ValueError("Cần ít nhất 2 fold")

    pred = np.empty(len(y), dtype=object)
    proba = np.full((len(y), len(GRADES)), np.nan)
    with_proba = True
    per_fold = []
    for k in fold_ids:
        tr, va = np.flatnonzero(folds != k), np.flatnonzero(folds == k)
        model, seconds = fit_model(make_model, X.iloc[tr], y[tr])
        p = np.asarray(model.predict(X.iloc[va]), dtype=object)
        pr = predict_proba_grades(model, X.iloc[va])
        pred[va] = p
        if pr is None:
            with_proba = False
        else:
            proba[va] = pr
        per_fold.append({"fold": int(k), "n_train": int(len(tr)), "n_eval": int(len(va)),
                         "fit_seconds": round(seconds, 2), **compute_metrics(y[va], p, pr)})

    oof_proba = proba if with_proba else None
    keys = METRICS + CLASS_METRICS
    result = {
        "folds": per_fold,
        "mean": _summary(per_fold, keys, np.mean),
        "std": _summary(per_fold, keys, lambda v: np.std(v, ddof=1) if len(v) > 1 else 0.0),
        "oof": compute_metrics(y, pred, oof_proba),
    }
    if segments:
        result["segments"] = {
            name: {"rows": int(m.sum()),
                   **compute_metrics(y[m], pred[m], oof_proba[m] if oof_proba is not None else None)}
            for name, m in segments.items() if m.sum() > 0}
    preds = pd.DataFrame({"fold": folds, "y_true": y, "y_pred": pred})
    if "row_id" in X.columns:
        preds.insert(0, "row_id", X["row_id"].to_numpy())
    if oof_proba is not None:
        for j, g in enumerate(GRADES):
            preds[f"p_{g}"] = oof_proba[:, j]
    result["predictions"] = preds
    return result


def evaluate_holdout(make_model, X, y, train_mask, eval_mask):
    """Huấn luyện trên train_mask, đo trên eval_mask (dùng cho bài kiểm tra giữ lại Pháp)."""
    y = np.asarray(y, dtype=object)
    tr, ev = np.flatnonzero(np.asarray(train_mask)), np.flatnonzero(np.asarray(eval_mask))
    if len(tr) == 0 or len(ev) == 0:
        raise ValueError("Phần huấn luyện hoặc phần đo rỗng")
    model, seconds = fit_model(make_model, X.iloc[tr], y[tr])
    p = np.asarray(model.predict(X.iloc[ev]), dtype=object)
    return {"n_train": int(len(tr)), "n_eval": int(len(ev)), "fit_seconds": round(seconds, 2),
            **compute_metrics(y[ev], p, predict_proba_grades(model, X.iloc[ev]))}


# ======================================================================================
# Đường cơ sở
# ======================================================================================
def _grade_counts(y):
    y = np.asarray(y, dtype=object)
    return np.array([np.sum(y == g) for g in GRADES], dtype=float)


class MajorityClassBaseline(BaseEstimator):
    """Đường cơ sở 1: luôn đoán hạng phổ biến nhất của tập huấn luyện; xác suất = tỷ lệ từng hạng trong tập đó."""

    def fit(self, X, y):
        counts = _grade_counts(y)
        if counts.sum() == 0:
            raise ValueError("Tập huấn luyện rỗng")
        self.classes_ = np.array(GRADES, dtype=object)
        self.prior_ = counts / counts.sum()
        self.majority_ = GRADES[int(np.argmax(counts))]
        return self

    def predict(self, X):
        return np.full(len(X), self.majority_, dtype=object)

    def predict_proba(self, X):
        return np.tile(self.prior_, (len(X), 1))


class CategoryMajorityBaseline(BaseEstimator):
    """Đường cơ sở 2: đoán hạng phổ biến nhất của nhóm danh mục (mặc định pnns_groups_2) trong tập huấn luyện.

    Sản phẩm thiếu nhóm xếp vào nhóm "missing" (cũng học từ train). Nhóm chưa gặp lúc fit -> hạng phổ biến nhất
    toàn tập. Hòa thì chọn hạng phổ biến hơn trên toàn tập. Xác suất = (số đếm của nhóm + smoothing x tỷ lệ toàn tập)
    / (cỡ nhóm + smoothing), để log-loss không vô cực khi nhóm nhỏ chưa có đủ mọi hạng.
    """

    def __init__(self, column=CATEGORY_BASELINE_COLUMN, smoothing=PROBA_SMOOTHING):
        self.column = column
        self.smoothing = smoothing

    def _keys(self, X):
        return [clean_pnns(v) or MISSING for v in X[self.column]]

    def fit(self, X, y):
        y = np.asarray(y, dtype=object)
        counts = {}
        for key, g in zip(self._keys(X), y):
            counts.setdefault(key, np.zeros(len(GRADES)))[GRADE_INDEX[g]] += 1
        total = _grade_counts(y)
        if total.sum() == 0:
            raise ValueError("Tập huấn luyện rỗng")
        self.classes_ = np.array(GRADES, dtype=object)
        self.prior_ = total / total.sum()
        self.default_ = GRADES[int(np.argmax(total))]
        self.group_grade_ = {k: GRADES[int(np.argmax(c + 1e-6 * self.prior_))] for k, c in counts.items()}
        self.group_proba_ = {k: (c + self.smoothing * self.prior_) / (c.sum() + self.smoothing)
                             for k, c in counts.items()}
        self.group_size_ = {k: int(c.sum()) for k, c in counts.items()}
        return self

    def predict(self, X):
        return np.array([self.group_grade_.get(k, self.default_) for k in self._keys(X)], dtype=object)

    def predict_proba(self, X):
        return np.array([self.group_proba_.get(k, self.prior_) for k in self._keys(X)], dtype=float)


BASELINES = {
    "majority": ("Đoán hạng phổ biến nhất", MajorityClassBaseline),
    "pnns_groups_2": ("Hạng phổ biến nhất theo pnns_groups_2", CategoryMajorityBaseline),
}
BASELINE_SHORT = {"majority": "đa số", "pnns_groups_2": "pnns_groups_2"}


# ======================================================================================
# Báo cáo
# ======================================================================================
def _pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


def grade_distribution(y):
    y = np.asarray(y, dtype=object)
    return {g: _pct(int(np.sum(y == g)), len(y)) for g in GRADES}


def describe_split(split, y):
    """Số dòng, số nhóm và tỷ lệ hạng của toàn bộ, dev, test, từng fold và từng vai trò bài kiểm tra quốc gia."""
    y = np.asarray(y, dtype=object)
    n = len(split)
    dev = (split["split"] == "dev").to_numpy()

    def part(mask, base):
        return {"rows": int(mask.sum()), "share": _pct(int(mask.sum()), base),
                "groups": int(split.loc[mask, "group_id"].nunique()), "grades": grade_distribution(y[mask])}

    parts = {"all": part(np.ones(n, dtype=bool), n), "dev": part(dev, n),
             "test": part((split["split"] == "test").to_numpy(), n)}
    folds = {int(k): part(dev & (split["fold"] == k).to_numpy(), int(dev.sum()))
             for k in sorted(split.loc[dev, "fold"].unique())}
    roles = {r: part(dev & (split["country_holdout"] == r).to_numpy(), int(dev.sum())) for r in HOLDOUT_ROLES}
    sizes = split["group_id"].value_counts()
    return {"parts": parts, "folds": folds, "country_holdout": roles,
            "largest_group": {"group_id": str(sizes.index[0]), "rows": int(sizes.iloc[0]),
                              "share": _pct(int(sizes.iloc[0]), n)},
            "test_fingerprint": fingerprint_test_codes(split)}


def run_baselines(X, y, split):
    """Chạy hai đường cơ sở CHỈ trên dev: 5 fold, theo quốc gia (ngoài fold) và bài kiểm tra giữ lại Pháp."""
    X_dev, y_dev, s_dev = select_dev(X, y, split)
    segments = country_segments(X_dev["countries_tags"].to_numpy(dtype=object))
    roles = s_dev["country_holdout"].to_numpy()
    out = {}
    for key, (_, cls) in BASELINES.items():
        cv = evaluate(cls, X_dev, y_dev, s_dev["fold"].to_numpy(), segments=segments)
        cv.pop("predictions")
        out[key] = {"cv": cv, "holdout": evaluate_holdout(cls, X_dev, y_dev, roles == "train", roles == "eval")}
    return out


def build_report(X, y, split, seed=SEED, n_folds=N_FOLDS, holdout_country=HOLDOUT_COUNTRY):
    return {
        "params": {"seed": seed, "test_share": 1 / TEST_SPLITS, "n_folds": n_folds,
                   "splitter": "StratifiedGroupKFold(shuffle=True)", "group_column": "group_id",
                   "holdout_country": holdout_country, "primary_metric": PRIMARY_METRIC,
                   "category_baseline_column": CATEGORY_BASELINE_COLUMN, "proba_smoothing": PROBA_SMOOTHING},
        "rows": len(X),
        "split": describe_split(split, y),
        "baselines": run_baselines(X, y, split),
    }


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join("" if c is None else str(c).replace("|", "/") for c in r) + " |" for r in rows]
    return "\n".join(out)


def _fmt(v, digits=3):
    return "—" if v is None else f"{v:.{digits}f}"


def _mean_std(cv, k):
    m, s = cv["mean"][k], cv["std"][k]
    return "—" if m is None else f"{m:.3f} ± {s:.3f}"


METRIC_LABELS = {
    "macro_f1": ("Macro-F1 (chỉ số chính)", "trung bình F1 của 5 hạng, mỗi hạng nặng như nhau", "cao"),
    "weighted_f1": ("Weighted-F1", "trung bình F1 theo số mẫu mỗi hạng", "cao"),
    "accuracy": ("Accuracy", "tỷ lệ đoán đúng hạng", "cao"),
    "qwk": ("QWK", "Quadratic Weighted Kappa: phạt nặng khi đoán lệch xa (A thành E)", "cao, tối đa 1"),
    "within_one": ("Lệch ≤ 1 hạng", "tỷ lệ dự đoán lệch tối đa một hạng", "cao"),
    "mae": ("MAE (thang 0-4)", "số hạng lệch trung bình, A=0 ... E=4", "thấp"),
    "log_loss": ("Log-loss", "xác suất mô hình gán cho hạng đúng có tốt không", "thấp"),
}
SEGMENT_LABELS = {"france": "Bán ở Pháp", "united_states": "Bán ở Mỹ", "other": "Còn lại (không Pháp, không Mỹ)"}
ROLE_LABELS = {"train": "train: không bán ở Pháp", "eval": "eval: bán ở Pháp",
               "excluded": "excluded: không bán ở Pháp nhưng cùng nhóm với hàng Pháp"}


def _part_row(name, p):
    return [name, p["rows"], p["share"], p["groups"]] + [p["grades"][g] for g in GRADES]


def render_report(r, generated_at):
    s, b, prm = r["split"], r["baselines"], r["params"]
    keys = list(BASELINES)
    names = [BASELINES[k][0] for k in keys]
    grade_head = [f"{g.upper()} %" for g in GRADES]
    lines = [
        "# Thiết lập đánh giá và đường cơ sở (Bước 7)", "",
        f"- Thời điểm: {generated_at}",
        f"- Đầu vào: `data/final/clean_features.parquet` + `clean_labels.parquet`, **{r['rows']}** dòng.",
        f"- Cách chia: {prm['splitter']} theo `{prm['group_column']}`, seed {prm['seed']}; test = "
        f"{prm['test_share']:.0%}, dev chia {prm['n_folds']} fold. Tập chia lưu ở `data/final/split.parquet`.",
        "- **Tập test bị khóa**: chưa mô hình nào, kể cả đường cơ sở, được đo trên test. Mọi số dưới đây tính trên dev.",
        f"- Dấu vân tay tập test (SHA-256 của danh sách mã vạch test, 16 ký tự đầu): `{s['test_fingerprint']}`. "
        "Chạy lại mà ra chuỗi khác nghĩa là tập test đã đổi.",
        "", "## 1. Chia dữ liệu", "",
        _table(["Phần", "Số dòng", "% (của toàn bộ / của dev)", "Số nhóm"] + grade_head,
               [_part_row("Toàn bộ", s["parts"]["all"]), _part_row("Dev", s["parts"]["dev"]),
                _part_row("**Test (khóa)**", s["parts"]["test"])]
               + [_part_row(f"Dev - fold {k}", p) for k, p in s["folds"].items()]),
        "", "## 2. Kiểm tra", "",
        "- Không nhóm nào nằm ở cả dev và test; mỗi nhóm chỉ nằm trong một fold "
        "(`assert_split_valid`, chạy mỗi lần tạo tập chia).",
        f"- Nhóm lớn nhất: `{s['largest_group']['group_id']}` {s['largest_group']['rows']} dòng "
        f"({s['largest_group']['share']}%), nên không fold nào bị một thương hiệu chi phối.",
        "- Chạy lại lệnh mà tập chia khác tệp đã lưu thì lệnh dừng, không ghi đè (khóa tập test).",
        "", f"## 3. Bài kiểm tra giữ lại Pháp (`{prm['holdout_country']}`, chỉ trong dev)", "",
        "Huấn luyện trên sản phẩm không bán ở Pháp, đo trên sản phẩm bán ở Pháp. Sản phẩm không bán ở Pháp nhưng cùng "
        "thương hiệu (nhóm) với hàng Pháp bị bỏ khỏi phần huấn luyện, để mô hình không \"nhớ\" thương hiệu.", "",
        _table(["Vai trò", "Số dòng", "% của dev", "Số nhóm"] + grade_head,
               [_part_row(ROLE_LABELS[k], p) for k, p in s["country_holdout"].items()]),
        "", "## 4. Bộ chỉ số", "",
        _table(["Chỉ số", "Ý nghĩa", "Tốt khi"], [list(METRIC_LABELS[k]) for k in METRICS]),
        "", "Chỉ số chính là Macro-F1 vì lớp lệch (E 28,4%, B 11,0%): accuracy cao vẫn có thể bỏ quên hạng ít mẫu. "
        "QWK, lệch ≤ 1 hạng và MAE tính đến thứ tự A < B < C < D < E.",
        "", "## 5. Đường cơ sở: 5 fold trên dev (trung bình ± độ lệch chuẩn giữa các fold)", "",
        _table(["Chỉ số"] + names, [[METRIC_LABELS[k][0]] + [_mean_std(b[x]["cv"], k) for x in keys]
                                    for k in METRICS]),
        "", "## 6. F1 từng hạng (gộp dự đoán ngoài fold)", "",
        _table(["Hạng"] + names, [[g.upper()] + [_fmt(b[x]["cv"]["oof"][f"f1_{g}"]) for x in keys] for g in GRADES]),
        "", "## 7. Theo quốc gia (dự đoán ngoài fold, trên dev)", "",
        _table(["Nhóm", "Số dòng"] + [f"Macro-F1 {BASELINE_SHORT[x]}" for x in keys]
               + [f"Accuracy {BASELINE_SHORT[x]}" for x in keys],
               [[SEGMENT_LABELS[seg], b[keys[0]]["cv"]["segments"][seg]["rows"]]
                + [_fmt(b[x]["cv"]["segments"][seg]["macro_f1"]) for x in keys]
                + [_fmt(b[x]["cv"]["segments"][seg]["accuracy"]) for x in keys]
                for seg in SEGMENT_LABELS if seg in b[keys[0]]["cv"].get("segments", {})]),
        "", "## 8. Giữ lại Pháp", "",
        _table(["Chỉ số"] + names, [[METRIC_LABELS[k][0]] + [_fmt(b[x]["holdout"][k]) for x in keys]
                                    for k in METRICS]),
        "", "## 9. Đọc kết quả", "",
        f"- Đoán một hạng cho tất cả đạt accuracy {_fmt(b['majority']['cv']['mean']['accuracy'])} nhưng Macro-F1 chỉ "
        f"{_fmt(b['majority']['cv']['mean']['macro_f1'])}, vì 4/5 hạng có F1 = 0. Đây là lý do không dùng accuracy làm "
        "chỉ số chính.",
        f"- Đoán theo `pnns_groups_2` đạt accuracy {_fmt(b['pnns_groups_2']['cv']['mean']['accuracy'])} (EDA ước "
        "lượng 0.505 khi học và đo trên cùng dữ liệu, nên lạc quan hơn) và Macro-F1 "
        f"{_fmt(b['pnns_groups_2']['cv']['mean']['macro_f1'])}. Mô hình ở Bước 8 phải vượt mốc này trên cả Macro-F1 "
        "và QWK.",
        f"- Giữ lại Pháp: đoán theo `pnns_groups_2` đạt Macro-F1 {_fmt(b['pnns_groups_2']['holdout']['macro_f1'])}, "
        "so với "
        f"{_fmt(b['pnns_groups_2']['cv'].get('segments', {}).get('france', {}).get('macro_f1'))} trên hàng Pháp "
        "khi Pháp nằm trong 5 fold. Ở Bước 8, khoảng cách này cho biết mô hình học từ nước khác dùng cho Pháp tốt "
        "đến đâu.",
        "- Mô hình ở Bước 8 dùng đúng `evaluate()` và cùng các fold này, nên các con số so sánh được trực tiếp.",
    ]
    return "\n".join(lines) + "\n"


# ======================================================================================
# Dòng lệnh
# ======================================================================================
def _json_default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    return str(o)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bước 7: chia dữ liệu, khóa tập test, chạy đường cơ sở")
    ap.add_argument("--features", default="data/final/clean_features.parquet")
    ap.add_argument("--labels", default="data/final/clean_labels.parquet")
    ap.add_argument("--split-out", default="data/final/split.parquet")
    ap.add_argument("--report", default="reports/evaluation_setup.md")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--n-folds", type=int, default=N_FOLDS)
    ap.add_argument("--holdout-country", default=HOLDOUT_COUNTRY)
    ap.add_argument("--overwrite-split", action="store_true",
                    help="cho phép ghi đè tập chia đã lưu (mở khóa test; phải ghi lý do vào docs/scope_decision.md)")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    for path in (args.features, args.labels):
        if not os.path.isfile(path):
            print(f"Không tìm thấy {path}. Hãy chạy python -m src.cleaning trước.")
            return 1
    X, y = load_xy(args.features, args.labels)
    if X.empty:
        print("Bảng đặc trưng sạch rỗng.")
        return 1

    split = build_split(X, y, seed=args.seed, n_folds=args.n_folds, holdout_country=args.holdout_country)
    assert_split_valid(split, n_folds=args.n_folds)
    if os.path.isfile(args.split_out) and not args.overwrite_split:
        if not same_split(pd.read_parquet(args.split_out), split):
            print(f"Tập chia mới KHÁC {args.split_out} (tập test đã khóa). Không ghi đè. Nếu thật sự phải chia lại "
                  "(vd. dữ liệu sạch đã đổi), chạy với --overwrite-split và ghi lý do vào docs/scope_decision.md.")
            return 1
        print(f"Tập chia khớp {args.split_out}: tập test không đổi.")
    else:
        os.makedirs(os.path.dirname(args.split_out) or ".", exist_ok=True)
        split.to_parquet(args.split_out, index=False)

    report = build_report(X, y, split, seed=args.seed, n_folds=args.n_folds, holdout_country=args.holdout_country)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(render_report(report, stamp))
    with open(os.path.splitext(args.report)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump({"generated_at": stamp, **report}, f, ensure_ascii=False, indent=2, default=_json_default)

    p = report["split"]["parts"]
    print(f"Dev {p['dev']['rows']} dòng ({p['dev']['groups']} nhóm) | Test (khóa) {p['test']['rows']} dòng "
          f"({p['test']['groups']} nhóm) | vân tay test {report['split']['test_fingerprint']}")
    for key, (label, _) in BASELINES.items():
        cv = report["baselines"][key]["cv"]["mean"]
        print(f"{label:<40} macro-F1 {cv['macro_f1']:.3f}  accuracy {cv['accuracy']:.3f}  QWK {cv['qwk']:.3f}")
    print(f"Đã ghi: {args.split_out}, {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
