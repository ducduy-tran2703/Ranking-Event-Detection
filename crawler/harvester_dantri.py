"""
URL Harvester - Báo Dân Trí (dantri.com.vn)
--------------------------------------------------------
Khác kiến trúc với Chính phủ/Nhân Dân: vì trang danh mục phân trang
(dạng /*/trang-N.htm) bị chặn trong robots.txt, ta backfill qua Sitemap
(được robots.txt công khai cho phép), duyệt TẤT CẢ 10 chuyên mục trong
CÙNG MỘT lượt quét, thay vì gọi riêng cho từng chuyên mục như 2 nguồn trước.

Luồng xử lý:
1. Fetch sitemap index (articles.xml) -> danh sách sitemap theo tháng,
   sắp xếp mới nhất trước.
2. Duyệt lần lượt từng sitemap tháng, với mỗi URL bài viết:
   - Tách slug đầu tiên trong path.
   - Nếu slug khớp ánh xạ trực tiếp -> gán category tương ứng.
   - Nếu slug là "thoi-su" -> fetch thêm trang chi tiết, tìm script
     "ggCatList" - chỉ nhận nếu giá trị đúng "thoi-su/chinh-tri".
   - Slug khác -> bỏ qua.
3. Dừng khi TẤT CẢ 10 category đã đủ max_articles, hoặc hết sitemap
   để duyệt (KHÔNG giới hạn số tháng lùi về quá khứ).

Lưu ý kiến trúc: khác với Chính phủ/Nhân Dân, Harvester ở đây CHỈ trả về
URL (không giữ lại HTML đã tải khi kiểm tra thoi-su) - giữ ranh giới đơn
giản "Harvester chỉ lo URL, Bronze Ingestor chỉ lo tải nội dung", chấp
nhận việc các bài Chính trị bị tải lại lần 2 ở bước Ingestor.
"""

import json
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("harvester_dantri")

BASE_URL = "https://dantri.com.vn"
SITEMAP_INDEX_URL = "https://dantri.com.vn/sitemaps/articles.xml"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
RATE_LIMIT_MIN = 3.0
RATE_LIMIT_MAX = 4.0
REQUEST_TIMEOUT = 10
RETRY_BACKOFFS = [2, 4, 8]

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Ánh xạ slug -> category chuẩn hóa (theo schema_contract.md)
SLUG_TO_CATEGORY = {
    "the-thao": "Thể Thao",
    "du-lich": "Du Lịch",
    "giao-duc": "Giáo Dục",
    "phap-luat": "Pháp Luật",
    "suc-khoe": "Sức Khỏe",
    "the-gioi": "Thế Giới",
    "giai-tri": "Văn Hóa",
    "kinh-doanh": "Kinh Tế",
    "cong-nghe": "Khoa học - Công Nghệ",
    "khoa-hoc": "Khoa học - Công Nghệ",
}
SPECIAL_SLUG_THOI_SU = "thoi-su"
CHINH_TRI_GGCATLIST_VALUE = "thoi-su/chinh-tri"
CHINH_TRI_CATEGORY_LABEL = "Chính Trị"
THOI_SU_CHECK_CACHE_PATH = "dantri_thoisu_check_cache.jsonl"

# Toàn bộ nhãn category cần thu thập cho nguồn Dân Trí
TARGET_CATEGORIES = set(SLUG_TO_CATEGORY.values()) | {CHINH_TRI_CATEGORY_LABEL}

_GG_CAT_LIST_RE = re.compile(r'ggCatList\s*=\s*"([^"]+)"')
_SITEMAP_FILENAME_DATE_RE = re.compile(r"Article-(\d{4}-\d{2}-\d{2})\.xml")


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _polite_sleep() -> None:
    time.sleep(random.uniform(RATE_LIMIT_MIN, RATE_LIMIT_MAX))


