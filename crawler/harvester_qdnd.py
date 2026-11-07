"""
URL Harvester - Báo Quân đội nhân dân (qdnd.vn)
--------------------------------------------------------
Backfill qua Sitemap, duyệt theo NGÀY (khác Dân Trí duyệt theo THÁNG).
Mọi slug ánh xạ trực tiếp 1-1 sang category, không có trường hợp mơ hồ
cần kiểm tra thêm như "thoi-su" bên Dân Trí.

Luồng xử lý:
1. Fetch sitemap index (feed-0.xml) -> lọc chỉ giữ các sitemap khớp mẫu
   tên "news-DD-MM-YYYY.xml" (loại bỏ topic.xml, news-categories.xml...),
   sắp xếp mới nhất trước.
2. Duyệt lần lượt từng sitemap ngày, phân loại URL theo slug đầu tiên.
3. Dừng khi TẤT CẢ category cần thu thập đã đủ max_articles, hoặc hết
   sitemap để duyệt (không giới hạn số ngày lùi về quá khứ).

LƯU Ý namespace XML: sitemap của qdnd.vn dùng
"http://www.google.com/schemas/sitemap/0.9", KHÁC với chuẩn sitemaps.org
mà Dân Trí dùng - phải khai báo đúng, nếu không ElementTree sẽ tìm thấy
0 phần tử mà không báo lỗi gì.
"""

import logging
import random
import re
import time
from datetime import datetime
from typing import Dict, List
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("harvester_qdnd")

SITEMAP_INDEX_URL = "https://www.qdnd.vn/sitemaps/pid/feed-0.xml"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
RATE_LIMIT_MIN = 1.5
RATE_LIMIT_MAX = 2.0
REQUEST_TIMEOUT = 10
RETRY_BACKOFFS = [2, 4, 8]

# QUAN TRỌNG: namespace riêng của qdnd.vn, khác chuẩn sitemaps.org
SITEMAP_NS = {"sm": "http://www.google.com/schemas/sitemap/0.9"}

SLUG_TO_CATEGORY = {
    "giao-duc-khoa-hoc": "Giáo Dục",
    "chinh-tri": "Chính Trị",
    "kinh-te": "Kinh Tế",
    "quoc-te": "Thế Giới",
    "van-hoa": "Văn Hóa",
    "the-thao": "Thể Thao",
    "y-te": "Sức Khỏe",
    "phap-luat": "Pháp Luật",
    "du-lich": "Du Lịch",
}
TARGET_CATEGORIES = set(SLUG_TO_CATEGORY.values())

# Chỉ khớp sitemap dạng "news-DD-MM-YYYY.xml", loại bỏ topic.xml, news-categories.xml...
_DAILY_SITEMAP_RE = re.compile(r"news-(\d{2})-(\d{2})-(\d{4})\.xml")


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _polite_sleep() -> None:
    time.sleep(random.uniform(RATE_LIMIT_MIN, RATE_LIMIT_MAX))


def _fetch_with_retry(session: requests.Session, url: str) -> requests.Response | None:
    attempt = 0
    while True:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code in (403, 428, 429):
                logger.critical(
                    "Nhận status %d cho %s - DẤU HIỆU BỊ CHẶN, dừng chương trình.",
                    resp.status_code, url,
                )
                raise SystemExit(f"Bị chặn (status {resp.status_code}) - dừng.")
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            if attempt >= len(RETRY_BACKOFFS):
                logger.warning("Hết lượt retry cho %s: %s", url, exc)
                return None
            wait = RETRY_BACKOFFS[attempt]
            logger.warning("Lỗi mạng cho %s (lần %d): %s -> chờ %ds", url, attempt + 1, exc, wait)
            time.sleep(wait)
            attempt += 1


