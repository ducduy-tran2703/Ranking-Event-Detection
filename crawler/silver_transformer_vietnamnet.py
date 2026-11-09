"""VietnamNet Bronze → the nine-field Silver contract, without R2 side effects."""

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
    ".ck-cms-insert-neww-group, .ck-cms-insert-news, figure, figcaption, "
    ".insert-wiki-content, .vnn-content-image, .banner-advertisement, "
    ".vmcadszone, script, style, noscript, iframe"
)
BOILER = re.compile(
    r"^(?:ảnh|hình ảnh|photo|image|video|clip|nguồn|đồ họa|xem video|theo dõi video|xem clip|video clip|clip nóng)\s*[:：–—-]"
    r"|^(?:đọc thêm|xem thêm|tin liên quan|bài viết liên quan)\b"
    r"|đăng ký đề cử.*tại đây|tham gia bình chọn|mọi ý kiến đóng góp xin gửi về|liên hệ hotline",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return normalize_text(re.sub(r"[\u200b-\u200f\u2060\ufeff]", " ", text))


def _news_nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from _news_nodes(item)
    elif isinstance(value, dict):
        kinds = value.get("@type", [])
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if isinstance(kinds, list) and any(k in kinds for k in ("NewsArticle", "Article")):
            yield value
        yield from _news_nodes(value.get("@graph", []))


def _structured_articles(soup):
    for script in soup.select("script[type='application/ld+json']"):
        try:
            yield from _news_nodes(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            continue


def _parse_date(value: str) -> str | None:
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})\D+(\d{1,2}):(\d{2})", value)
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


def extract_published_date(soup, articles) -> str | None:
    candidates = [node.get("datePublished") for node in articles]
    for node in soup.select("meta[property='article:published_time'], meta[name='pubdate']"):
        candidates.append(node.get("content"))
    for node in soup.select(".bread-crumb-detail__time, .publish-date"):
        candidates.append(node.get_text(" ", strip=True))
    for candidate in candidates:
        if isinstance(candidate, str) and (parsed := _parse_date(candidate)):
            return parsed
    return None


def extract_author(soup, articles) -> str | None:
    names, seen = [], set()
    for node in soup.select(".article-detail-author .name a, .article-detail-author__info .name"):
        name = clean_text(node.get_text(" ", strip=True))
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)
    if names:
        return ", ".join(names)
    for article in articles:
        authors = article.get("author", [])
        for author in authors if isinstance(authors, list) else [authors]:
            name = author.get("name", "") if isinstance(author, dict) else author
            if isinstance(name, str) and (name := clean_text(name)) and name.casefold() not in seen:
                seen.add(name.casefold())
                names.append(name)
        if names:
            return ", ".join(names)
    return None


def extract_clean_content_text(soup) -> str:
    root = soup.select_one("#maincontent, .maincontent")
    if root is None:
        return ""
    content = BeautifulSoup(str(root), "html.parser")
    for node in content.select(NOISE):
        node.decompose()
    paragraphs = []
    for node in content.find_all(["p", "h2", "h3"]):
        text = clean_text(node.get_text(" ", strip=True))
        if text and not BOILER.search(text):
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def transform_record(bronze_record: dict) -> dict | None:
    soup = BeautifulSoup(bronze_record["raw_html"], "html.parser")
    title = soup.select_one("h1.content-detail-title, h1.title")
    sapo = soup.select_one("h2.content-detail-sapo, .content-detail-sapo")
    articles = list(_structured_articles(soup))
    published_at = extract_published_date(soup, articles)
    if title is None or not clean_text(title.get_text()) or published_at is None:
        return None
    url = bronze_record["url"]
    return {
        "article_id": compute_article_id(url),
        "url": url,
        "source": "vietnamnet",
        "category": bronze_record["category"],
        "title": clean_text(title.get_text(" ", strip=True)),
        "sapo": clean_text(sapo.get_text(" ", strip=True)) if sapo else "",
        "author": extract_author(soup, articles),
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
