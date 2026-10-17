# Quyết định phạm vi và nguồn dữ liệu

## Kết quả kiểm toán lần 1 (Search API, 17/10/2026)

| Chỉ số | Giá trị | Nhận xét |
|---|---|---|
| Tổng bản ghi | 1.500 | 7 tệp từ nhiều lần chạy crawler |
| Bản ghi trùng mã vạch | 885 | chỉ khoảng 615 sản phẩm khác nhau |
| Có nhãn A-E hợp lệ | 1.486 | |
| Dùng được (nhãn + thành phần) | 1.482 | mục tiêu >= 10.000 |
| Hạng ít mẫu nhất | 144 | tính cả bản ghi trùng |
| Độ phủ NOVA | 87,0% | tốt |
| Thẻ thành phần có tiền tố en: | 93,8% | tốt |
| Thương hiệu lớn nhất | 3,5% | tốt cho GroupKFold |
| Quốc gia lớn nhất | 79,7% | lệch mạnh về một quốc gia |
| Trường cá nhân | CÓ (300 bản ghi) | từ tệp thu thập bằng phiên bản crawler cũ |
| Trường phiên bản Nutri-Score | `nutriscore_version`, `nutriscore_2021_tags`, `nutriscore_2023_tags` | cần thống nhất ở bước cleaning |

Search API trả lỗi HTTP 503 liên tục khi thu thập (17/10/2026), mỗi bộ lọc chỉ lấy được 1-2 trang.

## Kết quả kiểm toán lần 2 (bản dump Parquet, 17/10/2026)

| Chỉ số | Giá trị | Nhận xét |
|---|---|---|
| Tổng bản ghi | 30.000 | mẫu tự nhiên, seed 42 |
| Bản ghi trùng mã vạch | 0 | |
| Dùng được (nhãn + thành phần) | 29.998 | vượt mục tiêu 10.000 |
| Phân bố hạng | A 4.540 / B 3.309 / C 6.502 / D 7.128 / E 8.519 | lệch vừa phải (E/B khoảng 2,6 lần) |
| Độ phủ NOVA | 90,3% | |
| Thẻ thành phần có tiền tố en: | 94,8% | |
| Thiếu thương hiệu | 14,9% | lần kiểm toán đầu báo nhầm đây là "thương hiệu lớn nhất"; đã sửa raw_audit.py |
| Thương hiệu lớn nhất thật | khoảng 1,0% (`xx:U`) | tốt cho GroupKFold |
| Quốc gia | 162; Mỹ 37,8%, Pháp 28,9% | `en:world` (709) không phải quốc gia |
| Trường cá nhân | không có | |
| Trường phiên bản Nutri-Score | KHÔNG có trong dump (chỉ có `nutriscore_grade`, `nutriscore_score`) | xem bên dưới |

## Quyết định
- Nguồn dữ liệu: chuyển sang bản dump Parquet chính thức (`openfoodfacts/product-database`, tệp `food.parquet`).
  Dữ liệu Search API cũ được lưu trữ riêng, không dùng cho mô hình.
- Cách lấy mẫu: ngẫu nhiên tự nhiên 30.000 sản phẩm đủ điều kiện, seed 42 (giữ phân bố nhãn thật;
  xử lý mất cân bằng bằng trọng số lớp ở bước mô hình).
- Dữ liệu cá nhân: xóa tệp thô chứa trường cá nhân và làm trống bảng raw_products trước khi nạp dữ liệu mới.
- Phạm vi quốc gia: giữ toàn bộ 162 quốc gia (phương án a, chốt 18/10/2026). `countries_tags` và
  `n_countries` là đặc trưng; bỏ `en:world`. Kết quả mô hình phải báo cáo riêng cho Mỹ, Pháp và nhóm còn lại.
- Phiên bản công thức Nutri-Score: bản dump không có trường phiên bản, nên không tách được nhãn theo công thức
  2017/2021 và 2023. Bước 4 chỉ chẩn đoán (so điểm với hạng theo hai bảng ngưỡng, mục 9 của
  `reports/cleaning_report.md`), không lọc. Ghi là hạn chế của dự án.
- Làm sạch (Bước 4): loại nhãn ngoài A-E, dòng không có thành phần, mã vạch hỏng, `ingredients_n` > 150,
  trùng mã vạch và trùng nội dung; sản phẩm ≤ 1 thành phần chỉ gắn cờ, không loại. Không lọc dựa trên dinh dưỡng.
- Nhóm GroupKFold: theo thương hiệu đã chuẩn hóa; sản phẩm thiếu thương hiệu nhóm theo tên chuẩn hóa.

## Rủi ro đã biết
- Bản dump không có `pnns_groups_*`; dùng `food_groups_tags` thay thế (cấp 1 và cấp 2).
- Quốc gia lệch mạnh; cần báo cáo hiệu năng theo quốc gia.
- Nhãn trộn hai phiên bản công thức Nutri-Score; mô hình học một "nhãn trung bình" của hai công thức.
- Sản phẩm Mỹ không mang nhãn Nutri-Score thật trên bao bì; hạng là do Open Food Facts tự tính.
