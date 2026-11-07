# Dự đoán Nutri-Score từ thành phần, phụ gia, danh mục và NOVA

Dự án dùng dữ liệu Open Food Facts để dự đoán hạng Nutri-Score (A–E) cho sản phẩm thiếu bảng dinh dưỡng,
chỉ dựa trên thành phần, phụ gia, danh mục, nhóm NOVA và quốc gia. Chi tiết: `docs/problem_statement.md`.

**Sản phẩm chính là 6 notebook chạy sẵn, có kết quả, và một dashboard**, đi theo quy trình 9 bước của môn học:

| Notebook | Bước trong quy trình |
|---|---|
| `notebooks/01_bai_toan.ipynb` | 1. Business Understanding, 2. Analytic Approach, 3. Data Requirements |
| `notebooks/02_thu_thap_du_lieu.ipynb` | 4. Data Collection: DuckDB SQL trên bản dump → PostgreSQL (JSONB) → SQL trích xuất |
| `notebooks/03_eda.ipynb` | 5. Data Understanding / EDA: kiểm toán bằng SQL + khám phá bằng pandas |
| `notebooks/04_chuan_bi_du_lieu.ipynb` | 6. Data Preparation: làm sạch, chia train/validation/test, đặc trưng |
| `notebooks/05_mo_hinh.ipynb` | 7. Modeling, 8. Evaluation trên tập dev (so sánh và chốt mô hình) |
| `notebooks/06_danh_gia.ipynb` | 8. Evaluation cuối: mở tập test một lần, khoảng tin cậy, phân tích lỗi, giải thích mô hình |
| `dashboard/app.py` (Streamlit) | 9. Deployment: nhập sản phẩm, xem hạng dự đoán, xác suất, giải thích và sản phẩm thay thế |

## Kết quả chính (tập test 20%, 5.982 sản phẩm, thương hiệu không có trong dữ liệu học)

| Mô hình | Macro-F1 | QWK | Accuracy | Lệch ≤ 1 hạng |
|---|---|---|---|---|
| Đường cơ sở: luôn đoán hạng phổ biến nhất | 0,088 | 0,000 | 28,4% | 52,2% |
| Đường cơ sở: hạng phổ biến nhất của nhóm `pnns_groups_2` | 0,414 | 0,462 | 46,1% | 73,3% |
| **LightGBM tinh chỉnh bằng Optuna** | **0,635** (KTC 95% 0,616–0,652) | **0,758** | **65,1%** | **88,5%** |

- Điểm test gần bằng điểm đánh giá chéo trên dev (Macro-F1 0,625, QWK 0,768): không bị lạc quan do chọn mô hình.
- Nhóm đặc trưng quan trọng nhất là danh mục, rồi đến thành phần; NOVA gần như không thêm thông tin (+0,001).
- Khó nhất: hạng B, món ăn hỗn hợp, sản phẩm thiếu nhóm. 67% lỗi chỉ lệch 1 hạng, phần lớn do sản phẩm sát ranh giới
  điểm hoặc khác điển hình của nhóm (mô hình không biết *lượng* đường/muối/chất béo).

## Cấu trúc thư mục
```text
.
├── notebooks/                 # 6 notebook ở trên (sản phẩm nộp chính)
├── src/                       # mã dùng lại nhiều lần, mỗi tệp ngắn
│   ├── fetch_from_dump.py     # Bước 4: lấy mẫu từ bản dump Parquet bằng SQL (DuckDB)
│   ├── load_raw_to_postgres.py# Bước 4: nạp JSON thô vào PostgreSQL
│   ├── db.py                  # kết nối PostgreSQL (.env), chạy câu SQL -> DataFrame
│   ├── cleaning.py            # Bước 6: chuẩn hóa, lọc, loại trùng, chống rò rỉ nhãn, group_id
│   ├── features.py            # Bước 6: sklearn Pipeline đặc trưng
│   ├── modeling.py            # Bước 6-8: chia dữ liệu, khóa test, chỉ số, đánh giá chéo, mô hình
│   └── predict.py             # Bước 9: dự đoán, giải thích ("tắt thẻ"), gợi ý sản phẩm tốt hơn cho một sản phẩm
├── dashboard/app.py           # Bước 9: giao diện Streamlit (chỉ giao diện, logic ở src/predict.py)
├── .streamlit/config.toml     # cấu hình dashboard (tắt gửi thống kê sử dụng, ẩn nút Deploy, màu chính)
├── sql/
│   ├── init_raw_db.sql        # tạo bảng raw_products (JSONB)
│   ├── audit_queries.sql      # 11 truy vấn kiểm toán dữ liệu thô
│   └── extract_products.sql   # JSONB -> bảng phẳng
├── tests/                     # pytest
├── docs/                      # problem_statement, scope_decision, data_dictionary, eda_findings, giải thích mã, báo cáo Word
├── reports/                   # figures/ (biểu đồ do notebook lưu), model_results.json, test_results.json
├── artifacts/                 # best_model.joblib (cục bộ, không đẩy lên Git)
└── data/{raw,processed,final,external}/   # dữ liệu cục bộ, không đẩy lên Git
```

