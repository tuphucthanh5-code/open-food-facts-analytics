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

## Cách làm Bước 6 và điểm lệch so với kế hoạch (26/10/2026)
- Mọi biến đổi nằm trong một sklearn Pipeline (`build_feature_pipeline`); không lưu ma trận đặc trưng fit trên toàn bộ
  dữ liệu, vì ngưỡng thẻ, ánh xạ danh mục và phép chuẩn hóa phải học lại trên tập huấn luyện của từng fold.
  `reports/features_report.md` chỉ mô tả (fit trên toàn bộ để đếm cột, không dùng nhãn).
- Cùng một `min_freq` cho mọi cột danh sách thẻ (thành phần, phụ gia, danh mục, nhãn, quốc gia, thành phần đầu tiên)
  để dễ giải thích. Ngưỡng 100: 1.163 đặc trưng; ngưỡng 20: 2.858.
- Kết quả bổ sung `pnns_groups_1`: bổ sung được 3.038/5.966 sản phẩm thiếu (50,9%), còn 2.928 để `missing` vì thẻ
  danh mục chung chung (`en:snacks`, `en:desserts`) không đủ thuần hoặc chưa dịch (`en:yogures`). Thử trên 20% sản phẩm
  đã biết nhóm (chia theo `group_id`): đúng 95,7%; con số này lạc quan hơn thực tế vì lý do trên. `pnns_groups_2`
  chưa bổ sung (thiếu ở cùng các dòng), để giá trị `missing`.
- Lệch kế hoạch "thành phần đứng thứ 1-3": `ingredients_tags` chèn thẻ cha ngay sau mỗi thành phần
  (`en:sugar`, `en:added-sugar`, `en:disaccharide`), nên thẻ thứ 2-3 thường chỉ là thẻ cha của thành phần đầu. Chỉ dùng
  thành phần **đầu tiên** (luôn đúng) và vị trí **tương đối** của đường, muối, chất béo (1 = đứng đầu, 0 = không có).
  Nhận diện đường/muối/chất béo theo từ trong thẻ `en:`, là xấp xỉ, ghi là hạn chế.
- Không dùng `brand`/`brands_tags` làm đặc trưng: thương hiệu là nhóm GroupKFold, nên thương hiệu ở tập kiểm tra không
  bao giờ có trong tập huấn luyện. Không làm TF-IDF trên `ingredients_text` (tùy chọn trong kế hoạch), để sau nếu cần.
- `flag_missing_nova` không đưa vào vì trùng `nova_missing`. Khi Bước 8 bỏ nhóm `flags`, mô hình vẫn biết NOVA bị thiếu
  qua nhóm `nova`; muốn bỏ hẳn tín hiệu "thiếu" thì phải bỏ cả cột `nova_missing`.

## Quyết định Bước 7 (chia dữ liệu và đánh giá, 04/11/2026)
- Trước Bước 7 đã chạy lại toàn bộ chuỗi từ PostgreSQL (raw_audit -> staging -> cleaning -> features) vào thư mục tạm
  và so với tệp hiện có: 5 tệp parquet giống từng giá trị, `raw_audit.json`, `cleaning_report.json`,
  `features_report.json` và `feature_names.txt` không đổi. Dữ liệu ổn định, chưa cần làm lại bước nào.
- Tập test 20%: dùng **StratifiedGroupKFold** 5 phần theo `group_id` (seed 42), lấy phần đầu tiên làm test (5.982 dòng,
  3.053 nhóm). Lý do: so với GroupShuffleSplit (thử cùng seed: 21,4% dữ liệu, tỷ lệ hạng lệch tới 0,75 điểm %), cách
  này cho đúng 20,0% và tỷ lệ từng hạng lệch tối đa 0,01 điểm %, lại cùng công cụ với 5 fold bên trong.
- Khóa tập test: lưu `data/final/split.parquet`; `select_test` chỉ trả dữ liệu khi gọi với `final=True` (Bước 9);
  báo cáo ghi dấu vân tay SHA-256 của danh sách mã vạch test (`2e511eab89b680b7`); lệnh dừng nếu tập chia mới khác tệp
  đã lưu (chỉ ghi đè với `--overwrite-split`, và phải ghi lý do vào tệp này). Đường cơ sở cũng không được đo trên test.
- Dev 80% (23.922 dòng, 12.088 nhóm) chia 5 fold bằng StratifiedGroupKFold (seed 42); mọi mô hình ở Bước 8 dùng cùng
  các fold này qua hàm `evaluate()`, hàm này tạo và fit một mô hình mới trong từng fold.
