"""Bước 8 - Huấn luyện, so sánh mô hình, ablation và tinh chỉnh bằng Optuna. CHỈ dùng tập dev (test vẫn khóa).

Đầu vào: data/final/clean_features.parquet, clean_labels.parquet và data/final/split.parquet (tạo ở Bước 7).

Cấu hình chính (chốt 05/11/2026, lý do trong docs/scope_decision.md):
    - min_freq = 100 (thẻ có ở >= 100 sản phẩm của phần huấn luyện mới thành một cột).
    - Bỏ nhóm đặc trưng "flags" (cờ chất lượng dữ liệu): mô hình học từ thông tin món ăn, không học từ thói quen
      nhập liệu. Hai lựa chọn này vẫn được đo lại một lần (min_freq = 20, có flags) để ghi số liệu vào báo cáo.

Mọi mô hình là một NutriModel = pipeline đặc trưng Bước 6 + một bộ phân loại, nên khi đưa vào evaluate() (Bước 7),
đặc trưng được fit lại trên phần huấn luyện của từng fold. Các mô hình:
    logreg        Logistic Regression đa lớp trên ma trận thưa, trọng số lớp cân bằng (chọn C bằng lưới nhỏ)
    tree          cây quyết định nông (chọn độ sâu bằng lưới nhỏ)
    lgbm          LightGBM phân loại, trọng số lớp cân bằng, dừng sớm
    lgbm_ordinal  LightGBM hồi quy trên thang 0-4 (A=0 ... E=4) rồi cắt thành hạng bằng 4 ngưỡng tối ưu Macro-F1

Dừng sớm và chọn ngưỡng KHÔNG dùng fold đang đo: mỗi lần fit, tách 1/10 số nhóm (thương hiệu) của phần huấn luyện
làm "tập dừng sớm"; mô hình học trên 9/10 còn lại.

Đầu ra của dòng lệnh:
    reports/modeling_results.md / .json      bảng so sánh mô hình, ablation, kết quả Optuna
    artifacts/best_model.joblib              mô hình tốt nhất fit trên toàn bộ dev, kèm tham số và phiên bản thư viện
    data/processed/oof_predictions.parquet   dự đoán ngoài fold (trên dev) của mô hình tốt nhất, cho Bước 9

Chạy từ thư mục gốc dự án (mất khoảng 1 giờ, phần lớn là Optuna và ablation):
    python -m src.models.train
"""
import argparse
import inspect
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone

import joblib
import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
import scipy
import sklearn
from scipy import sparse
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.tree import DecisionTreeClassifier
from sklearn.utils.class_weight import compute_sample_weight
from sklearn.utils.metaestimators import available_if

from src.features import FEATURE_GROUPS, feature_names, fit_feature_pipeline
from src.models import evaluate as ev

# --- Tham số mặc định (ghi lại trong báo cáo) -------------------------------------------
SEED = ev.SEED
GRADES = ev.GRADES
MIN_FREQ = 100
MAIN_GROUPS = tuple(g for g in FEATURE_GROUPS if g != "flags")
KINDS = ("logreg", "tree", "lgbm", "lgbm_ordinal")

EARLY_STOP_SPLITS = 10             # tách 1/10 số nhóm của phần huấn luyện làm tập dừng sớm
EARLY_STOP_ROUNDS = 50             # dừng khi 50 vòng liền không tốt hơn trên tập dừng sớm
MAX_ROUNDS = 3000                  # số cây tối đa (thực tế dừng sớm hơn nhiều)
N_TRIALS = 40                      # số lần thử Optuna (kế hoạch: 30-50)
LOGREG_C_GRID = (0.03, 0.1, 0.3, 1.0)
TREE_DEPTH_GRID = (4, 6, 8)
TREE_MIN_LEAF = 20
# Gần với mặc định của LightGBM; reg_lambda/reg_alpha = 0,001 (coi như không phạt) vì Optuna dò chúng trên thang log
# nên không nhận 0, mà lần thử đầu tiên của Optuna chính là bộ tham số này.
LGBM_DEFAULTS = {"learning_rate": 0.05, "num_leaves": 31, "min_child_samples": 20, "reg_lambda": 1e-3,
                 "reg_alpha": 1e-3, "colsample_bytree": 1.0, "subsample": 1.0}
LGBM_FIXED = {"class_weight": "balanced", "subsample_freq": 1, "deterministic": True, "force_row_wise": True,
              "verbose": -1}
ORDINAL_START = (0.5, 1.5, 2.5, 3.5)   # ngưỡng ban đầu: làm tròn điểm dự đoán về hạng gần nhất
THRESHOLD_STEP = 0.02

# Ablation kiểu cộng dồn (theo kế hoạch): thêm lần lượt từng nhóm; bậc cuối = cấu hình chính.
ABLATION_LADDER = (
    ("Chỉ thành phần (thành phần + vị trí đường/muối/béo)", ("ingredients", "position")),
    ("+ phụ gia", ("ingredients", "position", "additives")),
    ("+ danh mục", ("ingredients", "position", "additives", "categories")),
    ("+ NOVA", ("ingredients", "position", "additives", "categories", "nova")),
    ("+ số đếm, nhãn, quốc gia (cấu hình chính)", MAIN_GROUPS),
)
# Hai phép đo phụ cho hai quyết định đã chốt (không đổi cấu hình chính).
SIDE_CHECKS = (
    ("min_freq = 20", 20, MAIN_GROUPS),
    ("Có nhóm flags", MIN_FREQ, FEATURE_GROUPS),
)

