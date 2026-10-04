import argparse
import gzip
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

load_dotenv()

ENDPOINT = "https://world.openfoodfacts.org/api/v2/search"
USER_AGENT = os.getenv(
    "OFF_USER_AGENT",
    "StudentProject - NutriScore - Version 1.0 - set-your-email-in-.env",
)
MIN_DELAY = 7.0  # Search API giới hạn 10 req/phút -> tối thiểu 6s, dùng 7s

# Chỉ xin các trường cần dùng; không xin creator, editors_tags, ...
FIELDS = [
    "code", "product_name", "brands", "brands_tags", "countries_tags",
    "categories_tags", "pnns_groups_1", "pnns_groups_2",
    "ingredients_text", "ingredients_tags", "ingredients_n",
    "ingredients_analysis_tags", "additives_tags", "additives_n",
    "allergens_tags", "labels_tags", "nova_group",
    "ingredients_from_palm_oil_n", "nutriscore_grade", "nutriments",
    "last_modified_t", "lang",
]

os.makedirs("logs", exist_ok=True)
os.makedirs("data/raw", exist_ok=True)

logger = logging.getLogger("FoodFactsAcquisition")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler("logs/acquisition.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)


def create_robust_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return session


def fetch_one_filter(session, gz_file, filters, target, page_size, delay):
    """Lấy tối đa `target` bản ghi cho một bộ lọc, ghi vào gz_file."""
    fetched, page = 0, 1
    while fetched < target:
        params = {
            "page": page,
            "page_size": page_size,
            "fields": ",".join(FIELDS),
            **filters,
        }
        req_time = datetime.now(timezone.utc).isoformat()
        try:
            resp = session.get(ENDPOINT, params=params, timeout=30)
        except requests.exceptions.RequestException as exc:
            logger.error(f"Lỗi mạng ở page {page}, filters={filters}: {exc}")
            break
        if resp.status_code != 200:
            logger.error(f"Page {page} filters={filters} lỗi HTTP {resp.status_code}. Dừng.")
            break

        data = resp.json()
        products = data.get("products", [])
        if page == 1:
            logger.info(f"filters={filters}: API báo có {data.get('count')} sản phẩm khớp")
        if not products:
            logger.info("Hết sản phẩm.")
            break

        for item in products:
            if fetched >= target:
                break
            record = {
                "_metadata": {
                    "retrieved_at": req_time,
                    "source_endpoint": ENDPOINT,
                    "request_url": resp.url,
                    "http_status": resp.status_code,
                    "page": page,
                    "filters": filters,
                },
                "raw_payload": item,
            }
            gz_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            fetched += 1

        logger.info(f"Page {page}: {len(products)} bản ghi (đã lấy {fetched}/{target}) filters={filters}")
        page += 1
        time.sleep(delay)
    return fetched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=300, help="số bản ghi tối đa cho MỖI bộ lọc")
    ap.add_argument("--country", default="", help="ví dụ: vietnam (không có tiền tố en:)")
    ap.add_argument("--grades", default="", help="ví dụ: a,b,c,d,e (mỗi hạng một lượt lấy)")
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--delay", type=float, default=MIN_DELAY)
    args = ap.parse_args()

    delay = max(args.delay, MIN_DELAY)
    base = {}
    if args.country:
        base["countries_tags_en"] = args.country
    grades = [g.strip() for g in args.grades.split(",") if g.strip()] or [None]

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = f"data/raw/raw_products_{ts}.jsonl.gz"
    logger.info(f"Bắt đầu. Đích: {out}, delay={delay}s")

    session = create_robust_session()
    total = 0
    with gzip.open(out, "wt", encoding="utf-8") as gz:
        for g in grades:
            filters = dict(base)
            if g:
                filters["nutrition_grades_tags"] = g
            total += fetch_one_filter(session, gz, filters, args.target, args.page_size, delay)
    logger.info(f"Hoàn tất. Tổng {total} bản ghi trong {out}")


if __name__ == "__main__":
    main()
