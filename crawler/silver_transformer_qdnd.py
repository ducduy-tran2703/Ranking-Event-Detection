"""
Silver Transformer - Báo Quân đội nhân dân (qdnd.vn)
--------------------------------------------------------
published_at có dạng "Thứ bảy, 22/08/2026 - 05:32" (kèm tên thứ tiếng Việt
ở đầu) - dùng regex trích riêng phần "DD/MM/YYYY - HH:MM", bỏ qua tên thứ,
vì strptime không tự xử lý được tên thứ tiếng Việt.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

if __package__:
    from .common_utils import normalize_text, compute_article_id
else:
    from common_utils import normalize_text, compute_article_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("silver_transformer_qdnd")

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Bắt "22/08/2026 - 05:32" trong chuỗi "Thứ bảy, 22/08/2026 - 05:32"
_PUBLISHED_AT_PATTERN_RE = re.compile(r"(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}:\d{2})")


def _extract_title(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one("h1.post-title")
    if tag is None:
        return None
    text = normalize_text(tag.get_text(separator=" ", strip=True))
    return text or None


def _extract_sapo(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one("div.post-summary")
    if tag is None:
        return None
    text = normalize_text(tag.get_text(separator=" ", strip=True))
    return text or None


def _extract_published_at(soup: BeautifulSoup) -> str | None:
    container = soup.select_one("span.post-subinfo")
    if container is None:
        return None

    # Lấy toàn bộ text của container rồi regex tìm mẫu ngày giờ, thay vì
    # phụ thuộc cứng vào đúng span con nào - an toàn hơn nếu thứ tự thay đổi
    full_text = container.get_text(separator=" ", strip=True)
    match = _PUBLISHED_AT_PATTERN_RE.search(full_text)
    if match is None:
        return None

    date_str, time_str = match.groups()
    try:
        naive_dt = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
    except ValueError:
        return None
    return naive_dt.replace(tzinfo=VN_TZ).isoformat()


def _extract_author(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one("p.author-top")
    if tag is None:
        return None
    text = normalize_text(tag.get_text(separator=" ", strip=True))
    return text or None


def _extract_content_text(soup: BeautifulSoup) -> str:
    container = soup.select_one('div[itemprop="articleBody"]')
    if container is None:
        return ""
    all_p = container.find_all("p", recursive=False)
    paragraphs = [
        normalize_text(p.get_text(separator=" ", strip=True))
        for p in all_p
        if p.get_text(strip=True)
    ]
    return "\n".join(paragraphs)


def transform_record(bronze_record: dict) -> dict | None:
    url = bronze_record["url"]
    soup = BeautifulSoup(bronze_record["raw_html"], "html.parser")

    title = _extract_title(soup)
    if title is None:
        logger.warning("Bỏ qua (thiếu title): %s", url)
        return None

    sapo = _extract_sapo(soup)
    if sapo is None:
        logger.warning("Bỏ qua (thiếu sapo): %s", url)
        return None

    published_at = _extract_published_at(soup)
    if published_at is None:
        logger.warning("Bỏ qua (không parse được published_at): %s", url)
        return None

    author = _extract_author(soup)
    content_text = _extract_content_text(soup)

    return {
        "article_id": compute_article_id(url),
        "url": url,
        "source": "QDND",
        "category": bronze_record.get("category"),
        "title": title,
        "sapo": sapo,
        "author": author,
        "published_at": published_at,
        "content_text": content_text,
    }


def run_silver_transform(bronze_path: str, silver_path: str) -> None:
    bronze_path = Path(bronze_path)
    silver_path = Path(silver_path)

    total = 0
    success = 0

    with bronze_path.open("r", encoding="utf-8") as fin, \
         silver_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            total += 1
            bronze_record = json.loads(line)
            silver_record = transform_record(bronze_record)
            if silver_record is not None:
                fout.write(json.dumps(silver_record, ensure_ascii=False) + "\n")
                success += 1

    logger.info("Hoàn tất: %d/%d bản ghi Bronze được chuyển thành công sang Silver.",
                success, total)


if __name__ == "__main__":
    run_silver_transform(
        bronze_path="bronze_qdnd.jsonl",
        silver_path="silver_qdnd.jsonl",
    )