- Bài kiểm tra giữ lại quốc gia: **chỉ Pháp** (chọn 04/11/2026, gọn hơn khi trình bày; Pháp là thị trường gốc của
  Nutri-Score). Chạy trong dev, không đụng tập test. Đo trên sản phẩm có `en:france` (6.883 dòng), huấn luyện trên sản
  phẩm không bán ở Pháp (13.248 dòng). **Bỏ khỏi phần huấn luyện** 3.791 dòng (578 nhóm) không bán ở Pháp nhưng cùng
  `group_id` với hàng Pháp, theo đúng nguyên tắc GroupKFold, để kết quả không lạc quan nhờ "nhớ" thương hiệu.
- Bộ chỉ số: Macro-F1 (chính), Weighted-F1, accuracy, QWK, tỷ lệ lệch ≤ 1 hạng, MAE thang 0-4, log-loss. Báo cáo thêm
  theo nhóm quốc gia (bán ở Pháp / bán ở Mỹ / còn lại; sản phẩm bán ở cả hai nước tính ở cả hai nhóm).
- Hai đường cơ sở (5 fold trên dev): đoán hạng phổ biến nhất: Macro-F1 0,088, accuracy 0,284; đoán hạng phổ biến nhất
  theo `pnns_groups_2` (thiếu nhóm thành `missing`, nhóm chưa gặp thành hạng phổ biến nhất): Macro-F1 0,412, accuracy
  0,462, QWK 0,463. Con số 50,5% của EDA là accuracy học và đo trên cùng dữ liệu nên lạc quan hơn 0,462.
  Xác suất của đường cơ sở theo nhóm được làm trơn (`smoothing = 1`) chỉ để log-loss xác định; không ảnh hưởng hạng đoán.

## Quyết định Bước 8 (mô hình, 05/11/2026)
- **Cấu hình đặc trưng chính: `min_freq = 100`, bỏ nhóm `flags`** (người dùng chốt 05/11/2026, trước khi đo).
  - Ngưỡng 100: mỗi thẻ có ít nhất 100 ví dụ trong phần huấn luyện nên trọng số học được ổn định; ít đặc trưng hơn
    (1.163 so với 2.858 cột ở ngưỡng 20, đếm trên toàn bộ dữ liệu trong `reports/features_report.md`; mỗi fold dev ít
    hơn một chút), chạy nhanh hơn, giải thích bằng SHAP dễ hơn.
  - Bỏ `flags` (`flag_few_ingredients`, `flag_missing_brand`, `share_ingredients_off_taxonomy`,
    `pnns_groups_1_imputed`): các cột này mô tả chất lượng nhập liệu chứ không mô tả món ăn. EDA phát hiện 13 cho thấy
    việc thiếu dữ liệu tự nó đoán được nhãn; sản phẩm mục tiêu (thiếu dinh dưỡng) thường thiếu cả dữ liệu khác, nên mô
    hình dựa vào cờ có thể lệch. Không phải rò rỉ nhãn (cờ không tính từ dinh dưỡng).
  - Bỏ `flags` không xóa hết tín hiệu "thiếu dữ liệu": `ingredients_n` (nhóm numeric), `nova_missing` (nhóm nova) và giá
    trị `missing` của nhóm danh mục vẫn còn. Phép so sánh chỉ đo phần đóng góp thêm của 4 cột trên.
  - Cả hai lựa chọn vẫn được đo lại một lần (mục 6 của `reports/modeling_results.md`) để có số liệu khi trình bày; nếu
    chênh lệch lớn hơn độ lệch chuẩn giữa các fold thì báo lại người dùng trước khi giữ quyết định.
- **Mô hình** (theo kế hoạch Bước 8), tất cả đi qua `evaluate()` của Bước 7 trên cùng 5 fold dev, đặc trưng fit lại
  trong từng fold (lớp `NutriModel` gói pipeline đặc trưng và bộ phân loại):
  - Logistic Regression đa lớp trên ma trận thưa, `class_weight="balanced"`; chọn C trong {0,03; 0,1; 0,3; 1}.
  - Cây quyết định nông, `class_weight="balanced"`, mỗi lá ≥ 20 sản phẩm; chọn độ sâu trong {4; 6; 8}.
  - LightGBM phân loại, `class_weight="balanced"`, dừng sớm; một bản tham số mặc định, một bản tinh chỉnh bằng Optuna.
  - LightGBM hồi quy thứ tự: đoán số trên thang 0-4 (trọng số mẫu cân bằng theo hạng), cắt thành hạng bằng 4 ngưỡng
    chọn để Macro-F1 cao nhất. Không cho xác suất nên không có log-loss.
  - Không dùng SMOTE (ma trận thưa nhiều chiều); không làm MLP/DistilBERT (tùy chọn trong kế hoạch).
