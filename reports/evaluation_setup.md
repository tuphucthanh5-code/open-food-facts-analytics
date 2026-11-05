# Thiết lập đánh giá và đường cơ sở (Bước 7)

- Thời điểm: 2026-11-04T07:32:52+00:00
- Đầu vào: `data/final/clean_features.parquet` + `clean_labels.parquet`, **29904** dòng.
- Cách chia: StratifiedGroupKFold(shuffle=True) theo `group_id`, seed 42; test = 20%, dev chia 5 fold. Tập chia lưu ở `data/final/split.parquet`.
- **Tập test bị khóa**: chưa mô hình nào, kể cả đường cơ sở, được đo trên test. Mọi số dưới đây tính trên dev.
- Dấu vân tay tập test (SHA-256 của danh sách mã vạch test, 16 ký tự đầu): `2e511eab89b680b7`. Chạy lại mà ra chuỗi khác nghĩa là tập test đã đổi.

## 1. Chia dữ liệu

| Phần | Số dòng | % (của toàn bộ / của dev) | Số nhóm | A % | B % | C % | D % | E % |
|---|---|---|---|---|---|---|---|---|
| Toàn bộ | 29904 | 100.0 | 15141 | 15.1 | 11.0 | 21.7 | 23.8 | 28.4 |
| Dev | 23922 | 80.0 | 12088 | 15.1 | 11.0 | 21.7 | 23.8 | 28.4 |
| **Test (khóa)** | 5982 | 20.0 | 3053 | 15.1 | 11.0 | 21.7 | 23.8 | 28.4 |
| Dev - fold 0 | 4783 | 20.0 | 2408 | 15.1 | 11.0 | 21.7 | 23.8 | 28.4 |
| Dev - fold 1 | 4783 | 20.0 | 2424 | 15.1 | 11.0 | 21.7 | 23.8 | 28.4 |
| Dev - fold 2 | 4786 | 20.0 | 2429 | 15.1 | 11.0 | 21.7 | 23.8 | 28.4 |
| Dev - fold 3 | 4787 | 20.0 | 2417 | 15.1 | 11.0 | 21.7 | 23.8 | 28.4 |
| Dev - fold 4 | 4783 | 20.0 | 2410 | 15.1 | 11.0 | 21.7 | 23.8 | 28.4 |

## 2. Kiểm tra

- Không nhóm nào nằm ở cả dev và test; mỗi nhóm chỉ nằm trong một fold (`assert_split_valid`, chạy mỗi lần tạo tập chia).
- Nhóm lớn nhất: `brand:carrefour` 328 dòng (1.1%), nên không fold nào bị một thương hiệu chi phối.
- Chạy lại lệnh mà tập chia khác tệp đã lưu thì lệnh dừng, không ghi đè (khóa tập test).

## 3. Bài kiểm tra giữ lại Pháp (`en:france`, chỉ trong dev)

Huấn luyện trên sản phẩm không bán ở Pháp, đo trên sản phẩm bán ở Pháp. Sản phẩm không bán ở Pháp nhưng cùng thương hiệu (nhóm) với hàng Pháp bị bỏ khỏi phần huấn luyện, để mô hình không "nhớ" thương hiệu.

| Vai trò | Số dòng | % của dev | Số nhóm | A % | B % | C % | D % | E % |
|---|---|---|---|---|---|---|---|---|
| train: không bán ở Pháp | 13248 | 55.4 | 8875 | 15.2 | 11.1 | 20.6 | 23.6 | 29.5 |
| eval: bán ở Pháp | 6883 | 28.8 | 3213 | 14.8 | 10.8 | 22.9 | 24.3 | 27.3 |
| excluded: không bán ở Pháp nhưng cùng nhóm với hàng Pháp | 3791 | 15.8 | 578 | 15.5 | 11.3 | 23.3 | 23.4 | 26.5 |

## 4. Bộ chỉ số

