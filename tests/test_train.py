"""Kiểm thử Bước 8 (src/models/train.py): mô hình, dừng sớm, ngưỡng thứ tự, Optuna, ablation, dòng lệnh."""
import joblib
import numpy as np
import pandas as pd
import pytest

from src import features as fe
from src.models import evaluate as ev
from src.models import train as tr
from tests.test_evaluate import dataset


@pytest.fixture(scope="module")
def data():
    X, y = dataset()
    return X, y, ev.build_split(X, y)


@pytest.fixture(scope="module")
def dev(data):
    X, y, split = data
    return ev.select_dev(X, y, split)


# --------------------------------------------------------------------------- cấu hình đã chốt
def test_main_config_is_min_freq_100_without_flags():
    assert tr.MIN_FREQ == 100
    assert "flags" not in tr.MAIN_GROUPS
    assert set(tr.MAIN_GROUPS) | {"flags"} == set(fe.FEATURE_GROUPS)


def test_ablation_and_side_checks_use_known_groups():
    for _, groups in tr.ABLATION_LADDER:
        assert set(groups) <= set(fe.FEATURE_GROUPS)
    assert tuple(tr.ABLATION_LADDER[-1][1]) == tr.MAIN_GROUPS
    sizes = [len(g) for _, g in tr.ABLATION_LADDER]
    assert sizes == sorted(sizes)                      # cộng dồn: mỗi bậc thêm nhóm
    labels = {label for label, _, _ in tr.SIDE_CHECKS}
    assert labels == {"min_freq = 20", "Có nhóm flags"}


# --------------------------------------------------------------------------- tập dừng sớm
def test_inner_split_keeps_groups_apart_and_takes_about_a_tenth(dev):
    X, y, _ = dev
    groups = X["group_id"].to_numpy(dtype=object)
    fit_idx, stop_idx = tr.inner_split(y, groups)
    assert len(fit_idx) + len(stop_idx) == len(y)
    assert not set(groups[fit_idx]) & set(groups[stop_idx])
    assert 0.05 <= len(stop_idx) / len(y) <= 0.2


def test_inner_split_is_reproducible(dev):
    X, y, _ = dev
    g = X["group_id"].to_numpy(dtype=object)
    assert np.array_equal(tr.inner_split(y, g)[1], tr.inner_split(y, g)[1])


# --------------------------------------------------------------------------- ngưỡng thứ tự
def test_apply_thresholds_maps_scores_to_grades():
    cuts = [0.5, 1.5, 2.5, 3.5]
    assert tr.apply_thresholds([-1, 0.49, 0.5, 1.7, 3.49, 3.5, 9], cuts).tolist() == [0, 0, 1, 2, 3, 4, 4]


def test_macro_f1_int_matches_sklearn():
    rng = np.random.default_rng(0)
    t, p = rng.integers(0, 5, 300), rng.integers(0, 5, 300)
    p[p == 1] = 2                                      # một hạng không bao giờ được đoán
    expected = ev.compute_metrics(np.array(ev.GRADES)[t], np.array(ev.GRADES)[p])["macro_f1"]
    assert tr.macro_f1_int(t, p) == pytest.approx(expected, abs=1e-4)


def test_optimize_thresholds_beats_rounding_and_stays_increasing():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 5, 2000)
    score = y * 0.6 + 0.3 + rng.normal(0, 0.15, len(y))   # điểm bị "nén": làm tròn thường đoán sai
    cuts = tr.optimize_thresholds(score, y)
    assert np.all(np.diff(cuts) > 0)
    rounded = tr.macro_f1_int(y, tr.apply_thresholds(score, tr.ORDINAL_START))
    assert tr.macro_f1_int(y, tr.apply_thresholds(score, cuts)) > rounded + 0.2


# --------------------------------------------------------------------------- mô hình
@pytest.mark.parametrize("kind", tr.KINDS)
def test_nutri_model_fits_and_predicts_every_kind(dev, kind):
    X, y, _ = dev
    m = tr.NutriModel(kind, min_freq=5).fit(X, y)
    pred = m.predict(X)
    assert len(pred) == len(X) and set(pred) <= set(ev.GRADES)
    assert list(m.classes_) == list(ev.GRADES)
    assert m.n_features_ == len(m.feature_names())
    if kind == "lgbm_ordinal":
        assert not hasattr(m, "predict_proba")         # hồi quy không cho xác suất -> evaluate để trống log-loss
        assert np.all(np.diff(m.core_.cuts_) > 0)
    else:
        p = m.predict_proba(X)
        assert p.shape == (len(X), 5) and np.allclose(p.sum(axis=1), 1)


