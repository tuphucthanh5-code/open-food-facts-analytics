# Kết quả mô hình (Bước 8)

- Thời điểm: 2026-11-05T06:31:25+00:00
- Chỉ dùng tập dev: **23922** dòng, 5 fold của Bước 7. Tập test (5982 dòng, vân tay `2e511eab89b680b7`) **vẫn khóa**: chưa mô hình nào được đo trên test.
- Cấu hình đặc trưng chính: `min_freq = 100`, các nhóm numeric, position, ingredients, additives, categories, nova, labels, countries; **bỏ nhóm flags**. Đặc trưng được fit lại trên phần huấn luyện của từng fold.
- LightGBM dừng sớm trên 10% số nhóm của phần huấn luyện (dừng sau 50 vòng không tiến bộ), không dùng fold đang đo.
- Thời gian chạy (giây): grid_search 57.6, optuna 3950.2, models 260.1, ablation 1060.7, total 5346.5.

## 1. So sánh mô hình: 5 fold trên dev (trung bình ± độ lệch chuẩn giữa các fold)

| Chỉ số | Đường cơ sở: hạng phổ biến nhất | Đường cơ sở: theo pnns_groups_2 | Logistic Regression | Cây quyết định nông | LightGBM (tham số mặc định) | LightGBM hồi quy thứ tự + ngưỡng | LightGBM (Optuna) |
|---|---|---|---|---|---|---|---|
| Macro-F1 (chỉ số chính) | 0.088 ± 0.000 | 0.412 ± 0.004 | 0.562 ± 0.010 | 0.481 ± 0.020 | 0.607 ± 0.009 | 0.557 ± 0.015 | 0.625 ± 0.007 |
| Weighted-F1 | 0.126 ± 0.000 | 0.434 ± 0.003 | 0.580 ± 0.008 | 0.493 ± 0.018 | 0.623 ± 0.008 | 0.572 ± 0.012 | 0.641 ± 0.005 |
| Accuracy | 0.284 ± 0.000 | 0.462 ± 0.003 | 0.579 ± 0.009 | 0.494 ± 0.013 | 0.623 ± 0.009 | 0.564 ± 0.014 | 0.642 ± 0.005 |
| QWK | 0.000 ± 0.000 | 0.463 ± 0.012 | 0.710 ± 0.016 | 0.562 ± 0.025 | 0.750 ± 0.014 | 0.786 ± 0.013 | 0.762 ± 0.012 |
| Lệch ≤ 1 hạng | 0.522 ± 0.000 | 0.734 ± 0.003 | 0.858 ± 0.008 | 0.796 ± 0.024 | 0.884 ± 0.006 | 0.911 ± 0.007 | 0.891 ± 0.006 |
| MAE (thang 0-4) | 1.606 ± 0.000 | 0.975 ± 0.011 | 0.625 ± 0.024 | 0.824 ± 0.047 | 0.541 ± 0.019 | 0.539 ± 0.020 | 0.511 ± 0.015 |
| Log-loss | 1.559 ± 0.000 | 1.281 ± 0.010 | 1.021 ± 0.015 | 1.359 ± 0.041 | 0.933 ± 0.015 | — | 0.900 ± 0.014 |

Log-loss của mô hình hồi quy thứ tự để trống vì mô hình này không cho xác suất từng hạng.

## 2. F1 từng hạng (gộp dự đoán ngoài fold)

| Hạng | Đường cơ sở: hạng phổ biến nhất | Đường cơ sở: theo pnns_groups_2 | Logistic Regression | Cây quyết định nông | LightGBM (tham số mặc định) | LightGBM hồi quy thứ tự + ngưỡng | LightGBM (Optuna) |
|---|---|---|---|---|---|---|---|
| A | 0.000 | 0.480 | 0.665 | 0.538 | 0.704 | 0.685 | 0.715 |
| B | 0.000 | 0.262 | 0.425 | 0.399 | 0.474 | 0.414 | 0.492 |
| C | 0.000 | 0.384 | 0.474 | 0.445 | 0.541 | 0.471 | 0.575 |
| D | 0.000 | 0.344 | 0.537 | 0.439 | 0.574 | 0.520 | 0.589 |
| E | 0.443 | 0.589 | 0.711 | 0.596 | 0.740 | 0.700 | 0.753 |

## 3. Theo quốc gia (dự đoán ngoài fold) và bài kiểm tra giữ lại Pháp (Macro-F1)

| Mô hình | Bán ở Pháp | Bán ở Mỹ | Còn lại (không Pháp, không Mỹ) | Giữ lại Pháp | QWK giữ lại Pháp |
|---|---|---|---|---|---|
| Đường cơ sở: hạng phổ biến nhất | 0.086 | 0.099 | 0.079 | 0.086 | 0.000 |
| Đường cơ sở: theo pnns_groups_2 | 0.437 | 0.406 | 0.390 | 0.425 | 0.547 |
| Logistic Regression | 0.597 | 0.541 | 0.554 | 0.559 | 0.723 |
| Cây quyết định nông | 0.505 | 0.471 | 0.475 | 0.471 | 0.562 |
| LightGBM (tham số mặc định) | 0.628 | 0.600 | 0.594 | 0.585 | 0.740 |
| LightGBM hồi quy thứ tự + ngưỡng | 0.585 | 0.547 | 0.545 | 0.532 | 0.771 |
| LightGBM (Optuna) | 0.650 | 0.619 | 0.607 | 0.601 | 0.763 |

## 4. Chọn tham số

Lưới nhỏ cho hai mô hình đơn giản (Macro-F1 trung bình 5 fold):

