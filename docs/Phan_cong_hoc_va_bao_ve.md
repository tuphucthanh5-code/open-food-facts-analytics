# Phân công học và kế hoạch bảo vệ trước hội đồng

Tài liệu này thay cho cách chia cũ (theo 11 bước của kế hoạch Cách A, lúc chưa làm Bước 7). Từ 05/11/2026 dự án làm theo
**quy trình 9 bước của cô**, notebook là sản phẩm chính, mã rút gọn rất nhiều. Đọc cùng `docs/Giai_thich_ma_nguon.md`
(giải thích từng hàm, câu hỏi hay gặp, gõ lại nhanh).

---

## 1. Cấu trúc dự án hiện tại

```text
.
├── notebooks/           SẢN PHẨM CHÍNH, đã chạy sẵn kết quả (6 tệp)
├── src/                 hàm dùng lại nhiều lần (8 tệp, 824 dòng, kể cả predict.py)
├── sql/                 3 tệp SQL (187 dòng): tạo bảng, kiểm toán, trích xuất
├── dashboard/app.py     giao diện Streamlit (230 dòng); logic nằm ở src/predict.py để test được
├── .streamlit/config.toml
├── tests/               125 test (9 tệp, 765 dòng): chống rò rỉ, tập test chỉ mở một lần, SQL, dashboard
├── docs/                problem_statement, scope_decision, data_dictionary, eda_findings, Giai_thich_ma_nguon, 2 báo cáo Word
├── reports/             figures/ (19 ảnh), model_results.json, test_results.json
├── artifacts/best_model.joblib      mô hình đã đóng băng (cục bộ, không vào Git)
└── data/{external,raw,processed,final,archive}/    cục bộ, không vào Git
```

Luồng dữ liệu (mỗi mũi tên ghi rõ tệp làm việc đó):

```text
food.parquet (8 GB) --fetch_from_dump.py (SQL DuckDB)--> data/raw/*.jsonl.gz
  --load_raw_to_postgres.py--> PostgreSQL raw_products (JSONB)
  --sql/extract_products.sql (nb 02)--> data/processed/products.parquet (30.000 x 29)
  --cleaning.py (nb 04)--> data/final/clean_features.parquet (X 29.904 x 27) + clean_labels.parquet (y)
  --modeling.make_split (đã khóa)--> data/final/split.parquet (dev 23.922 / 5 fold | test 5.982)
  --features.py + modeling.py (nb 05, chỉ dev)--> artifacts/best_model.joblib, reports/model_results.json
  --nb 06 mở test MỘT lần--> reports/test_results.json
  --predict.py--> dashboard/app.py
```

### Tệp theo từng bước của cô

| Bước của cô | Notebook | Tệp mã | Dòng |
|---|---|---|---|
| 1-3. Bài toán, hướng phân tích, yêu cầu dữ liệu | `01_bai_toan` | chỉ notebook + `docs/problem_statement.md` | 8 ô |
| 4. Thu thập dữ liệu (SQL) | `02_thu_thap_du_lieu` | `fetch_from_dump.py` 123, `load_raw_to_postgres.py` 66, `db.py` 43, `sql/init_raw_db.sql` 14, `sql/extract_products.sql` 53 | 299 |
| 5. Hiểu dữ liệu, EDA | `03_eda` | `sql/audit_queries.sql` 120 (11 câu); phần B viết thẳng trong notebook (pandas) | 120 |
| 6. Chuẩn bị dữ liệu | `04_chuan_bi_du_lieu` | `cleaning.py` 201, `features.py` 110, `modeling.make_split/check_split/fingerprint` | 311 + khoảng 45 |
| 7. Mô hình + 8. Đánh giá trên dev | `05_mo_hinh` | `modeling.py` 174 (`cross_validate`, `metrics`, `CategoryBaseline`, `make_model`), dùng `features.py` | 174 |
| 8. Đánh giá cuối trên test | `06_danh_gia` | `modeling.select_test(final=True)` (chỉ nb 06 được gọi); bootstrap, calibration, "tắt thẻ" viết trong notebook | - |
| 9. Triển khai | dashboard | `predict.py` 107, `dashboard/app.py` 230, `.streamlit/config.toml` | 337 |