## Cài đặt
```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```
Mở `.env` và điền mật khẩu PostgreSQL (tệp này không bao giờ đẩy lên Git).
Dùng Python 3.11. `requirements.txt` ghim đúng phiên bản đã dùng để học mô hình: khác phiên bản scikit-learn hoặc
LightGBM thì `artifacts/best_model.joblib` có thể không mở được.

## Chạy lại từ đầu
1. Tải bản dump (khoảng 8 GB) và lấy mẫu 30.000 sản phẩm bằng SQL:
   ```bat
   curl -L -C - -o data\external\food.parquet "https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet?download=true"
   python -m src.fetch_from_dump --n 30000 --seed 42
   ```
2. Tạo bảng và nạp vào PostgreSQL (raw layer):
   ```bat
   psql -U postgres -c "CREATE DATABASE food_facts_db;"
   psql -U postgres -d food_facts_db -f sql\init_raw_db.sql
   python -m src.load_raw_to_postgres data\raw\raw_products_dump_<thời điểm>.jsonl.gz
   ```
3. Kiểm toán dữ liệu thô: chạy từng câu trong `sql/audit_queries.sql` bằng pgAdmin/psql, hoặc mở notebook 03.
4. Chạy các notebook theo thứ tự (mỗi notebook lưu kết quả cho notebook sau):
   ```bat
   jupyter nbconvert --to notebook --execute --inplace notebooks\01_bai_toan.ipynb notebooks\02_thu_thap_du_lieu.ipynb notebooks\03_eda.ipynb notebooks\04_chuan_bi_du_lieu.ipynb
   jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=7200 notebooks\05_mo_hinh.ipynb
   jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 notebooks\06_danh_gia.ipynb
   ```
   Notebook 05 mất khoảng 45 phút (tinh chỉnh Optuna và ablation), notebook 06 khoảng 5 phút.

Tập test 20% (`split == "test"` trong `data/final/split.parquet`) bị khóa: mã chỉ trả về tập này khi gọi
`select_test(..., final=True)`, và chỉ notebook 06 được gọi (test tự động kiểm tra). Mô hình được chốt ở notebook 05
trước khi mở test; tập test đã mở một lần ngày 07/11/2026 và mô hình không được chỉnh lại sau đó.

## Dashboard (Bước 9)
Cần có `artifacts/best_model.joblib` và `data/final/clean_*.parquet` (chạy notebook 04, 05 trước). Từ thư mục gốc:
```bat
streamlit run dashboard\app.py
```
Trình duyệt mở `http://localhost:8501`.
- **Tab Dự đoán:**
  - nhập mã vạch của một sản phẩm trong dữ liệu (ví dụ `3457221000505`, có hạng thật để so), hoặc tự nhập thành phần
    (tiếng Anh, theo thứ tự trên bao bì), phụ gia, nhóm sản phẩm, NOVA, quốc gia;
  - kết quả gồm hạng dự đoán, xác suất 5 hạng (có cảnh báo khi độ tự tin dưới 50%), giải thích bằng "tắt thẻ", và các
    sản phẩm cùng nhóm có hạng tốt hơn với thành phần giống nhất.
- **Tab Tổng quan:** chỉ số trên tập test, ma trận nhầm lẫn, thẻ kéo hạng, phân bố hạng theo nhóm và thị trường.

Ảnh chụp: `reports/figures/dashboard_01_du_doan_ma_vach.png` (mã vạch), `dashboard_02_tu_nhap_chua_chac.png` (tự nhập,
có cảnh báo độ tự tin thấp), `dashboard_03_tong_quan.png` (tab Tổng quan).