def _fetch_sitemap_index(session: requests.Session) -> List[str]:
    """Lấy danh sách URL sitemap theo tháng, sắp xếp mới nhất trước."""
    resp = session.get(SITEMAP_INDEX_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.content)

    entries = []
    for sitemap_tag in root.findall("sm:sitemap", SITEMAP_NS):
        loc_tag = sitemap_tag.find("sm:loc", SITEMAP_NS)
        if loc_tag is None or not loc_tag.text:
            continue
        loc = loc_tag.text.strip()
        match = _SITEMAP_FILENAME_DATE_RE.search(loc)
        if match is None:
            logger.warning("Không parse được ngày từ tên sitemap: %s", loc)
            continue
        file_date = datetime.strptime(match.group(1), "%Y-%m-%d")
        entries.append((file_date, loc))

    entries.sort(key=lambda x: x[0], reverse=True)
    return [loc for _, loc in entries]


def _fetch_month_sitemap_urls(session: requests.Session, sitemap_url: str) -> List[str]:
    """Lấy danh sách URL bài viết trong 1 file sitemap tháng."""
    resp = session.get(sitemap_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.content)

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


def _load_thoi_su_check_cache() -> Dict[str, bool]:
    """Nạp lại kết quả kiểm tra ggCatList đã có từ lần chạy trước, tránh kiểm tra lại."""
    cache: Dict[str, bool] = {}
    path = Path(THOI_SU_CHECK_CACHE_PATH)
    if not path.exists():
        return cache
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                cache[record["url"]] = record["is_chinh_tri"]
            except (json.JSONDecodeError, KeyError):
                continue
    logger.info("Nạp lại %d kết quả kiểm tra ggCatList đã cache từ lần chạy trước.", len(cache))
    return cache


def _append_thoi_su_check_cache(url: str, is_chinh_tri: bool) -> None:
    with open(THOI_SU_CHECK_CACHE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"url": url, "is_chinh_tri": is_chinh_tri}, ensure_ascii=False) + "\n")


def _check_is_chinh_tri(session: requests.Session, url: str) -> bool:
    """
    Fetch trang chi tiết, kiểm tra script ggCatList có đúng 'thoi-su/chinh-tri' không.
    Có retry+backoff cho lỗi mạng tạm thời. Nếu gặp 403/429 (dấu hiệu bị chặn
    thật, khác với timeout thoáng qua), dừng hẳn ngay lập tức thay vì bỏ qua
    âm thầm - để bạn biết mà xử lý (đổi User-Agent, tăng delay, tạm dừng...).
    """
    attempt = 0
    while True:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)

            if resp.status_code in (403, 428, 429):
                logger.critical(
                    "Nhận status %d cho %s - ĐÂY LÀ DẤU HIỆU BỊ CHẶN THẬT SỰ, "
                    "không phải lỗi mạng thoáng qua. Dừng chương trình.",
                    resp.status_code, url,
                )
                raise SystemExit(
                    f"Bị chặn (status {resp.status_code}) - dừng để tránh chặn nặng hơn."
                )

            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            if attempt >= len(RETRY_BACKOFFS):
                logger.warning("Hết lượt retry khi kiểm tra ggCatList cho %s: %s", url, exc)
                return False
            wait = RETRY_BACKOFFS[attempt]
            logger.warning("Lỗi mạng khi kiểm tra %s (lần %d): %s -> chờ %ds rồi thử lại",
                           url, attempt + 1, exc, wait)
            time.sleep(wait)
            attempt += 1

    match = _GG_CAT_LIST_RE.search(resp.text)
    if match is None:
        return False
    return match.group(1).strip() == CHINH_TRI_GGCATLIST_VALUE


