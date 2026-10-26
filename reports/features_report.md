# Báo cáo đặc trưng (Bước 6)

- Thời điểm: 2026-10-26T09:26:58+00:00
- Đầu vào: `data/final/clean_features.parquet`, **29904** dòng. Không đọc nhãn.
- Ngưỡng mặc định: thẻ có ở ≥ 100 sản phẩm; chốt ngưỡng ở Bước 8 bằng F1 trung bình theo lớp (GroupKFold).
- Số đặc trưng dưới đây do fit trên toàn bộ dữ liệu, CHỈ để mô tả. Ở Bước 7-8 pipeline được fit lại trên tập huấn luyện của từng fold, nên số cột mỗi fold có thể chênh vài cột.

## 1. Số đặc trưng theo nhóm và ngưỡng

| Nhóm | Nội dung | min_freq = 20 | min_freq = 100 |
|---|---|---|---|
| numeric | Số đếm (thành phần, phụ gia, dị ứng, độ dài chữ, %, dầu cọ) | 7 | 7 |
| position | Vị trí đường/muối/chất béo, thành phần đầu tiên | 190 | 42 |
| ingredients | Multi-hot thành phần + số thẻ hiếm | 1492 | 628 |
| additives | Multi-hot phụ gia + số phụ gia theo nhóm số E | 214 | 116 |
| categories | pnns_groups_1/2, thẻ danh mục, cờ đồ uống/béo/phô mai | 700 | 262 |
| nova | NOVA 1-4 và thiếu | 5 | 5 |
| labels | Nhãn bao bì, thuần chay/dầu cọ, hữu cơ | 194 | 70 |
| countries | Quốc gia | 52 | 29 |
| flags | Cờ chất lượng dữ liệu | 4 | 4 |
| **Tổng** |  | **2858** | **1163** |

## 2. Bổ sung `pnns_groups_1` từ `categories_tags`

- Thẻ danh mục dùng được: có ở ≥ 5 sản phẩm đã biết nhóm; chỉ bổ sung khi nhóm phổ biến nhất của thẻ chiếm > 50%. Không dùng nhãn.
- Gộp nhóm: alcoholic beverages -> beverages.
- Thử trên 4867 sản phẩm đã biết nhóm (giấu nhóm, chia theo `group_id`, seed 42): bổ sung được 100.0%, đúng 95.7% trong số đó. Con số hơi lạc quan vì sản phẩm thật sự thiếu nhóm thường có thẻ danh mục chung chung hoặc chưa dịch.
- Áp dụng cho 5966 sản phẩm thiếu nhóm: bổ sung 3038 (50.9%), còn 2928 để `missing`.

| Nhóm bổ sung | Số sản phẩm |
|---|---|
| sugary snacks | 1372 |
| milk and dairy products | 532 |
| cereals and potatoes | 287 |
| fats and sauces | 274 |
| salty snacks | 213 |
| fish meat eggs | 130 |
| composite foods | 95 |
| beverages | 82 |
| fruits and vegetables | 53 |

## 3. Đặc trưng tự tạo: tỷ lệ sản phẩm có đặc trưng

| Đặc trưng | % sản phẩm |
|---|---|
| Có đường (thẻ en: chứa sugar, syrup, glucose...) | 51.7 |
| Đường là thành phần đầu tiên | 8.0 |
| Có muối | 54.0 |
| Có chất béo/dầu | 44.1 |
| Chất béo/dầu là thành phần đầu tiên | 2.5 |
| Có dầu cọ | 9.4 |
| Chữ thành phần có ghi tỷ lệ % | 45.2 |
| Hữu cơ (nhãn organic/bio) | 10.5 |
| Đồ uống (en:beverages) | 10.4 |
| Chất béo/dầu/hạt (danh mục) | 5.5 |
| Phô mai (en:cheeses) | 4.1 |

## 4. Phụ gia theo nhóm số E (% sản phẩm có ít nhất một)

| Nhóm | % sản phẩm |
|---|---|
| add_colours | 15.2 |
| add_preservatives | 19.1 |
| add_antioxidants_acids | 36.8 |
| add_thickeners_emulsifiers | 27.5 |
| add_acidity_anticaking | 10.4 |
| add_flavour_enhancers | 2.5 |
| add_sweeteners | 4.8 |
| add_other | 7.7 |

## 5. NOVA (one-hot)

| Cột | Số sản phẩm |
|---|---|
| nova_1 | 3414 |
| nova_2 | 454 |
| nova_3 | 5884 |
| nova_4 | 17243 |
| nova_missing | 2909 |

## 6. Kiểm tra chống rò rỉ

- `RowFeatures` từ chối bảng đầu vào có cột nhãn, dinh dưỡng hay trường cá nhân (`assert_no_leakage`).
- `TagVectorizer` từ chối thẻ rò rỉ (logo Nutri-Score, Health Star...) lọt vào danh sách cột.
- `assert_feature_names_clean` kiểm tra mọi tên đặc trưng sau khi fit: không có cột bị cấm.
- Phần cần học (ngưỡng thẻ, ánh xạ danh mục, trung vị, chuẩn hóa) chỉ fit trên tập huấn luyện.
