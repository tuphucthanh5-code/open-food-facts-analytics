"""Lấy dữ liệu từ bản dump Parquet chính thức của Open Food Facts (thay cho Search API).

Bản dump: https://huggingface.co/datasets/openfoodfacts/product-database (tệp food.parquet, khoảng 8 GB).
Công cụ dùng DuckDB để đọc CHỈ các cột cần thiết, lọc sản phẩm đủ điều kiện cho Phương án A
(nhãn A-E hợp lệ + có ingredients_tags), lấy mẫu có thể tái lập (seed), rồi ghi ra
data/raw/raw_products_dump_<thời điểm>.jsonl.gz cùng định dạng với crawler, nên các bước sau
(load_raw_to_postgres, raw_audit, staging) chạy được mà không phải sửa.

Không bao giờ đọc các cột cá nhân (creator, editors, last_editor, ...).

Ví dụ (chạy từ thư mục gốc dự án):
    python -m src.fetch_from_dump --describe                      # xem cột có trong tệp
    python -m src.fetch_from_dump --n 30000                       # mẫu ngẫu nhiên tự nhiên 30.000 sản phẩm
    python -m src.fetch_from_dump --strategy stratified --per-grade 6000
    python -m src.fetch_from_dump --source remote --n 30000       # đọc thẳng từ Hugging Face (không tải trước)
"""
import argparse
import gzip
import json
import os
import sys
import time
from datetime import datetime, timezone

import duckdb

from src.raw_audit import PII_FIELDS, VALID_GRADES

DEFAULT_SOURCE = "data/external/food.parquet"
REMOTE_SOURCE = "hf://datasets/openfoodfacts/product-database/food.parquet"
DOWNLOAD_URL = "https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet?download=true"

REQUIRED_COLUMNS = ("code", "nutriscore_grade", "ingredients_tags")
SELECT_COLUMNS = (
    "code", "product_name", "brands_tags", "countries_tags", "categories_tags", "food_groups_tags",
    "ingredients_tags", "ingredients_text", "ingredients_n", "ingredients_from_palm_oil_n",
    "ingredients_analysis_tags", "additives_tags", "additives_n", "allergens_tags", "labels_tags",
    "nova_group", "nutriscore_grade", "nutriscore_score", "nutriments", "lang", "last_modified_t",
)
# Chốt chặn: danh sách cột đọc vào không được giao với trường cá nhân
assert not set(SELECT_COLUMNS) & (set(PII_FIELDS) | {"editors", "photographers", "last_modified_by", "owner"})


# ======================================================================================
# Chuyển đổi một dòng Parquet sang payload giống API
# ======================================================================================
def pick_text(entries, prefer_lang=None):
    """product_name / ingredients_text trong Parquet là list {lang, text}. Ưu tiên main -> lang sản phẩm -> en."""
    if isinstance(entries, str):
        return entries.strip() or None
    if not isinstance(entries, list):
        return None
    by_lang = {}
    for e in entries:
        if isinstance(e, dict) and isinstance(e.get("text"), str) and e["text"].strip():
            by_lang.setdefault(e.get("lang"), e["text"].strip())
    for key in ("main", prefer_lang, "en"):
        if key in by_lang:
            return by_lang[key]
    return next(iter(by_lang.values()), None)


def nutriments_to_dict(entries):
    """nutriments trong Parquet là list {name, 100g, ...}; đổi về dict {"<name>_100g": giá trị} như API."""
    if isinstance(entries, dict):
        return entries
    out = {}
    for e in entries or []:
        if isinstance(e, dict) and e.get("name") and e.get("100g") is not None:
            out[f"{e['name']}_100g"] = e["100g"]
    return out


def food_group_label(tag):
    """'en:sugary-snacks' -> 'sugary snacks' (dùng thay cho pnns_groups vốn không có trong Parquet)."""
    if not isinstance(tag, str) or not tag.strip():
        return None
    t = tag.split(":", 1)[-1]
    return t.replace("-", " ").strip() or None


