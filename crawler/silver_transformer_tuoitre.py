"""Tuổi Trẻ Bronze → the nine-field Silver contract (docs/tong-hop.md §5.3)."""

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
    "figure, figcaption, .PhotoCMS_Caption, [type='RelatedOneNews'], "
    ".detail-player, .embed-tts, [type='Photo'], [type='photo-grid-album'], "
    ".readmore-body-box, .detail-tab, script, style, iframe"
)
BOILER = re.compile(
    r"^(?:ảnh|hình ảnh|photo|image|video|clip|nguồn|đồ họa|xem video|xem clip)\s*[:：–—-]"
    r"|^(?:đọc thêm|xem thêm|tin liên quan|bài viết liên quan)\s*[:：]?"
    r"|ưu tiên tuổi trẻ trên google|chọn tuổi trẻ làm nguồn tin ưu tiên",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff]", " ", text)
    return normalize_text(text)


def _news_nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from _news_nodes(item)
    elif isinstance(value, dict):
        kinds = value.get("@type", [])
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if "NewsArticle" in kinds or "Article" in kinds:
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
    except (ValueError, AttributeError):
        match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})\s*[-–]?\s*(\d{1,2}):(\d{2})", value or "")
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
    for node in soup.select(
        "meta[property='article:published_time'], meta[name='pubdate'], "
        "[data-role='publishdate'], time[itemprop='datePublished']"
    ):
        candidates.extend(
            (node.get("content"), node.get("datetime"), node.get_text(" ", strip=True))
        )
    for candidate in candidates:
        if isinstance(candidate, str) and (parsed := _parse_date(candidate)):
            return parsed
    return None


def extract_author(soup, articles) -> str | None:
    node = soup.select_one(".detail-author .name, .detail-author-bot .name")
    if node and (name := clean_text(node.get_text(" ", strip=True))):
        return name
    names = []
    for article in articles:
        authors = article.get("author", [])
        for author in authors if isinstance(authors, list) else [authors]:
            name = author.get("name", "") if isinstance(author, dict) else author
            if isinstance(name, str) and clean_text(name):
                names.append(clean_text(name))
        if names:
            return ", ".join(dict.fromkeys(names))
    return None


def extract_content(soup) -> str:
    root = soup.select_one("div[data-role='content'], .detail-content")
    if root is None:
        return ""
    content = BeautifulSoup(str(root), "html.parser")
    for node in content.select(NOISE):
        node.decompose()
    paragraphs = []
    for node in content.find_all(["p", "h2", "h3"]):
        text = clean_text(node.get_text(" ", strip=True))
        # Keep short factual sentences and repeated text; neither is evidence
        # of boilerplate. Exclude only the source's explicit widget patterns.
        if text and not BOILER.search(text):
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def transform_record(bronze_record: dict) -> dict | None:
    soup = BeautifulSoup(bronze_record["raw_html"], "html.parser")
    title = soup.select_one("h1[data-role='title'], h1.detail-title")
    sapo = soup.select_one("[data-role='sapo'], .detail-sapo")
    articles = list(_structured_articles(soup))
    published_at = extract_published_date(soup, articles)
    if title is None or not clean_text(title.get_text()) or published_at is None:
        return None
    url = bronze_record["url"]
    return {
        "article_id": compute_article_id(url),
        "url": url,
        "source": "tuoitre",
        "category": bronze_record["category"],
        "title": clean_text(title.get_text(" ", strip=True)),
        "sapo": clean_text(sapo.get_text(" ", strip=True)) if sapo else "",
        "author": extract_author(soup, articles),
        "published_at": published_at,
        "content_text": extract_content(soup),
    }


def run_silver_transform(bronze_path: str, silver_path: str) -> None:
    # Explicit output; never replace an existing dataset by accident.
    with (
        Path(bronze_path).open(encoding="utf-8") as fin,
        Path(silver_path).open("x", encoding="utf-8") as fout,
    ):
        for line in fin:
            if line.strip() and (record := transform_record(json.loads(line))) is not None:
                fout.write(json.dumps(record, ensure_ascii=False) + "\n")
