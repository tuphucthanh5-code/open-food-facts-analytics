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
- Bảng ngưỡng điểm -> hạng (đối chiếu 23/10/2026): lấy theo mã tính nhãn của chính Open Food Facts
  (`openfoodfacts-server/lib/ProductOpener/Nutriscore.pm`, hàm `compute_nutriscore_grade_2021` và
  `compute_nutriscore_grade_2023`), vì nhãn trong dump do mã này tính ra. Ngưỡng đồ uống khớp thêm với báo cáo
  chính thức của Ủy ban khoa học Nutri-Score (2/2023). Kết quả: ngưỡng thực phẩm thường trong mã đã đúng;
  bổ sung ngưỡng riêng của nhóm chất béo/dầu/hạt bản 2023 (A ≤ -6), nhận diện xấp xỉ qua `categories_tags`;
  phô mai và thịt đỏ không có ngưỡng riêng; đồ uống vẫn bỏ qua. Không dòng nào bị thêm hay loại.
  Sau khi sửa: chỉ 0,1% thực phẩm *chỉ* khớp bản 2017, 5,2% *chỉ* khớp bản 2023, 0,6% không khớp (chủ yếu là
  sữa uống mà bản 2023 tính là đồ uống). Điều này phù hợp với việc OFF tính lại toàn bộ theo công thức mới từ
  cuối 2024, nên nhãn gần như theo bản 2023.
- Làm sạch (Bước 4): loại nhãn ngoài A-E, dòng không có thành phần, mã vạch hỏng, `ingredients_n` > 150,
  trùng mã vạch và trùng nội dung; sản phẩm ≤ 1 thành phần chỉ gắn cờ, không loại. Không lọc dựa trên dinh dưỡng.
- Nhóm GroupKFold: theo thương hiệu đã chuẩn hóa; sản phẩm thiếu thương hiệu nhóm theo tên chuẩn hóa.
- Rò rỉ nhãn qua `labels_tags` (phát hiện khi rà soát mã 23/10/2026): cột này chứa logo Nutri-Score in trên bao bì
  (`en:nutriscore-grade-a`...; 1.848 dòng, 61% trùng đúng hạng thật) và các hệ thống điểm/cảnh báo tính từ bảng
  dinh dưỡng (Health Star Rating, Keyhole, nhãn "exceso"/"alto en" của Mỹ Latinh). Bước 4 bỏ các thẻ này khỏi
  `labels_tags` (2.263 dòng bị ảnh hưởng), KHÔNG loại dòng nào; `assert_no_leaky_values` kiểm tra giá trị, vì hai
  chốt cũ chỉ kiểm tra tên cột. Ranh giới: lời quảng cáo về một chất (`en:low-fat`, `en:no-added-sugar`) được giữ,
  vì có sẵn trên bao bì kể cả khi thiếu bảng dinh dưỡng; đây là lựa chọn có chủ đích, ghi là hạn chế.
- Mở rộng chốt chặn rò rỉ sang `categories_tags` (23/10/2026): rà mọi cột chữ của X bằng cùng mẫu nhận diện thì thấy
  1 dòng có thẻ danh mục do người dùng tự gõ `fr:nutri score a` (đúng hạng thật A). Bước 4 bỏ thẻ này giống
  `labels_tags` và `assert_no_leaky_values` kiểm tra cả hai cột. KHÔNG lọc `product_name`, `ingredients_tags`,
  `ingredients_text`: chỉ 14 dòng chứa chữ chú thích logo "NUTRI-SCORE ABCDE" hoặc rác OCR, không nêu hạng cụ thể,
  và mẫu dễ nhận nhầm trong câu văn (vd. "el consumo en exceso", cảnh báo thuốc nhuận tràng). Ghi là hạn chế.

## Quyết định đầu Bước 6 (feature engineering, 26/10/2026)
- Thành phần: mỗi thẻ thành một cột 0/1; thẻ hiếm gộp vào cột `n_rare_ingredients`. Đã đếm trên `clean_features.parquet`
  (29.904 dòng, 53.793 thẻ): ngưỡng ≥ 20 sản phẩm giữ 1.491 cột, ngưỡng ≥ 100 giữ 627 cột. Ngưỡng là tham số; chọn
  bằng điểm F1 trung bình theo lớp (GroupKFold) ở Bước 8, nếu gần nhau thì chọn 100 cho gọn và dễ giải thích.
  Danh sách thẻ giữ lại học trong từng fold huấn luyện; nếu đếm trên toàn bộ thì ghi là hạn chế (không dùng nhãn).
- `pnns_groups_1` thiếu 20,0% (5.966 dòng): bổ sung từ `categories_tags` bằng ánh xạ thẻ danh mục -> nhóm, học chỉ từ
  các dòng đã có nhóm (trong tập huấn luyện của từng fold), KHÔNG dùng nhãn Nutri-Score. Giữ cờ `pnns_groups_1_imputed`.
  Đo độ chính xác của phép bổ sung bằng cách giấu nhóm của các dòng đã có rồi suy lại. Thẻ mới sinh ra vẫn phải qua
  `assert_no_leaky_values`. Nhóm `alcoholic beverages` chỉ có 4 dòng nên gộp vào `beverages` (chốt 26/10/2026).
- NOVA: đưa vào như biến phân loại one-hot `nova_1`..`nova_4` và `nova_missing` (2.909 dòng thiếu; NOVA 2 chỉ có 454
  dòng). `nova_missing` trùng `flag_missing_nova`, chỉ giữ một. Không điền giá trị trung bình.
- Các cờ thiếu dữ liệu (`flag_few_ingredients`, `flag_missing_nova`, `flag_missing_brand`,
  `any_off_taxonomy_ingredient`, `pnns_groups_1_imputed`): vẫn tạo đủ ở Bước 6, gom thành nhóm đặc trưng `flags` riêng;
  Bước 8 so mô hình có và không có nhóm này rồi mới chốt.
- Đường cơ sở Bước 7: đoán hạng phổ biến nhất (28,4%) và đoán theo `pnns_groups_2`, tính lại bằng GroupKFold
  (học trên train, đo trên test) thay cho con số 50,5% ước lượng trên chính dữ liệu. Chỉ số chính: F1 trung bình theo lớp.

## Rủi ro đã biết
- Bản dump không có `pnns_groups_*`; dùng `food_groups_tags` thay thế (cấp 1 và cấp 2).
- Quốc gia lệch mạnh; cần báo cáo hiệu năng theo quốc gia.
- Nhãn có thể trộn hai phiên bản công thức Nutri-Score; mức trộn nhỏ (chỉ 0,1% thực phẩm chỉ khớp bản 2017),
  nhưng 94% khớp cả hai bảng nên không xác định được chắc chắn phiên bản của từng dòng.
- Sản phẩm Mỹ không mang nhãn Nutri-Score thật trên bao bì; hạng là do Open Food Facts tự tính.
