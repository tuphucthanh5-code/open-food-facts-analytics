"""Kiểm thử Bước 7 (src/models/evaluate.py): chia dữ liệu, khóa test, chỉ số, evaluate(), đường cơ sở, dòng lệnh."""
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from src import features as fe
from src.models import evaluate as ev
from tests.test_features import crow, frame

COUNTRIES = (["en:france"], ["en:united-states"], ["en:spain"])
PNNS2 = ("sweets", "cheese", "beverages", "meat")


def dataset(n_groups=40, per_group=5):
    """Dữ liệu giả: mỗi nhóm một quốc gia và một pnns_groups_2; nhóm chia hết cho 6 có thêm một sản phẩm Tây Ban Nha."""
    rows, y = [], []
    for gi in range(n_groups):
        for j in range(per_group):
            country = ["en:spain"] if (gi % 6 == 0 and j == 0) else COUNTRIES[gi % 3]
            rows.append(crow(code=f"{100000 + len(rows)}", group_id=f"brand:b{gi}", countries_tags=country,
                             pnns_groups_2=PNNS2[gi % 4]))
            y.append(ev.GRADES[(gi + j) % 5])
    return frame(rows), np.array(y, dtype=object)


@pytest.fixture(scope="module")
def data():
    X, y = dataset()
    return X, y, ev.build_split(X, y)


# --------------------------------------------------------------------------- đọc dữ liệu
def test_grade_to_int_is_ordered_and_rejects_unknown():
    assert ev.grade_to_int(["a", "c", "e"]).tolist() == [0, 2, 4]
    with pytest.raises(ValueError, match="Hạng không hợp lệ"):
        ev.grade_to_int(["a", "z"])


def test_check_alignment_rejects_shifted_rows_and_bad_labels():
    X = pd.DataFrame({"row_id": [0, 1, 2]})
    ok = pd.DataFrame({"row_id": [0, 1, 2], "nutriscore_grade": ["a", "b", "e"]})
    ev.check_alignment(X, ok)
    with pytest.raises(ValueError, match="lệch row_id"):
        ev.check_alignment(X, ok.iloc[[1, 0, 2]])
    with pytest.raises(ValueError, match="ngoài a-e"):
        ev.check_alignment(X, ok.assign(nutriscore_grade=["a", "x", "e"]))


def test_load_xy_reads_aligned_parquet(tmp_path, data):
    X, y, _ = data
    X.to_parquet(tmp_path / "x.parquet", index=False)
    pd.DataFrame({"row_id": X["row_id"], "code": X["code"], "nutriscore_grade": y}).to_parquet(
        tmp_path / "y.parquet", index=False)
    X2, y2 = ev.load_xy(tmp_path / "x.parquet", tmp_path / "y.parquet")
    assert len(X2) == len(X)
    assert y2.tolist() == y.tolist()


# --------------------------------------------------------------------------- chia dữ liệu
def test_split_has_expected_shape_and_passes_checks(data):
    X, y, split = data
    assert list(split.columns) == ev.SPLIT_COLUMNS
    ev.assert_split_valid(split)
    share = (split["split"] == "test").mean()
    assert 0.1 <= share <= 0.3
    assert set(split.loc[split["split"] == "test", "fold"]) == {-1}
    assert set(split.loc[split["split"] == "dev", "fold"]) == set(range(ev.N_FOLDS))
    assert set(split.loc[split["split"] == "test", "country_holdout"]) == {"test"}


def test_no_group_crosses_dev_test_or_folds(data):
    _, _, split = data
    per_group = split.groupby("group_id").agg(splits=("split", "nunique"), folds=("fold", "nunique"))
    assert (per_group["splits"] == 1).all()
    assert (per_group["folds"] == 1).all()


def test_split_is_reproducible_and_depends_on_seed(data):
    X, y, split = data
    assert ev.same_split(split, ev.build_split(X, y))
    other = ev.build_split(X, y, seed=7)
    assert ev.fingerprint_test_codes(other) != ev.fingerprint_test_codes(split)


def test_test_split_keeps_grade_balance():
    X, y = dataset(n_groups=100, per_group=5)
    split = ev.build_split(X, y)
    test = (split["split"] == "test").to_numpy()
    full = pd.Series(y).value_counts(normalize=True)
    part = pd.Series(y[test]).value_counts(normalize=True)
    assert (part - full).abs().max() < 0.05


def test_country_holdout_roles_excludes_same_brand_outside_country():
    countries = [["en:france"], ["en:spain"], ["en:spain"], ["en:france", "en:belgium"], None]
    groups = ["brand:x", "brand:x", "brand:y", "brand:z", "name:w"]
    roles = ev.country_holdout_roles(countries, groups, "en:france")
    assert roles.tolist() == ["eval", "excluded", "train", "eval", "train"]


