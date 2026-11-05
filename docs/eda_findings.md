# Phát hiện EDA (Bước 5)

Nguồn: `notebooks/03_eda.ipynb` (chạy trên 30.000 bản ghi thô, trước khi làm sạch). Biểu đồ trong `reports/figures/eda_*.png`.
Phần A kiểm toán bằng SQL trên PostgreSQL (`sql/audit_queries.sql`), phần B khám phá bằng pandas trên
`data/processed/products.parquet`.

## A. Kiểm toán bằng SQL: dữ liệu đạt mọi yêu cầu của notebook 01

| Yêu cầu | Kết quả | Mục |
|---|---|---|
| ≥ 10.000 bản ghi dùng được (nhãn A-E + có thành phần) | 29.998 / 30.000 | A2 |
| Mỗi hạng ≥ 100 mẫu | ít nhất 3.309 (B) | A2 |
| NOVA phủ ≥ 50% | 90,3% | A2 |
| Thẻ thành phần có tiền tố `en:` ≥ 90% | 94,8% (739.875 thẻ) | A5 |
| Thương hiệu lớn nhất ≤ 10% | 1,0% (`xx:U`); thiếu thương hiệu 14,9% | A5 |
| Không có trường cá nhân | không có | A6 |
| Không trùng mã vạch | 0 (kiểm tra bằng JOIN bảng với chính nó) | A1, A7 |

10.963 mã vạch bắt đầu bằng số 0 (phải giữ dạng chuỗi). Trường lộ đáp án có trong dữ liệu thô: `nutriments`,
`nutriscore_grade`, `nutriscore_score` (chỉ dùng làm y hoặc EDA).

## B. Phát hiện chính

| # | Phát hiện | Số liệu | Hệ quả |
|---|---|---|---|
| 1 | Hạng lệch vừa phải | A 15,1%, B 11,0%, C 21,7%, D 23,8%, E 28,4%; E/B = 2,57 | `class_weight="balanced"` + Macro-F1; không cần SMOTE |
| 2 | Mẫu đại diện cho toàn bộ dump | phân bố hạng mẫu và toàn dump (1,42 triệu sản phẩm) chênh < 0,5 điểm % | kết luận trên mẫu áp dụng được cho sản phẩm có nhãn |
| 3 | Biến đếm lệch phải | số thành phần: trung vị 11, trung bình 14,9, lớn nhất 231; số phụ gia: trung vị 1, trung bình 1,9 | log(1+x) + StandardScaler |
| 4 | Ngoại lai | 1.372 sản phẩm vượt ngưỡng IQR (44 thành phần) là món ăn thật nên giữ; 19 sản phẩm > 150 thành phần là lỗi nhập liệu nên loại; 4.011 sản phẩm ≤ 1 thành phần vẫn hợp lệ nên chỉ gắn cờ | quy tắc lọc ở notebook 04 |
| 5 | Bảng dinh dưỡng có giá trị phi lý | đường tối đa 1.110 g/100 g, muối 2.100 g/100 g, đạm âm | không ảnh hưởng mô hình vì không dùng làm đặc trưng |
| 6 | Thiếu dữ liệu | `labels_tags` 55%, `additives_tags` 44% (phần lớn là "không có"), `pnns_groups` ~20%, thương hiệu 15%, NOVA 9,7% | thiếu là một giá trị riêng `missing`; số đếm điền trung vị |
| 7 | Trùng nội dung | 75 sản phẩm trùng thương hiệu + tên + thành phần (khác mã vạch) | loại trùng, tránh lọt từ train sang test |
| 8 | Dinh dưỡng lộ đáp án | Spearman với hạng: điểm Nutri-Score 0,95; năng lượng 0,49; chất béo bão hòa 0,49; đường 0,45 | cấm làm đặc trưng |
| 9 | Biến được phép dùng chỉ tương quan vừa phải | NOVA 0,38; số phụ gia 0,32; số thành phần 0,28 | cần thông tin nội dung (thẻ thành phần, danh mục) |
| 10 | Hạng khác nhau theo thị trường | E: Mỹ 33,0%, Pháp 26,8%, còn lại 24,7% | đặc trưng quốc gia; báo cáo riêng Pháp / Mỹ / còn lại |
| 11 | Danh mục rất mạnh nhưng chưa đủ | "hạng phổ biến nhất của nhóm `pnns_groups_2`" đúng 50,6% trên sản phẩm có nhóm, 30,7% trên sản phẩm thiếu nhóm, 46,5% toàn bộ (học và đo trên cùng dữ liệu, chỉ để mô tả) | đường cơ sở phải vượt; giữ `missing` làm một nhóm; dùng thêm `categories_tags` |
| 12 | Thẻ thành phần đuôi dài | 55.647 thẻ khác nhau; 629 thẻ có ở ≥ 100 sản phẩm chiếm 84,5% lượt xuất hiện (ngưỡng 20: 1.489 thẻ, 89,7%) | `min_freq = 100` |
| 13 | Thành phần kéo về D/E (lift) | sô-cô-la sữa 1,86; dầu hạt cọ 1,81; bơ ca cao 1,80; bột sữa nguyên kem 1,78; bơ sữa 1,77. Kéo về A/B: nước ép cà chua 0,18; đậu Hà Lan 0,24; bột semolina 0,27-0,28; cải 0,30-0,31; đậu gà 0,37 (tỷ lệ D/E chung 52,2%) | gợi ý cho câu hỏi 2; kiểm tra lại bằng mô hình ở notebook 05 |
| 14 | Phụ gia đi kèm D/E | E476 1,84; E252 1,80; E503 1,74-1,77; E903 1,77; phẩm màu E110, E171, E102, E133, E129 khoảng 1,65-1,72 | phụ gia đi cùng bánh kẹo, không nhất thiết là nguyên nhân |
| 15 | NOVA liên hệ vừa với hạng | chi-bình phương 7.323, p ≈ 0; Cramér's V = 0,25 | NOVA hữu ích nhưng không thay được thành phần |
| 16 | Thẻ lộ đáp án trong `labels_tags` | 2.263 sản phẩm; logo `en:nutriscore-grade-*` trùng đúng hạng 61% trên 1.802 sản phẩm có logo, phần lớn còn lại lệch 1 hạng | xóa thẻ (giữ dòng), kiểm tra lại theo giá trị |

## Danh sách vấn đề → xử lý ở notebook 04

Bảng đầy đủ 13 vấn đề nằm ở cuối notebook 03. Tóm tắt: tách dinh dưỡng khỏi đặc trưng; xóa thẻ lộ đáp án; loại 2 dòng
thiếu nhãn, 19 dòng > 150 thành phần, 75 dòng trùng nội dung; chuẩn hóa thương hiệu và dùng làm nhóm khi chia dữ liệu;
thiếu thành `missing`; log + chuẩn hóa biến đếm; `min_freq = 100`; trọng số lớp; bỏ `en:world`.