| Chỉ số | Ý nghĩa | Tốt khi |
|---|---|---|
| Macro-F1 (chỉ số chính) | trung bình F1 của 5 hạng, mỗi hạng nặng như nhau | cao |
| Weighted-F1 | trung bình F1 theo số mẫu mỗi hạng | cao |
| Accuracy | tỷ lệ đoán đúng hạng | cao |
| QWK | Quadratic Weighted Kappa: phạt nặng khi đoán lệch xa (A thành E) | cao, tối đa 1 |
| Lệch ≤ 1 hạng | tỷ lệ dự đoán lệch tối đa một hạng | cao |
| MAE (thang 0-4) | số hạng lệch trung bình, A=0 ... E=4 | thấp |
| Log-loss | xác suất mô hình gán cho hạng đúng có tốt không | thấp |

Chỉ số chính là Macro-F1 vì lớp lệch (E 28,4%, B 11,0%): accuracy cao vẫn có thể bỏ quên hạng ít mẫu. QWK, lệch ≤ 1 hạng và MAE tính đến thứ tự A < B < C < D < E.

## 5. Đường cơ sở: 5 fold trên dev (trung bình ± độ lệch chuẩn giữa các fold)

| Chỉ số | Đoán hạng phổ biến nhất | Hạng phổ biến nhất theo pnns_groups_2 |
|---|---|---|
| Macro-F1 (chỉ số chính) | 0.088 ± 0.000 | 0.412 ± 0.004 |
| Weighted-F1 | 0.126 ± 0.000 | 0.434 ± 0.003 |
| Accuracy | 0.284 ± 0.000 | 0.462 ± 0.003 |
| QWK | 0.000 ± 0.000 | 0.463 ± 0.012 |
| Lệch ≤ 1 hạng | 0.522 ± 0.000 | 0.734 ± 0.003 |
| MAE (thang 0-4) | 1.606 ± 0.000 | 0.975 ± 0.011 |
| Log-loss | 1.559 ± 0.000 | 1.281 ± 0.010 |

## 6. F1 từng hạng (gộp dự đoán ngoài fold)

| Hạng | Đoán hạng phổ biến nhất | Hạng phổ biến nhất theo pnns_groups_2 |
|---|---|---|
| A | 0.000 | 0.480 |
| B | 0.000 | 0.262 |
| C | 0.000 | 0.384 |
| D | 0.000 | 0.344 |
| E | 0.443 | 0.589 |

## 7. Theo quốc gia (dự đoán ngoài fold, trên dev)

| Nhóm | Số dòng | Macro-F1 đa số | Macro-F1 pnns_groups_2 | Accuracy đa số | Accuracy pnns_groups_2 |
|---|---|---|---|---|---|
| Bán ở Pháp | 6883 | 0.086 | 0.437 | 0.273 | 0.491 |
| Bán ở Mỹ | 9005 | 0.099 | 0.406 | 0.329 | 0.462 |
| Còn lại (không Pháp, không Mỹ) | 8132 | 0.079 | 0.390 | 0.246 | 0.438 |

## 8. Giữ lại Pháp

| Chỉ số | Đoán hạng phổ biến nhất | Hạng phổ biến nhất theo pnns_groups_2 |
|---|---|---|
| Macro-F1 (chỉ số chính) | 0.086 | 0.425 |
| Weighted-F1 | 0.117 | 0.452 |
| Accuracy | 0.273 | 0.480 |
| QWK | 0.000 | 0.547 |
| Lệch ≤ 1 hạng | 0.516 | 0.756 |
| MAE (thang 0-4) | 1.614 | 0.889 |
| Log-loss | 1.560 | 1.240 |

## 9. Đọc kết quả

- Đoán một hạng cho tất cả đạt accuracy 0.284 nhưng Macro-F1 chỉ 0.088, vì 4/5 hạng có F1 = 0. Đây là lý do không dùng accuracy làm chỉ số chính.
- Đoán theo `pnns_groups_2` đạt accuracy 0.462 (EDA ước lượng 0.505 khi học và đo trên cùng dữ liệu, nên lạc quan hơn) và Macro-F1 0.412. Mô hình ở Bước 8 phải vượt mốc này trên cả Macro-F1 và QWK.
- Giữ lại Pháp: đoán theo `pnns_groups_2` đạt Macro-F1 0.425, so với 0.437 trên hàng Pháp khi Pháp nằm trong 5 fold. Ở Bước 8, khoảng cách này cho biết mô hình học từ nước khác dùng cho Pháp tốt đến đâu.
- Mô hình ở Bước 8 dùng đúng `evaluate()` và cùng các fold này, nên các con số so sánh được trực tiếp.
