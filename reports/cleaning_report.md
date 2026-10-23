# Báo cáo làm sạch dữ liệu (Bước 4)

- Thời điểm: 2026-10-23T16:05:19+00:00
- Đầu vào: **30000** dòng; giữ lại: **29904** dòng (99.7%)
- Tham số: số thành phần tối đa 150; gắn cờ khi ≤ 1 thành phần; bỏ thẻ quốc gia en:world

## 1. Phễu làm sạch

| Bước | Loại bỏ | Còn lại |
|---|---|---|
| Đầu vào (sau staging) | 0 | 30000 |
| Nhãn không phải A-E | 2 | 29998 |
| Không có danh sách thành phần | 0 | 29998 |
| Mã vạch thiếu hoặc chứa ký tự không phải số | 0 | 29998 |
| Số thành phần > 150 (lỗi nhập liệu) | 19 | 29979 |
| Trùng mã vạch (giữ bản sửa gần nhất) | 0 | 29979 |
| Trùng nội dung: cùng thương hiệu + tên + thành phần | 75 | 29904 |

- Nhóm trùng nội dung có nhãn mâu thuẫn: 2

## 2. Chuẩn hóa

| Mục | Giá trị |
|---|---|
| Số thương hiệu khác nhau trước chuẩn hóa | 12940 |
| Số thương hiệu khác nhau sau chuẩn hóa | 10835 |
| Dòng có thẻ en:world (đã bỏ thẻ) | 709 |
| Dòng không còn quốc gia nào | 152 |
| Dòng có thẻ nhãn rò rỉ (Nutri-Score, Health Star...) đã bỏ khỏi labels_tags | 2263 |
| Dòng có thẻ rò rỉ (vd. fr:nutri score a) đã bỏ khỏi categories_tags | 1 |
| ingredients_n âm -> thiếu | 0 |
| ingredients_from_palm_oil_n âm -> thiếu | 0 |
| additives_n âm -> thiếu | 0 |
| ingredients_n thiếu, lấy theo số thẻ | 0 |

## 3. Phân bố hạng sau làm sạch

| Hạng | Số dòng | % |
|---|---|---|
| A | 4517 | 15.1 |
| B | 3296 | 11.0 |
| C | 6482 | 21.7 |
| D | 7112 | 23.8 |
| E | 8497 | 28.4 |

## 4. Cờ chất lượng (giữ dòng, chỉ gắn cờ)

| Cờ | Số dòng | % |
|---|---|---|
| few_ingredients | 3981 | 13.3 |
| missing_nova | 2909 | 9.7 |
| missing_brand | 4556 | 15.2 |
| any_off_taxonomy_ingredient | 9276 | 31.0 |

## 5. Nhóm cho GroupKFold

- Số nhóm: 15141; nhóm lớn nhất `brand:carrefour` có 328 dòng (1.1%)
- Sản phẩm thiếu thương hiệu được nhóm theo tên chuẩn hóa, không gộp chung.

## 6. Thương hiệu sau chuẩn hóa (10828 thương hiệu)

| Thương hiệu | Số dòng |
|---|---|
| carrefour | 328 |
| u | 308 |
| auchan | 229 |
| aldi | 193 |
| coop | 163 |
| nestle | 158 |
| casino | 132 |
| marque-repere | 113 |
| tesco | 109 |
| lidl | 108 |
| leader-price | 104 |
| great-value | 94 |
| hacendado | 93 |
| albert-heijn | 93 |
| monoprix | 88 |

## 7. Quốc gia (160 quốc gia, giữ toàn bộ theo phương án a)

| Quốc gia | Số dòng |
|---|---|
| en:united-states | 11271 |
| en:france | 8637 |
| en:germany | 2967 |
| en:united-kingdom | 1316 |
| en:spain | 1247 |
| en:italy | 1056 |
| en:switzerland | 748 |
| en:belgium | 704 |
| en:netherlands | 640 |
| en:canada | 422 |
| en:poland | 349 |
| en:australia | 259 |
| en:austria | 238 |
| en:ireland | 217 |
| en:portugal | 212 |

## 8. Số thành phần

- Trung vị 11.0; phân vị 99: 73.0; lớn nhất: 146

## 9. Kiểm tra điểm - hạng Nutri-Score (chẩn đoán phiên bản công thức, KHÔNG dùng để lọc)

- Bỏ qua 3121 đồ uống (bảng ngưỡng khác); 0 thực phẩm không có điểm.
- 1596 thực phẩm thuộc nhóm chất béo/dầu/hạt dùng ngưỡng riêng của bản 2023 (A ≤ -6). Phô mai và thịt đỏ không có ngưỡng riêng.
- Nguồn ngưỡng: mã tính nhãn của Open Food Facts (`Nutriscore.pm`). Phần lớn dòng 'không khớp' còn lại là sữa uống (bản 2023 tính là đồ uống) mà danh mục không gắn `en:beverages`.

| Kết quả | Số dòng | % |
|---|---|---|
| Khớp cả hai bảng ngưỡng | 25183 | 94.0 |
| Chỉ khớp ngưỡng cũ (2017) | 39 | 0.1 |
| Chỉ khớp ngưỡng mới (2023) | 1394 | 5.2 |
| Không khớp bảng nào | 167 | 0.6 |