### Bước cũ so với bước mới

| Kế hoạch cũ (11 bước, tài liệu Cách A) | Nay nằm ở | Thay đổi |
|---|---|---|
| 0. Chốt định hướng | notebook 01, `problem_statement.md` | gộp vào Bước 1-3 của cô |
| 1. Raw layer (PostgreSQL) | notebook 02 mục 4.2, `load_raw_to_postgres.py`, `init_raw_db.sql` | giữ; thêm lấy mẫu bằng SQL DuckDB |
| 2. Kiểm toán thô | notebook 03 phần A, `sql/audit_queries.sql` | `src/raw_audit.py` (511 dòng) thay bằng 11 câu SQL |
| 3. Staging | notebook 02 mục 4.3, `sql/extract_products.sql` | `src/staging.py` (268 dòng) thay bằng 1 câu SQL, kết quả giống hệt |
| 4. Cleaning | notebook 04, `cleaning.py` | 579 thành 201 dòng, kết quả giống hệt (29.904 x 27) |
| 5. EDA | notebook 03 phần B | chung notebook với kiểm toán |
| 6. Feature engineering | `features.py` (645 thành 110), notebook 04 mục 6.6 | thuộc Bước 6 của cô (chuẩn bị dữ liệu), dùng ở notebook 05 |
| 7. Chia dữ liệu | `modeling.make_split`, notebook 04 mục 6.5 | tập test khóa, vân tay `2e511eab89b680b7` |
| 8. Modeling | notebook 05, `modeling.py` | `src/models/train.py` (708 dòng) thành hàm trong `modeling.py` |
| 9. Đánh giá, lỗi, SHAP | notebook 06 | **bỏ SHAP**, dùng "tắt thẻ" (SHAP sai số học); mở test một lần |
| 10. Dashboard | `predict.py`, `dashboard/app.py` | xong, kèm 3 ảnh chụp |
| 11. Đóng gói | README, `requirements.txt`, CI, model card | xong; còn gắn tag Git khi nộp |

Đã xóa: `src/raw_audit.py`, `src/staging.py`, `src/models/`, notebook cũ `00_raw_audit` và `01_eda`, các báo cáo `.md/.json` tự sinh
trong `reports/`, `HUONG_DAN_BUOC_4.md`. Mã `src/` từ 3.719 dòng xuống 717 (nay 824 vì thêm `predict.py`); test từ khoảng 2.800
xuống 765 dòng.

**Vì sao phải chia lại:** cách cũ chia theo bước 1-6 của kế hoạch cũ. Nay kiểm toán và staging chỉ còn là SQL, EDA và
chuẩn bị dữ liệu nằm ở hai notebook khác nhau, và còn thêm phần mô hình, đánh giá, dashboard chưa ai nhận.

---

## 2. Phân công lại cho 3 người

Nguyên tắc: mỗi người nắm **một mạch liền** của dữ liệu, khối lượng tương đương, không ai chỉ học phần dễ. Phần hội đồng
hỏi sâu nhất (rò rỉ, chia theo nhóm, tập test, đánh giá) giao cho người làm Bước 6 và Bước 7-8.

