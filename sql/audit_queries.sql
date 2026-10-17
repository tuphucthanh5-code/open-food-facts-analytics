-- Truy vấn kiểm toán dữ liệu thô (Bước 2). Chạy từng câu trong psql hoặc pgAdmin:
--   psql -U postgres -d food_facts_db -f sql/audit_queries.sql

-- 1. Tổng số bản ghi, số mã vạch duy nhất, số bản ghi trùng mã
SELECT count(*) AS total_records,
       count(DISTINCT code) AS unique_codes,
       count(*) - count(DISTINCT code) AS duplicate_records
FROM raw_products;

-- 2. Phân bố nhãn gốc (gồm cả giá trị lạ như unknown, not-applicable)
SELECT coalesce(payload->>'nutriscore_grade', '(thiếu)') AS grade, count(*) AS n
FROM raw_products
GROUP BY 1
ORDER BY n DESC;

-- 3. Số bản ghi có nhãn hợp lệ a-e
SELECT count(*) AS labeled
FROM raw_products
WHERE lower(payload->>'nutriscore_grade') IN ('a', 'b', 'c', 'd', 'e');

-- 4. Số bản ghi DÙNG ĐƯỢC cho Phương án A: nhãn hợp lệ và có danh sách thành phần
SELECT count(*) AS usable
FROM raw_products
WHERE lower(payload->>'nutriscore_grade') IN ('a', 'b', 'c', 'd', 'e')
  AND jsonb_typeof(payload->'ingredients_tags') = 'array'
  AND jsonb_array_length(payload->'ingredients_tags') > 0;

-- 5. Phân bố hạng trong nhóm dùng được (kiểm tra mất cân bằng lớp)
SELECT lower(payload->>'nutriscore_grade') AS grade, count(*) AS n
FROM raw_products
WHERE lower(payload->>'nutriscore_grade') IN ('a', 'b', 'c', 'd', 'e')
  AND jsonb_typeof(payload->'ingredients_tags') = 'array'
  AND jsonb_array_length(payload->'ingredients_tags') > 0
GROUP BY 1
ORDER BY 1;

-- 6. Số bản ghi dùng được có nhóm NOVA hợp lệ (1-4)
SELECT count(*) AS usable_with_nova
FROM raw_products
WHERE lower(payload->>'nutriscore_grade') IN ('a', 'b', 'c', 'd', 'e')
  AND jsonb_typeof(payload->'ingredients_tags') = 'array'
  AND jsonb_array_length(payload->'ingredients_tags') > 0
  AND payload->>'nova_group' IN ('1', '2', '3', '4');

-- 7. Top 15 quốc gia trong nhóm dùng được
SELECT c AS country, count(*) AS n
FROM raw_products,
     LATERAL jsonb_array_elements_text(payload->'countries_tags') AS c
WHERE lower(payload->>'nutriscore_grade') IN ('a', 'b', 'c', 'd', 'e')
  AND jsonb_typeof(payload->'ingredients_tags') = 'array'
  AND jsonb_array_length(payload->'ingredients_tags') > 0
  AND jsonb_typeof(payload->'countries_tags') = 'array'
GROUP BY c
ORDER BY n DESC
LIMIT 15;

-- 8. Top 15 thương hiệu trong nhóm dùng được (ảnh hưởng cách chia GroupKFold)
SELECT coalesce(payload->'brands_tags'->>0, '(thiếu)') AS brand, count(*) AS n
FROM raw_products
WHERE lower(payload->>'nutriscore_grade') IN ('a', 'b', 'c', 'd', 'e')
  AND jsonb_typeof(payload->'ingredients_tags') = 'array'
  AND jsonb_array_length(payload->'ingredients_tags') > 0
GROUP BY 1
ORDER BY n DESC
LIMIT 15;

-- 9. Danh sách tất cả khóa trong JSON thô và số bản ghi chứa khóa đó
--    (dùng để tìm trường liên quan phiên bản Nutri-Score và trường cá nhân)
SELECT k AS field, count(*) AS n
FROM raw_products,
     LATERAL jsonb_object_keys(payload) AS k
GROUP BY k
ORDER BY k;

-- 10. Mã vạch bắt đầu bằng 0 hoặc chứa ký tự không phải số
SELECT count(*) FILTER (WHERE code LIKE '0%') AS leading_zero,
       count(*) FILTER (WHERE code !~ '^[0-9]+$') AS non_digit
FROM raw_products;
