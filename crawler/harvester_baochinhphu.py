"""
URL Harvester - Báo Điện tử Chính phủ (baochinhphu.vn)
--------------------------------------------------------
Thu thập danh sách URL bài viết cho MỘT chuyên mục cụ thể (backfill lịch sử).

Giai đoạn A: lấy URL từ HTML render sẵn (SSR) ở trang danh mục gốc
    - div.list__focus       -> a.box-category-link-title
    - div.list__listing (2 khối) -> a.box-stream-link-title

Giai đoạn B: lấy thêm URL từ các trang phân trang qua AJAX
    - GET https://baochinhphu.vn/timelinelist/{zone_id}/{page}.htm
    - Fragment trả về chỉ chứa các khối .box-stream-item (không có wrapper thừa)

Nhãn chuyên mục (category_label) được gán CỐ ĐỊNH theo tham số đầu vào,
không suy luận từ nội dung trang - vì hàm này được gọi riêng cho từng
chuyên mục cụ thể.
"""

import logging
import random
import time
from typing import List, Set
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("harvester")

BASE_URL = "https://baochinhphu.vn"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
RATE_LIMIT_MIN = 1.5
RATE_LIMIT_MAX = 2.0
REQUEST_TIMEOUT = 10


def _make_session() -> requests.Session:
    """Tạo session dùng chung cho toàn bộ quá trình harvest, giữ header nhất quán."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _normalize_url(href: str) -> str:
    """Chuyển href (có thể là relative) thành URL tuyệt đối, dùng làm khóa dedup."""
    return urljoin(BASE_URL, href.strip())


def _extract_focus_urls(soup: BeautifulSoup) -> List[str]:
    """Lấy URL từ khối div.list__focus (tin nổi bật đầu trang)."""
    urls = []
    for focus_block in soup.select("div.list__focus"):
        for a_tag in focus_block.select("a.box-category-link-title"):
            href = a_tag.get("href")
            if href:
                urls.append(_normalize_url(href))
    return urls


def _extract_listing_urls(soup: BeautifulSoup) -> List[str]:
    """Lấy URL từ TẤT CẢ khối div.list__listing (không giả định số lượng cố định)."""
    urls = []
    for listing_block in soup.select("div.list__listing"):
        for a_tag in listing_block.select("a.box-stream-link-title"):
            href = a_tag.get("href")
            if href:
                urls.append(_normalize_url(href))
    return urls


def _extract_stream_item_urls(soup: BeautifulSoup) -> List[str]:
    """
    Lấy URL từ fragment trả về bởi endpoint timelinelist (Giai đoạn B).
    Fragment đã xác nhận là "sạch", chỉ chứa các khối .box-stream-item,
    dùng chung selector a.box-stream-link-title như ở list__listing.
    """
    urls = []
    for item in soup.select(".box-stream-item"):
        a_tag = item.select_one("a.box-stream-link-title")
        if a_tag and a_tag.get("href"):
            urls.append(_normalize_url(a_tag["href"]))
    return urls


def harvest_category_backfill(
    category_url: str,
    zone_id: int,
    max_articles: int = 500,
) -> List[str]:
    """
    Thu thập tối đa `max_articles` URL bài viết duy nhất cho một chuyên mục.

    Args:
        category_url: URL trang danh mục gốc, ví dụ
            "https://baochinhphu.vn/van-hoa/the-thao.htm"
        zone_id: mã chuyên mục dùng cho endpoint timelinelist (xác minh qua DevTools)
        max_articles: số lượng URL tối đa cần thu thập cho chuyên mục này

    Returns:
        Danh sách URL bài viết duy nhất (đã loại trùng), thứ tự theo lúc thu thập.
    """
    session = _make_session()
    seen_urls: Set[str] = set()
    ordered_urls: List[str] = []

    def _add_urls(urls: List[str]) -> None:
        for u in urls:
            if u not in seen_urls:
                seen_urls.add(u)
                ordered_urls.append(u)

    # ---------- Giai đoạn A: trang gốc (SSR) ----------
    logger.info("Giai đoạn A: tải trang danh mục gốc %s", category_url)
    try:
        resp = session.get(category_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Lỗi khi tải trang danh mục gốc: %s", exc)
        return ordered_urls

    soup = BeautifulSoup(resp.text, "html.parser")
    _add_urls(_extract_focus_urls(soup))
    _add_urls(_extract_listing_urls(soup))
    logger.info("Giai đoạn A thu được %d URL", len(ordered_urls))

    if len(ordered_urls) >= max_articles:
        return ordered_urls[:max_articles]

    # ---------- Giai đoạn B: phân trang AJAX ----------
    page = 2
    while len(ordered_urls) < max_articles:
        time.sleep(random.uniform(RATE_LIMIT_MIN, RATE_LIMIT_MAX))
        timeline_url = f"{BASE_URL}/timelinelist/{zone_id}/{page}.htm"

        try:
            resp = session.get(timeline_url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("Lỗi request trang %d, dừng lại: %s", page, exc)
            break

        # Điều kiện dừng 1: request thất bại hoặc nội dung rỗng
        if resp.status_code != 200 or not resp.text.strip():
            logger.info("Trang %d trả về rỗng/lỗi (status=%s), dừng.", page, resp.status_code)
            break

        fragment_soup = BeautifulSoup(resp.text, "html.parser")
        page_urls = _extract_stream_item_urls(fragment_soup)

        # Điều kiện dừng 2: không còn khối .box-stream-item nào
        if not page_urls:
            logger.info("Trang %d không còn bài viết, dừng.", page)
            break

        _add_urls(page_urls)
        logger.info("Trang %d: tổng cộng %d URL đã thu thập", page, len(ordered_urls))

        # Điều kiện dừng 3: đã đủ số lượng cần thiết
        if len(ordered_urls) >= max_articles:
            logger.info("Đã đạt max_articles=%d, dừng.", max_articles)
            break

        page += 1

    return ordered_urls[:max_articles]


if __name__ == "__main__":
    # Ví dụ chạy thử cho chuyên mục Thể thao
    # LƯU Ý: zone_id dưới đây cần được xác minh lại qua DevTools trước khi chạy thật
    urls = harvest_category_backfill(
        category_url="https://baochinhphu.vn/van-hoa/the-thao.htm",
        zone_id=102447,
        max_articles=500,
    )
    print(f"\nTổng số URL thu được: {len(urls)}")
    for u in urls[:10]:
        print(u)