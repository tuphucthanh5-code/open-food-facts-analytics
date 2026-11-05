"""Cấu hình và dữ liệu giả dùng chung cho các test (không cần mạng, không cần PostgreSQL)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def root():
    return ROOT


def product(**over):
    """Một dòng giống đầu ra của sql/extract_products.sql (có cả nhãn và dinh dưỡng như dữ liệu thật)."""
    row = {
        "row_id": 0, "code": "3017620422003", "product_name": "Pâte  à tartiner", "brands_tags": ["xx:Nutella"],
        "countries_tags": ["en:france", "en:world"], "categories_tags": ["en:spreads", "en:sweet-spreads"],
        "ingredients_tags": ["en:sugar", "en:palm-oil", "en:hazelnut"], "ingredients_analysis_tags": ["en:non-vegan"],
        "additives_tags": ["en:e322"], "allergens_tags": ["en:milk"],
        "labels_tags": ["en:nutriscore-grade-e", "en:green-dot"], "pnns_groups_1": "sugary snacks",
        "pnns_groups_2": "sweets", "ingredients_text": "sucre, huile de palme, noisettes", "ingredients_n": 3.0,
        "ingredients_from_palm_oil_n": 1.0, "additives_n": 1.0, "nova_group": 4.0, "lang": "fr",
        "last_modified": pd.Timestamp("2024-01-01", tz="UTC"), "nutriscore_grade": "e", "nutriscore_score": 26.0,
        "sugars_100g": 56.3, "salt_100g": 0.1,
    }
    row.update(over)
    return row


def frame(*rows):
    """DataFrame từ nhiều dòng product(); row_id đánh lại 0, 1, 2..."""
    return pd.DataFrame([{**r, "row_id": i} for i, r in enumerate(rows)])


def synthetic_products(n=120, seed=0):
    """n sản phẩm giả, mỗi thương hiệu 2 sản phẩm, hạng phụ thuộc vào thành phần (để mô hình học được gì đó)."""
    import random

    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        sweet = i % 2 == 0
        grade = rnd.choice("de") if sweet else rnd.choice("abc")
        ingredients = (["en:sugar", "en:cocoa-butter"] if sweet else ["en:water", "en:carrot"]) + \
            rnd.sample(["en:salt", "en:milk", "en:wheat", "en:egg"], 2)
        rows.append(product(
            code=f"{i:013d}", product_name=f"Sản phẩm {i}", brands_tags=[f"brand{i // 2}"],
            countries_tags=["en:france"] if i % 3 else ["en:united-states"],
            categories_tags=["en:snacks"] if sweet else ["en:vegetables"], ingredients_tags=ingredients,
            labels_tags=["en:organic"] if i % 4 == 0 else [], pnns_groups_2="sweets" if sweet else "vegetables",
            pnns_groups_1="sugary snacks" if sweet else "fruits and vegetables", ingredients_n=4.0,
            nova_group=float(4 if sweet else 1), nutriscore_grade=grade,
            last_modified=pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(days=i)))
    return frame(*rows)


@pytest.fixture
def clean_data():
    """(X, y) đã làm sạch từ 120 sản phẩm giả."""
    from src.cleaning import clean

    X, y, _ = clean(synthetic_products())
    return X, y["nutriscore_grade"].to_numpy(dtype=object)