| Mô hình | Tham số | Macro-F1 |
|---|---|---|
| Logistic Regression | C=0.03 | 0.561 |
| Logistic Regression | C=0.1 | 0.562 |
| Logistic Regression | C=0.3 | 0.562 |
| Logistic Regression | C=1.0 | 0.560 |
| Cây quyết định nông | max_depth=4, min_samples_leaf=20 | 0.390 |
| Cây quyết định nông | max_depth=6, min_samples_leaf=20 | 0.446 |
| Cây quyết định nông | max_depth=8, min_samples_leaf=20 | 0.481 |

Optuna cho LightGBM: 40 lần thử (lần đầu là tham số mặc định), 34 chạy hết, 6 bị cắt sớm vì kém hơn trung vị. Tốt nhất: lần thử 36, Macro-F1 0.625.

| Tham số | Giá trị tốt nhất | Mặc định |
|---|---|---|
| learning_rate | 0.0263 | 0.05 |
| num_leaves | 189 | 31 |
| min_child_samples | 7 | 20 |
| reg_lambda | 0.0348 | 0.001 |
| reg_alpha | 0.0054 | 0.001 |
| colsample_bytree | 0.348 | 1.0 |
| subsample | 0.8872 | 1.0 |

Năm lần thử tốt nhất:

| Lần thử | Macro-F1 | Số cây trung bình | Tham số |
|---|---|---|---|
| 36 | 0.625 | 218 | learning_rate=0.0263, num_leaves=189, min_child_samples=7, reg_lambda=0.0348, reg_alpha=0.0054, colsample_bytree=0.348, subsample=0.8872 |
| 35 | 0.624 | 245 | learning_rate=0.023, num_leaves=236, min_child_samples=6, reg_lambda=0.074, reg_alpha=0.0029, colsample_bytree=0.31, subsample=0.9126 |
| 24 | 0.624 | 264 | learning_rate=0.0276, num_leaves=141, min_child_samples=5, reg_lambda=0.1046, reg_alpha=0.0029, colsample_bytree=0.323, subsample=0.8952 |
| 39 | 0.624 | 243 | learning_rate=0.0239, num_leaves=193, min_child_samples=6, reg_lambda=0.0407, reg_alpha=0.0017, colsample_bytree=0.3836, subsample=0.8758 |
| 28 | 0.623 | 185 | learning_rate=0.0309, num_leaves=201, min_child_samples=5, reg_lambda=0.6554, reg_alpha=0.0076, colsample_bytree=0.5356, subsample=0.9706 |

Lưu ý: tham số được chọn bằng chính 5 fold này nên Macro-F1 của mô hình đã tinh chỉnh hơi lạc quan. Con số khách quan sẽ có ở Bước 9 khi đo trên tập test.

## 5. Ablation (LightGBM (Optuna), 5 fold dev)

Cộng dồn từng nhóm đặc trưng (thứ tự theo kế hoạch):

| Bậc | Macro-F1 | Tăng so với bậc trước | QWK | Accuracy |
|---|---|---|---|---|
| Chỉ thành phần (thành phần + vị trí đường/muối/béo) | 0.559 ± 0.008 | — | 0.682 | 0.578 |
| + phụ gia | 0.561 ± 0.012 | +0.002 | 0.685 | 0.580 |
| + danh mục | 0.623 ± 0.007 | +0.063 | 0.761 | 0.640 |
| + NOVA | 0.624 ± 0.007 | +0.001 | 0.764 | 0.641 |
| + số đếm, nhãn, quốc gia (cấu hình chính) | 0.625 ± 0.007 | +0.001 | 0.762 | 0.642 |

Bỏ từng nhóm khỏi cấu hình chính (Macro-F1 giảm càng nhiều, nhóm càng quan trọng):

| Nhóm bị bỏ | Macro-F1 | Thay đổi | QWK |
|---|---|---|---|
| categories | 0.565 | -0.060 | 0.692 |
| ingredients | 0.598 | -0.027 | 0.738 |
| position | 0.618 | -0.007 | 0.757 |
| nova | 0.622 | -0.003 | 0.764 |
| additives | 0.623 | -0.002 | 0.764 |
| labels | 0.623 | -0.002 | 0.764 |
| countries | 0.624 | -0.001 | 0.764 |
| numeric | 0.626 | +0.001 | 0.766 |

## 6. Hai quyết định đã chốt, đo lại một lần

| Thay đổi so với cấu hình chính | Macro-F1 | Thay đổi | QWK |
|---|---|---|---|
| Cấu hình chính (min_freq = 100, bỏ flags) | 0.625 | — | 0.762 |
| min_freq = 20 | 0.630 | +0.005 | 0.768 |
| Có nhóm flags | 0.623 | -0.002 | 0.764 |

Độ lệch chuẩn Macro-F1 giữa 5 fold của cấu hình chính: 0.007. Thay đổi nhỏ hơn mức này coi như không khác biệt.

## 7. Kết luận

- Mô hình tốt nhất theo Macro-F1: **LightGBM (Optuna)** (learning_rate=0.0263, num_leaves=189, min_child_samples=7, reg_lambda=0.0348, reg_alpha=0.0054, colsample_bytree=0.348, subsample=0.8872): Macro-F1 0.625, QWK 0.762, accuracy 0.642.
- So với đường cơ sở `pnns_groups_2` (Macro-F1 0.412, QWK 0.463): **vượt cả hai chỉ số**.
- Mô hình này được fit lại trên toàn bộ dev và lưu ở `artifacts/best_model.joblib` (không đẩy lên Git); dự đoán ngoài fold lưu ở `data/processed/oof_predictions.parquet` cho phân tích lỗi ở Bước 9.
- Phiên bản thư viện: python 3.11.9, scikit-learn 1.9.1, lightgbm 4.7.0, optuna 5.0.0, numpy 2.4.6, pandas 3.0.6, scipy 1.17.1, joblib 1.6.0.
