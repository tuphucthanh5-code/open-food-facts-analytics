-- Kiểm toán dữ liệu thô bằng SQL (thay cho src/raw_audit.py cũ).
-- Chạy từng câu trong pgAdmin/psql, hoặc trong notebook 03 bằng src.db.load_queries + src.db.query.
-- "Dùng được" = có nhãn a-e và có danh sách thành phần (điều kiện của bài toán).

-- name: tong_quan
-- Số bản ghi, mã vạch trùng, mã bắt đầu bằng 0 (phải giữ dạng chuỗi), mã có ký tự lạ
SELECT count(*)                                              AS so_ban_ghi,
       count(DISTINCT code)                                  AS so_ma_vach,
       count(*) - count(DISTINCT code)                       AS ban_ghi_trung_ma,
       count(*) FILTER (WHERE code LIKE '0%')                AS ma_bat_dau_bang_0,
       count(*) FILTER (WHERE code !~ '^[0-9]+$')            AS ma_co_ky_tu_la,
       count(*) FILTER (WHERE jsonb_typeof(payload->'code') <> 'string') AS ma_khong_phai_chuoi
FROM raw_products;

-- name: nhan_goc
-- Phân bố nhãn gốc, kể cả giá trị thiếu hoặc lạ
SELECT coalesce(lower(payload->>'nutriscore_grade'), '(thiếu)') AS nhan,
       count(*)                                                AS so_ban_ghi
FROM raw_products
GROUP BY 1
ORDER BY 2 DESC;

-- name: dung_duoc
-- Số bản ghi dùng được và độ phủ NOVA trong số đó
SELECT count(*)                                                                AS dung_duoc,
       count(*) FILTER (WHERE payload->>'nova_group' IN ('1', '2', '3', '4'))  AS co_nova,
       round(100.0 * count(*) FILTER (WHERE payload->>'nova_group' IN ('1', '2', '3', '4')) / count(*), 1)
                                                                               AS pct_co_nova
FROM raw_products
WHERE lower(payload->>'nutriscore_grade') IN ('a', 'b', 'c', 'd', 'e')
  AND jsonb_typeof(payload->'ingredients_tags') = 'array'
  AND jsonb_array_length(payload->'ingredients_tags') > 0;

-- name: hang_theo_nova
-- Bảng chéo hạng x NOVA (GROUP BY + FILTER): NOVA 4 có kéo hạng xuống không?
SELECT lower(payload->>'nutriscore_grade')                        AS hang,
       count(*) FILTER (WHERE payload->>'nova_group' = '1')       AS nova_1,
       count(*) FILTER (WHERE payload->>'nova_group' = '2')       AS nova_2,
       count(*) FILTER (WHERE payload->>'nova_group' = '3')       AS nova_3,
       count(*) FILTER (WHERE payload->>'nova_group' = '4')       AS nova_4,
       count(*) FILTER (WHERE coalesce(payload->>'nova_group', '') NOT IN ('1', '2', '3', '4')) AS thieu_nova
FROM raw_products
WHERE lower(payload->>'nutriscore_grade') IN ('a', 'b', 'c', 'd', 'e')
GROUP BY 1
ORDER BY 1;

-- name: ty_le_thieu
-- Tỷ lệ thiếu (khóa vắng, null, chuỗi rỗng hoặc mảng rỗng) của các trường chính
SELECT f                                                                                    AS truong,
       round(100.0 * count(*) FILTER (WHERE v IS NULL OR v IN ('null', '""', '[]')) / count(*), 1) AS pct_thieu
FROM raw_products,
     unnest(ARRAY['product_name', 'brands_tags', 'countries_tags', 'categories_tags', 'pnns_groups_1',
                  'pnns_groups_2', 'ingredients_text', 'ingredients_tags', 'ingredients_n', 'additives_tags',
                  'allergens_tags', 'labels_tags', 'nova_group', 'nutriscore_grade', 'nutriments']) AS f,
     LATERAL (SELECT payload->f AS v) AS x
GROUP BY f
ORDER BY 2 DESC;

-- name: so_thanh_phan
-- Thống kê số thành phần: trung vị, lớn nhất, số sản phẩm rất ít (<= 1) hoặc phi lý (> 150) thành phần
SELECT min(n) AS nho_nhat,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY n) AS trung_vi,
       round(avg(n), 1) AS trung_binh,
       max(n) AS lon_nhat,
       count(*) FILTER (WHERE n <= 1) AS toi_da_1_thanh_phan,
       count(*) FILTER (WHERE n > 150) AS tren_150_thanh_phan
FROM (SELECT (payload->>'ingredients_n')::int AS n
      FROM raw_products
      WHERE payload->>'ingredients_n' ~ '^[0-9]+$') AS s;

-- name: the_taxonomy
-- Tỷ lệ thẻ thành phần đã chuẩn hóa theo taxonomy (tiền tố en:)
SELECT count(*)                                                     AS so_the,
       round(100.0 * count(*) FILTER (WHERE t LIKE 'en:%') / count(*), 1) AS pct_the_en
FROM raw_products,
     jsonb_array_elements_text(CASE WHEN jsonb_typeof(payload->'ingredients_tags') = 'array'
                                    THEN payload->'ingredients_tags' ELSE '[]' END) AS t;

-- name: thuong_hieu
-- Thương hiệu lớn nhất chiếm bao nhiêu % (ảnh hưởng cách chia theo nhóm thương hiệu)
SELECT coalesce(payload->'brands_tags'->>0, '(thiếu)')       AS thuong_hieu,
       count(*)                                              AS so_ban_ghi,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1)    AS pct
FROM raw_products
GROUP BY 1
ORDER BY 2 DESC
LIMIT 10;

-- name: quoc_gia
-- Top quốc gia (một sản phẩm có thể bán ở nhiều nước)
SELECT c                                                                     AS quoc_gia,
       count(*)                                                              AS so_ban_ghi,
       round(100.0 * count(*) / (SELECT count(*) FROM raw_products), 1)      AS pct
FROM raw_products,
     jsonb_array_elements_text(CASE WHEN jsonb_typeof(payload->'countries_tags') = 'array'
                                    THEN payload->'countries_tags' ELSE '[]' END) AS c
GROUP BY c
ORDER BY 2 DESC
LIMIT 10;

-- name: truong_nhay_cam
-- Mọi khóa JSON có trong dữ liệu, phân loại: trường cá nhân (KHÔNG được có) và trường rò rỉ nhãn (không làm đặc trưng)
SELECT k        AS truong,
       count(*) AS so_ban_ghi,
       CASE WHEN k IN ('creator', 'editors_tags', 'last_editor', 'correctors_tags', 'photographers_tags',
                       'informers_tags', 'checkers_tags') THEN 'CÁ NHÂN: không được thu thập'
            WHEN k LIKE 'nutri%' OR k IN ('misc_tags', 'states_tags', 'data_quality_tags')
                 THEN 'RÒ RỈ NHÃN: không làm đặc trưng'
            ELSE 'dùng được' END AS loai
FROM raw_products,
     jsonb_object_keys(payload) AS k
GROUP BY k
ORDER BY 3, 1;

-- name: ma_trung_join
-- Tự JOIN bảng với chính nó: mã vạch nào xuất hiện ở nhiều dòng (khác id)?
SELECT a.code, a.id AS id_a, b.id AS id_b, a.source_file AS tep_a, b.source_file AS tep_b
FROM raw_products AS a
JOIN raw_products AS b ON a.code = b.code AND a.id < b.id
LIMIT 20;
