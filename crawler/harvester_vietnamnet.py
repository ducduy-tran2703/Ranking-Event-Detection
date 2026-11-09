"""VietnamNet category pagination and link filtering from the supplied scripts."""

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

BASE_URL = "https://vietnamnet.vn"
TARGET_CATEGORIES = {
    BASE_URL + "/the-thao": "Thể Thao",
    BASE_URL + "/du-lich": "Du Lịch",
    BASE_URL + "/giao-duc": "Giáo Dục",
    BASE_URL + "/thoi-su/phap-luat": "Pháp Luật",
    BASE_URL + "/suc-khoe": "Sức Khỏe",
    BASE_URL + "/the-gioi": "Thế Giới",
    BASE_URL + "/van-hoa-giai-tri": "Văn Hóa",
    BASE_URL + "/chinh-tri": "Chính Trị",
    BASE_URL + "/kinh-doanh": "Kinh Tế",
    BASE_URL + "/cong-nghe": "Khoa học - Công nghệ",
}
ARTICLE_PATH = re.compile(r"^/[a-zA-Z0-9_/-]+-\d+\.html$")
EXCLUDED_SUBPATHS = ("/video/", "/podcast/", "/talkshow/", "/interactive/", "/multimedia/")


def listing_url(category_url: str, page_index: int) -> str:
    return f"{category_url}-page{page_index}"


def normalize_article_url(href: str, base_url: str = BASE_URL) -> str | None:
    try:
        parts = urlsplit(urljoin(base_url, href.strip()))
    except ValueError:
        return None
    if (
        parts.scheme not in ("http", "https")
        or parts.netloc.lower() not in ("vietnamnet.vn", "www.vietnamnet.vn")
        or not ARTICLE_PATH.fullmatch(parts.path)
        or any(part in parts.path.lower() for part in EXCLUDED_SUBPATHS)
    ):
        return None
    return urlunsplit(("https", "vietnamnet.vn", parts.path, "", ""))


def extract_article_urls(soup: BeautifulSoup, base_url: str = BASE_URL) -> list[str]:
    urls = (normalize_article_url(link["href"], base_url) for link in soup.select("a[href]"))
    return list(dict.fromkeys(url for url in urls if url))