| | Người 1: Dữ liệu vào và triển khai | Người 2: Chuẩn bị dữ liệu | Người 3: Mô hình và đánh giá |
|---|---|---|---|
| Bước của cô | 1-4, nửa đầu Bước 5, Bước 9 | nửa sau Bước 5, Bước 6 | Bước 7, 8 |
| Notebook | 01, 02, 03 (phần A, SQL) | 03 (phần B, pandas), 04 | 05, 06 |
| Tệp mã | `db.py`, `fetch_from_dump.py`, `load_raw_to_postgres.py`, `sql/*.sql`, `predict.py`, `dashboard/app.py` | `cleaning.py`, `features.py`, `modeling.make_split/check_split/fingerprint/select_*` | `modeling.py` (phần còn lại); `features.py` ở mức dùng |
| Khối lượng | khoảng 750 dòng, nhưng SQL và giao diện dễ đọc | khoảng 360 dòng, khái niệm khó nhất | khoảng 130 dòng, nhiều thống kê nhất |
| Khái niệm phải giải thích | lấy mẫu ngẫu nhiên có seed bằng SQL, JSONB (`->`, `->>`), raw layer, `GROUP BY ... FILTER`, JOIN tự thân tìm mã trùng, Streamlit (`cache_resource`, tab), "tắt thẻ" trong `explain`, gợi ý thay thế (cosine) | rò rỉ nhãn (2 lớp: tên cột, giá trị), phễu làm sạch, `group_id`, StratifiedGroupKFold, multi-hot + `min_freq`, Pipeline chỉ fit trên train, lift, Cramér's V | Macro-F1, QWK, `class_weight`, 4 mô hình + 2 đường cơ sở, Optuna, ablation, giữ lại Pháp, tập test mở một lần, bootstrap theo thương hiệu, calibration (ECE), phân tích lỗi, vì sao bỏ SHAP |
| Con số phải thuộc | 4.815.797 sản phẩm trong dump, 943.455 mã đủ điều kiện, mẫu 30.000, 0 trường cá nhân | 29.904 sau làm sạch (loại 2 + 19 + 75), 15.141 nhóm, 2.263 dòng bỏ thẻ logo, 908 / 1.009 cột | 0,625 (dev) và **0,635 (test)**, QWK 0,758, KTC 0,616-0,652, đường cơ sở 0,414, ablation bỏ danh mục -0,054, 2.090 lỗi (67% lệch 1 hạng) |

Người 1 còn làm slide giới thiệu bài toán (Bước 1) vì nắm bài toán và dashboard (ảnh chụp dùng làm slide).

### Tệp cụ thể từng người phải nắm chắc

Ba mức: **Nắm chắc** = giải thích được từng hàm, gõ lại được phần cốt lõi. **Hiểu ý** = biết tệp làm gì, đọc hiểu khi hội đồng mở ra.
**Biết có** = biết nó tồn tại và để làm gì.

#### Người 1: dữ liệu vào và triển khai

| Mức | Tệp | Nắm gì trong tệp |
|---|---|---|
| Nắm chắc | `notebooks/01_bai_toan.ipynb`, `docs/problem_statement.md` | bài toán, 3 câu hỏi nghiên cứu, tiêu chí thành công |
| Nắm chắc | `notebooks/02_thu_thap_du_lieu.ipynb` | in 2 câu SQL lấy mẫu, đếm 943.455 mã đủ điều kiện, câu SQL trích xuất ra `products.parquet` |
| Nắm chắc | `src/fetch_from_dump.py` | `PICK_SQL`, `ROWS_SQL`, `ELIGIBLE`, `COLUMNS` (không có cột cá nhân), `fetch` |
| Nắm chắc | `sql/extract_products.sql`, `sql/init_raw_db.sql` | `->`, `->>`, `jsonb_typeof`, bảng `raw_products` (`payload JSONB`, `UNIQUE (code, source_file)`) |
| Nắm chắc | `sql/audit_queries.sql` + `notebooks/03_eda.ipynb` phần A (A1-A8) | 11 câu kiểm toán: `GROUP BY ... FILTER`, `truong_nhay_cam`, `ma_trung_join` (JOIN bảng với chính nó) |
| Nắm chắc | `src/predict.py` | `to_tags`, `make_row`, `predict`, `explain` ("tắt thẻ"), `alternatives` (cosine) |
| Nắm chắc | `dashboard/app.py`, `.streamlit/config.toml` | `get_model`/`get_data` (cache), `show_prediction`, 2 chế độ nhập, tab Tổng quan |
| Hiểu ý | `src/db.py`, `src/load_raw_to_postgres.py` | `connect` đọc `.env`, `query`, `load_queries`; nạp bằng `ON CONFLICT DO NOTHING` |
| Hiểu ý | `tests/test_fetch_from_dump.py`, `test_sql.py`, `test_predict.py`, `test_dashboard.py` | test cho biết hàm hứa làm gì |
| Hiểu ý | `reports/figures/dashboard_01..03.png` | dùng làm slide |
| Biết có | `.env.example`, `README.md` | quy ước bí mật; cách chạy lại |

#### Người 2: chuẩn bị dữ liệu

