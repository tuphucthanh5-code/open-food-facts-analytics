# Phát biểu bài toán

## Tên đề tài
- Tiếng Việt: Dự đoán Nutri-Score cho sản phẩm thiếu thông tin dinh dưỡng từ thành phần, phụ gia, danh mục và nhóm NOVA – dữ liệu Open Food Facts.
- Tiếng Anh: Predicting Nutri-Score for Products Lacking Nutrition Facts from Ingredients, Additives, Categories and NOVA Group Using Open Food Facts Data.

## Bài toán
- **Đầu vào:** danh sách thành phần, phụ gia, danh mục sản phẩm, nhóm NOVA.
- **Đầu ra:** hạng Nutri-Score A–E (phân loại có thứ tự).
- **Bối cảnh sử dụng:** ước lượng chất lượng dinh dưỡng cho sản phẩm chưa có bảng dinh dưỡng trên Open Food Facts.

## Nguyên tắc chống rò rỉ nhãn
Bảng dinh dưỡng chỉ dùng để kiểm tra chất lượng nhãn và EDA, **không** đưa vào đặc trưng mô hình.

Các cột bị cấm làm đặc trưng:
- Nhãn và biến thể: `nutriscore_*`, `nutrition_grade_fr`, `nutrition_grades_tags`, `nutrition-score-fr_100g`.
- Toàn bộ `nutriments` (mọi hậu tố `_100g`, `_serving`, `_value`, `_unit`) và các tỷ lệ tự tính từ chúng.
- `nutrient_levels`, `nutrient_levels_tags`, `misc_tags`, `states_tags`, `data_quality_tags`.
- Các trường cá nhân: `creator`, `editors_tags`, `last_editor`, `correctors_tags`, `photographers_tags`, `informers_tags`, `checkers_tags`.

## Câu hỏi nghiên cứu
1. Chỉ từ thành phần, phụ gia, danh mục và NOVA, dự đoán Nutri-Score chính xác đến mức nào, và nhóm sản phẩm nào khó nhất?
2. Thành phần và phụ gia nào kéo hạng xuống D/E mạnh nhất?
3. Nhóm đặc trưng nào đóng góp nhiều nhất, và NOVA bổ sung bao nhiêu so với riêng thành phần?

## Giới hạn đã biết
- Tập huấn luyện gồm sản phẩm đã có bảng dinh dưỡng; sản phẩm thiếu dinh dưỡng thực tế có thể khác về loại hàng và thương hiệu.
- Dữ liệu lấy qua Search API không phải mẫu ngẫu nhiên.
- Công thức Nutri-Score có nhiều phiên bản; cần kiểm tra và thống nhất một phiên bản.
