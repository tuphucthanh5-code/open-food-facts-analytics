# Phát hiện từ phân tích khám phá (Bước 5)

Nguồn: `notebooks/01_eda.ipynb`, chạy trên dữ liệu sạch (29.904 sản phẩm). Mọi con số dưới đây do notebook tính trực tiếp từ dữ liệu,
chạy lại notebook là số cập nhật theo. Biểu đồ nằm trong `reports/figures/`.

Quy ước: **hạng D/E** gọi là nhóm "xấu"; **lift** = P(D/E | có thành phần) / P(D/E) chung; **Cramér's V** đo độ mạnh liên hệ giữa hai biến phân loại
(0 = độc lập, 1 = phụ thuộc hoàn toàn); **Spearman ρ** đo tương quan thứ hạng.

## Các phát hiện

| # | Phát hiện (có số liệu) | Biểu đồ |
|---|---|---|
| 1 | Trong 29.904 sản phẩm, hạng E chiếm nhiều nhất (28,4%, 8.497 sản phẩm) và hạng B ít nhất (11,0%, 3.296); lớp lớn nhất gấp 2,6 lần lớp nhỏ nhất, mất cân bằng nhẹ nên dùng trọng số lớp và F1 trung bình theo lớp. | [eda_01](../reports/figures/eda_01_phan_bo_nhan.png) |
| 2 | Tỷ lệ hạng E là 33,0% ở Mỹ, 26,6% ở Pháp và 24,7% ở nhóm còn lại; khác biệt có ý nghĩa thống kê (chi-bình phương p<0,001) nhưng mức liên hệ nhỏ (Cramér's V = 0,063). 121 sản phẩm bán ở cả hai nước được loại khỏi phép so sánh này. | [eda_02](../reports/figures/eda_02_nhan_theo_quoc_gia.png) |
| 3 | Nhóm "sugary snacks" có 91,5% sản phẩm hạng D/E trong khi nhóm "fruits and vegetables" chỉ 12,8%; nhưng 5.966 sản phẩm (20,0%) không có `pnns_groups_1`, nên đặc trưng danh mục cần xử lý giá trị thiếu (dùng `categories_tags` bổ sung). | [eda_03](../reports/figures/eda_03_nhan_theo_nhom_danh_muc.png) |
| 4 | Có 53.793 thẻ thành phần khác nhau, trong đó 84,1% chỉ xuất hiện đúng 1 lần và 93,7% dưới 5 lần; chỉ 1.491 thẻ có từ 20 sản phẩm và 627 thẻ từ 100 sản phẩm, nên Bước 6 cần ngưỡng tần suất tối thiểu (các thẻ ≥100 vẫn phủ 95,7% sản phẩm). | [eda_04](../reports/figures/eda_04_duoi_dai_thanh_phan.png) |
| 5 | Với P(D/E) chung = 52,2%, các thành phần có lift cao nhất gồm e127, milk-chocolate, confectioner-s-glaze (lift 1,87 đến 1,85), trong khi green-bean chỉ 0,04; phụ gia có lift cao nhất là e127 (1,87). | [eda_05](../reports/figures/eda_05_lift_thanh_phan_phu_gia.png) |
| 6 | Tuy nhiên 54,0% sản phẩm chứa 10 thành phần lift cao nhất thuộc nhóm "sugary snacks", nên lift phản ánh một phần việc thành phần đó nằm trong đồ ngọt chứ chưa chứng minh nó tự kéo hạng xuống; cần phân tích SHAP trong từng nhóm ở Bước 9. | [eda_05](../reports/figures/eda_05_lift_thanh_phan_phu_gia.png) |
| 7 | Số phụ gia trung vị tăng từ 0 (hạng A) lên 2 (hạng E) và số thành phần trung vị từ 4 lên 14; tương quan Spearman với hạng là 0,32 (phụ gia) và 0,28 (thành phần), tức yếu đến vừa, nên hai số đếm này hữu ích nhưng không đủ để dự đoán một mình. | [eda_06](../reports/figures/eda_06_phu_gia_thanh_phan_theo_hang.png) |
| 8 | Trong 26.995 sản phẩm có NOVA, 55,4% sản phẩm NOVA 1 đạt hạng A còn 36,1% sản phẩm NOVA 4 là hạng E; liên hệ vừa phải (Cramér's V = 0,295, Spearman ρ = 0,37, chi-bình phương p<0,001). | [eda_07](../reports/figures/eda_07_nova_vs_nutriscore.png) |
| 9 | Quan hệ không đơn điệu: nhóm NOVA 2 (nguyên liệu chế biến như dầu, đường, bơ) có 45,6% hạng E dù chỉ ở mức chế biến thấp, nên NOVA nên đưa vào mô hình như biến phân loại chứ không phải biến số liên tục. | [eda_07](../reports/figures/eda_07_nova_vs_nutriscore.png) |
| 10 | Tỷ lệ thiếu thương hiệu là 31,5% ở Mỹ so với 4,9% ở Pháp, và thiếu NOVA là 11,6% so với 7,0%; sản phẩm Mỹ cũng nghiêng về siêu chế biến hơn (68,2% NOVA 4 so với 59,6% ở Pháp). | [eda_08](../reports/figures/eda_08_thieu_du_lieu_theo_quoc_gia.png) |
| 11 | Điểm Nutri-Score tương quan Spearman 0,95 với hạng, còn đường, béo bão hòa và muối lần lượt 0,45, 0,49 và 0,31; vì vậy bảng dinh dưỡng và điểm chỉ nằm trong bảng audit, không bao giờ làm đặc trưng. | [eda_09](../reports/figures/eda_09_ro_ri_dinh_duong.png) |
| 12 | Rò rỉ cũng ẩn trong `labels_tags`: 1.799 sản phẩm (6,0%) in sẵn logo Nutri-Score trên bao bì và logo trùng hạng thật ở 60,9% trường hợp; cùng với các nhãn Health Star, Keyhole và cảnh báo "exceso", Bước 4 đã bỏ các thẻ này khỏi 2.263 dòng. | [eda_09](../reports/figures/eda_09_ro_ri_dinh_duong.png) |
| 13 | Sản phẩm chỉ có ≤ 1 thành phần chiếm 32,0% hạng A và 24,8% hạng B nhưng chỉ 5,7% hạng D; riêng hạng B thiếu NOVA tới 18,1% so với 6,8% hạng D, nên việc thiếu dữ liệu tự nó mang thông tin về nhãn và phải ghi vào phần hạn chế (3.981 sản phẩm bị gắn cờ ít thành phần). | [eda_10](../reports/figures/eda_10_co_chat_luong_theo_hang.png) |
| 14 | Trong các nhóm có từ 400 sản phẩm, "meat" (entropy 0,97) và "dressings and sauces" (0,93) có hạng lẫn lộn nhất, còn "chocolate products" (0,24) gần như đồng nhất; chỉ cần đoán hạng phổ biến nhất trong từng nhóm `pnns_groups_2` đã đạt 50,5% độ chính xác (so với 28,4% nếu đoán một hạng cho tất cả), đây là mốc đường cơ sở cho Bước 7. | [eda_11](../reports/figures/eda_11_do_kho_theo_nhom.png) |

## Quyết định rút ra cho các bước sau

| Từ phát hiện | Quyết định | Áp dụng ở |
|---|---|---|
| 1 | Giữ trọng số lớp, không dùng SMOTE; đo bằng F1 trung bình theo lớp | Bước 7-8 |
| 2, 10 | Báo cáo kết quả riêng cho Mỹ, Pháp và nhóm còn lại; nhớ rằng nhãn Mỹ do Open Food Facts tự tính | Bước 9 |
| 3 | Đặc trưng danh mục lấy từ cả `pnns_groups_*` và `categories_tags` vì 20,0% thiếu `pnns_groups_1` | Bước 6 |
| 4 | Đặt ngưỡng tần suất tối thiểu cho thành phần (gợi ý thử 20 và 100 sản phẩm), phần còn lại gộp vào một cột "hiếm" | Bước 6 |
| 5, 6 | Không kết luận "thành phần X làm giảm hạng" chỉ từ lift; dùng SHAP trong từng nhóm sản phẩm | Bước 9 |
| 9 | NOVA đưa vào như biến phân loại (one-hot), có thêm giá trị "thiếu" | Bước 6 |
| 11, 12 | Giữ quy tắc chống rò rỉ; `assert_no_leaky_values` kiểm tra cả giá trị | Đã làm ở Bước 4 |
| 13 | Ghi vào hạn chế: cờ thiếu dữ liệu mang thông tin về nhãn; thử mô hình có và không có các cờ | Bước 8 |
| 14 | Đường cơ sở 1: đoán hạng phổ biến nhất (28,4%); đường cơ sở 2: hạng phổ biến nhất theo `pnns_groups_2` (50,5%, ước lượng trên chính dữ liệu này nên hơi lạc quan) | Bước 7 |

## Trả lời sơ bộ các câu hỏi nghiên cứu

1. **Độ chính xác và nhóm khó nhất:** chưa đo được, cần mô hình. Dữ liệu gợi ý các nhóm "meat", "dressings and sauces", "fish and seafood" và "unsweetened beverages" khó nhất (phát hiện 14); đoán theo danh mục đơn thuần đã đạt khoảng 50%.
2. **Thành phần và phụ gia kéo xuống D/E:** các phụ gia e127, e476, e252 và các thành phần như dầu hạt cọ, sô cô la sữa có lift cao (phát hiện 5), nhưng phần lớn nằm trong đồ ngọt (phát hiện 6), nên cần SHAP để tách ảnh hưởng.
3. **Đóng góp của nhóm đặc trưng, NOVA bổ sung bao nhiêu:** NOVA có liên hệ vừa phải với hạng (V = 0,295, phát hiện 8); mức bổ sung thực sự phải đo bằng thí nghiệm có và không có NOVA ở Bước 8.

## Hạn chế của phân tích này

- Lift, tương quan và entropy chỉ mô tả mối liên hệ, **không phải quan hệ nhân quả**.
- Các phép tính dùng nhãn là để EDA; chúng không được đưa vào đặc trưng và không phải kết quả mô hình.
- Nhãn có thể trộn công thức Nutri-Score 2017 và 2023 (xem `docs/scope_decision.md`, mục 9 của `reports/cleaning_report.md`).
- Nhóm quốc gia "Mỹ", "Pháp", "Còn lại" không chồng nhau; 121 sản phẩm bán ở cả hai nước bị loại khỏi phép so sánh theo quốc gia.
- Ngưỡng "ít thành phần" theo `ingredients_n` ≤ 1 (3.981 sản phẩm, 13,3%), đúng quyết định đã chốt.
