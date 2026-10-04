# Dự đoán Nutri-Score từ thành phần, phụ gia, danh mục và NOVA

Dự án dùng dữ liệu Open Food Facts để dự đoán hạng Nutri-Score (A–E) cho sản phẩm thiếu bảng dinh dưỡng,
chỉ dựa trên thành phần, phụ gia, danh mục và nhóm NOVA. Chi tiết xem `docs/problem_statement.md`.

## Cấu trúc thư mục
```text
.
├── .env.example               # mẫu cấu hình (không chứa mật khẩu thật)
├── requirements.txt
├── sql/init_raw_db.sql        # tạo bảng raw trong PostgreSQL
├── src/
│   ├── fetch_raw_food_facts.py    # thu thập dữ liệu qua Search API v2
│   └── load_raw_to_postgres.py    # nạp JSON thô vào PostgreSQL (JSONB)
├── docs/problem_statement.md
├── data/{raw,processed,final}/    # dữ liệu cục bộ, không đẩy lên Git
└── logs/                          # nhật ký cục bộ, không đẩy lên Git
```

## Cài đặt
```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```
Mở `.env` và điền mật khẩu PostgreSQL cùng email liên hệ thật cho `OFF_USER_AGENT`.

## Chạy
1. Tạo cơ sở dữ liệu và bảng:
   ```bat
   psql -U postgres -c "CREATE DATABASE food_facts_db;"
   psql -U postgres -d food_facts_db -f sql\init_raw_db.sql
   ```
2. Thu thập dữ liệu (ví dụ 100 sản phẩm cho mỗi hạng A và E):
   ```bat
   python src\fetch_raw_food_facts.py --target 100 --grades a,e
   ```
3. Nạp vào PostgreSQL:
   ```bat
   python src\load_raw_to_postgres.py
   ```

## Giới hạn tốc độ
Search API của Open Food Facts giới hạn khoảng 10 request/phút cho mỗi IP, nên script giãn cách tối thiểu 7 giây
giữa các request. Hãy kiểm tra tài liệu hiện hành của Open Food Facts trước khi thu thập số lượng lớn.

## Dữ liệu và giấy phép
Dữ liệu từ [Open Food Facts](https://world.openfoodfacts.org), phát hành theo Open Database License (ODbL);
hình ảnh theo CC BY-SA. Kho mã này không chứa dữ liệu thật; hãy chạy script để tải.
Không lưu các trường định danh người đóng góp.

## Giới hạn của dự án
Sẽ bổ sung sau khi có kết quả.
