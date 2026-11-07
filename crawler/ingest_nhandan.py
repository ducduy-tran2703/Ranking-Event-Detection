"""
Bronze Ingestor - Báo Nhân Dân điện tử (nhandan.vn)
--------------------------------------------------------
Nhận danh sách URL (từ harvester_nhandan.harvest_category_backfill),
tải nội dung chi tiết từng bài, chỉ giữ lại phần HTML trong thẻ
<div class="article">, lưu vào file JSONL tầng Bronze.

Logic giống hệt Bronze Ingestor của báo Chính phủ (resumable, retry+backoff,
ghi append từng dòng), chỉ khác selector nội dung chính.
"""

import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Set

import requests
from bs4 import BeautifulSoup

if __package__:
    from .harvester_nhandan import _make_session, REQUEST_TIMEOUT, harvest_category_backfill
else:
    from harvester_nhandan import _make_session, REQUEST_TIMEOUT, harvest_category_backfill

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingestor_nhandan")

RATE_LIMIT_MIN = 1.5
RATE_LIMIT_MAX = 2.0
RETRY_BACKOFFS = [2, 4, 8]
ARTICLE_CONTENT_SELECTOR = "div.article"


def _load_existing_urls(output_path: Path) -> Set[str]:
    existing: Set[str] = set()
    if not output_path.exists():
        return existing
    with output_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                existing.add(record["url"])
            except (json.JSONDecodeError, KeyError):
                logger.warning("Bỏ qua dòng hỏng trong file cũ: %s", line[:80])
    return existing


def _fetch_with_retry(session: requests.Session, url: str) -> requests.Response | None:
    attempt = 0
    while True:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp
            if resp.status_code >= 500:
                raise requests.RequestException(f"Server lỗi {resp.status_code}")
            logger.warning("URL %s trả về status %d, bỏ qua.", url, resp.status_code)
            return None
        except requests.RequestException as exc:
            if attempt >= len(RETRY_BACKOFFS):
                logger.error("Hết lượt retry cho %s: %s", url, exc)
                return None
            wait = RETRY_BACKOFFS[attempt]
            logger.warning("Lỗi mạng cho %s (lần %d): %s -> chờ %ds rồi thử lại",
                           url, attempt + 1, exc, wait)
            time.sleep(wait)
            attempt += 1


def ingest_urls(urls: List[str], category_label: str, output_path: str) -> None:
    output_path = Path(output_path)
    already_done = _load_existing_urls(output_path)
    to_fetch = [u for u in urls if u not in already_done]

    logger.info(
        "Chuyên mục '%s': %d URL đầu vào, %d đã có sẵn, %d cần tải.",
        category_label, len(urls), len(urls) - len(to_fetch), len(to_fetch),
    )

    session = _make_session()
    success_count = 0
    skipped_structure_count = 0
    failed_urls: List[str] = []

    with output_path.open("a", encoding="utf-8") as out_file:
        for url in to_fetch:
            time.sleep(random.uniform(RATE_LIMIT_MIN, RATE_LIMIT_MAX))

            resp = _fetch_with_retry(session, url)
            if resp is None:
                failed_urls.append(url)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            content_tag = soup.select_one(ARTICLE_CONTENT_SELECTOR)

            if content_tag is None:
                logger.info("Bỏ qua (không khớp cấu trúc bài viết): %s", url)
                skipped_structure_count += 1
                continue

            record = {
                "url": url,
                "raw_html": str(content_tag),
                "category": category_label,
                "crawled_at": datetime.now(timezone.utc).isoformat(),
            }
            out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_file.flush()
            success_count += 1

    logger.info(
        "Chuyên mục '%s' hoàn tất: %d thành công, %d bỏ qua (sai cấu trúc), %d lỗi mạng.",
        category_label, success_count, skipped_structure_count, len(failed_urls),
    )

    if failed_urls:
        failed_path = output_path.with_name(output_path.stem + "_failed.txt")
        with failed_path.open("a", encoding="utf-8") as f:
            for u in failed_urls:
                f.write(u + "\n")
        logger.info("Đã ghi %d URL lỗi mạng vào %s", len(failed_urls), failed_path)


# ----------------------------------------------------------------------------
# CẤU HÌNH CHUYÊN MỤC - điền zone_id thật (verify qua DevTools) trước khi chạy
# ----------------------------------------------------------------------------
CATEGORIES = [
    {"category_url": "https://nhandan.vn/chinhtri/", "zone_id": 1171, "category_label": "Chính Trị"},
    {"category_url": "https://nhandan.vn/du-lich/", "zone_id": 1257, "category_label": "Du Lịch"},  # 2.
    {"category_url": "https://nhandan.vn/giaoduc/", "zone_id": 1303, "category_label": "Giáo Dục"},  # 3.
    {"category_url": "https://nhandan.vn/phapluat/", "zone_id": 1287, "category_label": "Pháp Luật"},  # 4.
    {"category_url": "https://nhandan.vn/y-te/", "zone_id": 1309, "category_label": "Sức Khỏe"},  # 5.
    {"category_url": "https://nhandan.vn/thethao/", "zone_id": 1224, "category_label": "Thể Thao"},  # 6.
    {"category_url": "https://nhandan.vn/khoahoc-congnghe/", "zone_id": 1292, "category_label": "Khoa học - Công nghệ"},  # 7.
    {"category_url": "https://nhandan.vn/kinhte/", "zone_id": 1185, "category_label": "Kinh Tế"},  # 8.
    {"category_url": "https://nhandan.vn/vanhoa/", "zone_id": 1251, "category_label": "Văn Hóa"},  # 9.
    {"category_url": "https://nhandan.vn/thegioi/", "zone_id": 1231, "category_label": "Thế Giới"},  # 10.
]

MAX_ARTICLES_PER_CATEGORY = 500
OUTPUT_PATH = "bronze_nhandan.jsonl"


def run_all_categories() -> None:
    for cfg in CATEGORIES:
        if not cfg["category_url"] or cfg["zone_id"] is None or not cfg["category_label"]:
            logger.warning("Bỏ qua mục cấu hình chưa điền: %s", cfg)
            continue

        logger.info("=== Bắt đầu chuyên mục: %s ===", cfg["category_label"])
        urls = harvest_category_backfill(
            category_url=cfg["category_url"],
            zone_id=cfg["zone_id"],
            max_articles=MAX_ARTICLES_PER_CATEGORY,
        )
        ingest_urls(urls, category_label=cfg["category_label"], output_path=OUTPUT_PATH)


if __name__ == "__main__":
    run_all_categories()
