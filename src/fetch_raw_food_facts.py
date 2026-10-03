import os
import sys
import time
import json
import gzip
import logging
from datetime import datetime, timezone
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# 1. CẤU HÌNH LOGGING
os.makedirs("logs", exist_ok=True)
os.makedirs("data/raw", exist_ok=True)

logger = logging.getLogger("FoodFactsAcquisition")
logger.setLevel(logging.INFO)

# Tránh add duplicate handler nếu chạy lại trong notebook
if not logger.handlers:
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.FileHandler("logs/acquisition.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


# 2. CẤU HÌNH HTTP SESSION VỚI RETRY VÀ USER-AGENT HỢP LỆ
def create_robust_session() -> requests.Session:
    """
    Khởi tạo Session với cơ chế Retry backoff khi gặp lỗi HTTP 429 (Rate Limit) hoặc 5xx.
    Tuân thủ quy định User-Agent của Open Food Facts.
    """
    session = requests.Session()
    
    retries = Retry(
        total=5,
        backoff_factor=1.5,  # Chờ: 1.5s, 3s, 6s, 12s...
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    session.headers.update({
        "User-Agent": "StudentDataScienceProject - NutritionAnalytics - Version 1.0 - contact@student.university.edu",
        "Accept": "application/json"
    })
    return session


# 3. HÀM CÀO DỮ LIỆU TỪ SEARCH API V2
def fetch_openfoodfacts_raw(
    search_term: str = "",
    countries_tag: str = "en:vietnam",
    target_count: int = 1000,
    page_size: int = 100,
    request_delay: float = 1.0
):
    """
    Tải dữ liệu từ Open Food Facts Search API v2 và lưu thô dạng JSON Lines (.jsonl.gz).
    """
    endpoint = "https://world.openfoodfacts.org/api/v2/search"
    session = create_robust_session()
    
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_filepath = f"data/raw/raw_products_{timestamp_str}.jsonl.gz"
    
    logger.info(f"Bắt đầu thu thập dữ liệu...")
    logger.info(f"Bộ lọc: countries_tag='{countries_tag}', target={target_count}, page_size={page_size}")
    logger.info(f"Đích lưu dữ liệu thô: {output_filepath}")
    
    fetched_records = 0
    current_page = 1
    
    with gzip.open(output_filepath, "wt", encoding="utf-8") as gz_file:
        while fetched_records < target_count:
            params = {
                "page": current_page,
                "page_size": page_size,
                "json": 1
            }
            if search_term:
                params["search_terms"] = search_term
            if countries_tag:
                params["countries_tags_en"] = countries_tag

            req_time = datetime.now(timezone.utc).isoformat()
            
            try:
                response = session.get(endpoint, params=params, timeout=20)
                status = response.status_code
                
                if status != 200:
                    logger.error(f"Page {current_page} thất bại với mã lỗi HTTP {status}. Dừng.")
                    break
                    
                data = response.json()
                products = data.get("products", [])
                
                if not products:
                    logger.info("Không còn sản phẩm nào từ API. Hoàn tất thu thập.")
                    break
                
                for item in products:
                    # Đóng gói nguyên vẹn JSON thô kèm siêu dữ liệu truy vết nguồn
                    raw_record = {
                        "_metadata": {
                            "retrieved_at": req_time,
                            "request_url": response.url,
                            "http_status": status,
                            "page": current_page
                        },
                        "raw_payload": item
                    }
                    gz_file.write(json.dumps(raw_record, ensure_ascii=False) + "\n")
                    fetched_records += 1
                    
                    if fetched_records >= target_count:
                        break
                
                logger.info(f"Page {current_page}: Lấy thành công {len(products)} bản ghi (Tổng cộng: {fetched_records}/{target_count})")
                current_page += 1
                
                # Tuân thủ Rate Limit: Dừng tối thiểu request_delay giây trước khi gửi request tiếp theo
                time.sleep(request_delay)
                
            except requests.exceptions.RequestException as exc:
                logger.error(f"Lỗi mạng khi gọi Page {current_page}: {exc}")
                break

    logger.info(f"Quá trình hoàn tất. Đã lưu {fetched_records} bản ghi thô vào '{output_filepath}'.")


if __name__ == "__main__":
    # Tham số: target_count=500 (bạn có thể tăng lên 5000 - 20000 tùy dung lượng cần nộp)
    fetch_openfoodfacts_raw(
        countries_tag="",      # Để trống để lấy toàn cầu hoặc "en:vietnam" để lọc Việt Nam
        target_count=300,      # Test lấy 300 sản phẩm trước
        page_size=100,
        request_delay=1.0      # Giãn cách 1 giây mỗi request
    )
