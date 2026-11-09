"""VnExpress category pages and scoped article links, adapted from supplied scripts."""

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

BASE_URL = "https://vnexpress.net"
TARGET_CATEGORIES = {
    BASE_URL + "/the-thao": "Thể Thao",
    BASE_URL + "/du-lich": "Du Lịch",
    BASE_URL + "/giao-duc": "Giáo Dục",
    BASE_URL + "/phap-luat": "Pháp Luật",
    BASE_URL + "/suc-khoe": "Sức Khỏe",
    BASE_URL + "/the-gioi": "Thế Giới",
    BASE_URL + "/giai-tri": "Văn Hóa",
    BASE_URL + "/thoi-su/chinh-tri": "Chính Trị",
    BASE_URL + "/kinh-doanh": "Kinh Tế",
    BASE_URL + "/khoa-hoc-cong-nghe": "Khoa học - Công nghệ",
}
ARTICLE_PATH = re.compile(r"^/[a-zA-Z0-9_/-]+-\d+\.html$")
EXCLUDED_SUBPATHS = ("/video/", "/podcast/", "/photo/", "/interactive/")


def listing_url(category_url: str, page_index: int) -> str:
    return category_url if page_index == 0 else f"{category_url}-p{page_index + 1}"


def normalize_article_url(href: str, base_url: str = BASE_URL) -> str | None:
    try:
        parts = urlsplit(urljoin(base_url, href.strip()))
    except ValueError:
        return None
    if (
        parts.scheme not in ("http", "https")
        or parts.netloc.lower() not in ("vnexpress.net", "www.vnexpress.net")
        or not ARTICLE_PATH.fullmatch(parts.path)
        or any(part in parts.path.lower() for part in EXCLUDED_SUBPATHS)
    ):
        return None
    return urlunsplit(("https", "vnexpress.net", parts.path, "", ""))


def extract_article_urls(soup: BeautifulSoup, base_url: str = BASE_URL) -> list[str]:
    links = []
    for article in soup.select("article"):
        title = article.select_one(".title-news a[href], h2 a[href], h3 a[href]")
        links.extend([title] if title else article.select("a[href]"))
    urls = (normalize_article_url(link["href"], base_url) for link in links)
    return list(dict.fromkeys(url for url in urls if url))
