-- Bước 4: trích xuất dữ liệu từ cột JSONB của raw_products thành bảng phẳng (một dòng = một sản phẩm).
-- Chạy trong pgAdmin/psql để xem, hoặc trong notebook 02 (src.db.query).
-- Không lọc dòng nào ở đây: lọc và loại trùng là việc của bước chuẩn bị dữ liệu (notebook 04).
-- Không lấy trường cá nhân (creator, editors_tags...). Cột dinh dưỡng và nhãn chỉ dùng cho EDA và làm y,
-- KHÔNG BAO GIỜ làm đặc trưng.

-- name: products
SELECT
    row_number() OVER (ORDER BY id) - 1                                  AS row_id,   -- thứ tự cố định theo id
    NULLIF(trim(payload->>'code'), '')                                   AS code,     -- giữ dạng chuỗi (số 0 đầu)
    NULLIF(trim(payload->>'product_name'), '')                           AS product_name,
    -- Danh sách thẻ: chỉ nhận mảng JSON, còn lại để NULL
    CASE WHEN jsonb_typeof(payload->'brands_tags') = 'array' THEN payload->'brands_tags' END            AS brands_tags,
    CASE WHEN jsonb_typeof(payload->'countries_tags') = 'array' THEN payload->'countries_tags' END      AS countries_tags,
    CASE WHEN jsonb_typeof(payload->'categories_tags') = 'array' THEN payload->'categories_tags' END    AS categories_tags,
    CASE WHEN jsonb_typeof(payload->'ingredients_tags') = 'array' THEN payload->'ingredients_tags' END  AS ingredients_tags,
    CASE WHEN jsonb_typeof(payload->'ingredients_analysis_tags') = 'array'
         THEN payload->'ingredients_analysis_tags' END                                                  AS ingredients_analysis_tags,
    CASE WHEN jsonb_typeof(payload->'additives_tags') = 'array' THEN payload->'additives_tags' END      AS additives_tags,
    CASE WHEN jsonb_typeof(payload->'allergens_tags') = 'array' THEN payload->'allergens_tags' END      AS allergens_tags,
    CASE WHEN jsonb_typeof(payload->'labels_tags') = 'array' THEN payload->'labels_tags' END            AS labels_tags,
    -- Nhóm danh mục: chữ thường, 'unknown' coi như thiếu
    NULLIF(lower(NULLIF(trim(payload->>'pnns_groups_1'), '')), 'unknown')  AS pnns_groups_1,
    NULLIF(lower(NULLIF(trim(payload->>'pnns_groups_2'), '')), 'unknown')  AS pnns_groups_2,
    NULLIF(trim(payload->>'ingredients_text'), '')                       AS ingredients_text,
    -- Số đếm: chỉ nhận giá trị dạng số
    CASE WHEN payload->>'ingredients_n' ~ '^-?[0-9]+(\.[0-9]+)?$'
         THEN (payload->>'ingredients_n')::float8 END                    AS ingredients_n,
    CASE WHEN payload->>'ingredients_from_palm_oil_n' ~ '^-?[0-9]+(\.[0-9]+)?$'
         THEN (payload->>'ingredients_from_palm_oil_n')::float8 END      AS ingredients_from_palm_oil_n,
    CASE WHEN payload->>'additives_n' ~ '^-?[0-9]+(\.[0-9]+)?$'
         THEN (payload->>'additives_n')::float8 END                      AS additives_n,
    -- NOVA hợp lệ là 1-4
    CASE WHEN payload->>'nova_group' ~ '^[1-4](\.0+)?$'
         THEN (payload->>'nova_group')::float8::int END                  AS nova_group,
    NULLIF(lower(trim(payload->>'lang')), '')                            AS lang,
    CASE WHEN payload->>'last_modified_t' ~ '^[0-9]+$'
         THEN to_timestamp((payload->>'last_modified_t')::bigint) END    AS last_modified,
    -- Nhãn (y): chỉ nhận a-e
    CASE WHEN lower(trim(payload->>'nutriscore_grade')) IN ('a', 'b', 'c', 'd', 'e')
         THEN lower(trim(payload->>'nutriscore_grade')) END              AS nutriscore_grade,
    -- Điểm và bảng dinh dưỡng: CHỈ cho EDA (rò rỉ nhãn nếu dùng làm đặc trưng)
    CASE WHEN jsonb_typeof(payload->'nutriscore_score') = 'number'
         THEN (payload->>'nutriscore_score')::float8 END                 AS nutriscore_score,
    (payload->'nutriments'->>'energy-kcal_100g')::float8                 AS energy_kcal_100g,
    (payload->'nutriments'->>'fat_100g')::float8                         AS fat_100g,
    (payload->'nutriments'->>'saturated-fat_100g')::float8               AS saturated_fat_100g,
    (payload->'nutriments'->>'sugars_100g')::float8                      AS sugars_100g,
    (payload->'nutriments'->>'fiber_100g')::float8                       AS fiber_100g,
    (payload->'nutriments'->>'proteins_100g')::float8                    AS proteins_100g,
    (payload->'nutriments'->>'salt_100g')::float8                        AS salt_100g
FROM raw_products
ORDER BY id;
