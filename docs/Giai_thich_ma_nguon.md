# Giải thích mã nguồn (tài liệu học để thuyết trình và "code lại trước hội đồng")

Mã đã được rút gọn ngày 05/11/2026 theo quy trình 9 bước của giảng viên: **notebook là sản phẩm chính**, `src/` chỉ
giữ những hàm dùng lại nhiều lần. Toàn bộ mã Python còn 717 dòng (trước đó 3.719 dòng), cộng 187 dòng SQL.
Đọc theo thứ tự: mục 1 (bức tranh), mục 2 (SQL), mục 3-7 (từng tệp `src/`), mục 8 (notebook), mục 9 (câu hỏi hay gặp),
mục 10 (gõ lại nhanh những hàm quan trọng nhất). Notebook 06 (đánh giá cuối trên tập test) ở mục 8.

---

## 1. Bức tranh tổng thể

```text
food.parquet (8 GB)  ──DuckDB SQL──►  data/raw/*.jsonl.gz  ──INSERT──►  PostgreSQL raw_products (JSONB)
   src/fetch_from_dump.py                          src/load_raw_to_postgres.py
                                                                            │ sql/extract_products.sql (notebook 02)
                                                                            ▼
                                                        data/processed/products.parquet (30.000 × 29)
                                                                            │ src/cleaning.py (notebook 04)
                                                                            ▼
                                  data/final/clean_features.parquet (X 29.904 × 27) + clean_labels.parquet (y)
                                                                            │ src/modeling.make_split (đã khóa)
                                                                            ▼
                                  data/final/split.parquet: dev 23.922 (5 fold) | test 5.982 (KHÓA)
                                                                            │ src/features.py + src/modeling.py (notebook 05)
                                                                            ▼
                                  artifacts/best_model.joblib, oof_predictions.parquet, reports/model_results.json
                                                                            │ notebook 06: mở test MỘT lần (select_test final=True)
                                                                            ▼
                                  test_predictions.parquet, reports/test_results.json (kết quả khách quan)
```

Hai ý quyết định cả thiết kế (hội đồng hay hỏi):
1. **Chống rò rỉ nhãn.** Hạng Nutri-Score được *tính từ* bảng dinh dưỡng, nên dinh dưỡng, điểm, và các thẻ in logo
   Nutri-Score trên bao bì đều là "đáp án". Chúng bị chặn ở hai lớp: theo **tên cột** (`assert_no_leakage`) và theo
   **giá trị thẻ** (`assert_no_leaky_values`, `check_feature_names`).
2. **Chia theo thương hiệu.** Sản phẩm cùng hãng rất giống nhau; chia ngẫu nhiên thì mô hình gặp "anh em" của sản phẩm
   test lúc học → điểm cao ảo. `group_id` = thương hiệu đã chuẩn hóa.

---

## 2. SQL (thư mục `sql/`)

| Tệp | Vai trò |
|---|---|
| `init_raw_db.sql` | tạo bảng `raw_products`: `payload JSONB` giữ nguyên JSON gốc; `UNIQUE (code, source_file)` để nạp lại không trùng |
| `audit_queries.sql` | 11 câu kiểm toán (thay cho `raw_audit.py` 511 dòng cũ). Mỗi câu mở đầu bằng `-- name: <tên>` để Python đọc theo tên |
| `extract_products.sql` | một câu `SELECT` làm phẳng JSONB thành bảng (thay cho `staging.py` 268 dòng cũ); cho kết quả giống hệt bản Python cũ ở cả 30.000 dòng |

Cú pháp cần nhớ:

| Cú pháp | Ý nghĩa | Ví dụ trong dự án |
|---|---|---|
| `payload->'x'` | lấy giá trị JSON (mảng giữ nguyên) | `payload->'ingredients_tags'` |
| `payload->>'x'` | lấy giá trị dạng chữ | `payload->>'code'` |
| `jsonb_typeof(x) = 'array'` | kiểm tra kiểu | chỉ nhận mảng thẻ |
| `jsonb_array_elements_text(x)` | "bung" mảng thành nhiều dòng | đếm quốc gia, đếm thẻ `en:` |
| `jsonb_object_keys(payload)` | liệt kê khóa JSON | tìm trường cá nhân / trường lộ đáp án |
| `count(*) FILTER (WHERE ...)` | đếm có điều kiện | hạng × NOVA |
| `row_number() OVER (ORDER BY id)` | đánh số thứ tự | `row_id` cố định |
| `sum(count(*)) OVER ()` | tổng toàn bảng trong cùng câu | % thương hiệu |
| `percentile_cont(0.5) WITHIN GROUP (ORDER BY n)` | trung vị | số thành phần |
| `a JOIN a AS b ON a.code = b.code AND a.id < b.id` | tự JOIN tìm trùng | `ma_trung_join` |
| DuckDB `QUALIFY row_number() OVER (PARTITION BY code ORDER BY last_modified_t DESC) = 1` | giữ bản mới nhất mỗi mã | lấy mẫu từ dump |

