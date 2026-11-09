"""Thanh Niên Bronze → nine-field Silver; adapted without the old R2 uploader."""

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .common_utils import compute_article_id, normalize_text

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
NOISE = (
    "script, style, noscript, iframe, #tn_detail_foryou1_pc_per, "
    ".newsrec-dcb-gb-container, .item-related, #ureka-ucp-autoplacement, "
    "div[id^='zone-'], div[id^='placement-'], figure, figcaption, .PhotoCMS_Author, "
    "div[data-check-position], [type='boxhighlight'], .boxhighlight, .boxhighlight-content"
)
INLINE_TAGS = ("span", "font", "i", "em", "b", "strong", "u", "small", "sub", "sup", "strike", "a")
BOILER = re.compile(
    r"^(?:ảnh|photo|video)\s*[:：]"
    r"|^(?:đọc thêm|xem thêm|tin liên quan|bài viết liên quan|dành cho bạn|theo dõi trên|liên hệ hotline)\b"
    r"|bài dự thi gửi về|thể lệ cuộc thi tại",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", text)
    return normalize_text(text)


def _parse_date(value: str) -> str | None:
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})\s*[-–]?\s*(\d{1,2}):(\d{2})", value)
        if not match:
            return None
        day, month, year, hour, minute = map(int, match.groups())
        try:
            dt = datetime(year, month, day, hour, minute, tzinfo=VN_TZ)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt.astimezone(VN_TZ).isoformat()


def normalize_published_date(soup: BeautifulSoup) -> str | None:
    # Keep the original source precedence: publishdate, meta, visible date.
    selectors = (
        "time[data-role='publishdate']",
        "meta[property='article:published_time'], meta[itemprop='datePublished']",
        ".detail-time, .detail-date",
    )
    for selector in selectors:
        for node in soup.select(selector):
            for raw in (node.get("datetime"), node.get("content"), node.get_text(" ", strip=True)):
                if isinstance(raw, str) and (parsed := _parse_date(raw)):
                    return parsed
    return None


def _extract_text(soup, selector, meta_selector) -> str:
    node = soup.select_one(selector)
    if node and (text := clean_text(node.get_text(" ", strip=True))):
        return text
    meta = soup.select_one(meta_selector)
    return clean_text(meta.get("content", "")) if meta else ""


def extract_author(soup: BeautifulSoup) -> str | None:
    names, seen = [], set()
    for node in soup.select(".mauthor-info .name, .author-info .name, a[href*='/author/']"):
        name = clean_text(node.get_text(" ", strip=True))
        name = re.sub(r"^[-–—/,\s]+|[-–—/,\s]+$", "", name)
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)
    if names:
        return ", ".join(names)
    node = soup.select_one("meta[name='author']")
    return (clean_text(node.get("content", "")) or None) if node else None


def extract_clean_content_text(soup: BeautifulSoup) -> str:
    root = soup.select_one("div.detail-content, [itemprop='articleBody']")
    if root is None:
        return ""
    content = BeautifulSoup(str(root), "html.parser")
    for node in content.select(NOISE):
        node.decompose()
    # Unwrap then smooth: "Vi<b>ệt</b> Nam" remains "Việt Nam" rather than
    # inserting spaces into words split by formatting tags in the old HTML.
    for node in content.find_all(INLINE_TAGS):
        node.unwrap()
    content.smooth()
    paragraphs = []
    for node in content.find_all(["p", "h2", "h3"]):
        text = clean_text(node.get_text(" ", strip=True))
        if text and not BOILER.search(text):
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def transform_record(bronze_record: dict) -> dict | None:
    soup = BeautifulSoup(bronze_record["raw_html"], "html.parser")
    title = _extract_text(soup, "h1.detail-title, h1.title-detail", "meta[property='og:title']")
    published_at = normalize_published_date(soup)
    if not title or published_at is None:
        return None
    url = bronze_record["url"]
    return {
        "article_id": compute_article_id(url),
        "url": url,
        "source": "thanhnien",
        "category": bronze_record["category"],
        "title": title,
        "sapo": _extract_text(
            soup,
            "div.detail-sapo, [data-role='sapo']",
            "meta[name='description'], meta[property='og:description']",
        ),
        "author": extract_author(soup),
        "published_at": published_at,
        "content_text": extract_clean_content_text(soup),
    }


def run_silver_transform(bronze_path: str, silver_path: str) -> None:
    with (
        Path(bronze_path).open(encoding="utf-8") as fin,
        Path(silver_path).open("x", encoding="utf-8") as fout,
    ):
        for line in fin:
            if line.strip() and (record := transform_record(json.loads(line))) is not None:
                fout.write(json.dumps(record, ensure_ascii=False) + "\n")