MODEL_LABELS = {
    "majority": "Đường cơ sở: hạng phổ biến nhất",
    "pnns_groups_2": "Đường cơ sở: theo pnns_groups_2",
    "logreg": "Logistic Regression",
    "tree": "Cây quyết định nông",
    "lgbm": "LightGBM (tham số mặc định)",
    "lgbm_ordinal": "LightGBM hồi quy thứ tự + ngưỡng",
    "lgbm_tuned": "LightGBM (Optuna)",
}
BASELINE_KEYS = ("majority", "pnns_groups_2")


# ======================================================================================
# Ma trận đặc trưng và tập dừng sớm
# ======================================================================================
def to_matrix(M):
    """Ma trận thưa CSR float32 (LightGBM và Logistic Regression đều nhận, tốn ít bộ nhớ)."""
    return sparse.csr_matrix(M, dtype=np.float32)


def inner_split(y, groups, seed=SEED, n_splits=EARLY_STOP_SPLITS):
    """(chỉ số học, chỉ số dừng sớm) trong PHẦN HUẤN LUYỆN: tách khoảng 1/n_splits số nhóm, giữ tỷ lệ hạng.

    Cùng một thương hiệu không nằm ở cả hai phần, để việc dừng sớm không bị lạc quan vì "đã thấy" thương hiệu.
    """
    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    fit_idx, stop_idx = next(sgkf.split(np.zeros(len(y)), y, groups=groups))
    return fit_idx, stop_idx


def _eval_kwargs(model, M, y):
    """LightGBM >= 4.7 dùng eval_X/eval_y; bản cũ hơn dùng eval_set."""
    if "eval_X" in inspect.signature(model.fit).parameters:
        return {"eval_X": (M,), "eval_y": (y,)}
    return {"eval_set": [(M, y)]}


# ======================================================================================
# Ngưỡng cho hồi quy thứ tự
# ======================================================================================
def apply_thresholds(score, cuts):
    """Điểm liên tục -> hạng 0..4: điểm < cuts[0] là 0 (A), cuts[0] <= điểm < cuts[1] là 1 (B), ..."""
    return np.searchsorted(np.asarray(cuts, dtype=float), np.asarray(score, dtype=float), side="right")


def macro_f1_int(y_true, y_pred, n_classes=len(GRADES)):
    """Macro-F1 cho nhãn số nguyên 0..n-1 (nhanh hơn sklearn, dùng khi thử hàng trăm bộ ngưỡng)."""
    y_true, y_pred = np.asarray(y_true, dtype=int), np.asarray(y_pred, dtype=int)
    tp = np.bincount(y_true[y_true == y_pred], minlength=n_classes).astype(float)
    n_true = np.bincount(y_true, minlength=n_classes).astype(float)
    n_pred = np.bincount(y_pred, minlength=n_classes).astype(float)
    denom = n_true + n_pred
    f1 = np.divide(2 * tp, denom, out=np.zeros(n_classes), where=denom > 0)
    return float(f1.mean())


def optimize_thresholds(score, y_int, start=ORDINAL_START, step=THRESHOLD_STEP, passes=3):
    """Tìm 4 ngưỡng tăng dần cho Macro-F1 cao nhất (dò từng ngưỡng một, lặp vài lượt). Trả về mảng 4 ngưỡng."""
    score = np.asarray(score, dtype=float)
    cuts = np.array(start, dtype=float)
    best = macro_f1_int(y_int, apply_thresholds(score, cuts))
    lo_bound, hi_bound = -0.5, len(GRADES) - 0.5
    for _ in range(passes):
        improved = False
        for i in range(len(cuts)):
            lo = cuts[i - 1] + step if i > 0 else lo_bound
            hi = cuts[i + 1] - step if i < len(cuts) - 1 else hi_bound
            for c in np.arange(lo, hi + 1e-9, step):
                trial = cuts.copy()
                trial[i] = c
                f = macro_f1_int(y_int, apply_thresholds(score, trial))
                if f > best + 1e-12:
                    best, cuts, improved = f, trial, True
        if not improved:
            break
    return cuts


# ======================================================================================
# Bộ phân loại trên ma trận đặc trưng (core)
# ======================================================================================
class PlainCore:
    """Bọc một bộ phân loại sklearn để có cùng giao diện fit(M, y, groups) với các core LightGBM."""

    def __init__(self, estimator):
        self.estimator = estimator

    def fit(self, M, y, groups=None):
        self.estimator.fit(M, y)
        self.classes_ = self.estimator.classes_
        return self

    def predict(self, M):
        return self.estimator.predict(M)

    def predict_proba(self, M):
        return self.estimator.predict_proba(M)