| Mức | Tệp | Nắm gì trong tệp |
|---|---|---|
| Nắm chắc | `notebooks/03_eda.ipynb` phần B (B2-B15) | thống kê mô tả, thiếu, IQR, tương quan (B9: dinh dưỡng là đáp án), danh mục (B11), lift (B13), logo Nutri-Score (B15) |
| Nắm chắc | `docs/eda_findings.md` | các phát hiện EDA đã chốt |
| Nắm chắc | `notebooks/04_chuan_bi_du_lieu.ipynb` | bảng phễu, hai lớp chống rò rỉ, tập chia + vân tay, `select_test` bị chặn, vector đặc trưng của sản phẩm ví dụ |
| Nắm chắc | `src/cleaning.py` | `LEAKY_LABEL_PATTERN`, `is_leaky_label`, `assert_no_leakage`, `assert_no_leaky_values`, `normalize`, `apply_filters` (phễu), `add_flags_and_groups`, `make_group_id`, `clean` |
| Nắm chắc | `src/features.py` | `MIN_FREQ`, `GROUPS`, `row_features`, `relative_position`, `multi_hot`, `make_features` (Pipeline), `check_feature_names` |
| Nắm chắc | `src/modeling.py` phần chia | `make_split`, `check_split`, `fingerprint`, `select_dev`, `select_test` |
| Nắm chắc | `docs/data_dictionary.md` | ý nghĩa 27 cột của X (test bắt buộc mỗi cột phải có ở đây) |
| Hiểu ý | `tests/test_cleaning.py`, `tests/test_features.py` | test chống rò rỉ, phễu, đặc trưng |
| Hiểu ý | `reports/figures/eda_01..09.png` | đọc được từng ảnh nói lên điều gì |
| Biết có | `docs/scope_decision.md` | mỗi quyết định phạm vi kèm lý do (đọc các mục về làm sạch, đặc trưng, chia) |

#### Người 3: mô hình và đánh giá

| Mức | Tệp | Nắm gì trong tệp |
|---|---|---|
| Nắm chắc | `notebooks/05_mo_hinh.ipynb` | 2 đường cơ sở, 4 mô hình, Optuna, bảng so sánh, ma trận nhầm lẫn, giữ lại Pháp, ablation, đặc trưng quan trọng |
| Nắm chắc | `notebooks/06_danh_gia.ipynb` | mở test một lần, bảng test so với dev, bootstrap theo thương hiệu, bỏ sản phẩm có bản sao, calibration, ô kiểm tra SHAP thất bại, hàm `without` ("tắt thẻ"), bảng nguyên nhân lỗi |
| Nắm chắc | `src/modeling.py` phần mô hình | `metrics` (Macro-F1, QWK, ROC-AUC), `cross_validate`, `summarize`, `CategoryBaseline`, `make_model` |
| Nắm chắc | `reports/model_results.json`, `reports/test_results.json` | nguồn các con số 0,625 (dev) và 0,635 (test) |
| Hiểu ý | `src/features.py` | chỉ cần biết đầu vào và đầu ra của `make_features` và 8 nhóm đặc trưng (cho phần ablation) |
| Hiểu ý | `tests/test_modeling.py`, `tests/test_notebooks.py` | bằng chứng test chỉ mở một lần, tập chia khớp vân tay |
| Hiểu ý | `reports/figures/model_01..03.png`, `eval_01..04.png` | đọc được từng ảnh nói lên điều gì |
| Biết có | `artifacts/best_model.joblib`, `data/processed/oof_predictions.parquet`, `test_predictions.parquet` | cục bộ, không vào Git |

#### Cả 3 người cùng đọc

`README.md` (model card), `docs/Giai_thich_ma_nguon.md` mục 1 và mục 9, `tests/test_project_structure.py` (các quy tắc dự án
được test canh giữ), hai báo cáo Word, và `docs/Phan_cong_hoc_va_bao_ve.md` này.

### Phần chung (cả 3 người cùng thuộc, mỗi người kể lại được trong 3 phút)

