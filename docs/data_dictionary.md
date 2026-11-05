# Từ điển dữ liệu

Luồng dữ liệu và nơi tạo ra từng bảng:

| Bảng / tệp | Tạo bởi | Vào Git? |
|---|---|---|
| `data/raw/raw_products_dump_<thời điểm>.jsonl.gz` | `python -m src.fetch_from_dump` (SQL DuckDB trên `food.parquet`) | không |
| PostgreSQL `raw_products` (raw layer) | `sql/init_raw_db.sql` + `python -m src.load_raw_to_postgres <tệp>` | không |
| `data/processed/products.parquet` | notebook 02, câu SQL `sql/extract_products.sql` | không |
| `data/final/clean_features.parquet`, `clean_labels.parquet` | notebook 04, `src.cleaning.clean` | không |
| `data/final/split.parquet` | Bước 7 (`src.modeling.make_split`), **đã khóa**, notebook 04 chỉ đọc và đối chiếu | không |
| `artifacts/best_model.joblib`, `data/processed/oof_predictions.parquet`, `reports/model_results.json` | notebook 05 | chỉ `reports/model_results.json` |

---

## 1. `raw_products` (PostgreSQL, raw layer)

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `id` | BIGSERIAL | khóa chính, thứ tự nạp |
| `code` | TEXT | mã vạch (chuỗi, giữ số 0 đầu) |
| `retrieved_at` | TIMESTAMPTZ | thời điểm lấy dữ liệu |
| `source_endpoint` | TEXT | nguồn (đường dẫn `food.parquet`) |
| `request_url`, `http_status`, `page` | TEXT, INT, INT | để trống với bản dump (giữ từ thời dùng API) |
| `source_file` | TEXT | tên tệp `.jsonl.gz`; `UNIQUE (code, source_file)` chống nạp trùng |
| `payload` | JSONB | JSON gốc của sản phẩm, không sửa |

`payload` chỉ chứa các trường trong `src.fetch_from_dump.COLUMNS` (không có trường cá nhân), cộng `pnns_groups_1/2`
suy ra từ `food_groups_tags`.

## 2. `data/processed/products.parquet` (bảng phẳng từ SQL, chưa lọc)

Tạo bằng `sql/extract_products.sql`. Một dòng cho mỗi bản ghi của `raw_products`, sắp theo `id`.

| Cột | Kiểu | Lấy từ `payload` | Quy tắc trong SQL |
|---|---|---|---|
| `row_id` | int | — | `row_number() OVER (ORDER BY id) - 1` |
| `code` | string | `code` | `NULLIF(trim(...), '')` |
| `product_name` | string | `product_name` | như trên |
| `brands_tags`, `countries_tags`, `categories_tags`, `ingredients_tags`, `ingredients_analysis_tags`, `additives_tags`, `allergens_tags`, `labels_tags` | list[string] | cùng tên | chỉ nhận mảng JSON, sai kiểu thành NULL |
| `pnns_groups_1`, `pnns_groups_2` | string | cùng tên | chữ thường; `unknown` thành NULL |
| `ingredients_text` | string | cùng tên | `NULLIF(trim(...), '')` |
| `ingredients_n`, `ingredients_from_palm_oil_n`, `additives_n` | float | cùng tên | chỉ nhận giá trị dạng số |
| `nova_group` | int | `nova_group` | chỉ nhận 1-4 |
| `lang` | string | `lang` | chữ thường |
| `last_modified` | timestamp | `last_modified_t` | `to_timestamp(...)` |
| `nutriscore_grade` | string | `nutriscore_grade` | chỉ a-e (nhãn y) |
| `nutriscore_score`, `energy_kcal_100g`, `fat_100g`, `saturated_fat_100g`, `sugars_100g`, `fiber_100g`, `proteins_100g`, `salt_100g` | float | `nutriscore_score`, `nutriments` | **chỉ cho EDA**, cấm làm đặc trưng |

## 3. `data/final/clean_features.parquet` (X, 29.904 × 27, KHÔNG có nhãn)

| Cột | Kiểu | Quy tắc làm sạch (`src/cleaning.py`) |
|---|---|---|
| `row_id` | int | khóa ghép với y và tập chia |
| `code` | string | mã vạch |
| `group_id` | string | nhóm khi chia dữ liệu: `brand:<thương hiệu>`; thiếu thương hiệu thì `name:<tên chuẩn hóa>`; thiếu cả hai thì `code:<mã>` |
| `product_name` | string | gộp khoảng trắng thừa |
| `brand` | string | thương hiệu đầu tiên sau chuẩn hóa |
| `brands_tags` | list | bỏ tiền tố ngôn ngữ, bỏ dấu, chữ thường: `xx:Carrefour` → `carrefour` |
| `countries_tags` | list | bỏ `en:world` |
| `n_countries` | Int64 | số quốc gia sau khi bỏ `en:world` |
| `categories_tags` | list | chữ thường, bỏ trùng; bỏ thẻ lộ đáp án (vd. `fr:nutri score a`) |
| `pnns_groups_1`, `pnns_groups_2` | string | như SQL |
| `ingredients_tags` | list | chữ thường, bỏ trùng, giữ thứ tự (thứ tự = khối lượng giảm dần) |
| `ingredients_text` | string | như SQL |
| `ingredients_n` | Int64 | số âm thành thiếu; thiếu thì lấy số thẻ thành phần |
| `ingredients_from_palm_oil_n`, `additives_n` | Int64 | số âm thành thiếu |
| `ingredients_analysis_tags`, `additives_tags`, `allergens_tags` | list | chữ thường, bỏ trùng |
| `labels_tags` | list | như trên, và **bỏ thẻ lộ đáp án** (logo Nutri-Score, Health Star Rating, Keyhole, "exceso", "alto en"...) |
| `nova_group` | Int64 | 1-4 hoặc thiếu |
| `lang` | string | chữ thường |
| `last_modified` | datetime UTC | dùng để giữ bản mới nhất khi trùng mã |
| `share_ingredients_off_taxonomy` | Float64 | tỷ lệ thẻ thành phần không có tiền tố `en:` |
| `flag_few_ingredients` | bool | `ingredients_n` ≤ 1 (chỉ gắn cờ, không loại) |
| `flag_missing_nova` | bool | thiếu NOVA |
| `flag_missing_brand` | bool | thiếu thương hiệu |