**Bỏ `raw_audit.py` chỉ dùng SQL như thế nào?** Mỗi kiểm tra cũ có một câu SQL tương ứng:

| Kiểm tra cũ trong `raw_audit.py` | Câu SQL |
|---|---|
| tổng bản ghi, trùng mã, mã bắt đầu bằng 0, mã không phải chuỗi | `tong_quan` |
| phân bố nhãn gốc, số dùng được, độ phủ NOVA | `nhan_goc`, `dung_duoc` |
| hạng theo NOVA | `hang_theo_nova` |
| tỷ lệ thiếu từng trường | `ty_le_thieu` |
| số thành phần (trung vị, ≤ 1, > 150) | `so_thanh_phan` |
| tỷ lệ thẻ `en:` | `the_taxonomy` |
| mức tập trung thương hiệu, quốc gia | `thuong_hieu`, `quoc_gia` |
| trường cá nhân, trường lộ đáp án | `truong_nhay_cam` |
| trùng mã (JOIN) | `ma_trung_join` |

Phần "OK/WARN" của `evaluate_checks` cũ giờ là một bảng pandas 7 dòng ở mục A8 của notebook 03. Chạy trong pgAdmin:
mở `sql/audit_queries.sql`, bôi đen một câu, bấm F5. Kết quả đã khớp đúng mọi con số của báo cáo kiểm toán cũ.

---

## 3. `src/db.py` (43 dòng)

| Hàm | Làm gì | Vì sao |
|---|---|---|
| `connect()` | đọc `.env` bằng `load_dotenv()`, mở kết nối psycopg2 | mật khẩu không bao giờ nằm trong mã |
| `query(sql, params=None)` | chạy một câu SELECT, trả DataFrame | cột JSONB tự thành list/dict Python |
| `load_queries(path)` | tách tệp `.sql` theo dòng `-- name: <tên>` → dict | giữ SQL trong tệp `.sql` (chạy được cả trong pgAdmin) mà Python vẫn gọi theo tên |

## 4. `src/fetch_from_dump.py` (123 dòng) và `src/load_raw_to_postgres.py` (66 dòng)

- `ELIGIBLE`: điều kiện đủ để lấy mẫu (nhãn a-e, có thành phần, có mã, không lỗi thời).
- `PICK_SQL` (pha 1): `SELECT DISTINCT code ... ORDER BY md5(code || seed) LIMIT n`. **Vì sao md5?** Trộn ngẫu nhiên nhưng
  tái lập được: cùng seed luôn ra cùng thứ tự; không phụ thuộc thứ tự dòng trong tệp.
- `ROWS_SQL` (pha 2): đọc đủ cột cho mã đã chọn; `QUALIFY ... = 1` giữ **bản mới nhất đủ điều kiện** khi một mã có nhiều
  dòng. (Bản cũ đọc mọi dòng của mã mà không kiểm tra điều kiện, nên với 3 mã lặp đã lấy nhầm bản cũ; 2 bản trong đó
  không có nhãn. Đã sửa ngày 05/11/2026; mẫu đang dùng không chạy lại để giữ tập test đã khóa.)
- `pick_text`: tên/thành phần trong Parquet là list `{lang, text}`; ưu tiên `main` → ngôn ngữ sản phẩm → `en`.
- `nutriments_to_dict`: list `{name, 100g}` → `{"sugars_100g": ...}` giống API.
- `food_group_label`: `en:sugary-snacks` → `sugary snacks` (bản dump không có `pnns_groups`, dùng `food_groups_tags`).
- `row_to_payload`: ghép các bước trên; `code` luôn là chuỗi.
- `fetch(source, out_path, n, seed)`: chạy hai pha, ghi mỗi dòng `{"_metadata": {...thời điểm, nguồn...}, "raw_payload": {...}}`.
- `load_raw_to_postgres.load(path)`: đọc tệp, `INSERT ... ON CONFLICT (code, source_file) DO NOTHING` bằng
  `execute_values` (gửi theo lô 1.000 dòng).

