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
| `categories_tags` | list[string] | như trên, và bỏ thẻ rò rỉ cùng mẫu với `labels_tags` (vd. thẻ tự gõ `fr:nutri score a`) |
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

---

# Từ điển đặc trưng (Bước 6)

Tạo bởi `src/features.py`. Không lưu ma trận ra tệp: `build_feature_pipeline` trả về một sklearn Pipeline nhận
`clean_features.parquet` và trả về ma trận thưa; ở Bước 7-8 pipeline chỉ được fit trên tập huấn luyện của từng fold.
`python -m src.features` chỉ ghi báo cáo mô tả `reports/features_report.md` và danh sách tên `reports/feature_names.txt`.

Tên đặc trưng có dạng `<nhóm>-<phần>__<tên>`, ví dụ `ingredients__en:sugar`, `categories-pnns__pnns_groups_1_filled_beverages`.
Nhóm (để bật/tắt khi làm ablation): `numeric`, `position`, `ingredients`, `additives`, `categories`, `nova`, `labels`,
`countries`, `flags`.

## Cột trung gian do `RowFeatures` tạo (tính từ riêng từng dòng, không học từ dữ liệu)

| Cột | Nhóm | Quy tắc |
|---|---|---|
| `n_allergens` | numeric | số thẻ trong `allergens_tags` |
| `ingredients_text_len` | numeric | số ký tự của `ingredients_text` |
| `n_ingredients_with_percent` | numeric | số tỷ lệ phần trăm ghi trong chữ thành phần (`70 %`, `12,5%`) |
| `has_palm_oil` | numeric | 1 nếu `ingredients_from_palm_oil_n` > 0 hoặc có thẻ dầu/mỡ cọ (`en:palm-oil`, `en:palm-kernel-fat`...) |
| `pos_sugar`, `pos_salt`, `pos_fat` | position | vị trí tương đối của thẻ đầu tiên là đường / muối / chất béo trong `ingredients_tags`: 1 nếu đứng đầu, giảm dần về 0 ở cuối, 0 nếu không có. Nhận diện theo từ trong thẻ `en:` (sugar, syrup, glucose...; salt; oil, fat, butter...), bỏ thẻ phủ định như `en:fat-reduced-cocoa`, `en:no-added-sugar` |
| `first_ingredient` | position | danh sách chỉ gồm thẻ thành phần đầu tiên (thành phần nhiều nhất theo khối lượng) |
| `add_colours`, `add_preservatives`, `add_antioxidants_acids`, `add_thickeners_emulsifiers`, `add_acidity_anticaking`, `add_flavour_enhancers`, `add_sweeteners`, `add_other` | additives | số phụ gia theo nhóm số E: 1xx tạo màu, 2xx bảo quản, 3xx chống oxy hóa/axit, 4xx làm dày/nhũ hóa, 5xx điều chỉnh axit/chống đông vón, 6xx điều vị; chất tạo ngọt (E420, E421, E950-E969) tách riêng. `en:e322` và `en:e322i` chỉ tính một lần |
| `is_beverage`, `is_fat_oil_nut_seed`, `is_cheese` | categories | có `en:beverages` / thuộc nhóm chất béo, dầu, hạt (như Bước 4) / có `en:cheeses` trong `categories_tags` |
| `pnns_groups_2_filled` | categories | `pnns_groups_2` chữ thường; thiếu thành `missing` |
| `nova_1`, `nova_2`, `nova_3`, `nova_4`, `nova_missing` | nova | one-hot của `nova_group`; ngoài 1-4 hoặc thiếu thành `nova_missing` = 1. Thay cho `flag_missing_nova` |
| `is_organic` | labels | có nhãn hữu cơ (`en:organic`, `en:eu-organic`, mã `xx-bio-nn`, `fr:ab-agriculture-biologique`) |

## Cột do `CategoryGroupImputer` tạo (học từ tập huấn luyện)

| Cột | Nhóm | Quy tắc |
|---|---|---|
| `pnns_groups_1_filled` | categories | `pnns_groups_1` gốc (gộp `alcoholic beverages` vào `beverages`); nếu thiếu thì lấy nhóm phổ biến nhất của thẻ danh mục thuần nhất mà sản phẩm có (thẻ có ở ≥ 5 sản phẩm đã biết nhóm, nhóm chiếm > 50%); không đủ căn cứ thì `missing` |
| `pnns_groups_1_imputed` | flags | 1 nếu `pnns_groups_1_filled` là nhóm bổ sung, 0 nếu là nhóm gốc hoặc `missing` |

## Đặc trưng đưa vào mô hình

| Nhóm | Đặc trưng | Biến đổi (fit trên tập huấn luyện) |
|---|---|---|
| `numeric` | `ingredients_n`, `additives_n`, `ingredients_from_palm_oil_n`, `n_allergens`, `ingredients_text_len`, `n_ingredients_with_percent`; `has_palm_oil` | điền trung vị -> log(1 + x) -> chuẩn hóa; cờ để nguyên |
| `position` | `pos_sugar`, `pos_salt`, `pos_fat`; multi-hot `first_ingredient` | để nguyên; thẻ đầu tiên phải có ở ≥ `min_freq` sản phẩm |
| `ingredients` | multi-hot `ingredients_tags` + `n_rare` | giữ thẻ có ở ≥ `min_freq` sản phẩm; `n_rare` = log(1 + số thẻ không được giữ, kể cả thẻ chưa gặp) |
| `additives` | multi-hot `additives_tags` + `n_rare`; 8 cột `add_*` | như trên; số đếm theo nhóm: điền trung vị -> log(1 + x) -> chuẩn hóa |
| `categories` | one-hot `pnns_groups_1_filled`, `pnns_groups_2_filled`; multi-hot `categories_tags` + `n_rare`; `is_beverage`, `is_fat_oil_nut_seed`, `is_cheese` | nhóm chưa gặp lúc fit thành toàn 0 |
| `nova` | `nova_1` ... `nova_4`, `nova_missing` | để nguyên |
| `labels` | multi-hot `labels_tags` + `n_rare`; multi-hot `ingredients_analysis_tags` (thuần chay, chay, dầu cọ); `is_organic` | ngưỡng `min_freq` |
| `countries` | multi-hot `countries_tags` + `n_rare`; `n_countries` | ngưỡng `min_freq`; số quốc gia: log(1 + x) -> chuẩn hóa |
| `flags` | `flag_few_ingredients`, `flag_missing_brand`, `share_ingredients_off_taxonomy`, `pnns_groups_1_imputed` | để nguyên |

`min_freq` mặc định là 100 cho mọi cột danh sách thẻ (thử thêm 20; chốt ở Bước 8).
Không dùng làm đặc trưng: `row_id`, `code`, `group_id` (chỉ để chia dữ liệu), `brand`, `brands_tags` (thương hiệu là
nhóm GroupKFold nên thương hiệu ở tập kiểm tra không có trong tập huấn luyện), `product_name`, `lang`, `last_modified`,
`flag_missing_nova` (trùng `nova_missing`).
