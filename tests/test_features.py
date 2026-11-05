"""Bước 6b - đặc trưng: chỉ học từ tập fit, không rò rỉ, lưu/nạp được."""
import io

import joblib
import numpy as np
import pandas as pd
import pytest

from src.features import (GROUPS, check_feature_names, feature_names, make_features, relative_position,
                          row_features)


def test_relative_position():
    assert relative_position(["en:sugar", "en:water"], {"sugar"}) == 1.0
    assert relative_position(["en:water", "en:glucose-syrup"], {"syrup"}) == 0.5
    assert relative_position(["en:water"], {"sugar"}) == 0.0
    assert relative_position(["fr:sucre"], {"sugar"}) == 0.0     # chỉ xét thẻ taxonomy en:
    assert relative_position(None, {"sugar"}) == 0.0


def test_row_features_rejects_leaky_columns(clean_data):
    X, _ = clean_data
    with pytest.raises(ValueError):
        row_features(X.assign(sugars_100g=1.0))


def test_missing_nova_and_category_become_own_value(clean_data):
    X, _ = clean_data
    X = X.copy()
    X.loc[0, "nova_group"] = pd.NA
    X.loc[0, "pnns_groups_2"] = None
    rows = row_features(X.head(1))
    assert rows.loc[0, "nova"] == "missing"
    assert rows.loc[0, "pnns_groups_2"] == "missing"


def test_vocabulary_learned_only_from_fit_rows(clean_data):
    X, _ = clean_data
    feat = make_features(min_freq=2).fit(X.head(60))
    names = feature_names(feat)
    assert "ingredients__en:sugar" in names
    new = X.head(3).copy()
    new["ingredients_tags"] = [["en:never-seen-tag"]] * 3
    assert feat.transform(new).shape[1] == len(names)            # thẻ lạ không tạo cột mới
    assert "ingredients__en:never-seen-tag" not in names


def test_min_freq_drops_rare_tags(clean_data):
    X, _ = clean_data
    X = X.copy()
    X.at[0, "ingredients_tags"] = list(X.at[0, "ingredients_tags"]) + ["en:rare-tag"]
    assert "ingredients__en:rare-tag" in feature_names(make_features(min_freq=1).fit(X))
    assert "ingredients__en:rare-tag" not in feature_names(make_features(min_freq=30).fit(X))


def test_groups_select_feature_blocks(clean_data):
    X, _ = clean_data
    names = feature_names(make_features(min_freq=2, groups=("nova", "numeric")).fit(X))
    assert {n.split("__")[0] for n in names} == {"nova", "numeric"}
    assert set(GROUPS) == {"numeric", "position", "ingredients", "additives", "categories", "nova", "labels",
                           "countries"}


def test_numeric_columns_are_standardized(clean_data):
    X, _ = clean_data
    feat = make_features(min_freq=2, groups=("numeric",)).fit(X)
    m = feat.transform(X)
    m = m.toarray() if hasattr(m, "toarray") else np.asarray(m)
    assert np.allclose(m.mean(axis=0), 0, atol=1e-6)


def test_feature_names_clean():
    assert check_feature_names(["ingredients__en:sugar", "labels__en:organic"])
    with pytest.raises(ValueError):
        check_feature_names(["labels__en:nutriscore-grade-a"])
    with pytest.raises(ValueError):
        check_feature_names(["numeric__sugars_100g"])


def test_pipeline_survives_save_and_load(clean_data):
    X, _ = clean_data
    feat = make_features(min_freq=2).fit(X)
    buf = io.BytesIO()
    joblib.dump(feat, buf)
    buf.seek(0)
    again = joblib.load(buf)
    assert (again.transform(X) != feat.transform(X)).nnz == 0