## 5. `src/cleaning.py` (201 dòng)

Hằng số: `MAX_INGREDIENTS = 150`, `FEW_INGREDIENTS = 1`, `PII_FIELDS`, `LEAKY_LABEL_PATTERN` (biểu thức chính quy bắt
`nutri-score`, `health-star`, `keyhole`, `exceso`, `alto-en`...), `LEAKY_TAG_COLUMNS = (labels_tags, categories_tags)`,
`FEATURE_COLUMNS` (27 cột của X).

| Hàm | Làm gì |
|---|---|
| `as_list(v)` | list/mảng numpy → list; None, NaN, chuỗi → None |
| `clean_tags(values, drop)` | strip, chữ thường, bỏ rỗng, bỏ trùng, giữ thứ tự; None vẫn là None (khác `[]`) |
| `slugify(text)` | bỏ dấu (`unicodedata.normalize("NFKD")`), chữ thường, ký tự lạ → `-` |
| `clean_brands(values)` | bỏ tiền tố `xx:` rồi `slugify`: `xx:Carrefour`, `Carrefour ` → `carrefour` |
| `normalize_name(name)` | tên dùng để so trùng |
| `is_leaky_label(tag)` | thẻ có khớp `LEAKY_LABEL_PATTERN` không |
| `content_key(brand, name, ingredients)` | md5 của thương hiệu + tên + thành phần (so trùng nội dung) |
| `make_group_id(brand, name, code)` | `brand:...` / `name:...` / `code:...` |
| `assert_no_leakage(columns)` | báo lỗi nếu có cột chứa `nutri`, đuôi `_100g`, trường cá nhân... |
| `assert_no_leaky_values(X)` | báo lỗi nếu `labels_tags`/`categories_tags` còn thẻ lộ đáp án |
| `normalize(df)` | chuẩn hóa mọi cột, bỏ `en:world`, xóa thẻ lộ đáp án, số âm → thiếu, điền `ingredients_n` từ số thẻ. **Không loại dòng** |
| `apply_filters(df)` | lọc theo thứ tự và ghi phễu: nhãn → thành phần → mã vạch → > 150 → trùng mã (giữ bản mới nhất) → trùng nội dung |
| `add_flags_and_groups(df)` | cờ chất lượng + `group_id` |
| `clean(products)` | gọi 3 hàm trên, tách X (27 cột, không nhãn) và y, chạy hai hàm kiểm tra rò rỉ |

Bản mới cho kết quả **giống hệt** bản cũ (579 dòng) ở cả 29.904 dòng × 27 cột. Phần bỏ đi: báo cáo `.md/.json`, phần
chẩn đoán công thức 2017/2023 (kết luận vẫn ghi ở `docs/scope_decision.md`), dòng lệnh.

## 6. `src/features.py` (110 dòng)

| Thành phần | Làm gì | Vì sao |
|---|---|---|
| `tag_list(value)` | danh sách thẻ của một ô | dùng làm `analyzer` cho `CountVectorizer` (ô đã là danh sách, không cần tách chữ) |
| `relative_position(tags, words)` | `1 - i/len` của thẻ `en:` đầu tiên chứa một từ trong `words`; 0 nếu không có | thành phần ghi theo khối lượng giảm dần → đường đứng đầu = nhiều đường nhất. Dùng vị trí *tương đối* vì OFF chèn thẻ cha sau mỗi thành phần |
| `row_features(X)` | tạo cột số, vị trí, thành phần đầu, `pnns` (thiếu → `missing`), `nova` (chữ, thiếu → `missing`) | chỉ tính từ từng dòng, không học gì → không thể rò rỉ |
| `multi_hot(min_freq)` | `CountVectorizer(analyzer=tag_list, min_df=min_freq, binary=True)` | 1 nếu có thẻ; chỉ giữ thẻ có ở ≥ `min_freq` sản phẩm **của tập fit** |
| `make_features(min_freq=100, groups=GROUPS)` | `Pipeline([rows, ColumnTransformer(...)])` | gói mọi bước để fit lại trong từng fold |
| `feature_names(pipe)` | tên cột dạng `ingredients__en:sugar` | |
| `check_feature_names(names)` | không tên nào là thẻ lộ đáp án hay `_100g` | lớp chặn cuối |

