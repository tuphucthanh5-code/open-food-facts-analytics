# Báo cáo kiểm toán dữ liệu thô

- Thời điểm: 2026-10-17T17:57:43+00:00
- Nguồn: PostgreSQL, bảng raw_products
- Tổng bản ghi: **30000**
- Có nhãn A-E hợp lệ: **29998** (100.0%)
- Dùng được (nhãn hợp lệ + có thành phần): **29998** (100.0%)

## 1. Kết quả các kiểm tra

| Kiểm tra | Trạng thái | Chi tiết |
|---|---|---|
| Có dữ liệu | OK | 30000 bản ghi |
| Trùng mã vạch | OK | 0 bản ghi trùng mã (xử lý ở bước cleaning) |
| Số bản ghi dùng được (nhãn hợp lệ + có thành phần) | OK | 29998 bản ghi, mục tiêu tối thiểu 10000 |
| Mỗi hạng A-E đủ mẫu | OK | hạng ít nhất có 3309 mẫu, ngưỡng 100 |
| Độ phủ NOVA | OK | 90.3% bản ghi dùng được có nova_group hợp lệ (ngưỡng 50%) |
| Thẻ thành phần đã chuẩn hóa taxonomy (tiền tố en:) | OK | 94.8% thẻ có tiền tố en: (ngưỡng 90%) |
| Mức tập trung thương hiệu | WARN | thương hiệu lớn nhất chiếm 14.9% (ngưỡng 10%), ảnh hưởng GroupKFold |
| Mức tập trung quốc gia | INFO | quốc gia lớn nhất chiếm 37.8% bản ghi dùng được |
| Không thu thập trường cá nhân | OK | không có |
| Trường rò rỉ nhãn có trong dữ liệu thô | INFO | nutriments, nutriscore_grade, nutriscore_score -> phải loại ở bước staging, không đưa vào đặc trưng |
| Trường liên quan Nutri-Score (kiểm tra phiên bản công thức) | INFO | nutriscore_grade, nutriscore_score |
| Mã vạch lưu dạng chuỗi | OK | 0 mã không phải chuỗi; 10963 mã bắt đầu bằng 0 |

## 2. Phân bố nhãn gốc (trước khi chuẩn hóa)

| Giá trị | Số bản ghi |
|---|---|
| e | 8519 |
| d | 7128 |
| c | 6502 |
| a | 4540 |
| b | 3309 |
| (thiếu) | 2 |

## 3. Phân bố hạng A-E

| Hạng | Có nhãn | Dùng được |
|---|---|---|
| A | 4540 | 4540 |
| B | 3309 | 3309 |
| C | 6502 | 6502 |
| D | 7128 | 7128 |
| E | 8519 | 8519 |

## 4. Hạng theo NOVA (bản ghi dùng được)

| Hạng | NOVA 1 | NOVA 2 | NOVA 3 | NOVA 4 |
|---|---|---|---|---|
| A | 1905 | 13 | 934 | 1152 |
| B | 639 | 114 | 682 | 1274 |
| C | 517 | 83 | 1367 | 4010 |
| D | 271 | 39 | 1723 | 4607 |
| E | 106 | 209 | 1199 | 6234 |

## 5. Quốc gia (bản ghi dùng được; tổng 162 quốc gia)

| Quốc gia | Số bản ghi |
|---|---|
| en:united-states | 11326 |
| en:france | 8660 |
| en:germany | 2972 |
| en:united-kingdom | 1318 |
| en:spain | 1254 |
| en:italy | 1059 |
| en:switzerland | 749 |
| en:world | 709 |
| en:belgium | 706 |
| en:netherlands | 640 |
| en:canada | 423 |
| en:poland | 349 |
| en:australia | 259 |
| en:austria | 239 |
| en:ireland | 217 |

## 6. Ngôn ngữ (bản ghi dùng được)

| Ngôn ngữ | Số bản ghi |
|---|---|
| en | 14638 |
| fr | 8214 |
| de | 2552 |
| es | 1287 |
| it | 844 |
| nl | 591 |
| pl | 272 |
| pt | 248 |
| sv | 160 |
| nb | 143 |
| bg | 133 |
| cs | 128 |
| fi | 115 |
| ro | 106 |
| da | 85 |

## 7. Thương hiệu (bản ghi dùng được; 12939 thương hiệu khác nhau)

| Thương hiệu | Số bản ghi |
|---|---|
| (thiếu) | 4456 |
| xx:U | 307 |
| xx:Carrefour | 247 |
| xx:auchan | 229 |
| xx:aldi | 188 |
| xx:coop | 160 |
| xx:nestle | 151 |
| xx:Casino | 131 |
| xx:marque-repere | 115 |
| xx:leader-price | 103 |
| xx:hacendado | 94 |
| xx:Monoprix | 86 |
| xx:carrefour | 84 |
| xx:albert-heijn | 80 |
| xx:Picard | 76 |

## 8. Thành phần

- Số thành phần trung bình: 24.7; trung vị: 20.0
- Tỷ lệ bản ghi chỉ có ≤ 1 thành phần: 6.1%
- Tỷ lệ thẻ có tiền tố en:: 94.8%

## 9. Tỷ lệ thiếu theo trường

| Trường | Vắng mặt (toàn bộ) | Vắng hoặc rỗng (toàn bộ) | Vắng hoặc rỗng (có nhãn) |
|---|---|---|---|
| code | 0.0% | 0.0% | 0.0% |
| product_name | 0.7% | 0.7% | 0.7% |
| brands_tags | 13.1% | 14.9% | 14.9% |
| countries_tags | 0.0% | 0.3% | 0.3% |
| categories_tags | 0.0% | 0.0% | 0.0% |
| pnns_groups_1 | 19.9% | 19.9% | 19.9% |
| pnns_groups_2 | 20.4% | 20.4% | 20.4% |
| ingredients_text | 0.0% | 0.0% | 0.0% |
| ingredients_tags | 0.0% | 0.0% | 0.0% |
| ingredients_n | 0.0% | 0.0% | 0.0% |
| ingredients_analysis_tags | 0.0% | 0.0% | 0.0% |
| additives_tags | 0.0% | 44.1% | 44.1% |
| additives_n | 0.0% | 0.0% | 0.0% |
| allergens_tags | 0.0% | 38.6% | 38.6% |
| labels_tags | 39.6% | 55.2% | 55.2% |
| nova_group | 9.7% | 9.7% | 9.7% |
| nutriscore_grade | 0.0% | 0.0% | 0.0% |
| nutriments | 0.0% | 0.5% | 0.5% |
| last_modified_t | 0.0% | 0.0% | 0.0% |
| lang | 0.0% | 0.0% | 0.0% |

## 10. Mã vạch

- Thiếu: 0; duy nhất: 30000; bản ghi trùng: 0
- Bắt đầu bằng 0: 10963; chứa ký tự không phải số: 0; không phải chuỗi: 0

## 11. Trường rò rỉ, trường cá nhân, trường Nutri-Score

- Rò rỉ nhãn: nutriments, nutriscore_grade, nutriscore_score
- Cá nhân: không có
- Liên quan Nutri-Score: nutriscore_grade, nutriscore_score
