"""
Bronze Ingestor - Báo Dân Trí (dantri.com.vn)
--------------------------------------------------------
Khác với Chính phủ/Nhân Dân: trang chi tiết Dân Trí có 2 kiểu cấu trúc
HTML khác nhau. Thử lần lượt 2 selector, dùng khối nào khớp trước:

    1. div.dt-flex.dt-flex-col.dt-space-y-6   (bài viết dạng thường)
    2. article.e-magazine.bg-wrap.d-magazine  (bài dạng emagazine/longform)

Bronze KHÔNG lưu thêm field đánh dấu kiểu template - Silver Transformer
sẽ tự nhận diện lại bằng cách kiểm tra tag/class gốc của raw_html đã lưu,
giữ đúng schema Bronze {url, raw_html, category, crawled_at} nhất quán
với 2 nguồn trước.

Logic resumable, retry+backoff, ghi append giống hệt 2 Bronze Ingestor
đã viết cho Chính phủ/Nhân Dân.
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
    from .harvester_dantri import _make_session, REQUEST_TIMEOUT, harvest_dantri_backfill
else:
    from harvester_dantri import _make_session, REQUEST_TIMEOUT, harvest_dantri_backfill

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingestor_dantri")

RATE_LIMIT_MIN = 0.2
RATE_LIMIT_MAX = 0.5
RETRY_BACKOFFS = [1, 1, 1]

# Thử lần lượt theo thứ tự, dùng khối đầu tiên khớp
CONTENT_SELECTORS = [
    "div.dt-flex.dt-flex-col.dt-space-y-6",
    "article.e-magazine.bg-wrap.d-magazine",
]


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


def _extract_content_container(soup: BeautifulSoup) -> object | None:
    """Thử lần lượt các selector, trả về tag khớp đầu tiên, hoặc None nếu không khớp cả 2."""
    for selector in CONTENT_SELECTORS:
        tag = soup.select_one(selector)
        if tag is not None:
            return tag
    return None


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
            content_tag = _extract_content_container(soup)

            if content_tag is None:
                logger.info("Bỏ qua (không khớp cả 2 kiểu cấu trúc): %s", url)
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


MAX_ARTICLES_PER_CATEGORY = 200
OUTPUT_PATH = "bronze_dantri.jsonl"


def run_all_categories(include_chinh_tri: bool = True) -> None:
    """
    Khác với Chính phủ/Nhân Dân: không cần bảng cấu hình CATEGORIES thủ công,
    vì harvest_dantri_backfill() đã trả về URL cho toàn bộ category cần thu
    thập cùng lúc.

    include_chinh_tri=False: chỉ chạy 9 category thường (nhẹ, không tốn
    request kiểm tra phụ). Chạy riêng đợt include_chinh_tri=True sau đó,
    CÁCH THỜI GIAN với đợt đầu (khuyến nghị vài giờ trở lên), vì phần
    Chính trị tốn nhiều request kiểm tra ggCatList hơn hẳn, từng gây ra
    status 428 (bị chặn) khi chạy dồn cùng lúc.
    """
    data = harvest_dantri_backfill(
        max_articles_per_category=MAX_ARTICLES_PER_CATEGORY,
        include_chinh_tri=include_chinh_tri,
    )
    for category_label, urls in data.items():
        logger.info("=== Bắt đầu chuyên mục: %s ===", category_label)
        ingest_urls(urls, category_label=category_label, output_path=OUTPUT_PATH)


if __name__ == "__main__":
    # Đợt 1: chạy trước, không gồm Chính trị.
    # run_all_categories(include_chinh_tri=False)

    # Đợt 2: bỏ comment khi sẵn sàng chạy (đã giãn cách thời gian với đợt 1).
    run_all_categories(include_chinh_tri=True)
