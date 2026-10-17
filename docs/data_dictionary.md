# Từ điển dữ liệu staging

Tạo bởi `python -m src.staging`. Staging không lọc dòng; mỗi bản ghi thô cho đúng một dòng ở mỗi bảng.
Hai bảng ghép với nhau qua `row_id`.

## `data/processed/staging_features.parquet` (đặc trưng hợp lệ cho Phương án A)

| Cột | Kiểu | Nguồn trong JSON thô | Quy tắc |
|---|---|---|---|
| `row_id` | int | thứ tự đọc | khóa ghép với staging_audit |
| `code` | string | `code` | luôn là chuỗi, giữ số 0 đầu |
| `product_name` | string | `product_name` | strip; rỗng thành thiếu |
| `brand` | string | `brands_tags[0]` | thương hiệu đầu tiên; dùng làm nhóm khi chia GroupKFold |
| `brands_tags` | list[string] | `brands_tags` | |
| `countries_tags` | list[string] | `countries_tags` | |
| `categories_tags` | list[string] | `categories_tags` | |
| `pnns_groups_1` | string | `pnns_groups_1` | chữ thường; `unknown` thành thiếu |
| `pnns_groups_2` | string | `pnns_groups_2` | như trên |
| `ingredients_tags` | list[string] | `ingredients_tags` | thiếu giữ là null, rỗng giữ là [] |
| `ingredients_text` | string | `ingredients_text` | |
| `ingredients_n` | Int64 | `ingredients_n` | |
| `ingredients_from_palm_oil_n` | Int64 | `ingredients_from_palm_oil_n` | |
| `ingredients_analysis_tags` | list[string] | `ingredients_analysis_tags` | |
| `additives_tags` | list[string] | `additives_tags` | |
| `additives_n` | Int64 | `additives_n` | |
| `allergens_tags` | list[string] | `allergens_tags` | |
| `labels_tags` | list[string] | `labels_tags` | |
| `nova_group` | Int64 | `nova_group` | chỉ giữ 1-4, ngoài khoảng thành thiếu |
| `lang` | string | `lang` | |
| `last_modified` | datetime (UTC) | `last_modified_t` | giây kể từ 1970 đổi sang datetime |

Bảng này KHÔNG chứa: nhãn Nutri-Score, `nutriments`, `nutrient_levels*`, `misc_tags`, `states_tags`,
`data_quality_tags`, và mọi trường cá nhân (`creator`, `editors_tags`, `last_editor`...).
Hàm `assert_features_are_clean` chặn việc ghi bảng nếu có cột bị cấm.

## `data/processed/staging_audit.parquet` (chỉ để kiểm tra nhãn và EDA)

| Cột | Kiểu | Quy tắc |
|---|---|---|
| `row_id` | int | khóa ghép với staging_features |
| `code` | string | |
| `nutriscore_grade` | string | chuẩn hóa chữ thường, chỉ a-e; giá trị khác thành thiếu |
| `nutriscore_grade_raw` | string | giá trị gốc trước khi chuẩn hóa |
| `energy-kcal_100g` | float | từ `nutriments`; giá trị không phải số hữu hạn thành thiếu |
| `energy-kj_100g` | float | |
| `fat_100g` | float | |
| `saturated-fat_100g` | float | |
| `carbohydrates_100g` | float | |
| `sugars_100g` | float | |
| `fiber_100g` | float | |
| `proteins_100g` | float | |
| `salt_100g` | float | |
| `sodium_100g` | float | |

Ngoài ra bảng có thêm mọi cột `nutriscore_*` khác tìm thấy trong dữ liệu (điểm, phiên bản công thức nếu có).
Staging chưa quy đổi đơn vị và chưa lọc giá trị vô lý: đó là việc của bước cleaning.