def test_split_country_roles_never_share_a_group(data):
    _, _, split = data
    dev = split[split["split"] == "dev"]
    assert set(dev["country_holdout"]) <= set(ev.HOLDOUT_ROLES)
    train = set(dev.loc[dev["country_holdout"] == "train", "group_id"])
    evalg = set(dev.loc[dev["country_holdout"] == "eval", "group_id"])
    assert not train & evalg
    assert (dev["country_holdout"] == "excluded").any()     # nhóm b0, b6... có hàng Tây Ban Nha cùng thương hiệu Pháp


@pytest.mark.parametrize("breaker, message", [
    (lambda s: s.assign(split=np.where(s.index == s.index[s["split"] == "dev"][0], "test", s["split"])),
     "không được có fold"),
    (lambda s: s.assign(fold=np.where(s.index == s.index[s["split"] == "dev"][0], 9, s["fold"])), "fold 0.."),
    (lambda s: s.assign(country_holdout=s["country_holdout"].replace({"excluded": "train"})), "train và eval"),
    (lambda s: s.assign(row_id=0), "row_id bị trùng"),
])
def test_assert_split_valid_catches_broken_splits(data, breaker, message):
    _, _, split = data
    with pytest.raises(ValueError, match=message):
        ev.assert_split_valid(breaker(split.copy()))


def test_assert_split_valid_catches_group_on_both_sides(data):
    _, _, split = data
    s = split.copy()
    test_group = s.loc[s["split"] == "test", "group_id"].iloc[0]
    first_dev = s.index[s["split"] == "dev"][0]
    s.loc[first_dev, "group_id"] = test_group
    with pytest.raises(ValueError, match="cả dev và test"):
        ev.assert_split_valid(s)


def test_fingerprint_ignores_row_order_but_not_content(data):
    _, _, split = data
    fp = ev.fingerprint_test_codes(split)
    assert ev.fingerprint_test_codes(split.iloc[::-1]) == fp
    s = split.copy()
    s.loc[s.index[s["split"] == "test"][0], "code"] = "999999999"
    assert ev.fingerprint_test_codes(s) != fp


def test_same_split_detects_any_change(data):
    _, _, split = data
    assert ev.same_split(split, split.copy())
    changed = split.copy()
    changed.loc[changed.index[0], "fold"] = 3 if changed.loc[changed.index[0], "fold"] != 3 else 2
    assert not ev.same_split(split, changed)
    assert not ev.same_split(split, split.drop(columns="fold"))


def test_select_dev_hides_test_and_select_test_is_locked(data):
    X, y, split = data
    X_dev, y_dev, s_dev = ev.select_dev(X, y, split)
    assert set(s_dev["split"]) == {"dev"}
    assert len(X_dev) == len(y_dev) == int((split["split"] == "dev").sum())
    assert not set(X_dev["code"]) & set(split.loc[split["split"] == "test", "code"])
    with pytest.raises(PermissionError, match="khóa"):
        ev.select_test(X, y, split)
    X_te, y_te, s_te = ev.select_test(X, y, split, final=True)
    assert set(s_te["split"]) == {"test"}
    assert len(X_te) + len(X_dev) == len(X)


def test_select_dev_rejects_split_from_other_data(data):
    X, y, split = data
    with pytest.raises(ValueError, match="không khớp"):
        ev.select_dev(X.iloc[1:], y[1:], split)


# --------------------------------------------------------------------------- chỉ số
def test_compute_metrics_perfect_prediction():
    y = ["a", "b", "c", "d", "e"]
    m = ev.compute_metrics(y, y, np.eye(5))
    assert m["macro_f1"] == m["accuracy"] == m["qwk"] == m["within_one"] == 1.0
    assert m["mae"] == 0.0
    assert m["log_loss"] < 0.01


def test_compute_metrics_known_values_and_order():
    y = ["a", "b", "c", "d", "e"]
    m = ev.compute_metrics(y, ["a", "a", "c", "e", "e"])
    assert m["accuracy"] == 0.6
    assert m["mae"] == 0.4
    assert m["within_one"] == 1.0
    assert m["log_loss"] is None
    near = ev.compute_metrics(["a"] * 5 + ["e"] * 5, ["b"] * 5 + ["d"] * 5)
    far = ev.compute_metrics(["a"] * 5 + ["e"] * 5, ["e"] * 5 + ["a"] * 5)
    assert near["accuracy"] == far["accuracy"] == 0.0
    assert near["qwk"] > far["qwk"]          # QWK phạt đoán lệch xa nặng hơn
    assert near["mae"] < far["mae"]


