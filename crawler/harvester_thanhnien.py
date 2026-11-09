"""Thanh Niên timeline zones and URL extraction from the supplied crawl scripts."""

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

BASE_URL = "https://thanhnien.vn"
TIMELINE_TEMPLATE = BASE_URL + "/timelinelist/{zone_id}/{page}.htm"
TARGET_CATEGORIES = {
    "Thể Thao": "185318",
    "Du Lịch": "185234",
    "Giáo Dục": "18526",
    "Pháp Luật": "1855",
    "Sức Khỏe": "18565",
    "Thế Giới": "18566",
    "Văn Hóa": "18593",
    "Chính Trị": "185227",
    "Kinh Tế": "18549",
    "Khoa học - Công nghệ": "185315",
}
ARTICLE_PATH = re.compile(r"^/[a-zA-Z0-9_/-]+-\d+\.htm$")
EXCLUDED_SUBPATHS = (
    "/video/",
    "/truyen-hinh/",
    "/podcast/",
    "/interactive/",
    "/infographic/",
    "/media/",
    "/longform/",
)


def normalize_article_url(href: str) -> str | None:
    try:
        parts = urlsplit(urljoin(BASE_URL, href.strip()))
    except ValueError:
        return None
    if (
        parts.scheme not in ("http", "https")
        or parts.netloc.lower() not in ("thanhnien.vn", "www.thanhnien.vn")
        or not ARTICLE_PATH.fullmatch(parts.path)
        or any(part in parts.path.lower() for part in EXCLUDED_SUBPATHS)
    ):
        return None
    return urlunsplit(("https", "thanhnien.vn", parts.path, "", ""))


def extract_article_urls(soup: BeautifulSoup) -> list[str]:
    boxes = soup.select("div.box-category-item")
    links = []
    if boxes:
        for box in boxes:
            title = box.select_one(
                "a.box-category-link-title[href], a[data-linktype='newsdetail'][href]"
            )
            if title:
                links.append(title)
            links.extend(box.select("a.box-category-related-link-title[href]"))
    else:
        links = soup.select("a[href]")
    urls = (normalize_article_url(link["href"]) for link in links)
    return list(dict.fromkeys(url for url in urls if url))