1. **Sơ đồ luồng dữ liệu** ở trên, kể từng mũi tên làm gì.
2. **Bài toán:** dự đoán Nutri-Score A-E cho sản phẩm thiếu bảng dinh dưỡng, chỉ từ thành phần, phụ gia, danh mục, NOVA, quốc gia.
3. **Chống rò rỉ:** vì sao dinh dưỡng là "đáp án" (Spearman điểm-hạng 0,95), chặn ở đâu.
4. **Chia theo thương hiệu** và **tập test mở đúng một lần**, mô hình đóng băng.
5. **Kết quả cuối:** Macro-F1 0,635 so với 0,414 của đường cơ sở; hạn chế (không biết lượng đường, muối, chất béo).

Cách luyện chéo: người này đóng vai hội đồng, hỏi người kia các câu ở mục 9 của `Giai_thich_ma_nguon.md`, rồi đổi vai.

---

## 3. Khi lên hội đồng: mở những gì, theo thứ tự

Kể một mạch 10-12 phút, mỗi người 3-4 phút đúng phần của mình, rồi trả lời câu hỏi.

| # | Ai | Mở | Nói gì | Đừng sa đà |
|---|---|---|---|---|
| 1 | Người 1 | Slide + `docs/problem_statement.md` | bài toán, câu hỏi nghiên cứu, tiêu chí thành công | |
| 2 | Người 1 | `notebooks/02_thu_thap_du_lieu.ipynb` | 2 câu SQL lấy mẫu, nạp JSONB, câu SQL trích xuất | không đọc cả `fetch_from_dump.py` |
| 3 | Người 1 hoặc 2 | `notebooks/03_eda.ipynb` | A6 không có trường cá nhân; B9 tương quan chứng minh dinh dưỡng là đáp án; B13 lift | bỏ qua các ô mô tả |
| 4 | Người 2 | `notebooks/04_chuan_bi_du_lieu.ipynb` | bảng phễu, hai lớp chống rò rỉ, chia theo nhóm + vân tay | |
| 5 | Người 3 | `notebooks/05_mo_hinh.ipynb` | bảng so sánh mô hình, ablation, ma trận nhầm lẫn | |
| 6 | Người 3 | `notebooks/06_danh_gia.ipynb` | mở test một lần, KTC, "tắt thẻ", phân tích lỗi | |
| 7 | Người 1 | `streamlit run dashboard\app.py` | demo mã vạch `3457221000505` (đúng E 96%), rồi tự nhập thành phần để thấy cảnh báo "chưa chắc" | chạy thử trước một lần, mở sẵn |

Mở sẵn nhưng chỉ vào khi bị hỏi: `src/cleaning.py` (`is_leaky_label`, `assert_no_leaky_values`, `make_group_id`), `src/features.py`
(`make_features`, `relative_position`), `src/modeling.py` (`make_split`, `select_test`, `cross_validate`), `tests/test_notebooks.py`
(bằng chứng test chỉ mở một lần), `docs/scope_decision.md` (mỗi quyết định kèm lý do), `docs/data_dictionary.md`.

Chuẩn bị trước: bật `venv`, chạy `pytest -q` (125 test xanh), bật PostgreSQL, mở sẵn dashboard. **Không mở `.env`, không mở `data/`.**
Nếu hội đồng hỏi dữ liệu thô: dữ liệu không đẩy lên Git theo quy định, tái lập bằng seed 42 và `requirements.txt`.

---

## 4. Cách học code để trả lời được (và gõ lại khi bị xóa)

Học theo 3 mức, mỗi mức có một câu tự kiểm tra:

1. **Biết tệp để làm gì** (một câu). Tự kiểm tra: không nhìn tài liệu, nói được "tệp này nhận gì, trả ra gì".
2. **Hiểu từng hàm.** Mở notebook, chạy từng ô từ trên xuống, tự đổi **một** tham số (ví dụ `min_freq` 100 thành 20, `max_ingredients`)
   rồi xem kết quả đổi ở đâu. Không chạy lại notebook 05 (45 phút) và **không chạy lại notebook 06 ngoài lần đã chốt** (test chỉ mở một lần);
   học hai notebook này bằng cách đọc output và chạy từng hàm nhỏ trên fold 0 của dev. Tự kiểm tra: giải thích được "vì sao", không chỉ "làm gì".
3. **Gõ lại hàm cốt lõi** (không nhìn). Hội đồng có thể xóa code bắt viết lại; bản mẫu ở mục 10 của `Giai_thich_ma_nguon.md`.
   Sai tên hàm thư viện không sao, miễn nói đúng ý.

