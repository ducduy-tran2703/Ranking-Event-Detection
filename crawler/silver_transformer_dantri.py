"""
Silver Transformer - Báo Dân Trí (dantri.com.vn)
--------------------------------------------------------
Hỗ trợ 2 kiểu cấu trúc HTML đã khảo sát:
  Kiểu 1 (bài thường): title/sapo dùng class dt-*, thân bài trong #desktop-in-article
  Kiểu 2 (emagazine):  title/sapo dùng class e-magazine__*, thân bài trong
                       div.e-magazine__body.dnews__body

published_at và author dùng CHUNG 1 selector cho cả 2 kiểu.
Nhận diện kiểu bằng cách thử selector title kiểu 2 trước (class riêng biệt,
không đụng hàng), không thấy mới thử kiểu 1.
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
logger = logging.getLogger("silver_transformer_dantri")

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
SAPO_PREFIX_RE = re.compile(r"^\(Dân trí\)\s*[-–]\s*")

TITLE_SELECTOR_KIEU2 = "h1.e-magazine__title"
SAPO_SELECTOR_KIEU2 = "h2.e-magazine__sapo"
CONTENT_SELECTOR_KIEU2 = "div.e-magazine__body.dnews__body"

TITLE_SELECTOR_KIEU1 = (
    "h1.dt-font-inter.dt-font-semibold.dt-text-black.dt-text-4xl.dt-leading-12.-dt-mb-3"
)
SAPO_SELECTOR_KIEU1 = (
    "h2.dt-font-arial.dt-font-normal.dt-text-lg.dt-leading-160.dt-text-black-mine"
)
CONTENT_SELECTOR_KIEU1 = "#desktop-in-article"

# Dùng chung cho cả 2 kiểu
PUBLISHED_AT_SELECTOR = (
    "time.dt-flex.dt-items-center.dt-font-Inter.dt-text-13px.dt-leading-5.dt-text-common-sapo"
)
AUTHOR_SELECTOR = "div.dt-font-inter.dt-font-normal.dt-text-13px.dt-leading-5.dt-text-black"


def _extract_title_sapo_content(soup: BeautifulSoup):
    """
    Thử kiểu 2 trước, không thấy thử kiểu 1.
    Trả về (title, sapo, content_container) hoặc (None, None, None) nếu không khớp kiểu nào.
    """
    title_tag = soup.select_one(TITLE_SELECTOR_KIEU2)
    if title_tag is not None:
        sapo_tag = soup.select_one(SAPO_SELECTOR_KIEU2)
        content_container = soup.select_one(CONTENT_SELECTOR_KIEU2)
        return title_tag, sapo_tag, content_container

    title_tag = soup.select_one(TITLE_SELECTOR_KIEU1)
    if title_tag is not None:
        sapo_tag = soup.select_one(SAPO_SELECTOR_KIEU1)
        content_container = soup.select_one(CONTENT_SELECTOR_KIEU1)
        return title_tag, sapo_tag, content_container

    return None, None, None


def _extract_published_at(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one(PUBLISHED_AT_SELECTOR)
    if tag is None:
        return None
    raw_value = tag.get("datetime")
    if not raw_value:
        return None
    try:
        naive_dt = datetime.strptime(raw_value.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return naive_dt.replace(tzinfo=VN_TZ).isoformat()


def _extract_author(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one(AUTHOR_SELECTOR)
    if tag is None:
        return None
    text = normalize_text(tag.get_text(separator=" ", strip=True))
    return text or None


def _extract_content_text(container) -> str:
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

    title_tag, sapo_tag, content_container = _extract_title_sapo_content(soup)
    if title_tag is None:
        logger.warning("Bỏ qua (không khớp title ở cả 2 kiểu HTML): %s", url)
        return None
    title = normalize_text(title_tag.get_text(separator=" ", strip=True))
    if not title:
        logger.warning("Bỏ qua (title rỗng sau khi trích xuất): %s", url)
        return None

    sapo = normalize_text(sapo_tag.get_text(separator=" ", strip=True)) if sapo_tag is not None else ""
    sapo = SAPO_PREFIX_RE.sub("", sapo).strip()
    if not sapo:
        # Missing sapo is a quality flag, not a reject (same as the four older sources).
        logger.warning("Thiếu sapo, để rỗng (khung gắn cờ missing_sapo): %s", url)

    published_at = _extract_published_at(soup)
    if published_at is None:
        logger.warning("Bỏ qua (không parse được published_at): %s", url)
        return None

    author = _extract_author(soup)
    content_text = _extract_content_text(content_container)

    return {
        "article_id": compute_article_id(url),
        "url": url,
        "source": "DANTRI",
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
        bronze_path="bronze_dantri.jsonl",
        silver_path="silver_dantri.jsonl",
    )