def row_to_payload(row):
    p = {k: v for k, v in row.items() if k not in ("product_name", "ingredients_text", "nutriments")}
    lang = row.get("lang")
    p["product_name"] = pick_text(row.get("product_name"), lang)
    p["ingredients_text"] = pick_text(row.get("ingredients_text"), lang)
    p["nutriments"] = nutriments_to_dict(row.get("nutriments"))
    groups = row.get("food_groups_tags") or []
    p["pnns_groups_1"] = food_group_label(groups[0]) if len(groups) > 0 else None
    p["pnns_groups_2"] = food_group_label(groups[1]) if len(groups) > 1 else None
    if p.get("code") is not None:
        p["code"] = str(p["code"])
    return p


# ======================================================================================
# Truy vấn DuckDB
# ======================================================================================
def resolve_source(source):
    return REMOTE_SOURCE if source == "remote" else source


def connect(source):
    con = duckdb.connect()
    if source.startswith(("hf://", "http://", "https://")):
        con.execute("INSTALL httpfs")
        con.execute("LOAD httpfs")
    return con


def _sql_literal(text):
    return "'" + str(text).replace("'", "''") + "'"


def describe(con, source):
    rows = con.execute(f"DESCRIBE SELECT * FROM read_parquet({_sql_literal(source)})").fetchall()
    return {r[0]: r[1] for r in rows}


def plan_columns(available):
    missing_required = [c for c in REQUIRED_COLUMNS if c not in available]
    if missing_required:
        raise ValueError(f"Tệp Parquet thiếu cột bắt buộc: {missing_required}")
    selected = [c for c in SELECT_COLUMNS if c in available]
    missing_optional = [c for c in SELECT_COLUMNS if c not in available]
    return selected, missing_optional


def build_where(available, country=None):
    where = [
        "lower(nutriscore_grade) IN ('a', 'b', 'c', 'd', 'e')",
        "ingredients_tags IS NOT NULL",
        "len(ingredients_tags) > 0",
        "code IS NOT NULL",
    ]
    params = []
    if "obsolete" in available:
        where.append("coalesce(obsolete, false) = false")
    if country:
        if "countries_tags" not in available:
            raise ValueError("Không lọc được theo quốc gia: tệp không có cột countries_tags")
        where.append("list_contains(countries_tags, ?)")
        params.append(country)
    return " AND ".join(where), params