def harvest_dantri_backfill(
    max_articles_per_category: int = 100,
    include_chinh_tri: bool = True,
) -> Dict[str, List[str]]:
    """
    Duyệt sitemap Dân Trí theo tháng (mới nhất trước), phân loại URL theo
    slug, trả về dict {category: [urls]} cho đến khi TẤT CẢ category cần
    thu thập đã đủ max_articles_per_category, hoặc hết sitemap.

    Args:
        max_articles_per_category: số bài tối đa cho MỖI category.
        include_chinh_tri: nếu False, bỏ qua hoàn toàn việc kiểm tra
            ggCatList cho các URL "thoi-su" - dùng khi muốn chạy riêng
            9 category thường trước (nhẹ, không tốn request phụ), để dành
            category Chính trị (tốn nhiều request kiểm tra hơn hẳn) chạy
            vào một đợt khác, giãn cách thời gian với domain.
    """
    session = _make_session()
    target_categories = set(SLUG_TO_CATEGORY.values())
    if include_chinh_tri:
        target_categories.add(CHINH_TRI_CATEGORY_LABEL)

    result: Dict[str, List[str]] = {cat: [] for cat in target_categories}
    seen_urls = set()
    thoi_su_check_cache = _load_thoi_su_check_cache() if include_chinh_tri else {}

    def _is_all_full() -> bool:
        return all(len(result[cat]) >= max_articles_per_category for cat in target_categories)

    logger.info("Lấy danh sách sitemap theo tháng...")
    _polite_sleep()
    try:
        month_sitemap_urls = _fetch_sitemap_index(session)
    except (requests.RequestException, ElementTree.ParseError) as exc:
        logger.error("Lỗi khi tải sitemap index: %s", exc)
        return result

    logger.info("Tìm thấy %d sitemap tháng, bắt đầu duyệt từ mới nhất.", len(month_sitemap_urls))

    for sitemap_url in month_sitemap_urls:
        if _is_all_full():
            logger.info("Tất cả category đã đủ %d bài, dừng duyệt sitemap.",
                        max_articles_per_category)
            break

        _polite_sleep()
        try:
            article_urls = _fetch_month_sitemap_urls(session, sitemap_url)
        except (requests.RequestException, ElementTree.ParseError) as exc:
            logger.warning("Lỗi khi tải sitemap %s: %s, bỏ qua.", sitemap_url, exc)
            continue

        logger.info("Sitemap %s: %d URL bài viết.", sitemap_url, len(article_urls))

        for url in article_urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            slug = _extract_first_slug(url)

            if slug == SPECIAL_SLUG_THOI_SU:
                if not include_chinh_tri:
                    continue  # không thu thập Chính trị trong đợt chạy này, bỏ qua ngay
                if len(result[CHINH_TRI_CATEGORY_LABEL]) >= max_articles_per_category:
                    continue

                if url in thoi_su_check_cache:
                    is_chinh_tri = thoi_su_check_cache[url]
                else:
                    _polite_sleep()
                    is_chinh_tri = _check_is_chinh_tri(session, url)
                    thoi_su_check_cache[url] = is_chinh_tri
                    _append_thoi_su_check_cache(url, is_chinh_tri)

                if is_chinh_tri:
                    result[CHINH_TRI_CATEGORY_LABEL].append(url)
                continue

            category = SLUG_TO_CATEGORY.get(slug)
            if category is None:
                continue  # slug không nằm trong danh sách cần lấy

            if len(result[category]) >= max_articles_per_category:
                continue
            result[category].append(url)

        for cat in target_categories:
            logger.info("  Tiến độ '%s': %d/%d", cat, len(result[cat]), max_articles_per_category)

    return result


if __name__ == "__main__":
    # ĐỢT 1: 9 category thường - nhẹ, mỗi bài chỉ 1 request, không cần kiểm tra phụ.
    data = harvest_dantri_backfill(max_articles_per_category=100, include_chinh_tri=False)
    print("\n=== Tổng kết đợt 1 (không gồm Chính trị) ===")
    for cat, urls in data.items():
        print(f"{cat}: {len(urls)} URL")

    # ĐỢT 2: chạy RIÊNG, CÁCH THỜI GIAN với đợt 1 (khuyến nghị vài giờ trở lên),
    # để domain "nghỉ" trước khi thực hiện phần tốn request kiểm tra ggCatList nhất.
    # Bỏ comment dòng dưới khi sẵn sàng chạy đợt 2:
    #
    # data_chinh_tri = harvest_dantri_backfill(max_articles_per_category=100, include_chinh_tri=True)
    # print("\n=== Tổng kết đợt 2 (Chính trị) ===")
    # print(f"Chính Trị: {len(data_chinh_tri['Chính Trị'])} URL")