Dashboard chỉ dùng mô hình đã đóng băng; không học lại và không dùng bảng dinh dưỡng. Thành phần tự nhập thiếu các
"thẻ cha" mà Open Food Facts tự thêm (ví dụ `en:sugar` → `en:added-sugar`), nên kết quả kém chính xác hơn sản phẩm thật.

## Kiểm thử
```bat
pytest -q                   # toàn bộ test (test cần PostgreSQL tự bỏ qua nếu không kết nối được)
pytest -m integration -v    # chỉ test chạy SQL trên PostgreSQL thật
```

## Model card (thẻ mô hình)

| Mục | Nội dung |
|---|---|
| Mô hình | LightGBM phân loại 5 hạng (`class_weight="balanced"`), tham số chọn bằng Optuna 30 lần thử; sklearn Pipeline gồm cả bước tạo 1.009 đặc trưng; tệp `artifacts/best_model.joblib` |
| Mục đích | Ước lượng hạng Nutri-Score **tham khảo** cho sản phẩm đã có danh sách thành phần nhưng chưa có bảng dinh dưỡng (ví dụ để ưu tiên sản phẩm cần bổ sung dữ liệu trên Open Food Facts) |
| Không dùng cho | Tư vấn sức khỏe hay chế độ ăn; thay thế nhãn Nutri-Score chính thức; quyết định pháp lý hay ghi nhãn sản phẩm |
| Đầu vào | Thành phần (`ingredients_tags`), phụ gia, danh mục (`categories_tags`, `pnns_groups_1/2`), NOVA, nhãn bao bì, quốc gia. **Không** dùng bảng dinh dưỡng, điểm Nutri-Score, thương hiệu |
| Dữ liệu học | 23.922 sản phẩm (80% của mẫu ngẫu nhiên 29.904 sản phẩm sạch, 160 quốc gia, nhiều nhất Mỹ và Pháp); nhãn do Open Food Facts tính từ bảng dinh dưỡng, gần như theo công thức 2023 |
| Đánh giá | Tập test 5.982 sản phẩm của các thương hiệu không có trong dữ liệu học: Macro-F1 0,635 (KTC 95% 0,616–0,652), QWK 0,758, accuracy 65,1%, 88,5% lệch ≤ 1 hạng; Pháp 0,683, Mỹ 0,610, nước khác 0,617 |
| Độ tin cậy xác suất | ECE 0,047. Khi độ tự tin ≥ 80% (36,5% sản phẩm), đúng 89,2%; khi < 50% (21,4% sản phẩm), chỉ đúng 38,2%: nên hiện xác suất và cảnh báo |
| Giới hạn | Không biết lượng đường/muối/chất béo nên hay nhầm hạng kề nhau (nhất là B) và sản phẩm khác điển hình của nhóm; yếu hơn ở món ăn hỗn hợp, sản phẩm thiếu nhóm, thị trường ngoài Pháp; sản phẩm thiếu dinh dưỡng ngoài đời có thể khác sản phẩm dùng để học |
| Đạo đức, giấy phép | Không thu thập trường định danh người đóng góp; dữ liệu theo ODbL (xem dưới); mô hình là sản phẩm phái sinh dùng cho học tập |

## Dữ liệu và giấy phép
Dữ liệu từ [Open Food Facts](https://world.openfoodfacts.org) (bản dump Parquet trên Hugging Face:
`openfoodfacts/product-database`), giấy phép Open Database License (ODbL); hình ảnh theo CC BY-SA.
Cơ sở dữ liệu phái sinh (ví dụ bảng dữ liệu sạch) nếu công bố phải ghi nguồn và chia sẻ theo cùng giấy phép ODbL.
Kho mã không chứa dữ liệu thật; hãy chạy các bước trên để tải. Không thu thập trường định danh người đóng góp
(`creator`, `editors_tags`...).

## Giới hạn
- Mô hình học từ sản phẩm *có* bảng dinh dưỡng; sản phẩm thiếu dinh dưỡng ngoài đời có thể khác loại.
- Không biết *lượng* đường/muối/chất béo nên khó phân biệt hai hạng kề nhau (B/C, C/D).
- Dữ liệu nghiêng về Mỹ và Pháp; ở thị trường chưa từng thấy, điểm giảm vài phần trăm.
- Công thức Nutri-Score có nhiều phiên bản; bản dump không ghi phiên bản (nhãn gần như theo công thức 2023).