def select_codes(con, source, available, n=30000, strategy="natural", per_grade=None,
                 country=None, seed="42"):
    """Pha 1: chỉ đọc vài cột nhỏ để chọn mã vạch. Trả về (số đủ điều kiện theo hạng, số được chọn)."""
    where, params = build_where(available, country)
    src = _sql_literal(source)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE eligible AS
        SELECT code, lower(nutriscore_grade) AS grade, md5(CAST(code AS VARCHAR) || ?) AS k
        FROM read_parquet({src})
        WHERE {where}
        QUALIFY row_number() OVER (PARTITION BY code ORDER BY k) = 1
    """, [str(seed)] + params)
    eligible = dict(con.execute("SELECT grade, count(*) FROM eligible GROUP BY grade").fetchall())

    if strategy == "natural":
        con.execute("CREATE OR REPLACE TEMP TABLE picked AS SELECT code FROM eligible ORDER BY k LIMIT ?", [int(n)])
    elif strategy == "stratified":
        cap = int(per_grade) if per_grade else max(1, int(n) // len(VALID_GRADES))
        con.execute("""
            CREATE OR REPLACE TEMP TABLE picked AS
            SELECT code FROM eligible
            QUALIFY row_number() OVER (PARTITION BY grade ORDER BY k) <= ?
        """, [cap])
    else:
        raise ValueError("strategy phải là 'natural' hoặc 'stratified'")
    picked = con.execute("SELECT count(*) FROM picked").fetchone()[0]
    return {g: int(eligible.get(g, 0)) for g in VALID_GRADES}, int(picked)


def iter_selected_rows(con, source, columns, batch_size=2000, seed="42"):
    """Pha 2: đọc đủ cột cho các mã đã chọn, theo thứ tự cố định, không trùng mã."""
    cols = ", ".join(f'p."{c}"' for c in columns)
    cur = con.execute(f"""
        SELECT {cols}
        FROM read_parquet({_sql_literal(source)}) AS p
        SEMI JOIN picked USING (code)
        ORDER BY md5(CAST(p.code AS VARCHAR) || ?)
    """, [str(seed)])
    names = [d[0] for d in cur.description]
    seen = set()
    while True:
        batch = cur.fetchmany(batch_size)
        if not batch:
            break
        for values in batch:
            row = dict(zip(names, values))
            code = str(row.get("code"))
            if code in seen:
                continue
            seen.add(code)
            yield row


def extract(source, out_path, n=30000, strategy="natural", per_grade=None, country=None,
            seed="42", log=print):
    """Chạy cả hai pha và ghi tệp .jsonl.gz. Trả về dict tóm tắt."""
    source = resolve_source(source)
    con = connect(source)
    try:
        available = describe(con, source)
        columns, missing = plan_columns(available)
        if missing:
            log(f"Cảnh báo: tệp không có các cột tùy chọn {missing} (sẽ để trống)")
        t0 = time.time()
        eligible, picked = select_codes(con, source, available, n, strategy, per_grade, country, seed)
        log(f"Đủ điều kiện theo hạng: {eligible} | chọn {picked} ({time.time() - t0:.0f}s)")

        filters = {"strategy": strategy, "n": n, "per_grade": per_grade, "country": country, "seed": str(seed)}
        retrieved_at = datetime.now(timezone.utc).isoformat()
        written = 0
        folder = os.path.dirname(out_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with gzip.open(out_path, "wt", encoding="utf-8") as gz:
            for row in iter_selected_rows(con, source, columns, seed=seed):
                record = {
                    "_metadata": {
                        "retrieved_at": retrieved_at,
                        "source_endpoint": source,
                        "request_url": None,
                        "http_status": None,
                        "page": None,
                        "filters": filters,
                    },
                    "raw_payload": row_to_payload(row),
                }
                gz.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                written += 1
        log(f"Đã ghi {written} bản ghi vào {out_path} ({time.time() - t0:.0f}s)")
        return {"eligible": eligible, "picked": picked, "written": written, "missing_optional": missing}
    finally:
        con.close()


# ======================================================================================
# Dòng lệnh
# ======================================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="Lấy mẫu từ bản dump Parquet của Open Food Facts")
    ap.add_argument("--source", default=DEFAULT_SOURCE,
                    help=f"đường dẫn food.parquet, hoặc 'remote' để đọc thẳng {REMOTE_SOURCE}")
    ap.add_argument("--n", type=int, default=30000, help="số sản phẩm (strategy natural)")
    ap.add_argument("--strategy", choices=["natural", "stratified"], default="natural")
    ap.add_argument("--per-grade", type=int, default=None, help="số sản phẩm mỗi hạng (strategy stratified)")
    ap.add_argument("--country", default=None, help="ví dụ en:france (có tiền tố en:)")
    ap.add_argument("--seed", default="42")
    ap.add_argument("--out-dir", default="data/raw")
    ap.add_argument("--describe", action="store_true", help="chỉ in danh sách cột rồi thoát")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    source = resolve_source(args.source)
    if not source.startswith(("hf://", "http://", "https://")) and not os.path.exists(source):
        print(f"Không thấy tệp {source}. Tải về từ:\n  {DOWNLOAD_URL}\n"
              f"và đặt vào {DEFAULT_SOURCE}, hoặc dùng --source remote.")
        return 1

    if args.describe:
        con = connect(source)
        try:
            available = describe(con, source)
        finally:
            con.close()
        for name, typ in available.items():
            print(f"{name}: {typ}")
        _, missing = plan_columns(available)
        print(f"\nTổng {len(available)} cột. Cột cần mà không có: {missing or 'không'}")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(args.out_dir, f"raw_products_dump_{stamp}.jsonl.gz")
    summary = extract(source, out_path, args.n, args.strategy, args.per_grade, args.country, args.seed)
    return 0 if summary["written"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