- **Dừng sớm không dùng fold đang đo.** Mỗi lần fit, tách 1/10 số nhóm (`group_id`) của phần huấn luyện bằng
  StratifiedGroupKFold (seed 42) làm tập dừng sớm; dừng sau 50 vòng không tiến bộ, tối đa 3.000 cây. Ngưỡng của hồi quy
  thứ tự cũng chọn trên tập này. Lý do: dùng fold đang đo để dừng thì điểm fold đó bị lạc quan.
- **Optuna**: 40 lần thử (kế hoạch 30-50), TPE seed 42, MedianPruner (từ lần thử 6, sau fold 2). Mục tiêu: Macro-F1
  trung bình 5 fold dev. Lần thử đầu là tham số mặc định, nên kết quả không kém mặc định. Tham số dò: `learning_rate`,
  `num_leaves`, `min_child_samples`, `reg_lambda`, `reg_alpha`, `colsample_bytree`, `subsample`. Vì chọn tham số trên
  chính 5 fold này, Macro-F1 trên dev của mô hình đã tinh chỉnh hơi lạc quan; con số khách quan là tập test ở Bước 9.
  Để tiết kiệm thời gian, khi chọn tham số đặc trưng được tính một lần cho mỗi fold rồi dùng lại (`build_fold_cache`),
  cho kết quả giống hệt `NutriModel` trong `evaluate()` vì pipeline đặc trưng không dùng nhãn.
- **Chọn mô hình tốt nhất**: Macro-F1 trung bình 5 fold cao nhất; phải vượt đường cơ sở `pnns_groups_2` trên cả
  Macro-F1 (0,412) và QWK (0,463).
- **Ablation** bằng mô hình tốt nhất, hai kiểu bổ sung cho nhau: cộng dồn theo kế hoạch (thành phần → + phụ gia →
  + danh mục → + NOVA → tất cả) và bỏ từng nhóm khỏi cấu hình chính (cho biết nhóm nào không thay thế được).
- **Lưu mô hình**: mô hình tốt nhất fit lại trên toàn bộ dev (không có test), lưu `artifacts/best_model.joblib` kèm tham
  số, phiên bản thư viện và dấu vân tay tập test; không đẩy lên Git (`*.joblib` đã bị chặn). Dự đoán ngoài fold của nó
  lưu `data/processed/oof_predictions.parquet` cho phân tích lỗi ở Bước 9.
- **Thư viện mới**: `lightgbm` 4.7.0, `optuna` 5.0.0, `joblib` (thêm vào `requirements.txt`, chưa ghim phiên bản, việc
  ghim để Bước 11). LightGBM 4.7 đổi `eval_set` thành `eval_X`/`eval_y`; mã tự chọn theo phiên bản đang cài.

### Kết quả Bước 8 (chạy 05/11/2026, 89 phút; `reports/modeling_results.md`)
- Chỉ dùng dev; tập test vẫn khóa (vân tay `2e511eab89b680b7`). 5 fold dev, trung bình ± độ lệch chuẩn giữa các fold:

| Mô hình | Macro-F1 | QWK | Accuracy |
|---|---|---|---|
| Đường cơ sở: hạng phổ biến nhất | 0,088 | 0,000 | 0,284 |
| Đường cơ sở: theo `pnns_groups_2` | 0,412 ± 0,004 | 0,463 | 0,462 |
| Logistic Regression (C = 0,1) | 0,562 ± 0,010 | 0,710 | 0,579 |
| Cây quyết định nông (sâu 8) | 0,481 ± 0,020 | 0,562 | 0,494 |
| LightGBM mặc định | 0,607 ± 0,009 | 0,750 | 0,623 |
| LightGBM hồi quy thứ tự + ngưỡng | 0,557 ± 0,015 | **0,786** | 0,564 |
| **LightGBM Optuna** | **0,625 ± 0,007** | 0,762 | **0,642** |

- **Mô hình tốt nhất: LightGBM Optuna**, vượt đường cơ sở `pnns_groups_2` trên cả Macro-F1 (+0,213) và QWK (+0,299),
  tiêu chí hoàn thành Bước 8. Tham số: `learning_rate` 0,0263, `num_leaves` 189, `min_child_samples` 7, `reg_lambda`
  0,035, `reg_alpha` 0,005, `colsample_bytree` 0,348, `subsample` 0,887; khoảng 218 cây mỗi fold. Optuna cải thiện
  +0,018 Macro-F1 so với mặc định (0,607), lớn hơn độ lệch chuẩn giữa các fold (0,007).
