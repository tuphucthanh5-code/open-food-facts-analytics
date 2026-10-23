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

---

# Từ điển dữ liệu sau làm sạch (Bước 4)

Tạo bởi `python -m src.cleaning`. Ba tệp có cùng `row_id` (lấy từ staging) và cùng thứ tự dòng.

## `data/final/clean_features.parquet` (X: đặc trưng cho mô hình, KHÔNG có nhãn)

Các cột giữ nguyên tên từ staging nhưng đã chuẩn hóa: `row_id`, `code`, `product_name`, `brand`, `brands_tags`,
`countries_tags`, `categories_tags`, `pnns_groups_1`, `pnns_groups_2`, `ingredients_tags`, `ingredients_text`,
`ingredients_n`, `ingredients_from_palm_oil_n`, `ingredients_analysis_tags`, `additives_tags`, `additives_n`,
`allergens_tags`, `labels_tags`, `nova_group`, `lang`, `last_modified`.

| Cột | Kiểu | Quy tắc làm sạch |
|---|---|---|
| `brand`, `brands_tags` | string, list | bỏ tiền tố ngôn ngữ (`xx:`), bỏ dấu, chữ thường, ký tự lạ thành `-`: `xx:Carrefour` và `xx:carrefour` đều thành `carrefour` |
| `product_name` | string | gộp khoảng trắng thừa |
| `countries_tags` | list[string] | bỏ `en:world` (không phải quốc gia); giữ đủ 162 quốc gia |
| các cột `*_tags` khác | list[string] | strip, chữ thường, bỏ rỗng, bỏ trùng, giữ thứ tự |
| `labels_tags` | list[string] | như trên, và bỏ thẻ rò rỉ nhãn (logo Nutri-Score, Health Star Rating, Keyhole, nhãn cảnh báo "exceso"/"alto en"); giữ lời quảng cáo về một chất như `en:low-fat` |
| `ingredients_n`, `additives_n`, `ingredients_from_palm_oil_n` | Int64 | số âm thành thiếu; `ingredients_n` thiếu thì lấy số thẻ thành phần |
| `lang` | string | chữ thường |
| `group_id` | string | nhóm cho GroupKFold: `brand:<thương hiệu>`; nếu thiếu thương hiệu thì `name:<tên chuẩn hóa>`; nếu thiếu cả hai thì `code:<mã vạch>` |
| `n_countries` | Int64 | số quốc gia sau khi bỏ `en:world` (0 = không rõ) |
| `share_ingredients_off_taxonomy` | Float64 | tỷ lệ thẻ thành phần không có tiền tố `en:` |
| `flag_few_ingredients` | bool | `ingredients_n` ≤ 1 (giữ lại vì mật ong, dầu ăn... là hợp lệ) |
| `flag_missing_nova` | bool | không có `nova_group` hợp lệ |
| `flag_missing_brand` | bool | không có thương hiệu |

## `data/final/clean_labels.parquet` (y)

| Cột | Kiểu | Quy tắc |
|---|---|---|
| `row_id` | int | khóa ghép với clean_features |
| `code` | string | để đối chiếu |
| `nutriscore_grade` | string | chỉ a-e |

## `data/processed/clean_audit.parquet`

Các cột của `staging_audit`, chỉ cho những dòng được giữ lại. Chỉ dùng cho EDA và kiểm tra nhãn, không bao giờ làm đặc trưng.

## Các dòng bị loại (thứ tự trong phễu)

1. Nhãn không phải A-E. 2. Không có `ingredients_tags`. 3. Mã vạch thiếu hoặc có ký tự không phải số.
4. `ingredients_n` > 150 (tham số `--max-ingredients`). 5. Trùng mã vạch: giữ bản có `last_modified` mới nhất.
6. Trùng nội dung (cùng thương hiệu + tên chuẩn hóa + danh sách thành phần): giữ bản mới nhất.

Không bước nào dựa vào bảng dinh dưỡng hay điểm Nutri-Score.
