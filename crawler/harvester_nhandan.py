"""
URL Harvester - Báo Nhân Dân điện tử (nhandan.vn)
--------------------------------------------------------
Giai đoạn A: lấy URL từ HTML render sẵn (SSR) ở trang danh mục gốc
    - div.abf-cate            -> h2 a.cms-link
    - div.main-col.content-col -> h2 a.cms-link
  (chỉ lấy a.cms-link lồng trong h2, để loại link gắn ở ảnh minh họa)

Giai đoạn B: lấy thêm URL từ API JSON phân trang
    - GET https://api.nhandan.vn/api/morenews-zone-{zone_id}-{page}.html
          ?phrase=&page_size=30&sz={zone_id}&st=zone
    - Điều kiện dừng dựa vào field data.load_more (đáng tin hơn suy luận qua
      mảng rỗng, vì API trả tín hiệu tường minh)

Nhãn chuyên mục (category_label) được gán CỐ ĐỊNH theo tham số đầu vào,
giống thiết kế đã áp dụng cho báo Chính phủ.
"""

import logging
import random
import time
from typing import List, Set
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("harvester_nhandan")

BASE_URL = "https://nhandan.vn"
API_BASE_URL = "https://api.nhandan.vn"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
RATE_LIMIT_MIN = 1.5
RATE_LIMIT_MAX = 2.0
REQUEST_TIMEOUT = 10


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _normalize_url(href: str) -> str:
    """Chuyển href thành URL tuyệt đối (phòng trường hợp là đường dẫn tương đối)."""
    return urljoin(BASE_URL, href.strip())


def _extract_ssr_urls(soup: BeautifulSoup) -> List[str]:
    """Lấy URL từ 2 khối SSR: div.abf-cate và div.main-col.content-col."""
    urls = []
    for selector in ["div.abf-cate", "div.main-col.content-col"]:
        for container in soup.select(selector):
            for a_tag in container.select("h2 a.cms-link"):
                href = a_tag.get("href")
                if href:
                    urls.append(_normalize_url(href))
    return urls


def _fetch_api_page(session: requests.Session, zone_id: int, page: int) -> dict | None:
    """Gọi API morenews, trả về dict JSON hoặc None nếu lỗi."""
    api_url = (
        f"{API_BASE_URL}/api/morenews-zone-{zone_id}-{page}.html"
        f"?phrase=&page_size=30&sz={zone_id}&st=zone"
    )
    try:
        resp = session.get(api_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Lỗi khi gọi API trang %d: %s", page, exc)
        return None


def harvest_category_backfill(
    category_url: str,
    zone_id: int,
    max_articles: int = 500,
) -> List[str]:
    """
    Thu thập tối đa `max_articles` URL bài viết duy nhất cho một chuyên mục
    của báo Nhân Dân.

    Args:
        category_url: URL trang danh mục gốc, ví dụ "https://nhandan.vn/chinhtri/"
        zone_id: mã chuyên mục dùng cho API morenews
        max_articles: số lượng URL tối đa cần thu thập

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
    _add_urls(_extract_ssr_urls(soup))
    logger.info("Giai đoạn A thu được %d URL", len(ordered_urls))

    if len(ordered_urls) >= max_articles:
        return ordered_urls[:max_articles]

    # ---------- Giai đoạn B: phân trang qua API JSON ----------
    page = 2
    while len(ordered_urls) < max_articles:
        time.sleep(random.uniform(RATE_LIMIT_MIN, RATE_LIMIT_MAX))

        data = _fetch_api_page(session, zone_id, page)
        if data is None:
            logger.info("Lỗi gọi API ở trang %d, dừng.", page)
            break

        contents = data.get("data", {}).get("contents", [])
        page_urls = [item["url"] for item in contents if item.get("url")]

        if page_urls:
            _add_urls(page_urls)
            logger.info("Trang %d: tổng cộng %d URL đã thu thập", page, len(ordered_urls))

        load_more = data.get("data", {}).get("load_more", False)

        if len(ordered_urls) >= max_articles:
            logger.info("Đã đạt max_articles=%d, dừng.", max_articles)
            break

        if not load_more:
            logger.info("API báo load_more=false ở trang %d, dừng.", page)
            break

        page += 1

    return ordered_urls[:max_articles]


if __name__ == "__main__":
    # Ví dụ chạy thử cho chuyên mục Chính trị
    # LƯU Ý: zone_id dưới đây cần được xác minh lại qua DevTools trước khi chạy thật
    urls = harvest_category_backfill(
        category_url="https://nhandan.vn/chinhtri/",
        zone_id=1171,
        max_articles=30,
    )
    print(f"\nTổng số URL thu được: {len(urls)}")
    for u in urls[:30]:
        print(u)
