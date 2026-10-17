# Dự đoán Nutri-Score từ thành phần, phụ gia, danh mục và NOVA

Dự án dùng dữ liệu Open Food Facts để dự đoán hạng Nutri-Score (A–E) cho sản phẩm thiếu bảng dinh dưỡng,
chỉ dựa trên thành phần, phụ gia, danh mục và nhóm NOVA. Chi tiết xem `docs/problem_statement.md`.

## Cấu trúc thư mục
```text
.
├── .env.example               # mẫu cấu hình (không chứa mật khẩu thật)
├── .github/workflows/tests.yml  # tự chạy pytest mỗi lần push
├── requirements.txt           # thư viện chạy
├── requirements-dev.txt       # thêm pytest, jupyter, matplotlib
├── pytest.ini
├── sql/
│   ├── init_raw_db.sql        # tạo bảng raw_products (JSONB)
│   └── audit_queries.sql      # truy vấn kiểm toán dữ liệu thô
├── src/
│   ├── fetch_raw_food_facts.py    # thu thập dữ liệu qua Search API v2 (lượng nhỏ, minh họa)
│   ├── fetch_from_dump.py         # lấy mẫu từ bản dump Parquet chính thức (nguồn chính)
│   ├── load_raw_to_postgres.py    # nạp JSON thô vào PostgreSQL
│   ├── raw_audit.py               # kiểm toán dữ liệu thô (Bước 2)
│   └── staging.py                 # làm phẳng dữ liệu thô (Bước 3)
├── tests/                     # kiểm thử tự động (pytest)
├── notebooks/00_raw_audit.ipynb
├── reports/                   # báo cáo kiểm toán (raw_audit.md / .json)
├── docs/
│   ├── problem_statement.md
│   ├── scope_decision.md      # ghi quyết định phạm vi sau kiểm toán
│   └── data_dictionary.md     # từ điển cột của staging
├── data/{raw,processed,final,external}/  # dữ liệu cục bộ, không đẩy lên Git
│                                  # external/ chứa food.parquet tải từ Hugging Face
└── logs/                          # nhật ký cục bộ, không đẩy lên Git
```

## Cài đặt
```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```
Mở `.env` và điền mật khẩu PostgreSQL cùng email liên hệ thật cho `OFF_USER_AGENT`.

## Chạy
1. Tạo cơ sở dữ liệu và bảng:
   ```bat
   psql -U postgres -c "CREATE DATABASE food_facts_db;"
   psql -U postgres -d food_facts_db -f sql\init_raw_db.sql
   ```
2. Thu thập dữ liệu. Nguồn chính là bản dump Parquet chính thức (khoảng 8 GB):
   ```bat
   curl -L -C - -o data\external\food.parquet "https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet?download=true"
   python -m src.fetch_from_dump --describe
   python -m src.fetch_from_dump --n 30000 --seed 42
   ```
   Mẫu ngẫu nhiên tự nhiên, tái lập được nhờ `--seed`; chỉ lấy sản phẩm có nhãn A-E và có `ingredients_tags`,
   không đọc cột cá nhân. Search API (`python src\fetch_raw_food_facts.py`) chỉ dùng cho lượng nhỏ vì giới hạn
   10 request/phút và hay trả lỗi 503.
3. Nạp vào PostgreSQL:
   ```bat
   python src\load_raw_to_postgres.py
   ```
4. Kiểm toán dữ liệu thô (đọc từ tệp, không cần PostgreSQL):
   ```bat
   python -m src.raw_audit
   ```
   hoặc đọc từ cơ sở dữ liệu: `python -m src.raw_audit --source db`.
   Kết quả nằm ở `reports/raw_audit.md` và `reports/raw_audit.json`.

5. Staging: làm phẳng JSON thô thành hai bảng parquet tách biệt (đặc trưng / kiểm toán):
   ```bat
   python -m src.staging
   ```
   Kết quả: `data/processed/staging_features.parquet`, `data/processed/staging_audit.parquet`
   (không đẩy lên Git) và `reports/staging_report.md`. Xem `docs/data_dictionary.md`.

## Kiểm thử
```bat
pytest                      # toàn bộ test (test tích hợp tự bỏ qua nếu không có PostgreSQL)
pytest -m integration -v    # chỉ test cần PostgreSQL thật
pytest tests\test_raw_audit.py -v
```
Các test chạy không cần mạng và không cần máy chủ PostgreSQL (đối tượng giả thay thế).
Test tích hợp đọc cấu hình từ `.env` và tự bỏ qua khi không kết nối được.

## Giới hạn tốc độ
Search API của Open Food Facts giới hạn khoảng 10 request/phút cho mỗi IP, nên script giãn cách tối thiểu 7 giây
giữa các request. Hãy kiểm tra tài liệu hiện hành của Open Food Facts trước khi thu thập số lượng lớn.

## Dữ liệu và giấy phép
Dữ liệu từ [Open Food Facts](https://world.openfoodfacts.org) (bản dump Parquet trên Hugging Face: `openfoodfacts/product-database`), phát hành theo Open Database License (ODbL);
hình ảnh theo CC BY-SA. Kho mã này không chứa dữ liệu thật; hãy chạy script để tải.
Không lưu các trường định danh người đóng góp.

## Giới hạn của dự án
Sẽ bổ sung sau khi có kết quả kiểm toán.