- **Xác nhận hai quyết định đã chốt** (đo lại, mục 6 của báo cáo): `min_freq = 20` cho 0,630 (+0,005) và có nhóm `flags`
  cho 0,623 (-0,002). Cả hai chênh nhỏ hơn độ lệch chuẩn 0,007, nên giữ nguyên: ngưỡng 100 và bỏ `flags`. Với `flags`
  còn kém hơn một chút, nghĩa là 4 cột này không đem lại gì thêm khi đã có `ingredients_n`, `nova_missing` và nhóm
  `missing` của danh mục; bỏ chúng không làm mất độ chính xác.
- **Ablation** (LightGBM Optuna): nhóm `categories` (pnns_groups_1/2, thẻ danh mục) là nhóm quan trọng nhất: bỏ đi
  Macro-F1 tụt -0,060; khi cộng dồn, thêm nó vào "thành phần + phụ gia" tăng +0,063 (0,561 → 0,623). Thành phần: bỏ đi -0,027.
  Vị trí đường/muối/chất béo: -0,007. Phụ gia, NOVA, nhãn bao bì, quốc gia: mỗi nhóm chỉ ≤ 0,003 (không phân biệt được với
  nhiễu). `numeric` bỏ đi còn nhỉnh +0,001. Lưu ý: các nhóm có thông tin chồng lấn (ví dụ NOVA và phụ gia đều phản ánh mức
  siêu chế biến), nên "bỏ một nhóm mà điểm gần như không đổi" không có nghĩa nhóm đó vô dụng khi đứng riêng.
- **Theo quốc gia** (Macro-F1 ngoài fold): bán ở Pháp 0,650, bán ở Mỹ 0,619, còn lại 0,607. **Giữ lại Pháp** (học không
  có hàng Pháp, cùng thương hiệu cũng bị bỏ): 0,601, tụt 0,049 so với 0,650; đây là mức giảm khi dùng mô hình cho thị
  trường mới. Đường cơ sở `pnns_groups_2` tụt ít hơn (0,437 → 0,425) vì không học gì riêng cho từng nước.
- **Theo hạng**: E dễ nhất (F1 0,753), A 0,715, D 0,589, C 0,575, **B khó nhất (0,492)**, đúng với hạng ít mẫu nhất
  (11,0%) và ở giữa hai hạng kề.
- **Hồi quy thứ tự**: QWK cao nhất (0,786) và 91,1% dự đoán lệch tối đa một hạng (phân loại LightGBM Optuna: 0,762
  và 89,1%), nhưng Macro-F1 thấp hơn (0,557). Cách này ít nhầm xa nhưng kém ở việc chọn đúng hạng từng lớp. Chọn mô hình
  theo Macro-F1 (chỉ số chính đã chốt ở Bước 7), nên LightGBM phân loại thắng; ghi lại để thảo luận ở Bước 9.
- **Hạn chế ghi nhận**:
  - Macro-F1 dev của mô hình tinh chỉnh hơi lạc quan (tham số chọn trên chính 5 fold); con số khách quan là test ở Bước 9.
  - Nhiều lần thử tốt nhất của Optuna chạm cạnh không gian tìm (`min_child_samples` 5-7 khi cạnh dưới là 5;
    `colsample_bytree` 0,31-0,38 khi cạnh dưới là 0,3). Năm lần thử tốt nhất chỉ chênh 0,002 nên mở rộng không đáng kể.
  - Ablation chỉ chạy với mô hình tốt nhất (LightGBM); thứ hạng nhóm có thể khác với Logistic Regression.
  - Mô hình dùng nhãn mà OFF tính tự động, một phần nhãn có thể trộn công thức 2017 và 2023 (xem Rủi ro đã biết).

## Rủi ro đã biết
- Bản dump không có `pnns_groups_*`; dùng `food_groups_tags` thay thế (cấp 1 và cấp 2).
- Quốc gia lệch mạnh; cần báo cáo hiệu năng theo quốc gia.
- Nhãn có thể trộn hai phiên bản công thức Nutri-Score; mức trộn nhỏ (chỉ 0,1% thực phẩm chỉ khớp bản 2017),
  nhưng 94% khớp cả hai bảng nên không xác định được chắc chắn phiên bản của từng dòng.
- Sản phẩm Mỹ không mang nhãn Nutri-Score thật trên bao bì; hạng là do Open Food Facts tự tính.