Biến số đi qua `SimpleImputer(median)` → `log1p` → `StandardScaler` (trung bình 0, độ lệch chuẩn 1).
NOVA, `pnns_groups_1/2` dùng `OneHotEncoder(handle_unknown="ignore")` (giá trị chưa gặp lúc fit → toàn 0).

Phần bỏ so với bản cũ (645 dòng), đo lại cho thấy không làm giảm điểm: lớp `TagVectorizer` tự viết (thay bằng
`CountVectorizer`), cột `n_rare`, đếm phụ gia theo nhóm số E, số chất gây dị ứng, độ dài chữ thành phần, số tỷ lệ %,
cờ đồ uống/phô mai/hữu cơ (đã có sẵn dưới dạng thẻ), bộ bổ sung `pnns_groups_1` từ danh mục, nhóm `flags`.

## 7. `src/modeling.py` (174 dòng)

| Hàm / lớp | Làm gì |
|---|---|
| `make_split(X, y)` | `StratifiedGroupKFold(5, shuffle, seed 42)`: phần đầu là test 20%; dev chia tiếp 5 fold; thêm cột `country_holdout` (bài giữ lại Pháp). Tạo lại **giống hệt** tệp đã khóa |
| `check_split(split)` | không nhóm nào ở cả dev và test hay ở nhiều fold |
| `fingerprint(split)` | 16 ký tự đầu SHA-256 của các mã vạch test đã sắp xếp: `2e511eab89b680b7`. Đổi 1 mã là đổi vân tay |
| `select_dev(X, y, split)` | lấy phần dev |
| `select_test(X, y, split, final=False)` | **khóa**: báo `PermissionError` nếu không có `final=True` |
| `metrics(y_true, y_pred, proba)` | Macro-F1, accuracy, precision, recall (macro), QWK, tỷ lệ lệch ≤ 1 hạng; có xác suất thì thêm ROC-AUC (một-với-phần-còn-lại) và log-loss |
| `cross_validate(make_model, X, y, folds)` | mỗi fold: tạo mô hình **mới**, học 4 fold, dự đoán fold còn lại → (bảng chỉ số từng fold, dự đoán ngoài fold, xác suất) |
| `summarize(per_fold)` | "trung bình ± độ lệch chuẩn" |
| `CategoryBaseline` | đường cơ sở: hạng phổ biến nhất của `pnns_groups_2` (thiếu = nhóm `missing`); xác suất làm trơn bằng tỷ lệ chung |
| `make_model(kind, min_freq, groups, **params)` | `majority` (DummyClassifier), `category`, `logreg`, `tree`, `forest`, `lgbm`; trừ hai đường cơ sở, đều là `Pipeline([features, model])` với `class_weight="balanced"` |

**Vì sao đặc trưng nằm trong mô hình?** Để `cross_validate` fit lại cả phần "học" của đặc trưng (thẻ nào đủ phổ biến,
trung vị, độ lệch chuẩn) chỉ trên 4 fold huấn luyện. Nếu fit đặc trưng trên toàn bộ dev trước rồi mới chia, thông tin
fold kiểm định đã lọt vào.

Phần bỏ so với bản cũ (`evaluate.py` 649 + `train.py` 711 dòng): báo cáo `.md/.json`, dòng lệnh, lớp `NutriModel`
(thay bằng sklearn `Pipeline`), dừng sớm trên tập con bên trong, hồi quy thứ tự + tối ưu ngưỡng, cache đặc trưng theo fold
(giờ là 5 dòng trong notebook), Optuna 40 lần (giờ 30 lần, viết thẳng trong notebook).

---

## 8. Notebook

