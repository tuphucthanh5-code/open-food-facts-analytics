"""Chia dữ liệu, khóa test, chỉ số, đánh giá chéo, đường cơ sở, mô hình."""
import numpy as np
import pandas as pd
import pytest
from sklearn.base import BaseEstimator, ClassifierMixin

from src.modeling import (GRADES, CategoryBaseline, check_split, cross_validate, fingerprint, make_model,
                          make_split, metrics, select_dev, select_test)


def test_split_keeps_brands_together(clean_data):
    X, y = clean_data
    split = make_split(X, y)
    assert check_split(split)
    assert set(split["split"]) == {"dev", "test"}
    assert (split.loc[split["split"] == "test", "fold"] == -1).all()
    assert set(split.loc[split["split"] == "dev", "fold"]) == {0, 1, 2, 3, 4}


def test_split_is_reproducible_and_fingerprint_detects_change(clean_data):
    X, y = clean_data
    a, b = make_split(X, y), make_split(X, y)
    assert a.equals(b)
    assert fingerprint(a) == fingerprint(b)
    changed = a.copy()
    changed.loc[changed["split"] == "test", "code"] = changed.loc[changed["split"] == "test", "code"] + "0"
    assert fingerprint(changed) != fingerprint(a)


def test_check_split_rejects_shared_group():
    bad = pd.DataFrame({"group_id": ["g1", "g1"], "split": ["dev", "test"], "fold": [0, -1]})
    with pytest.raises(ValueError):
        check_split(bad)


def test_test_set_is_locked(clean_data):
    X, y = clean_data
    split = make_split(X, y)
    with pytest.raises(PermissionError):
        select_test(X, y, split)
    X_dev, y_dev, s_dev = select_dev(X, y, split)
    X_test, _, _ = select_test(X, y, split, final=True)
    assert len(X_dev) + len(X_test) == len(X)
    assert not set(X_dev["group_id"]) & set(X_test["group_id"])


def test_metrics_perfect_and_ordinal():
    y = list("abcdeabcde")
    perfect = metrics(y, y, np.eye(5)[[GRADES.index(g) for g in y]])
    assert perfect["macro_f1"] == 1.0 and perfect["qwk"] == 1.0 and perfect["roc_auc"] == 1.0
    near = metrics(list("abcde"), list("bcdee"))          # sai lệch 1 hạng
    far = metrics(list("abcde"), list("eeeaa"))           # sai lệch xa
    assert near["within_one"] == 1.0
    assert near["qwk"] > far["qwk"]


class Spy(ClassifierMixin, BaseEstimator):
    """Mô hình giả ghi lại các dòng đã học, để kiểm tra fold đo không lọt vào lúc học."""
    seen = []

    def fit(self, X, y):
        Spy.seen.append(set(X["row_id"]))
        self.classes_ = np.array(GRADES, dtype=object)
        return self

    def predict(self, X):
        return np.full(len(X), "c", dtype=object)

    def predict_proba(self, X):
        return np.tile([0.2] * 5, (len(X), 1))


def test_cross_validate_never_trains_on_eval_fold(clean_data):
    X, y = clean_data
    split = make_split(X, y)
    X_dev, y_dev, s_dev = select_dev(X, y, split)
    Spy.seen = []
    per_fold, pred, proba = cross_validate(Spy, X_dev, y_dev, s_dev["fold"].to_numpy())
    assert len(per_fold) == 5 and len(Spy.seen) == 5               # 5 mô hình mới
    for k, seen in enumerate(Spy.seen):
        assert not seen & set(X_dev.loc[s_dev["fold"] == k, "row_id"])
    assert (pred == "c").all() and proba.shape == (len(X_dev), 5)


def test_category_baseline():
    X = pd.DataFrame({"pnns_groups_2": ["sweets", "sweets", "sweets", "water", None, None]})
    y = np.array(["e", "e", "d", "a", "c", "c"], dtype=object)
    model = CategoryBaseline().fit(X, y)
    new = pd.DataFrame({"pnns_groups_2": ["sweets", "water", None, "never-seen"]})
    # nhóm lạ -> hạng phổ biến nhất chung (c và e cùng 2 lần; hòa thì lấy hạng đứng trước)
    assert list(model.predict(new)) == ["e", "a", "c", "c"]
    assert np.allclose(model.predict_proba(new).sum(axis=1), 1)


@pytest.mark.parametrize("kind", ["majority", "category", "logreg", "tree", "forest", "lgbm"])
def test_every_model_kind_fits(clean_data, kind):
    X, y = clean_data
    params = {"n_estimators": 10} if kind in ("forest", "lgbm") else {}
    model = make_model(kind, min_freq=2, **params).fit(X, y)
    assert set(model.predict(X)) <= set(GRADES)
    assert model.predict_proba(X).shape == (len(X), 5)


def test_unknown_model_kind():
    with pytest.raises(ValueError):
        make_model("svm")


def test_real_split_is_still_locked(root):
    """Tập chia thật (nếu có trên máy) phải còn nguyên: cùng vân tay đã ghi ở Bước 7."""
    path = root / "data" / "final" / "split.parquet"
    if not path.exists():
        pytest.skip("không có data/final/split.parquet trên máy này")
    split = pd.read_parquet(path)
    assert fingerprint(split) == "2e511eab89b680b7"
    assert check_split(split)