def test_nutri_model_drops_flags_by_default(dev):
    X, y, _ = dev
    names = tr.NutriModel("logreg", min_freq=5).fit(X, y).feature_names()
    assert not any(fe.feature_group(n) == "flags" for n in names)
    with_flags = tr.NutriModel("logreg", min_freq=5, groups=fe.FEATURE_GROUPS).fit(X, y).feature_names()
    assert any(fe.feature_group(n) == "flags" for n in with_flags)


def test_nutri_model_rejects_unknown_kind(dev):
    X, y, _ = dev
    with pytest.raises(ValueError, match="không tồn tại"):
        tr.NutriModel("svm").fit(X, y)
    with pytest.raises(ValueError, match="không tồn tại"):
        tr.make_core("svm")


def test_lgbm_core_uses_early_stopping(dev):
    X, y, _ = dev
    m = tr.NutriModel("lgbm", min_freq=5).fit(X, y)
    assert 1 <= m.core_.best_iteration_ < tr.MAX_ROUNDS   # nhãn giả không học được -> dừng rất sớm


def test_model_factory_gives_a_new_model_each_call():
    make = tr.model_factory("lgbm", {"num_leaves": 7}, min_freq=5)
    a, b = make(), make()
    assert a is not b and a.params == {"num_leaves": 7} and a.min_freq == 5


def test_nutri_model_works_inside_evaluate(dev):
    X, y, s = dev
    r = ev.evaluate(tr.model_factory("logreg", {"C": 0.1}, min_freq=5), X, y, s["fold"].to_numpy())
    assert r["oof"]["log_loss"] is not None
    r = ev.evaluate(tr.model_factory("lgbm_ordinal", min_freq=5), X, y, s["fold"].to_numpy())
    assert r["oof"]["log_loss"] is None


def test_fold_cache_matches_nutri_model(dev):
    """Đường tắt dùng khi chọn tham số phải cho cùng kết quả với NutriModel trong evaluate()."""
    X, y, s = dev
    folds = s["fold"].to_numpy()
    cache = tr.build_fold_cache(X, y, folds, min_freq=5)
    fast = tr.cv_score_cached("logreg", {"C": 0.3}, cache, y)
    slow = ev.evaluate(tr.model_factory("logreg", {"C": 0.3}, min_freq=5), X, y, folds)["mean"]["macro_f1"]
    assert fast == pytest.approx(slow, abs=1e-3)
    assert [c["fold"] for c in cache] == sorted(set(folds.tolist()))


def test_grid_search_returns_best_params(dev):
    X, y, s = dev
    cache = tr.build_fold_cache(X, y, s["fold"].to_numpy(), min_freq=5)
    best, rows = tr.grid_search("tree", [{"max_depth": 2}, {"max_depth": 4}], cache, y)
    assert best in [r["params"] for r in rows]
    assert max(r["macro_f1"] for r in rows) == next(r["macro_f1"] for r in rows if r["params"] == best)


def test_tune_lgbm_starts_from_defaults_and_is_reproducible(dev):
    X, y, s = dev
    cache = tr.build_fold_cache(X, y, s["fold"].to_numpy(), min_freq=5)
    best, info = tr.tune_lgbm(cache, y, n_trials=3)
    assert info["trials"][0]["params"] == tr.LGBM_DEFAULTS
    assert len(info["trials"]) == 3 and info["n_complete"] + info["n_pruned"] == 3
    assert set(best) == set(tr.LGBM_DEFAULTS)
    lines = []
    best2, _ = tr.tune_lgbm(cache, y, n_trials=3, log=lines.append)
    assert best == best2
    assert len(lines) == 3 and lines[0].startswith("  lần thử 1/3")


def test_beats_baseline_needs_both_metrics():
    base = {"cv": {"mean": {"macro_f1": 0.4, "qwk": 0.5}}}
    assert tr.beats_baseline({"cv": {"mean": {"macro_f1": 0.5, "qwk": 0.6}}}, base)
    assert not tr.beats_baseline({"cv": {"mean": {"macro_f1": 0.5, "qwk": 0.4}}}, base)
    assert not tr.beats_baseline({"cv": {"mean": {"macro_f1": 0.3, "qwk": 0.6}}}, base)


# --------------------------------------------------------------------------- chạy toàn bộ (chỉ dev)
@pytest.fixture(scope="module")
def run(data):
    X, y, split = data
    return tr.run_all(X, y, split, n_trials=2, min_freq=5, ablation=True, log=lambda m: None)


def test_run_all_compares_all_models_and_baselines(run, data):
    report, (kind, params), preds = run
    assert set(report["models"]) == set(tr.MODEL_LABELS)
    assert report["best"]["key"] in {"logreg", "tree", "lgbm", "lgbm_ordinal", "lgbm_tuned"}
    assert kind in tr.KINDS
    assert set(report["best"]["beats"]) == set(tr.BASELINE_KEYS)
    assert report["rows"]["dev"] == int((data[2]["split"] == "dev").sum())