class LGBMClassifierCore:
    """LightGBM phân loại, trọng số lớp cân bằng, dừng sớm trên 1/10 nhóm của phần huấn luyện."""

    def __init__(self, params=None, seed=SEED):
        self.params = dict(params or {})
        self.seed = seed

    def fit(self, M, y, groups):
        y = np.asarray(y, dtype=object)
        t = ev.grade_to_int(y)                 # LightGBM cần nhãn số cho cả tập dừng sớm: a..e -> 0..4
        fit_idx, stop_idx = inner_split(y, groups, self.seed)
        self.model_ = lgb.LGBMClassifier(n_estimators=MAX_ROUNDS, random_state=self.seed,
                                         **{**LGBM_DEFAULTS, **self.params, **LGBM_FIXED})
        self.model_.fit(M[fit_idx], t[fit_idx], **_eval_kwargs(self.model_, M[stop_idx], t[stop_idx]),
                        callbacks=[lgb.early_stopping(EARLY_STOP_ROUNDS, verbose=False)])
        self.classes_ = np.array(GRADES, dtype=object)[self.model_.classes_]
        self.best_iteration_ = int(self.model_.best_iteration_ or MAX_ROUNDS)
        return self

    def predict(self, M):
        return np.array(GRADES, dtype=object)[np.asarray(self.model_.predict(M), dtype=int)]

    def predict_proba(self, M):
        return self.model_.predict_proba(M)


class LGBMOrdinalCore:
    """LightGBM hồi quy trên thang 0-4 rồi cắt bằng 4 ngưỡng. Coi A < B < C < D < E là có thứ tự.

    Trọng số mẫu cân bằng theo hạng (như class_weight). Tập dừng sớm dùng cho cả dừng sớm lẫn chọn ngưỡng.
    Không có predict_proba (hồi quy không cho xác suất từng hạng), nên log-loss để trống.
    """

    def __init__(self, params=None, seed=SEED):
        self.params = dict(params or {})
        self.seed = seed

    def fit(self, M, y, groups):
        y = np.asarray(y, dtype=object)
        t = ev.grade_to_int(y)
        fit_idx, stop_idx = inner_split(y, groups, self.seed)
        fixed = {k: v for k, v in LGBM_FIXED.items() if k != "class_weight"}
        self.model_ = lgb.LGBMRegressor(n_estimators=MAX_ROUNDS, random_state=self.seed,
                                        **{**LGBM_DEFAULTS, **self.params, **fixed})
        self.model_.fit(M[fit_idx], t[fit_idx], sample_weight=compute_sample_weight("balanced", t[fit_idx]),
                        **_eval_kwargs(self.model_, M[stop_idx], t[stop_idx]),
                        callbacks=[lgb.early_stopping(EARLY_STOP_ROUNDS, verbose=False)])
        self.best_iteration_ = int(self.model_.best_iteration_ or MAX_ROUNDS)
        self.cuts_ = optimize_thresholds(self.model_.predict(M[stop_idx]), t[stop_idx])
        self.classes_ = np.array(GRADES, dtype=object)
        return self

    def predict(self, M):
        idx = apply_thresholds(self.model_.predict(M), self.cuts_)
        return np.array(GRADES, dtype=object)[idx]


def make_core(kind, params=None, seed=SEED):
    """Bộ phân loại MỚI chưa fit cho loại mô hình `kind` với tham số `params`."""
    params = dict(params or {})
    if kind == "logreg":
        return PlainCore(LogisticRegression(C=params.get("C", 1.0), class_weight="balanced", max_iter=3000,
                                            random_state=seed))
    if kind == "tree":
        return PlainCore(DecisionTreeClassifier(max_depth=params.get("max_depth", 6), class_weight="balanced",
                                                min_samples_leaf=params.get("min_samples_leaf", TREE_MIN_LEAF),
                                                random_state=seed))
    if kind == "lgbm":
        return LGBMClassifierCore(params, seed)
    if kind == "lgbm_ordinal":
        return LGBMOrdinalCore(params, seed)
    raise ValueError(f"Loại mô hình không tồn tại: {kind}. Chọn trong {KINDS}")


# ======================================================================================
# Mô hình hoàn chỉnh: đặc trưng + bộ phân loại
# ======================================================================================
class NutriModel(BaseEstimator, ClassifierMixin):
    """Pipeline đặc trưng Bước 6 + bộ phân loại. fit/predict nhận DataFrame clean_features (cần cột group_id).

    Dùng với evaluate(): evaluate(lambda: NutriModel("lgbm", params), X_dev, y_dev, folds). Mỗi fold tạo mô hình
    mới, nên ngưỡng thẻ, ánh xạ danh mục, chuẩn hóa... chỉ học từ phần huấn luyện của fold đó.
    """

    def __init__(self, kind="lgbm", params=None, min_freq=MIN_FREQ, groups=MAIN_GROUPS, seed=SEED):
        self.kind = kind
        self.params = params
        self.min_freq = min_freq
        self.groups = groups
        self.seed = seed

    def fit(self, X, y):
        y = np.asarray(y, dtype=object)
        if self.kind not in KINDS:
            raise ValueError(f"Loại mô hình không tồn tại: {self.kind}. Chọn trong {KINDS}")
        self.features_ = fit_feature_pipeline(X, min_freq=self.min_freq, groups=tuple(self.groups))
        M = to_matrix(self.features_.transform(X))
        self.core_ = make_core(self.kind, self.params, self.seed).fit(M, y, X["group_id"].to_numpy(dtype=object))
        self.classes_ = np.array(GRADES, dtype=object)
        self.n_features_ = M.shape[1]
        return self

    def _matrix(self, X):
        return to_matrix(self.features_.transform(X))

    def predict(self, X):
        return np.asarray(self.core_.predict(self._matrix(X)), dtype=object)

    def _has_proba(self):
        return self.kind != "lgbm_ordinal"

    @available_if(_has_proba)
    def predict_proba(self, X):
        """Xác suất 5 hạng theo thứ tự a-e (hạng mà phần huấn luyện không có thì xác suất 0).

        Ma trận float32 làm xác suất của Logistic Regression cũng là float32 (tổng lệch 1 khoảng 1e-7), nên chia lại
        cho tổng ở float64 để log-loss không cảnh báo.
        """
        p = ev.predict_proba_grades(self.core_, self._matrix(X))
        return p / p.sum(axis=1, keepdims=True)

    def feature_names(self):
        """Tên các cột đặc trưng (dùng cho SHAP ở Bước 9)."""
        return feature_names(self.features_)


