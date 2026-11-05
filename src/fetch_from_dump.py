"""Bước 4a - Lấy mẫu từ bản dump Parquet của Open Food Facts bằng SQL (DuckDB).

Nguồn: https://huggingface.co/datasets/openfoodfacts/product-database (food.parquet, khoảng 8 GB, đặt ở data/external/).
DuckDB đọc thẳng tệp Parquet bằng SQL, chỉ đọc các cột cần, nên không phải nạp 8 GB vào RAM.
Kết quả: data/raw/raw_products_dump_<thời điểm>.jsonl.gz (mỗi dòng: _metadata + raw_payload), sau đó nạp vào
PostgreSQL bằng src.load_raw_to_postgres.

Chạy từ thư mục gốc dự án:
    python -m src.fetch_from_dump --n 30000 --seed 42
"""
import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timezone

import duckdb

SOURCE = "data/external/food.parquet"
# Chỉ đọc các cột cần. KHÔNG có trường cá nhân (creator, editors, last_editor...).
COLUMNS = ["code", "product_name", "brands_tags", "countries_tags", "categories_tags", "food_groups_tags",
           "ingredients_tags", "ingredients_text", "ingredients_n", "ingredients_from_palm_oil_n",
           "ingredients_analysis_tags", "additives_tags", "additives_n", "allergens_tags", "labels_tags",
           "nova_group", "nutriscore_grade", "nutriscore_score", "nutriments", "lang", "last_modified_t"]
# Sản phẩm đủ điều kiện: có nhãn A-E, có danh sách thành phần, có mã vạch, chưa bị đánh dấu lỗi thời.
ELIGIBLE = ("lower(nutriscore_grade) IN ('a', 'b', 'c', 'd', 'e') AND len(ingredients_tags) > 0 "
            "AND code IS NOT NULL AND coalesce(obsolete, false) = false")

# Pha 1: chọn ngẫu nhiên n mã vạch. Sắp theo md5(mã || seed) = trộn ngẫu nhiên nhưng tái lập được.
PICK_SQL = """
CREATE OR REPLACE TEMP TABLE picked AS
SELECT code FROM (SELECT DISTINCT code FROM read_parquet('{src}') WHERE {eligible})
ORDER BY md5(code || ?) LIMIT ?
"""
# Pha 2: đọc đủ cột cho các mã đã chọn. Bản dump có mã lặp: giữ bản sửa gần nhất (last_modified_t lớn nhất).
ROWS_SQL = """
SELECT {columns} FROM read_parquet('{src}')
WHERE code IN (SELECT code FROM picked) AND {eligible}
QUALIFY row_number() OVER (PARTITION BY code ORDER BY last_modified_t DESC NULLS LAST) = 1
ORDER BY md5(code || ?)
"""


def pick_text(entries, lang=None):
    """product_name / ingredients_text trong Parquet là list {lang, text}: ưu tiên 'main', rồi ngôn ngữ sản phẩm, rồi 'en'."""
    texts = {}
    for e in entries or []:
        if isinstance(e, dict) and isinstance(e.get("text"), str) and e["text"].strip():
            texts.setdefault(e.get("lang"), e["text"].strip())   # mỗi ngôn ngữ giữ bản đầu tiên
    for key in ("main", lang, "en"):
        if key in texts:
            return texts[key]
    return next(iter(texts.values()), None)


def nutriments_to_dict(entries):
    """nutriments trong Parquet là list {name, 100g, ...}; đổi về dict {"<name>_100g": giá trị} như API của OFF."""
    return {f"{e['name']}_100g": e["100g"] for e in entries or [] if e.get("name") and e.get("100g") is not None}


def food_group_label(tag):
    """'en:sugary-snacks' -> 'sugary snacks' (thay cho pnns_groups vốn không có trong Parquet)."""
    if not isinstance(tag, str) or not tag.strip():
        return None
    return tag.split(":", 1)[-1].replace("-", " ").strip() or None


def row_to_payload(row):
    """Một dòng Parquet -> payload JSON cùng dạng với API của Open Food Facts."""
    p = {k: v for k, v in row.items() if k not in ("product_name", "ingredients_text", "nutriments")}
    p["code"] = str(row["code"])
    p["product_name"] = pick_text(row.get("product_name"), row.get("lang"))
    p["ingredients_text"] = pick_text(row.get("ingredients_text"), row.get("lang"))
    p["nutriments"] = nutriments_to_dict(row.get("nutriments"))
    groups = row.get("food_groups_tags") or []
    p["pnns_groups_1"] = food_group_label(groups[0]) if len(groups) > 0 else None
    p["pnns_groups_2"] = food_group_label(groups[1]) if len(groups) > 1 else None
    return p


def fetch(source, out_path, n=30000, seed="42", batch_size=2000):
    """Chạy hai pha SQL và ghi tệp .jsonl.gz. Trả về số bản ghi đã ghi."""
    src = source.replace("'", "''")
    con = duckdb.connect()
    try:
        con.execute(PICK_SQL.format(src=src, eligible=ELIGIBLE), [str(seed), int(n)])
        cur = con.execute(ROWS_SQL.format(columns=", ".join(COLUMNS), src=src, eligible=ELIGIBLE), [str(seed)])
        meta = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "source_endpoint": source,
                "request_url": None, "http_status": None, "page": None, "filters": {"n": n, "seed": str(seed)}}
        written = 0
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with gzip.open(out_path, "wt", encoding="utf-8") as gz:
            while batch := cur.fetchmany(batch_size):
                for values in batch:
                    record = {"_metadata": meta, "raw_payload": row_to_payload(dict(zip(COLUMNS, values)))}
                    gz.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    written += 1
        return written
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lấy mẫu ngẫu nhiên từ bản dump Parquet của Open Food Facts")
    ap.add_argument("--source", default=SOURCE)
    ap.add_argument("--n", type=int, default=30000)
    ap.add_argument("--seed", default="42")
    ap.add_argument("--out-dir", default="data/raw")
    args = ap.parse_args(argv)

    if not os.path.exists(args.source):
        print(f"Không thấy {args.source}. Tải food.parquet từ Hugging Face (openfoodfacts/product-database).")
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(args.out_dir, f"raw_products_dump_{stamp}.jsonl.gz")
    written = fetch(args.source, out_path, args.n, args.seed)
    print(f"Đã ghi {written} sản phẩm vào {out_path}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
