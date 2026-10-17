# Bước 4 - Làm sạch: cách chép và chạy

Chép đè các tệp trong gói này vào D:\open-food-facts-analytics (giữ nguyên cấu trúc thư mục).

| Tệp | Mới / sửa |
|---|---|
| src/cleaning.py | mới - module làm sạch |
| src/raw_audit.py | sửa - "(thiếu)" không còn bị tính là thương hiệu lớn nhất |
| tests/test_cleaning.py | mới - 93 test |
| tests/test_raw_audit.py | sửa - thêm 2 test cho lỗi thương hiệu |
| tests/test_project_structure.py | sửa - yêu cầu có src/cleaning.py |
| docs/data_dictionary.md | sửa - thêm từ điển cột sau làm sạch |
| docs/scope_decision.md | sửa - kết quả kiểm toán lần 2 và các quyết định |
| README.md | sửa - thêm bước 6 |

Chạy:
    venv\Scripts\activate
    pytest -q
    python -m src.raw_audit --source db
    python -m src.cleaning
    git status

Kết quả: data/final/clean_features.parquet, data/final/clean_labels.parquet,
data/processed/clean_audit.parquet, reports/cleaning_report.md, reports/cleaning_report.json
