# Báo cáo staging

- Thời điểm: 2026-10-23T15:22:35+00:00
- Nguồn: PostgreSQL, bảng raw_products
- Số dòng (không lọc): **30000**
- Có nhãn A-E hợp lệ: 29998
- Có danh sách thành phần: 30000
- Có NOVA hợp lệ: 27079

## Cột của staging_features (đặc trưng hợp lệ)

`row_id`, `code`, `product_name`, `brand`, `brands_tags`, `countries_tags`, `categories_tags`, `pnns_groups_1`, `pnns_groups_2`, `ingredients_tags`, `ingredients_text`, `ingredients_n`, `ingredients_from_palm_oil_n`, `ingredients_analysis_tags`, `additives_tags`, `additives_n`, `allergens_tags`, `labels_tags`, `nova_group`, `lang`, `last_modified`

## Cột của staging_audit (chỉ để kiểm tra nhãn và EDA)

`row_id`, `code`, `nutriscore_grade`, `nutriscore_grade_raw`, `energy-kcal_100g`, `energy-kj_100g`, `fat_100g`, `saturated-fat_100g`, `carbohydrates_100g`, `sugars_100g`, `fiber_100g`, `proteins_100g`, `salt_100g`, `sodium_100g`, `nutriscore_score`

## Tỷ lệ thiếu (%) trong staging_features

| Cột | Thiếu (%) |
|---|---|
| row_id | 0.0 |
| code | 0.0 |
| product_name | 0.7 |
| brand | 14.9 |
| brands_tags | 13.1 |
| countries_tags | 0.0 |
| categories_tags | 0.0 |
| pnns_groups_1 | 19.9 |
| pnns_groups_2 | 20.4 |
| ingredients_tags | 0.0 |
| ingredients_text | 0.0 |
| ingredients_n | 0.0 |
| ingredients_from_palm_oil_n | 25.7 |
| ingredients_analysis_tags | 0.0 |
| additives_tags | 0.0 |
| additives_n | 0.0 |
| allergens_tags | 0.0 |
| labels_tags | 39.6 |
| nova_group | 9.7 |
| lang | 0.0 |
| last_modified | 0.0 |