| Người | Thứ phải gõ lại được | Câu "vì sao" đi kèm |
|---|---|---|
| 1 | câu SQL lấy mẫu (`ORDER BY md5(code \|\| seed) LIMIT n`, lọc A-E và có thành phần); câu `SELECT payload->>'code', payload->'ingredients_tags' ...`; một câu `GROUP BY ... FILTER`; `db.query` | vì sao lấy mẫu bằng SQL (không kéo 8 GB vào RAM, seed cố định); vì sao giữ JSONB (raw layer giữ nguyên bản gốc) |
| 2 | `is_leaky_label` và xóa thẻ rò rỉ; `make_group_id`; một bước phễu trong `apply_filters`; `make_split` (StratifiedGroupKFold); `relative_position` | vì sao chặn cả giá trị chứ không chỉ tên cột; vì sao chia theo thương hiệu; vì sao không lọc theo dinh dưỡng |
| 3 | `cross_validate` (mô hình mới mỗi fold); `metrics` (Macro-F1, QWK); bootstrap theo thương hiệu; hàm "tắt thẻ" `without` | vì sao Macro-F1 mà không phải accuracy; vì sao test mở một lần; vì sao bỏ SHAP |

Lịch gợi ý cho mỗi người (khoảng 3 ngày): ngày 1 đọc mục của mình trong `Giai_thich_ma_nguon.md` và chạy các ô notebook; ngày 2
đọc `src/` của mình kèm test tương ứng (`tests/test_cleaning.py`, ...; test cho biết hàm được hứa làm gì); ngày 3 gõ lại hàm và hỏi đáp chéo.

### Câu hỏi hội đồng có thể hỏi

**Người 1**
- Vì sao dùng PostgreSQL JSONB mà không đọc thẳng Parquet? (Raw layer giữ nguyên JSON gốc để truy vết; thực hành SQL đúng yêu cầu Bước 4.)
- Mẫu có đại diện không? (Ngẫu nhiên seed 42 trong 943.455 mã đủ điều kiện; hạn chế: chỉ lấy sản phẩm có nhãn và có thành phần.)
- Dashboard có học lại mô hình không? Sao tự nhập kém chính xác hơn? (Mục 9 của `Giai_thich_ma_nguon.md`.)

**Người 2**
- Rò rỉ nhãn là gì, chặn thế nào? Có kiểm tra giá trị không? (Hai lớp; logo Nutri-Score trong `labels_tags`.)
- Vì sao loại 75 dòng trùng nội dung? Vì sao chỉ gắn cờ sản phẩm ít thành phần?
- `min_freq = 100` lấy đâu ra? Thiếu NOVA xử lý sao? Sao không SMOTE?

**Người 3**
- Sao chọn LightGBM? Optuna làm gì, có chạm cạnh lưới không? (`min_child_samples` = 3 chạm cạnh dưới: nói thẳng.)
- Điểm test cao hơn dev có lạ không? Test mở mấy lần, chứng minh thế nào?
- Mô hình sai ở đâu? Vì sao không dùng SHAP? Calibration là gì?

Câu hỏi khó nhất cho cả nhóm: **"Có chắc không lẫn đáp án vào đặc trưng?"** Trả lời: ba lớp chặn (tên cột, giá trị thẻ, kiểm tên cột
sau khi tạo đặc trưng) cộng test tự động; và kết quả không "đẹp bất thường" (0,635, không gần 1).

---

## 5. Việc còn lại liên quan đến bảo vệ

- Slide giới thiệu bài toán (Người 1), dùng ảnh `reports/figures/dashboard_01` đến `dashboard_03`.
- Ghi ngày hoặc phiên bản của bản dump `food.parquet` vào README.
- Gắn tag Git khi nộp. Chỉ commit khi nhóm quyết định; trước `git add` chạy `git status`, chắc chắn không có `.env`, `*.parquet`, `*.jsonl.gz`, `*.joblib`.
- Mục 8 "Những gì cần học" của báo cáo Word đầy đủ vẫn là bản cũ (theo kế hoạch 11 bước), giữ nguyên theo dặn; tài liệu này là bản cập nhật.