| Notebook | Ô quan trọng nên nắm |
|---|---|
| 01 | đếm trên dump bằng DuckDB (vì sao bài toán có ích); bảng tiêu chí thành công |
| 02 | in hai câu SQL lấy mẫu; đếm 943.455 mã đủ điều kiện; câu SQL trích xuất → `products.parquet` |
| 03 | A1-A8 SQL kiểm toán; B2 describe; B5 IQR; B9 tương quan (chứng minh dinh dưỡng là đáp án); B11 danh mục; B13 lift; B15 logo Nutri-Score |
| 04 | phễu làm sạch; hai lớp chống rò rỉ; tạo lại tập chia giống hệt + vân tay; `select_test` bị chặn; vector đặc trưng của sản phẩm ví dụ |
| 05 | `run()` + `cross_validate`; lưới C và độ sâu; Optuna; bảng so sánh; ma trận nhầm lẫn; giữ lại Pháp; ablation; đặc trưng quan trọng |
| 06 | kiểm tra vân tay rồi `select_test(final=True)` (chỉ ở đây); bảng test so với dev; bootstrap theo thương hiệu; bỏ sản phẩm có bản sao; calibration; ô kiểm tra SHAP thất bại và hàm `without` ("tắt thẻ"); `explain(i)`; bảng nguyên nhân lỗi |

Sản phẩm ví dụ xuyên suốt: "Caramel au beurre salé" (`3457221000505`, hạng E, thuộc dev).

Kết quả chính của notebook 05 (5 fold dev; notebook 05 không dùng tập test): LightGBM tinh chỉnh bằng Optuna Macro-F1 0,625 ± 0,007,
QWK 0,768, accuracy 0,643, 89,4% dự đoán lệch ≤ 1 hạng; đường cơ sở `pnns_groups_2` 0,412 / 0,463. Random Forest 0,606,
LightGBM mặc định 0,599, Logistic Regression 0,562, Decision Tree 0,516. Bỏ danh mục giảm 0,058, bỏ thành phần giảm 0,032;
các nhóm khác ≤ 0,006. Bản mã cũ dài gấp 5 lần đạt cùng Macro-F1 0,625.

Kết quả notebook 06 (tập test, mở một lần ngày 07/11/2026): Macro-F1 **0,635** (KTC 95% 0,616–0,652), QWK 0,758,
accuracy 0,651, 88,5% lệch ≤ 1 hạng; đường cơ sở `pnns_groups_2` 0,414 / 0,462. Chênh với dev chỉ +0,010. Bỏ 274 sản phẩm
có bản sao ở dev còn 0,621. Ablation trên test: bỏ danh mục −0,054, bỏ thành phần −0,032, NOVA +0,001 so với riêng thành
phần. 2.090 lỗi, 67% lệch 1 hạng; nguyên nhân lớn nhất là điểm sát ranh giới (36%).

---

## 9. Câu hỏi hay gặp (đáp ngắn)