def test_compute_metrics_counts_classes_never_predicted():
    m = ev.compute_metrics(["a", "b", "e", "e"], ["e", "e", "e", "e"])
    assert m["f1_a"] == m["f1_b"] == 0.0
    assert m["macro_f1"] == pytest.approx(m["f1_e"] / 5, abs=1e-3)


def test_predict_proba_grades_reorders_columns():
    class Fake:
        classes_ = np.array(["e", "a"], dtype=object)

        def predict_proba(self, X):
            return np.array([[0.9, 0.1]] * len(X))
    out = ev.predict_proba_grades(Fake(), [0, 0])
    assert out.shape == (2, 5)
    assert out[0].tolist() == [0.1, 0.0, 0.0, 0.0, 0.9]
    assert ev.predict_proba_grades(object(), [0]) is None


def test_country_segments():
    seg = ev.country_segments([["en:france"], ["en:united-states", "en:france"], ["en:spain"], None])
    assert seg["france"].tolist() == [True, True, False, False]
    assert seg["united_states"].tolist() == [False, True, False, False]
    assert seg["other"].tolist() == [False, False, True, True]


# --------------------------------------------------------------------------- đường cơ sở
def test_majority_baseline():
    m = ev.MajorityClassBaseline().fit(None, ["e", "e", "a", "c"])
    assert m.predict([0, 0, 0]).tolist() == ["e", "e", "e"]
    p = m.predict_proba([0])
    assert p.shape == (1, 5)
    assert p.sum() == pytest.approx(1.0)
    assert p[0, ev.GRADE_INDEX["e"]] == 0.5


def test_category_baseline_learns_group_grade_missing_and_unseen():
    X = pd.DataFrame({"pnns_groups_2": ["Sweets", "sweets", "sweets", "cheese", None, None, "cheese"]})
    y = ["e", "e", "d", "d", "b", "b", "d"]
    m = ev.CategoryMajorityBaseline().fit(X, y)
    new = pd.DataFrame({"pnns_groups_2": ["sweets", "cheese", None, "fish and seafood"]})
    assert m.predict(new).tolist() == ["e", "d", "b", m.default_]
    p = m.predict_proba(new)
    assert np.allclose(p.sum(axis=1), 1.0)
    seen = [ev.GRADE_INDEX[g] for g in "bde"]
    assert (p[:, seen] > 0).all()             # làm trơn: hạng có trong train không bao giờ có xác suất 0
    assert p[0].argmax() == ev.GRADE_INDEX["e"]


def test_category_baseline_breaks_ties_by_overall_frequency():
    X = pd.DataFrame({"pnns_groups_2": ["x", "x", "y", "y", "y"]})
    m = ev.CategoryMajorityBaseline().fit(X, ["a", "e", "e", "e", "c"])
    assert m.predict(pd.DataFrame({"pnns_groups_2": ["x"]})).tolist() == ["e"]


# --------------------------------------------------------------------------- evaluate()
def test_evaluate_returns_one_out_of_fold_prediction_per_row(data):
    X, y, split = data
    X_dev, y_dev, s_dev = ev.select_dev(X, y, split)
    r = ev.evaluate(ev.CategoryMajorityBaseline, X_dev, y_dev, s_dev["fold"],
                    segments=ev.country_segments(X_dev["countries_tags"]))
    assert len(r["folds"]) == ev.N_FOLDS
    assert sum(f["n_eval"] for f in r["folds"]) == len(X_dev)
    preds = r["predictions"]
    assert len(preds) == len(X_dev) and preds["y_pred"].notna().all()
    assert preds["row_id"].tolist() == X_dev["row_id"].tolist()
    assert np.allclose(preds[[f"p_{g}" for g in ev.GRADES]].sum(axis=1), 1.0)
    assert set(r["mean"]) == set(ev.METRICS + ev.CLASS_METRICS)
    assert set(r["segments"]) == {"france", "united_states", "other"}


def test_evaluate_fits_a_new_model_on_training_rows_only(data):
    X, y, split = data
    X_dev, y_dev, s_dev = ev.select_dev(X, y, split)
    seen = []

    class Spy(ev.MajorityClassBaseline):
        def fit(self, X, y):
            seen.append(set(X["row_id"]))
            return super().fit(X, y)

    ev.evaluate(Spy, X_dev, y_dev, s_dev["fold"])
    assert len(seen) == ev.N_FOLDS
    for k, train_rows in enumerate(seen):
        eval_rows = set(X_dev.loc[s_dev["fold"] == k, "row_id"])
        assert not train_rows & eval_rows


