# Dự đoán Nutri-Score từ thành phần, phụ gia, danh mục và NOVA

Dự án dùng dữ liệu Open Food Facts để dự đoán hạng Nutri-Score (A–E) cho sản phẩm thiếu bảng dinh dưỡng,
chỉ dựa trên thành phần, phụ gia, danh mục, nhóm NOVA và quốc gia. Chi tiết: `docs/problem_statement.md`.

**Sản phẩm chính là 5 notebook chạy sẵn, có kết quả**, đi theo quy trình 9 bước của môn học:

| Notebook | Bước trong quy trình |
|---|---|
| `notebooks/01_bai_toan.ipynb` | 1. Business Understanding, 2. Analytic Approach, 3. Data Requirements |
| `notebooks/02_thu_thap_du_lieu.ipynb` | 4. Data Collection: DuckDB SQL trên bản dump → PostgreSQL (JSONB) → SQL trích xuất |
| `notebooks/03_eda.ipynb` | 5. Data Understanding / EDA: kiểm toán bằng SQL + khám phá bằng pandas |
| `notebooks/04_chuan_bi_du_lieu.ipynb` | 6. Data Preparation: làm sạch, chia train/validation/test, đặc trưng |
| `notebooks/05_mo_hinh.ipynb` | 7. Modeling, 8. Evaluation trên tập dev (tập test còn khóa) |

## Cấu trúc thư mục
```text
.
├── notebooks/                 # 5 notebook ở trên (sản phẩm nộp chính)
├── src/                       # mã dùng lại nhiều lần, mỗi tệp ngắn
│   ├── fetch_from_dump.py     # Bước 4: lấy mẫu từ bản dump Parquet bằng SQL (DuckDB)
│   ├── load_raw_to_postgres.py# Bước 4: nạp JSON thô vào PostgreSQL
│   ├── db.py                  # kết nối PostgreSQL (.env), chạy câu SQL -> DataFrame
│   ├── cleaning.py            # Bước 6: chuẩn hóa, lọc, loại trùng, chống rò rỉ nhãn, group_id
│   ├── features.py            # Bước 6: sklearn Pipeline đặc trưng
│   └── modeling.py            # Bước 6-8: chia dữ liệu, khóa test, chỉ số, đánh giá chéo, mô hình
├── sql/
│   ├── init_raw_db.sql        # tạo bảng raw_products (JSONB)
│   ├── audit_queries.sql      # 11 truy vấn kiểm toán dữ liệu thô
│   └── extract_products.sql   # JSONB -> bảng phẳng
├── tests/                     # pytest
├── docs/                      # problem_statement, scope_decision, data_dictionary, eda_findings, giải thích mã
├── reports/                   # figures/ (biểu đồ do notebook lưu), model_results.json
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
   ```
   Notebook 05 mất khoảng 45 phút (tinh chỉnh Optuna và ablation).

Tập test 20% (`split == "test"` trong `data/final/split.parquet`) bị khóa: mã chỉ trả về tập này khi gọi
`select_test(..., final=True)`, việc chỉ làm một lần ở bước đánh giá cuối.

## Kiểm thử
```bat
pytest -q                   # toàn bộ test (test cần PostgreSQL tự bỏ qua nếu không kết nối được)
pytest -m integration -v    # chỉ test chạy SQL trên PostgreSQL thật
```

## Dữ liệu và giấy phép
Dữ liệu từ [Open Food Facts](https://world.openfoodfacts.org) (bản dump Parquet trên Hugging Face:
`openfoodfacts/product-database`), giấy phép Open Database License (ODbL); hình ảnh theo CC BY-SA.
Kho mã không chứa dữ liệu thật; hãy chạy các bước trên để tải. Không thu thập trường định danh người đóng góp
(`creator`, `editors_tags`...).

## Giới hạn
- Mô hình học từ sản phẩm *có* bảng dinh dưỡng; sản phẩm thiếu dinh dưỡng ngoài đời có thể khác loại.
- Không biết *lượng* đường/muối/chất béo nên khó phân biệt hai hạng kề nhau (B/C, C/D).
- Dữ liệu nghiêng về Mỹ và Pháp; ở thị trường chưa từng thấy, điểm giảm vài phần trăm.
- Công thức Nutri-Score có nhiều phiên bản; bản dump không ghi phiên bản (nhãn gần như theo công thức 2023).
