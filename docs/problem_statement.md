# Phát biểu bài toán

Bản đầy đủ, có số liệu chạy trực tiếp: `notebooks/01_bai_toan.ipynb` (bước 1-3 của quy trình).

## Tên đề tài
- Tiếng Việt: Dự đoán Nutri-Score cho sản phẩm thiếu thông tin dinh dưỡng từ thành phần, phụ gia, danh mục và nhóm NOVA – dữ liệu Open Food Facts.
- Tiếng Anh: Predicting Nutri-Score for Products Lacking Nutrition Facts from Ingredients, Additives, Categories and NOVA Group Using Open Food Facts Data.

## 1. Business Understanding
- **Vấn đề:** Nutri-Score chỉ tính được khi có bảng dinh dưỡng. Trong bản dump Open Food Facts (4,8 triệu sản phẩm)
  chỉ khoảng 30% có hạng A-E; khoảng 381 nghìn sản phẩm có danh sách thành phần nhưng không có Nutri-Score.
- **Goal:** ước lượng hạng Nutri-Score cho sản phẩm chưa có bảng dinh dưỡng.
- **Objectives:** mô hình phân loại A-E chỉ từ thành phần, phụ gia, danh mục, NOVA, quốc gia; vượt rõ đường cơ sở
  "đoán theo nhóm danh mục"; chỉ ra thành phần/phụ gia và nhóm đặc trưng ảnh hưởng nhiều nhất.
- **Stakeholders:** người tiêu dùng (ứng dụng quét mã vạch), cộng đồng Open Food Facts, nhà bán lẻ và nhà sản xuất nhỏ,
  nhà nghiên cứu dinh dưỡng.
- **Câu hỏi nghiên cứu:**
  1. Chỉ từ các đặc trưng trên, dự đoán đúng đến mức nào, và nhóm sản phẩm/hạng nào khó nhất?
  2. Thành phần và phụ gia nào kéo hạng xuống D/E mạnh nhất?
  3. Nhóm đặc trưng nào đóng góp nhiều nhất, và NOVA bổ sung bao nhiêu so với riêng thành phần?
- **Tiêu chí thành công:** Macro-F1 > 0,412 và QWK > 0,463 (đường cơ sở `pnns_groups_2`, 5 fold trên dev);
  ≥ 85% dự đoán lệch tối đa 1 hạng; đo một lần trên tập test 20% đã khóa; không dùng dinh dưỡng hay thẻ lộ đáp án.

## 2. Analytic Approach
- Descriptive/diagnostic: EDA (notebook 03). Predictive: **phân loại 5 lớp có thứ tự** (A < B < C < D < E).
- Thuật toán: 2 đường cơ sở, Logistic Regression, Decision Tree, Random Forest, LightGBM (tinh chỉnh bằng Optuna).
- Chỉ số chính Macro-F1; thêm Accuracy, Precision, Recall, QWK, ROC-AUC, tỷ lệ lệch ≤ 1 hạng.
- Kiểm định: chia theo thương hiệu (StratifiedGroupKFold), test 20% khóa đến bước đánh giá cuối.

## 3. Data Requirements
- **Đầu vào (đặc trưng):** thành phần, phụ gia, danh mục (`categories_tags`, `pnns_groups_1/2`), NOVA, nhãn bao bì,
  quốc gia. **Đầu ra (y):** `nutriscore_grade` a-e.
- **Nguồn:** bản dump Parquet `openfoodfacts/product-database` (ODbL), mẫu ngẫu nhiên 30.000 sản phẩm (seed 42).
- **Yêu cầu:** ≥ 10.000 sản phẩm dùng được, mỗi hạng ≥ 100 mẫu, NOVA phủ ≥ 50%, thẻ `en:` ≥ 90%,
  thương hiệu lớn nhất ≤ 10%, không có trường cá nhân (kiểm tra bằng SQL ở notebook 03).

## Nguyên tắc chống rò rỉ nhãn
Bảng dinh dưỡng chỉ dùng để EDA, **không** đưa vào đặc trưng mô hình. Các cột bị cấm làm đặc trưng:
- Nhãn và biến thể: `nutriscore_*`, `nutrition_grade_fr`, `nutrition_grades_tags`, `nutrition-score-fr_100g`.
- Toàn bộ `nutriments` (mọi hậu tố `_100g`, `_serving`...) và các tỷ lệ tự tính từ chúng.
- `nutrient_levels`, `nutrient_levels_tags`, `misc_tags`, `states_tags`, `data_quality_tags`.
- Thẻ lộ đáp án nằm trong **giá trị** của `labels_tags`/`categories_tags`: logo Nutri-Score, Health Star Rating,
  Keyhole, nhãn cảnh báo "exceso"/"alto en".
- Các trường cá nhân: `creator`, `editors_tags`, `last_editor`, `correctors_tags`, `photographers_tags`,
  `informers_tags`, `checkers_tags` (không thu thập).

## Giới hạn đã biết
- Tập huấn luyện gồm sản phẩm đã có bảng dinh dưỡng; sản phẩm thiếu dinh dưỡng thực tế có thể khác về loại hàng và thương hiệu.
- Mô hình không biết *lượng* thành phần nên khó phân biệt hai hạng kề nhau.
- Công thức Nutri-Score có nhiều phiên bản và dump không ghi phiên bản. Chẩn đoán ở Bước 4 (bản mã cũ): 94,0% khớp cả hai
  bảng ngưỡng, chỉ 0,1% chỉ khớp bản 2017, nên nhãn gần như theo bản 2023; không lọc, ghi là hạn chế.
- Dữ liệu nghiêng về Mỹ (38%) và Pháp (29%).
