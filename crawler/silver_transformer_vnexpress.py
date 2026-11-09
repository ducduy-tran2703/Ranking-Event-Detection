"""VnExpress Bronze → nine-field Silver; no network or R2 operations."""

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .common_utils import compute_article_id, normalize_text

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
BOILER = re.compile(
    r"^(?:ảnh|photo|image|video|clip)\s*[:：]"
    r"|^(?:đọc thêm|xem thêm|bài viết liên quan|tin liên quan|tìm hiểu thêm)\b"
    r"|đăng ký đề cử.*tại đây|tham gia bình chọn|bình chọn.*tại đây"
    r"|tra cứu học phí|tra cứu.*điểm chuẩn|liên hệ.*hotline",
    re.IGNORECASE,
)
MEDIA_CREDIT = re.compile(r"(?:ảnh|photo|image|video|clip)\s*[:：]", re.IGNORECASE)


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return normalize_text(re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", text))


def _parse_date(value: str) -> str | None:
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4}),?\s+(\d{1,2}):(\d{2})", value)
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
    candidates = [
        node.get("content")
        for node in soup.select("meta[name='pubdate'], meta[itemprop='datePublished']")
    ]
    candidates.extend(node.get_text(" ", strip=True) for node in soup.select("span.date"))
    for candidate in candidates:
        if isinstance(candidate, str) and (parsed := _parse_date(candidate)):
            return parsed
    return None


def _is_author_paragraph(node) -> bool:
    return "text-align:right" in re.sub(r"\s+", "", node.get("style", "")).lower()


def extract_author(soup: BeautifulSoup) -> str | None:
    for node in soup.select("article.fck_detail p.Normal"):
        if _is_author_paragraph(node) and (strong := node.find("strong")):
            name = MEDIA_CREDIT.split(clean_text(strong.get_text(" ", strip=True)), maxsplit=1)[
                0
            ].strip()
            if name:
                return name
    for node in soup.select("div.width-detail-photo p.author"):
        source = node.find("strong") or node
        name = MEDIA_CREDIT.split(clean_text(source.get_text(" ", strip=True)), maxsplit=1)[
            0
        ].strip()
        if name:
            return name
    return None


def extract_clean_content_text(soup: BeautifulSoup) -> str:
    root = soup.select_one("article.fck_detail")
    if root is None:
        return ""
    content = BeautifulSoup(str(root), "html.parser")
    for node in content.select("figure, figcaption, .box-tinlienquan, script, style, iframe"):
        node.decompose()
    paragraphs = []
    for node in content.select("p.Normal"):
        if _is_author_paragraph(node):
            continue
        text = clean_text(node.get_text(" ", strip=True))
        if text and not BOILER.search(text):
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def transform_record(bronze_record: dict) -> dict | None:
    soup = BeautifulSoup(bronze_record["raw_html"], "html.parser")
    title = soup.select_one("h1.title-detail")
    sapo = soup.select_one(".description")
    published_at = normalize_published_date(soup)
    if title is None or not clean_text(title.get_text()) or published_at is None:
        return None
    url = bronze_record["url"]
    return {
        "article_id": compute_article_id(url),
        "url": url,
        "source": "vnexpress",
        "category": bronze_record["category"],
        "title": clean_text(title.get_text(" ", strip=True)),
        "sapo": clean_text(sapo.get_text(" ", strip=True)) if sapo else "",
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