| Câu hỏi | Trả lời |
|---|---|
| Sao không dùng bảng dinh dưỡng? | Hạng được tính từ chính nó (Spearman điểm–hạng 0,95). Dùng là "chép đáp án"; sản phẩm thật sự thiếu dinh dưỡng cũng không có nó |
| Sao chia theo thương hiệu? | Cùng hãng → công thức gần giống; chia ngẫu nhiên cho điểm cao ảo |
| Sao Macro-F1 mà không phải accuracy? | Hạng lệch (E gấp 2,6 lần B). Luôn đoán E được accuracy 28% nhưng Macro-F1 chỉ 0,09 |
| QWK là gì? | Cohen's kappa có trọng số bình phương: sai xa (A→E) bị phạt nặng hơn sai gần (B→C) |
| Vì sao cần tập test khóa? | Chọn mô hình/tham số trên dev làm điểm dev hơi lạc quan; test chưa từng dùng cho kết quả khách quan |
| `min_freq = 100` lấy đâu ra? | EDA: 629 thẻ ≥ 100 sản phẩm phủ 84,5% lượt xuất hiện; ngưỡng 20 chỉ tăng Macro-F1 khoảng 0,005 (nhỏ hơn độ lệch giữa các fold) mà gấp 2,5 lần số cột |
| Thiếu NOVA xử lý sao? | Thành giá trị riêng `missing` (không đoán bừa); số đếm thiếu điền trung vị của tập huấn luyện |
| Sao không SMOTE? | Lệch chỉ vừa phải; `class_weight="balanced"` đơn giản hơn và không tạo dữ liệu giả từ thẻ |
| Ngoại lai xử lý sao? | Chỉ loại giá trị phi lý (> 150 thành phần, 19 dòng); giá trị lớn nhưng thật (món ăn nhiều thành phần) giữ và lấy log |
| Có kiểm tra rò rỉ trong giá trị không? | Có: logo Nutri-Score trong `labels_tags` (2.263 dòng) bị xóa; `assert_no_leaky_values` và `check_feature_names` kiểm tra lại |
| Có dữ liệu cá nhân không? | Không: không đọc các cột đó từ dump (`COLUMNS`), SQL `truong_nhay_cam` xác nhận |
| Tập test mở mấy lần? Sao biết không "nhìn trộm"? | Một lần, ở notebook 06. `select_test` báo lỗi nếu thiếu `final=True`; test tự động kiểm tra chỉ notebook 06 gọi, đúng một lần, sau khi kiểm tra vân tay. Code notebook 06 được chạy thử trước trên fold 0 của dev. Mô hình chốt ở notebook 05 và không chỉnh lại sau đó |
| Điểm test (0,635) cao hơn dev (0,625) có lạ không? | Không: chênh 0,010 nhỏ hơn độ rộng khoảng tin cậy (0,616–0,652). Hai con số gần nhau cho thấy chọn tham số trên dev không làm điểm lạc quan |
| Bootstrap là gì, sao rút theo thương hiệu? | Rút lại có hoàn lại 1.000 lần để xem chỉ số dao động bao nhiêu. Sản phẩm cùng hãng giống nhau nên rút cả hãng một lúc, nếu không khoảng tin cậy hẹp hơn thực tế |
| Sao không dùng SHAP? | Đã thử: tổng giá trị SHAP của LightGBM lệch tới 7,1 so với điểm thật vì cây quá sâu (tới 76 tầng). Giá trị sai thì không giải thích được. Dùng "tắt thẻ": đặt cột thẻ về 0, dự đoán lại, xem xác suất đổi bao nhiêu |
| Calibration (ECE) là gì? | Kiểm tra xác suất có đáng tin: trong các sản phẩm mô hình tự tin 70% thì khoảng 70% phải đúng. ECE 0,047 là khá tốt, hơi tự tin quá ở khoảng giữa |
| Mô hình sai ở đâu? | 67% lỗi chỉ lệch 1 hạng. Lớn nhất: điểm sát ranh giới (36%), sản phẩm khác điển hình của nhóm (ví dụ sô cô la hạng D bị đoán E), thiếu thông tin (16%). Gốc chung: không biết lượng đường/muối/chất béo |

---

## 10. Gõ lại nhanh (nếu hội đồng xóa mã)

```python
# Chia theo thương hiệu, giữ tỷ lệ hạng
from sklearn.model_selection import StratifiedGroupKFold
sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
_, test_idx = next(sgkf.split(X, y, groups=X["group_id"]))

# Đánh giá chéo: mô hình mới cho mỗi fold
for k in range(5):
    tr, va = folds != k, folds == k
    model = make_model("lgbm").fit(X_dev[tr], y_dev[tr])
    pred[va] = model.predict(X_dev[va])

# Multi-hot cho cột danh sách thẻ, chỉ giữ thẻ phổ biến
CountVectorizer(analyzer=lambda tags: list(tags), min_df=100, binary=True)

# Vị trí tương đối của đường
def relative_position(tags, words):
    for i, t in enumerate(tags):
        if t.startswith("en:") and set(t[3:].split("-")) & words:
            return 1 - i / len(tags)
    return 0.0
```
(Trong mã thật, `analyzer` là hàm `tag_list` đặt tên, vì hàm `lambda` không lưu được bằng joblib.)

```python
# Bootstrap theo thương hiệu (notebook 06, mục 8.9)
rows_of_group = list(pd.Series(np.arange(n)).groupby(groups).indices.values())
for _ in range(1000):
    pick = rng.integers(0, len(rows_of_group), len(rows_of_group))   # rút thương hiệu có hoàn lại
    ix = np.concatenate([rows_of_group[i] for i in pick])
    boot.append(f1_score(t[ix], p[ix], average="macro"))
np.quantile(boot, [0.025, 0.975])                                     # khoảng tin cậy 95%

# "Tắt thẻ" (notebook 06, mục 8.15): ảnh hưởng của cột j lên xác suất D/E
mask = np.ones(M.shape[1]); mask[j] = 0
p_off = clf.predict_proba(M[rows].multiply(mask).tocsr())[:, [3, 4]].sum(axis=1)
effect = (p_de[rows] - p_off).mean()
```
