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

## Quyết định
- Nguồn dữ liệu: chuyển sang bản dump Parquet chính thức (`openfoodfacts/product-database`, tệp `food.parquet`).
  Dữ liệu Search API cũ được lưu trữ riêng, không dùng cho mô hình.
- Cách lấy mẫu: ngẫu nhiên tự nhiên 30.000 sản phẩm đủ điều kiện, seed 42 (giữ phân bố nhãn thật;
  xử lý mất cân bằng bằng trọng số lớp ở bước mô hình).
- Dữ liệu cá nhân: xóa tệp thô chứa trường cá nhân và làm trống bảng raw_products trước khi nạp dữ liệu mới.
- Phạm vi quốc gia: (điền sau khi kiểm toán lại dữ liệu dump)
- Phiên bản công thức Nutri-Score: (điền sau khi kiểm toán lại)

## Rủi ro đã biết
- Bản dump không có `pnns_groups_*`; dùng `food_groups_tags` thay thế (cấp 1 và cấp 2).
- Quốc gia lệch mạnh; cần báo cáo hiệu năng theo quốc gia.
