"""Hàm tạo dữ liệu giả dùng chung cho các test."""


def make_payload(code="3017620422003", grade="c", ingredients=("en:sugar", "en:palm-oil"),
                 nova=4, countries=("en:france",), brand="nutella", lang="fr", **extra):
    """Tạo một sản phẩm giả giống cấu trúc raw_payload của Open Food Facts."""
    p = {
        "code": code,
        "product_name": "Sản phẩm thử",
        "brands_tags": [brand] if brand else [],
        "countries_tags": list(countries),
        "categories_tags": ["en:snacks"],
        "ingredients_tags": list(ingredients) if ingredients is not None else None,
        "ingredients_text": "sugar, palm oil",
        "nova_group": nova,
        "nutriscore_grade": grade,
        "nutriments": {"sugars_100g": 56.3},
        "lang": lang,
        "last_modified_t": 1700000000,
    }
    p.update(extra)
    return p