def test_evaluate_works_with_feature_pipeline_and_classifier(data):
    """Giao diện dùng ở Bước 8: Pipeline(đặc trưng Bước 6, bộ phân loại), fit lại trong từng fold."""
    X, y, split = data
    X_dev, y_dev, s_dev = ev.select_dev(X, y, split)

    def make():
        return Pipeline([("features", fe.build_feature_pipeline(min_freq=1)),
                         ("clf", LogisticRegression(max_iter=200, class_weight="balanced"))])
    r = ev.evaluate(make, X_dev, y_dev, s_dev["fold"])
    assert r["oof"]["log_loss"] is not None
    assert 0.0 <= r["oof"]["macro_f1"] <= 1.0


def test_evaluate_without_predict_proba_has_no_log_loss(data):
    X, y, split = data
    X_dev, y_dev, s_dev = ev.select_dev(X, y, split)

    class NoProba:
        def fit(self, X, y):
            self.g = pd.Series(y).mode()[0]
            return self

        def predict(self, X):
            return np.full(len(X), self.g, dtype=object)
    r = ev.evaluate(NoProba, X_dev, y_dev, s_dev["fold"])
    assert r["oof"]["log_loss"] is None and r["mean"]["log_loss"] is None
    assert "p_a" not in r["predictions"].columns


def test_evaluate_rejects_bad_inputs(data):
    X, y, _ = data
    with pytest.raises(ValueError, match="cùng số dòng"):
        ev.evaluate(ev.MajorityClassBaseline, X, y[:-1], np.zeros(len(X)))
    with pytest.raises(ValueError, match="ít nhất 2 fold"):
        ev.evaluate(ev.MajorityClassBaseline, X, y, np.zeros(len(X)))


def test_evaluate_holdout(data):
    X, y, split = data
    X_dev, y_dev, s_dev = ev.select_dev(X, y, split)
    roles = s_dev["country_holdout"].to_numpy()
    r = ev.evaluate_holdout(ev.CategoryMajorityBaseline, X_dev, y_dev, roles == "train", roles == "eval")
    assert r["n_train"] == int((roles == "train").sum())
    assert r["n_eval"] == int((roles == "eval").sum())
    with pytest.raises(ValueError, match="rỗng"):
        ev.evaluate_holdout(ev.MajorityClassBaseline, X_dev, y_dev, roles == "nope", roles == "eval")


# --------------------------------------------------------------------------- dòng lệnh
@pytest.fixture
def inputs(tmp_path, data):
    X, y, _ = data
    fx, fy = tmp_path / "clean_features.parquet", tmp_path / "clean_labels.parquet"
    X.to_parquet(fx, index=False)
    pd.DataFrame({"row_id": X["row_id"], "code": X["code"], "nutriscore_grade": y}).to_parquet(fy, index=False)
    return ["--features", str(fx), "--labels", str(fy), "--split-out", str(tmp_path / "final" / "split.parquet"),
            "--report", str(tmp_path / "rep" / "evaluation_setup.md")]


def test_main_writes_split_and_report(tmp_path, inputs, data):
    assert ev.main(inputs) == 0
    split = pd.read_parquet(tmp_path / "final" / "split.parquet")
    assert ev.same_split(split, data[2])
    text = (tmp_path / "rep" / "evaluation_setup.md").read_text(encoding="utf-8")
    assert text.startswith("# Thiết lập đánh giá")
    assert ev.fingerprint_test_codes(split) in text
    assert (tmp_path / "rep" / "evaluation_setup.json").is_file()


def test_main_rerun_keeps_locked_split(tmp_path, inputs, capsys):
    assert ev.main(inputs) == 0
    assert ev.main(inputs) == 0
    assert "tập test không đổi" in capsys.readouterr().out


def test_main_refuses_to_overwrite_a_different_split(tmp_path, inputs, data, capsys):
    path = tmp_path / "final" / "split.parquet"
    assert ev.main(inputs) == 0
    tampered = pd.read_parquet(path)
    tampered.loc[tampered.index[0], "fold"] = 4 if tampered.loc[tampered.index[0], "fold"] != 4 else 3
    tampered.to_parquet(path, index=False)
    assert ev.main(inputs) == 1
    assert "Không ghi đè" in capsys.readouterr().out
    assert ev.same_split(pd.read_parquet(path), tampered)
    assert ev.main(inputs + ["--overwrite-split"]) == 0
    assert ev.same_split(pd.read_parquet(path), data[2])


def test_main_returns_1_when_input_missing(tmp_path):
    assert ev.main(["--features", str(tmp_path / "none.parquet"), "--labels", str(tmp_path / "none2.parquet")]) == 1


# --------------------------------------------------------------------------- tài liệu
def test_data_dictionary_documents_split_columns(root):
    doc = (root / "docs" / "data_dictionary.md").read_text(encoding="utf-8")
    assert "split.parquet" in doc
    missing = [c for c in ev.SPLIT_COLUMNS + list(ev.HOLDOUT_ROLES) if f"`{c}`" not in doc]
    assert not missing, f"data_dictionary.md thiếu: {missing}"