Dòng bị loại (theo thứ tự): nhãn không phải A-E (2), không có thành phần (0), mã vạch hỏng (0), > 150 thành phần (19),
trùng mã vạch (0, giữ bản mới nhất), trùng nội dung thương hiệu + tên + thành phần (75). Không bước nào dựa vào dinh dưỡng.

## 4. `data/final/clean_labels.parquet` (y)

| Cột | Kiểu | Quy tắc |
|---|---|---|
| `row_id` | int | cùng thứ tự với X |
| `code` | string | đối chiếu |
| `nutriscore_grade` | string | a-e |

## 5. `data/final/split.parquet` (tập chia, đã khóa)

| Cột | Kiểu | Quy tắc |
|---|---|---|
| `row_id`, `code`, `group_id` | int, string, string | như X |
| `split` | string | `dev` (80%) / `test` (20%): StratifiedGroupKFold 5 phần theo `group_id`, seed 42, phần đầu là test |
| `fold` | int | 0-4 trong dev (StratifiedGroupKFold 5 fold, seed 42); -1 ở test |
| `country_holdout` | string | bài kiểm tra giữ lại Pháp (chỉ dev): `eval` bán ở Pháp; `train` không bán ở Pháp; `excluded` không bán ở Pháp nhưng cùng nhóm với một dòng `eval`; dòng test là `test` |

Dấu vân tay tập test (16 ký tự đầu SHA-256 của các mã vạch test đã sắp xếp): **`2e511eab89b680b7`**.

## 6. Đặc trưng (`src/features.py`, không lưu ra tệp)

Pipeline `make_features()` nằm bên trong mô hình và chỉ fit trên phần huấn luyện. Tên đặc trưng có dạng
`<phần>__<tên>`, ví dụ `ingredients__en:sugar`, `nova__nova_4`.

| Nhóm | Phần | Cách tạo |
|---|---|---|
| `numeric` | `numeric` | `ingredients_n`, `additives_n`, `ingredients_from_palm_oil_n`, `n_countries`: điền trung vị → log(1+x) → StandardScaler |
| `position` | `position` | `pos_sugar`, `pos_salt`, `pos_fat`: vị trí tương đối của thẻ `en:` đầu tiên chứa từ chỉ đường (sugar, syrup, glucose...), muối (salt), chất béo (oil, fat, butter...); 1 nếu đứng đầu, 0 nếu không có |
| `position` | `first` | multi-hot thành phần đứng đầu |
| `ingredients` | `ingredients` | multi-hot `ingredients_tags` |
| `additives` | `additives` | multi-hot `additives_tags` |
| `categories` | `pnns` | one-hot `pnns_groups_1`, `pnns_groups_2` (thiếu = `missing`) |
| `categories` | `categories` | multi-hot `categories_tags` |
| `nova` | `nova` | one-hot NOVA 1-4 và `missing` |
| `labels` | `labels`, `analysis` | multi-hot `labels_tags`, `ingredients_analysis_tags` |
| `countries` | `countries` | multi-hot `countries_tags` |

Multi-hot (`CountVectorizer(binary=True)`) chỉ giữ thẻ có ở ≥ `min_freq` = 100 sản phẩm của tập fit; khoảng 900 đặc trưng.
Không dùng làm đặc trưng: `row_id`, `code`, `group_id`, `brand`, `brands_tags` (thương hiệu là nhóm chia dữ liệu),
`product_name`, `lang`, `last_modified`, `allergens_tags`, `ingredients_text`, các cờ chất lượng.

## 7. Kết quả notebook 05

### `artifacts/best_model.joblib`
dict gồm: `model` (sklearn Pipeline `features` + `model`, đã học trên toàn bộ dev, nhận thẳng DataFrame
`clean_features`), `name`, `params`, `trained_on`, `cv_dev` (chỉ số trung bình 5 fold), `versions` (phiên bản thư viện).

### `data/processed/oof_predictions.parquet` (dự đoán ngoài fold trên dev)

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `row_id`, `code` | int, string | khóa |
| `fold` | int | fold mà dòng này được dự đoán (mô hình dự đoán không học fold này) |
| `y_true`, `y_pred` | string | hạng thật và hạng dự đoán |
| `p_a` ... `p_e` | float | xác suất từng hạng |

### `reports/model_results.json`
Mô hình tốt nhất, tham số Optuna, bảng so sánh (trung bình và độ lệch chuẩn 5 fold của mọi chỉ số), ablation.