def test_run_all_never_predicts_test_rows(run, data):
    _, _, preds = run
    split = data[2]
    test_codes = set(split.loc[split["split"] == "test", "code"])
    assert not set(preds["code"]) & test_codes
    assert len(preds) == int((split["split"] == "dev").sum())
    assert list(preds.columns[:2]) == ["row_id", "code"]


def test_run_all_never_unlocks_test(data, monkeypatch):
    def locked(*a, **k):
        raise AssertionError("Bước 8 không được gọi select_test")
    monkeypatch.setattr(ev, "select_test", locked)
    X, y, split = data
    tr.run_all(X, y, split, n_trials=1, min_freq=5, ablation=False, log=lambda m: None)


def test_run_all_ablation_tables(run):
    abl = run[0]["ablation"]
    assert [s["label"] for s in abl["ladder"]] == [label for label, _ in tr.ABLATION_LADDER]
    assert [d["group"] for d in abl["drop_one"]] == list(tr.MAIN_GROUPS)
    assert {s["label"] for s in abl["side_checks"]} == {label for label, _, _ in tr.SIDE_CHECKS}
    assert abl["ladder"][-1]["macro_f1"] == abl["main"]["macro_f1"]


def test_render_report_mentions_lock_and_sections(run):
    text = tr.render_report(run[0], "2026-11-05T00:00:00+00:00")
    assert text.startswith("# Kết quả mô hình (Bước 8)")
    assert run[0]["test_fingerprint"] in text and "vẫn khóa" in text
    for heading in ("## 1.", "## 4.", "## 5.", "## 6.", "## 7."):
        assert heading in text


# --------------------------------------------------------------------------- dòng lệnh
@pytest.fixture
def inputs(tmp_path, data):
    X, y, split = data
    fx, fy, fs = tmp_path / "clean_features.parquet", tmp_path / "clean_labels.parquet", tmp_path / "split.parquet"
    X.to_parquet(fx, index=False)
    pd.DataFrame({"row_id": X["row_id"], "code": X["code"], "nutriscore_grade": y}).to_parquet(fy, index=False)
    split.to_parquet(fs, index=False)
    return ["--features", str(fx), "--labels", str(fy), "--split", str(fs),
            "--report", str(tmp_path / "rep" / "modeling_results.md"),
            "--model-out", str(tmp_path / "art" / "best_model.joblib"),
            "--oof-out", str(tmp_path / "proc" / "oof_predictions.parquet"),
            "--trials", "1", "--min-freq", "5", "--no-ablation"]


def test_main_writes_report_model_and_oof(tmp_path, inputs, data):
    assert tr.main(inputs) == 0
    text = (tmp_path / "rep" / "modeling_results.md").read_text(encoding="utf-8")
    assert text.startswith("# Kết quả mô hình")
    assert (tmp_path / "rep" / "modeling_results.json").is_file()
    saved = joblib.load(tmp_path / "art" / "best_model.joblib")
    assert saved["kind"] in tr.KINDS and "KHÔNG gồm test" in saved["trained_on"]
    assert saved["test_fingerprint"] == ev.fingerprint_test_codes(data[2])
    assert set(saved["versions"]) >= {"scikit-learn", "lightgbm"}
    X = data[0]
    assert set(saved["model"].predict(X.head(5))) <= set(ev.GRADES)
    oof = pd.read_parquet(tmp_path / "proc" / "oof_predictions.parquet")
    assert {"row_id", "code", "fold", "y_true", "y_pred"} <= set(oof.columns)


def test_main_needs_split_from_step_7(tmp_path, inputs, capsys):
    args = list(inputs)
    args[args.index("--split") + 1] = str(tmp_path / "none.parquet")
    assert tr.main(args) == 1
    assert "src.models.evaluate" in capsys.readouterr().out


def test_main_rejects_zero_trials(inputs):
    args = list(inputs)
    args[args.index("--trials") + 1] = "0"
    assert tr.main(args) == 1


# --------------------------------------------------------------------------- tài liệu
def test_data_dictionary_documents_oof_columns(root):
    doc = (root / "docs" / "data_dictionary.md").read_text(encoding="utf-8")
    assert "oof_predictions.parquet" in doc
    cols = ["row_id", "code", "fold", "y_true", "y_pred"] + [f"p_{g}" for g in ev.GRADES]
    missing = [c for c in cols if f"`{c}`" not in doc]
    assert not missing, f"data_dictionary.md thiếu: {missing}"