def model_factory(kind, params=None, min_freq=MIN_FREQ, groups=MAIN_GROUPS, seed=SEED):
    """Hàm không tham số trả về NutriModel mới (đúng dạng make_model mà evaluate() cần)."""
    return lambda: NutriModel(kind, dict(params or {}), min_freq, tuple(groups), seed)


# ======================================================================================
# Đánh giá nhanh khi chọn tham số: tính đặc trưng mỗi fold MỘT lần rồi dùng lại
# ======================================================================================
def build_fold_cache(X, y, folds, min_freq=MIN_FREQ, groups=MAIN_GROUPS):
    """Với mỗi fold: fit pipeline đặc trưng trên phần huấn luyện, biến đổi cả hai phần.

    Kết quả giống hệt NutriModel trong evaluate() (pipeline đặc trưng không dùng nhãn và không phụ thuộc bộ phân
    loại), chỉ nhanh hơn vì không tính lại đặc trưng cho mỗi lần thử tham số.
    """
    y = np.asarray(y, dtype=object)
    folds = np.asarray(folds)
    group_ids = X["group_id"].to_numpy(dtype=object)
    cache = []
    for k in sorted(set(folds.tolist())):
        tr, va = np.flatnonzero(folds != k), np.flatnonzero(folds == k)
        pipe = fit_feature_pipeline(X.iloc[tr], min_freq=min_freq, groups=tuple(groups))
        cache.append({"fold": int(k), "train": tr, "eval": va, "groups_train": group_ids[tr],
                      "M_train": to_matrix(pipe.transform(X.iloc[tr])),
                      "M_eval": to_matrix(pipe.transform(X.iloc[va]))})
    return cache


def cv_score_cached(kind, params, cache, y, seed=SEED, trial=None):
    """Macro-F1 trung bình qua các fold trên đặc trưng đã tính sẵn. trial: lần thử Optuna (để cắt sớm lần thử kém)."""
    y = np.asarray(y, dtype=object)
    scores, iterations = [], []
    for step, c in enumerate(cache):
        core = make_core(kind, params, seed).fit(c["M_train"], y[c["train"]], c["groups_train"])
        scores.append(ev.compute_metrics(y[c["eval"]], core.predict(c["M_eval"]))["macro_f1"])
        iterations.append(getattr(core, "best_iteration_", None))
        if trial is not None:
            trial.report(float(np.mean(scores)), step)
            if trial.should_prune():
                raise optuna.TrialPruned()
    if trial is not None and all(i is not None for i in iterations):
        trial.set_user_attr("mean_best_iteration", float(np.mean(iterations)))
    return float(np.mean(scores))


def grid_search(kind, grid, cache, y, seed=SEED):
    """Thử từng bộ tham số trong `grid` (danh sách dict); trả về (bộ tốt nhất, bảng kết quả)."""
    results = [{"params": dict(p), "macro_f1": round(cv_score_cached(kind, p, cache, y, seed), 4)} for p in grid]
    best = max(results, key=lambda r: r["macro_f1"])
    return best["params"], results


def suggest_lgbm_params(trial):
    """Không gian tìm kiếm của Optuna cho LightGBM (ý nghĩa từng tham số: docs/Giai_thich_ma_nguon.md mục 13)."""
    return {
        "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 15, 255, log=True),
        "min_child_samples": trial.suggest_int("min_child_samples", 5, 100, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.3, 1.0),
        "subsample": trial.suggest_float("subsample", 0.5, 1.0),
    }


def tune_lgbm(cache, y, n_trials=N_TRIALS, seed=SEED, log=None):
    """Optuna (TPE, seed cố định) tối đa Macro-F1 trung bình 5 fold dev. Lần thử đầu = tham số mặc định.

    MedianPruner bỏ giữa chừng lần thử có Macro-F1 sau vài fold thấp hơn trung vị các lần trước (tiết kiệm thời gian).
    log: hàm in tiến độ sau mỗi lần thử (None = không in).
    """
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed),
                                pruner=optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=1))
    study.enqueue_trial(dict(LGBM_DEFAULTS))

    def progress(st, t):
        if log is not None:
            score = "bị cắt sớm" if t.value is None else f"Macro-F1 {t.value:.4f}"
            log(f"  lần thử {t.number + 1}/{n_trials}: {score} (tốt nhất {st.best_value:.4f})")

    study.optimize(lambda t: cv_score_cached("lgbm", suggest_lgbm_params(t), cache, y, seed, trial=t),
                   n_trials=n_trials, callbacks=[progress])
    trials = [{"number": t.number, "state": t.state.name,
               "macro_f1": None if t.value is None else round(t.value, 4),
               "mean_best_iteration": t.user_attrs.get("mean_best_iteration"),
               "params": {k: (round(v, 5) if isinstance(v, float) else v) for k, v in t.params.items()}}
              for t in study.trials]
    return dict(study.best_params), {"best_value": round(study.best_value, 4), "best_trial": study.best_trial.number,
                                     "n_complete": sum(t["state"] == "COMPLETE" for t in trials),
                                     "n_pruned": sum(t["state"] == "PRUNED" for t in trials), "trials": trials}