def _fetch_sitemap_index(session: requests.Session) -> List[str]:
    """Lấy danh sách sitemap theo ngày (đã lọc), sắp xếp mới nhất trước."""
    resp = _fetch_with_retry(session, SITEMAP_INDEX_URL)
    if resp is None:
        return []
    try:
        root = ElementTree.fromstring(resp.content)
    except ElementTree.ParseError as exc:
        logger.error("Lỗi parse XML sitemap index tại %s: %s", SITEMAP_INDEX_URL, exc)
        return []

    entries = []
    for sitemap_tag in root.findall("sm:sitemap", SITEMAP_NS):
        loc_tag = sitemap_tag.find("sm:loc", SITEMAP_NS)
        if loc_tag is None or not loc_tag.text:
            continue
        loc = loc_tag.text.strip()
        match = _DAILY_SITEMAP_RE.search(loc)
        if match is None:
            continue  # bỏ qua topic.xml, news-categories.xml...

        day, month, year = match.groups()
        try:
            file_date = datetime.strptime(f"{day}-{month}-{year}", "%d-%m-%Y")
        except ValueError:
            continue
        entries.append((file_date, loc))

    entries.sort(key=lambda x: x[0], reverse=True)
    return [loc for _, loc in entries]


def _fetch_day_sitemap_urls(session: requests.Session, sitemap_url: str) -> List[str]:
    resp = _fetch_with_retry(session, sitemap_url)
    if resp is None:
        return []
    try:
        root = ElementTree.fromstring(resp.content)
    except ElementTree.ParseError as exc:
        logger.warning("Lỗi XML tại %s: %s -> bỏ qua sitemap này.", sitemap_url, exc)
        return []

    urls = []
    for url_tag in root.findall("sm:url", SITEMAP_NS):
        loc_tag = url_tag.find("sm:loc", SITEMAP_NS)
        if loc_tag is not None and loc_tag.text:
            urls.append(loc_tag.text.strip())
    return urls


def _extract_first_slug(url: str) -> str:
    path = urlparse(url).path
    parts = [p for p in path.split("/") if p]
    return parts[0] if parts else ""


def harvest_qdnd_backfill(max_articles_per_category: int = 500) -> Dict[str, List[str]]:
    """
    Duyệt sitemap qdnd.vn theo ngày (mới nhất trước), phân loại URL theo
    slug, trả về dict {category: [urls]} cho đến khi TẤT CẢ category đủ
    max_articles_per_category, hoặc hết sitemap để duyệt.
    """
    session = _make_session()
    result: Dict[str, List[str]] = {cat: [] for cat in TARGET_CATEGORIES}
    seen_urls = set()

    def _is_all_full() -> bool:
        return all(len(result[cat]) >= max_articles_per_category for cat in TARGET_CATEGORIES)

    logger.info("Lấy danh sách sitemap theo ngày...")
    _polite_sleep()
    day_sitemap_urls = _fetch_sitemap_index(session)
    logger.info("Tìm thấy %d sitemap theo ngày, bắt đầu duyệt từ mới nhất.", len(day_sitemap_urls))

    for sitemap_url in day_sitemap_urls:
        if _is_all_full():
            logger.info("Tất cả category đã đủ %d bài, dừng duyệt sitemap.",
                        max_articles_per_category)
            break

        _polite_sleep()
        article_urls = _fetch_day_sitemap_urls(session, sitemap_url)
        logger.info("Sitemap %s: %d URL bài viết.", sitemap_url, len(article_urls))

        for url in article_urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            slug = _extract_first_slug(url)
            category = SLUG_TO_CATEGORY.get(slug)
            if category is None:
                continue  # slug không nằm trong danh sách cần lấy

            if len(result[category]) >= max_articles_per_category:
                continue
            result[category].append(url)

        for cat in TARGET_CATEGORIES:
            logger.info("  Tiến độ '%s': %d/%d", cat, len(result[cat]), max_articles_per_category)

    # Cảnh báo rõ các category không đủ sau khi đã hết sitemap để duyệt
    for cat in TARGET_CATEGORIES:
        if len(result[cat]) < max_articles_per_category:
            logger.warning(
                "Category '%s' chỉ đạt %d/%d bài sau khi đã duyệt hết sitemap - "
                "chấp nhận số lượng thấp hơn cho category này.",
                cat, len(result[cat]), max_articles_per_category,
            )

    return result


if __name__ == "__main__":
    data = harvest_qdnd_backfill(max_articles_per_category=5)
    print("\n=== Tổng kết ===")
    for cat, urls in data.items():
        print(f"{cat}: {len(urls)} URL")
        print(data[cat])
