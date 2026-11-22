"""Tuổi Trẻ timeline categories and URL extraction, adapted from the supplied scripts.

Network access belongs to automation.SourceClient; importing this module has no I/O.
"""

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

BASE_URL = "https://tuoitre.vn"
TIMELINE_TEMPLATE = BASE_URL + "/timeline/{zone_id}/trang-{page}.htm"
TARGET_CATEGORIES = {
    "Thể Thao": "1209",
    "Chính Trị": "3",
    "Pháp Luật": "6",
    "Kinh Tế": "11",
    "Thế Giới": "2",
    "Giáo Dục": "13",
    "Sức Khỏe": "12",
    "Văn Hóa": "200017",
    "Khoa học - Công nghệ": "661",
    "Du Lịch": "100",
}
ARTICLE_PATH = re.compile(r"^/[a-zA-Z0-9_/-]+-\d+\.htm$")
EXCLUDED_SUBPATHS = (
    "/video/",
    "/truyen-hinh/",
    "/podcast/",
    "/talkshow/",
    "/interactive/",
    "/infographic/",
    "/media/",
)


def normalize_article_url(href: str) -> str | None:
    parts = urlsplit(urljoin(BASE_URL, href.strip()))
    if (
        parts.scheme not in ("http", "https")
        or parts.netloc.lower() not in ("tuoitre.vn", "www.tuoitre.vn")
        or not ARTICLE_PATH.fullmatch(parts.path)
        or any(part in parts.path.lower() for part in EXCLUDED_SUBPATHS)
    ):
        return None
    return urlunsplit(("https", "tuoitre.vn", parts.path, "", ""))


def extract_article_urls(soup: BeautifulSoup) -> list[str]:
    items = soup.select("article.box-category-item, div.box-category-item")
    links = []
    if items:
        for item in items:
            link = item.select_one("a.box-category-link-title[href], a[data-binding='title'][href]")
            if link:
                links.append(link)
    else:
        links = soup.select("a[href]")
    urls = (normalize_article_url(link["href"]) for link in links)
    return list(dict.fromkeys(url for url in urls if url))