# ======================================================================================
# Chạy toàn bộ Bước 8 trên dev
# ======================================================================================
def run_cv(make_model, X_dev, y_dev, folds, segments, roles, keep_predictions=False):
    """evaluate() 5 fold + bài kiểm tra giữ lại Pháp. Bỏ bảng dự đoán khỏi kết quả trừ khi keep_predictions."""
    cv = ev.evaluate(make_model, X_dev, y_dev, folds, segments=segments)
    preds = cv.pop("predictions")
    out = {"cv": cv, "holdout": ev.evaluate_holdout(make_model, X_dev, y_dev, roles == "train", roles == "eval")}
    return (out, preds) if keep_predictions else out


def beats_baseline(result, baseline):
    """Mô hình phải hơn đường cơ sở trên CẢ Macro-F1 lẫn QWK (tiêu chí hoàn thành Bước 8)."""
    m, b = result["cv"]["mean"], baseline["cv"]["mean"]
    return bool(m["macro_f1"] > b["macro_f1"] and m["qwk"] > b["qwk"])


def run_ablation(kind, params, X_dev, y_dev, folds, min_freq=MIN_FREQ, seed=SEED, main_result=None, log=print):
    """Ablation trên 5 fold dev bằng mô hình tốt nhất: cộng dồn từng nhóm, bỏ từng nhóm, và hai phép đo phụ."""
    def score(mf, groups):
        cv = ev.evaluate(model_factory(kind, params, mf, groups, seed), X_dev, y_dev, folds)
        return {"macro_f1": cv["mean"]["macro_f1"], "macro_f1_std": cv["std"]["macro_f1"], "qwk": cv["mean"]["qwk"],
                "accuracy": cv["mean"]["accuracy"]}

    main = ({k: main_result["cv"]["mean"][k] for k in ("macro_f1", "qwk", "accuracy")}
            | {"macro_f1_std": main_result["cv"]["std"]["macro_f1"]}) if main_result else None
    ladder = []
    for label, groups in ABLATION_LADDER:
        log(f"  ablation cộng dồn: {label}")
        r = main if (main and tuple(groups) == MAIN_GROUPS and min_freq == MIN_FREQ) else score(min_freq, groups)
        ladder.append({"label": label, "groups": list(groups), **r})
    main = main or ladder[-1]
    drop_one = []
    for g in MAIN_GROUPS:
        log(f"  ablation bỏ nhóm: {g}")
        r = score(min_freq, tuple(x for x in MAIN_GROUPS if x != g))
        drop_one.append({"group": g, **r, "delta_macro_f1": round(r["macro_f1"] - main["macro_f1"], 4)})
    side = []
    for label, mf, groups in SIDE_CHECKS:
        log(f"  phép đo phụ: {label}")
        r = score(mf, groups)
        side.append({"label": label, "min_freq": mf, "groups": list(groups), **r,
                     "delta_macro_f1": round(r["macro_f1"] - main["macro_f1"], 4)})
    return {"main": main, "ladder": ladder, "drop_one": drop_one, "side_checks": side}


def library_versions():
    return {"python": platform.python_version(), "scikit-learn": sklearn.__version__, "lightgbm": lgb.__version__,
            "optuna": optuna.__version__, "numpy": np.__version__, "pandas": pd.__version__,
            "scipy": scipy.__version__, "joblib": joblib.__version__}


def run_all(X, y, split, n_trials=N_TRIALS, min_freq=MIN_FREQ, seed=SEED, ablation=True, log=print):
    """Toàn bộ Bước 8 trên dev. Trả về (báo cáo, cấu hình mô hình tốt nhất, dự đoán ngoài fold của mô hình đó)."""
    ev.assert_split_valid(split)
    X_dev, y_dev, s_dev = ev.select_dev(X, y, split)        # KHÔNG gọi select_test: tập test khóa đến Bước 9
    folds = s_dev["fold"].to_numpy()
    roles = s_dev["country_holdout"].to_numpy()
    segments = ev.country_segments(X_dev["countries_tags"].to_numpy(dtype=object))
    timings = {}

    t0 = time.perf_counter()
    log("Tính sẵn đặc trưng cho 5 fold (cấu hình chính)...")
    cache = build_fold_cache(X_dev, y_dev, folds, min_freq, MAIN_GROUPS)
    log("Chọn C cho Logistic Regression và độ sâu cho cây quyết định...")
    best_c, grid_lr = grid_search("logreg", [{"C": c} for c in LOGREG_C_GRID], cache, y_dev, seed)
    best_depth, grid_tree = grid_search("tree", [{"max_depth": d, "min_samples_leaf": TREE_MIN_LEAF}
                                                 for d in TREE_DEPTH_GRID], cache, y_dev, seed)
    timings["grid_search"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    log(f"Optuna: {n_trials} lần thử cho LightGBM...")
    best_lgbm, optuna_info = tune_lgbm(cache, y_dev, n_trials, seed, log=log)
    timings["optuna"] = time.perf_counter() - t0
    del cache

    t0 = time.perf_counter()
    configs = {"logreg": ("logreg", best_c), "tree": ("tree", best_depth), "lgbm": ("lgbm", {}),
               "lgbm_ordinal": ("lgbm_ordinal", {}), "lgbm_tuned": ("lgbm", best_lgbm)}
    results, predictions = {}, {}
    for key, (_, cls) in ev.BASELINES.items():
        log(f"Đánh giá {MODEL_LABELS[key]}...")
        results[key] = run_cv(cls, X_dev, y_dev, folds, segments, roles)
    for key, (kind, params) in configs.items():
        log(f"Đánh giá {MODEL_LABELS[key]}...")
        results[key], predictions[key] = run_cv(model_factory(kind, params, min_freq, MAIN_GROUPS, seed),
                                                X_dev, y_dev, folds, segments, roles, keep_predictions=True)
    timings["models"] = time.perf_counter() - t0

    best_key = max(configs, key=lambda k: results[k]["cv"]["mean"]["macro_f1"])
    best_kind, best_params = configs[best_key]
    passes = {b: beats_baseline(results[best_key], results[b]) for b in BASELINE_KEYS}

    abl = None
    if ablation:
        t0 = time.perf_counter()
        log(f"Ablation với {MODEL_LABELS[best_key]}...")
        abl = run_ablation(best_kind, best_params, X_dev, y_dev, folds, min_freq, seed, results[best_key], log)
        timings["ablation"] = time.perf_counter() - t0

    preds = predictions[best_key]
    preds.insert(1, "code", s_dev["code"].astype(str).to_numpy())
    report = {
        "params": {"seed": seed, "min_freq": min_freq, "groups": list(MAIN_GROUPS), "dropped_groups": ["flags"],
                   "n_folds": len(set(folds.tolist())), "early_stop_share": 1 / EARLY_STOP_SPLITS,
                   "early_stop_rounds": EARLY_STOP_ROUNDS, "max_rounds": MAX_ROUNDS, "n_trials": n_trials,
                   "logreg_c_grid": list(LOGREG_C_GRID), "tree_depth_grid": list(TREE_DEPTH_GRID),
                   "tree_min_leaf": TREE_MIN_LEAF, "lgbm_defaults": LGBM_DEFAULTS,
                   "lgbm_fixed": {k: v for k, v in LGBM_FIXED.items() if k != "verbose"}},
        "rows": {"dev": int(len(X_dev)), "test_locked": int((split["split"] == "test").sum())},
        "test_fingerprint": ev.fingerprint_test_codes(split),
        "grid_search": {"logreg": grid_lr, "tree": grid_tree},
        "optuna": {"best_params": best_lgbm, **optuna_info},
        "models": results,
        "best": {"key": best_key, "kind": best_kind, "params": best_params, "beats": passes},
        "ablation": abl,
        "timings_seconds": {k: round(v, 1) for k, v in timings.items()},
        "versions": library_versions(),
    }
    return report, (best_kind, best_params), preds


def fit_final_model(X, y, split, kind, params, min_freq=MIN_FREQ, seed=SEED):
    """Fit mô hình tốt nhất trên TOÀN BỘ dev (không dùng test). Bước 9 đo mô hình này trên test đúng một lần."""
    X_dev, y_dev, _ = ev.select_dev(X, y, split)
    return NutriModel(kind, dict(params), min_freq, MAIN_GROUPS, seed).fit(X_dev, y_dev), len(X_dev)


# ======================================================================================
# Báo cáo
# ======================================================================================
_table, _fmt, _mean_std = ev._table, ev._fmt, ev._mean_std


def _delta(v):
    return "—" if v is None else f"{v:+.3f}"


def _params_text(params):
    if not params:
        return "mặc định"
    return ", ".join(f"{k}={round(v, 4) if isinstance(v, float) else v}" for k, v in params.items())


def render_report(r, generated_at):
    prm, models, best = r["params"], r["models"], r["best"]
    keys = list(models)
    names = [MODEL_LABELS[k] for k in keys]
    b_key = best["key"]
    pn = models["pnns_groups_2"]["cv"]["mean"]
    bm = models[b_key]["cv"]["mean"]
    configs = {"logreg": r["grid_search"]["logreg"], "tree": r["grid_search"]["tree"]}
    lines = [
        "# Kết quả mô hình (Bước 8)", "",
        f"- Thời điểm: {generated_at}",
        f"- Chỉ dùng tập dev: **{r['rows']['dev']}** dòng, {prm['n_folds']} fold của Bước 7. Tập test "
        f"({r['rows']['test_locked']} dòng, vân tay `{r['test_fingerprint']}`) **vẫn khóa**: chưa mô hình nào được đo "
        "trên test.",
        f"- Cấu hình đặc trưng chính: `min_freq = {prm['min_freq']}`, các nhóm {', '.join(prm['groups'])}; "
        f"**bỏ nhóm {', '.join(prm['dropped_groups'])}**. Đặc trưng được fit lại trên phần huấn luyện của từng fold.",
        f"- LightGBM dừng sớm trên {prm['early_stop_share']:.0%} số nhóm của phần huấn luyện "
        f"(dừng sau {prm['early_stop_rounds']} vòng không tiến bộ), không dùng fold đang đo.",
        f"- Thời gian chạy (giây): {', '.join(f'{k} {v}' for k, v in r['timings_seconds'].items())}.",
        "", "## 1. So sánh mô hình: 5 fold trên dev (trung bình ± độ lệch chuẩn giữa các fold)", "",
        _table(["Chỉ số"] + names, [[ev.METRIC_LABELS[k][0]] + [_mean_std(models[x]["cv"], k) for x in keys]
                                    for k in ev.METRICS]),
        "", "Log-loss của mô hình hồi quy thứ tự để trống vì mô hình này không cho xác suất từng hạng.",
        "", "## 2. F1 từng hạng (gộp dự đoán ngoài fold)", "",
        _table(["Hạng"] + names, [[g.upper()] + [_fmt(models[x]["cv"]["oof"][f"f1_{g}"]) for x in keys]
                                  for g in GRADES]),
        "", "## 3. Theo quốc gia (dự đoán ngoài fold) và bài kiểm tra giữ lại Pháp (Macro-F1)", "",
        _table(["Mô hình"] + [ev.SEGMENT_LABELS[s] for s in ev.SEGMENT_LABELS] + ["Giữ lại Pháp", "QWK giữ lại Pháp"],
               [[MODEL_LABELS[x]] + [_fmt(models[x]["cv"]["segments"].get(s, {}).get("macro_f1"))
                                     for s in ev.SEGMENT_LABELS]
                + [_fmt(models[x]["holdout"]["macro_f1"]), _fmt(models[x]["holdout"]["qwk"])] for x in keys]),
        "", "## 4. Chọn tham số", "",
        "Lưới nhỏ cho hai mô hình đơn giản (Macro-F1 trung bình 5 fold):", "",
        _table(["Mô hình", "Tham số", "Macro-F1"],
               [[MODEL_LABELS[k], _params_text(g["params"]), _fmt(g["macro_f1"])] for k, rows in configs.items()
                for g in rows]),
        "", f"Optuna cho LightGBM: {prm['n_trials']} lần thử (lần đầu là tham số mặc định), "
        f"{r['optuna']['n_complete']} chạy hết, {r['optuna']['n_pruned']} bị cắt sớm vì kém hơn trung vị. "
        f"Tốt nhất: lần thử {r['optuna']['best_trial']}, Macro-F1 {_fmt(r['optuna']['best_value'])}.", "",
        _table(["Tham số", "Giá trị tốt nhất", "Mặc định"],
               [[k, round(v, 4) if isinstance(v, float) else v, prm["lgbm_defaults"].get(k)]
                for k, v in r["optuna"]["best_params"].items()]),
        "", "Năm lần thử tốt nhất:", "",
        _table(["Lần thử", "Macro-F1", "Số cây trung bình", "Tham số"],
               [[t["number"], _fmt(t["macro_f1"]),
                 "—" if t["mean_best_iteration"] is None else round(t["mean_best_iteration"]),
                 _params_text(t["params"])]
                for t in sorted([t for t in r["optuna"]["trials"] if t["state"] == "COMPLETE"],
                                key=lambda t: -t["macro_f1"])[:5]]),
        "", "Lưu ý: tham số được chọn bằng chính 5 fold này nên Macro-F1 của mô hình đã tinh chỉnh hơi lạc quan. "
        "Con số khách quan sẽ có ở Bước 9 khi đo trên tập test.",
    ]
    abl = r.get("ablation")
    if abl:
        lines += [
            "", f"## 5. Ablation ({MODEL_LABELS[b_key]}, 5 fold dev)", "",
            "Cộng dồn từng nhóm đặc trưng (thứ tự theo kế hoạch):", "",
            _table(["Bậc", "Macro-F1", "Tăng so với bậc trước", "QWK", "Accuracy"],
                   [[s["label"], _mean_std({"mean": s, "std": {"macro_f1": s["macro_f1_std"]}}, "macro_f1"),
                     "—" if i == 0 else _delta(s["macro_f1"] - abl["ladder"][i - 1]["macro_f1"]),
                     _fmt(s["qwk"]), _fmt(s["accuracy"])] for i, s in enumerate(abl["ladder"])]),
            "", "Bỏ từng nhóm khỏi cấu hình chính (Macro-F1 giảm càng nhiều, nhóm càng quan trọng):", "",
            _table(["Nhóm bị bỏ", "Macro-F1", "Thay đổi", "QWK"],
                   [[d["group"], _fmt(d["macro_f1"]), _delta(d["delta_macro_f1"]), _fmt(d["qwk"])]
                    for d in sorted(abl["drop_one"], key=lambda d: d["delta_macro_f1"])]),
            "", "## 6. Hai quyết định đã chốt, đo lại một lần", "",
            _table(["Thay đổi so với cấu hình chính", "Macro-F1", "Thay đổi", "QWK"],
                   [["Cấu hình chính (min_freq = 100, bỏ flags)", _fmt(abl["main"]["macro_f1"]), "—",
                     _fmt(abl["main"]["qwk"])]]
                   + [[s["label"], _fmt(s["macro_f1"]), _delta(s["delta_macro_f1"]), _fmt(s["qwk"])]
                      for s in abl["side_checks"]]),
            "", f"Độ lệch chuẩn Macro-F1 giữa 5 fold của cấu hình chính: {_fmt(abl['main']['macro_f1_std'])}. "
            "Thay đổi nhỏ hơn mức này coi như không khác biệt.",
        ]
    beats = best["beats"]
    lines += [
        "", "## 7. Kết luận", "",
        f"- Mô hình tốt nhất theo Macro-F1: **{MODEL_LABELS[b_key]}** ({_params_text(best['params'])}): Macro-F1 "
        f"{_fmt(bm['macro_f1'])}, QWK {_fmt(bm['qwk'])}, accuracy {_fmt(bm['accuracy'])}.",
        f"- So với đường cơ sở `pnns_groups_2` (Macro-F1 {_fmt(pn['macro_f1'])}, QWK {_fmt(pn['qwk'])}): "
        + ("**vượt cả hai chỉ số**." if all(beats.values()) else "**CHƯA vượt đủ hai chỉ số**, cần xem lại."),
        "- Mô hình này được fit lại trên toàn bộ dev và lưu ở `artifacts/best_model.joblib` (không đẩy lên Git); "
        "dự đoán ngoài fold lưu ở `data/processed/oof_predictions.parquet` cho phân tích lỗi ở Bước 9.",
        f"- Phiên bản thư viện: {', '.join(f'{k} {v}' for k, v in r['versions'].items())}.",
    ]
    return "\n".join(lines) + "\n"


# ======================================================================================
# Dòng lệnh
# ======================================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="Bước 8: huấn luyện và so sánh mô hình trên dev (test vẫn khóa)")
    ap.add_argument("--features", default="data/final/clean_features.parquet")
    ap.add_argument("--labels", default="data/final/clean_labels.parquet")
    ap.add_argument("--split", default="data/final/split.parquet")
    ap.add_argument("--report", default="reports/modeling_results.md")
    ap.add_argument("--model-out", default="artifacts/best_model.joblib")
    ap.add_argument("--oof-out", default="data/processed/oof_predictions.parquet")
    ap.add_argument("--trials", type=int, default=N_TRIALS, help="số lần thử Optuna")
    ap.add_argument("--min-freq", type=int, default=MIN_FREQ)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--no-ablation", action="store_true", help="bỏ qua ablation (chạy nhanh khi thử)")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    for path, hint in ((args.features, "python -m src.cleaning"), (args.labels, "python -m src.cleaning"),
                       (args.split, "python -m src.models.evaluate")):
        if not os.path.isfile(path):
            print(f"Không tìm thấy {path}. Hãy chạy {hint} trước.")
            return 1
    if args.trials < 1:
        print("--trials phải >= 1")
        return 1
    X, y = ev.load_xy(args.features, args.labels)
    split = pd.read_parquet(args.split)

    log = lambda msg: print(msg, flush=True)   # noqa: E731
    start = time.perf_counter()
    report, (kind, params), preds = run_all(X, y, split, n_trials=args.trials, min_freq=args.min_freq,
                                            seed=args.seed, ablation=not args.no_ablation, log=log)
    log("Fit mô hình tốt nhất trên toàn bộ dev...")
    model, n_rows = fit_final_model(X, y, split, kind, params, args.min_freq, args.seed)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["timings_seconds"]["total"] = round(time.perf_counter() - start, 1)

    os.makedirs(os.path.dirname(args.model_out) or ".", exist_ok=True)
    joblib.dump({"model": model, "kind": kind, "params": params, "min_freq": args.min_freq,
                 "groups": list(MAIN_GROUPS), "trained_on": f"dev ({n_rows} dòng), KHÔNG gồm test",
                 "test_fingerprint": report["test_fingerprint"], "n_features": model.n_features_,
                 "cv_mean": report["models"][report["best"]["key"]]["cv"]["mean"],
                 "versions": report["versions"], "created_at": stamp}, args.model_out)
    os.makedirs(os.path.dirname(args.oof_out) or ".", exist_ok=True)
    preds.to_parquet(args.oof_out, index=False)
    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(render_report(report, stamp))
    with open(os.path.splitext(args.report)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump({"generated_at": stamp, **report}, f, ensure_ascii=False, indent=2, default=ev._json_default)

    for key, res in report["models"].items():
        m = res["cv"]["mean"]
        print(f"{MODEL_LABELS[key]:<36} macro-F1 {m['macro_f1']:.3f}  QWK {m['qwk']:.3f}  accuracy {m['accuracy']:.3f}")
    best = report["best"]
    status = "vượt" if all(best["beats"].values()) else "CHƯA vượt"
    print(f"Tốt nhất: {MODEL_LABELS[best['key']]} ({status} cả hai đường cơ sở trên Macro-F1 và QWK)")
    print(f"Đã ghi: {args.report}, {args.model_out}, {args.oof_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
