"""
Silver Transformer - Báo Nhân Dân điện tử (nhandan.vn)
--------------------------------------------------------
Đọc bronze_nhandan.jsonl, parse raw_html (chỉ chứa nội dung trong div.article)
thành các trường có cấu trúc, ghi ra silver_nhandan.jsonl.

Khác biệt so với báo Chính phủ:
- published_at đọc trực tiếp từ attribute "content" của thẻ
  <meta class="cms-date" itemprop="datePublished">, đã sẵn định dạng
  ISO 8601 kèm offset giờ Việt Nam - chỉ cần validate, không cần strptime.
- Phân loại bài viết qua tiền tố trong title: [Ảnh], [Video], [Infographic].
  Bài [Infographic] bị loại bỏ hoàn toàn. Tiền tố [Ảnh]/[Video] bị cắt khỏi
  title trước khi lưu (không lưu thêm field phân loại, giữ đúng schema_contract.md).
- Ghi đè toàn bộ file Silver mỗi lần chạy, giống Chính phủ.
"""

import json
import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup

if __package__:
    from .common_utils import normalize_text, compute_article_id
else:
    from common_utils import normalize_text, compute_article_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("silver_transformer_nhandan")

# Nhận diện và cắt tiền tố loại bài viết ở đầu title, ví dụ "[Ảnh] Toàn cảnh..."
_ARTICLE_TYPE_PREFIX_RE = re.compile(r"^\s*\[(Ảnh|Video|Infographic)\]\s*", re.IGNORECASE)


def _detect_and_strip_prefix(title: str) -> tuple[str, str]:
    """
    Trả về (article_type, title_đã_cắt_tiền_tố).
    article_type in {"news", "anh", "video", "infographic"}.
    """
    match = _ARTICLE_TYPE_PREFIX_RE.match(title)
    if match is None:
        return "news", title

    prefix = match.group(1).lower()
    stripped_title = _ARTICLE_TYPE_PREFIX_RE.sub("", title, count=1).strip()

    if prefix == "video":
        return "video", stripped_title
    if prefix == "infographic":
        return "infographic", stripped_title
    return "anh", stripped_title  # "ảnh" (không dấu, viết thường để so sánh)


def _extract_title(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one("h1.article__title.cms-title")
    if tag is None:
        return None
    text = normalize_text(tag.get_text(separator=" ", strip=True))
    return text or None


def _extract_sapo(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one("div.article__sapo.cms-desc")
    if tag is None:
        return None
    text = normalize_text(tag.get_text(separator=" ", strip=True))
    return text or None


def _extract_published_at(soup: BeautifulSoup) -> str | None:
    """
    Đọc trực tiếp attribute "content" của meta.cms-date - đã sẵn ISO 8601
    kèm offset giờ Việt Nam, chỉ cần validate cú pháp.
    """
    tag = soup.select_one('meta.cms-date[itemprop="datePublished"]')
    if tag is None:
        return None
    content = tag.get("content")
    if not content:
        return None

    from datetime import datetime
    try:
        datetime.fromisoformat(content)  # chỉ để validate, giữ nguyên chuỗi gốc
    except ValueError:
        logger.warning("published_at không hợp lệ: %s", content)
        return None

    return content


def _extract_author(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one("div.article__author")
    if tag is None:
        return None
    text = normalize_text(tag.get_text(separator=" ", strip=True))
    return text or None


def _extract_content_text(soup: BeautifulSoup) -> str:
    container = soup.select_one("div.article__body.zce-content-body.cms-body")
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

    raw_title = _extract_title(soup)
    if raw_title is None:
        logger.warning("Bỏ qua (thiếu title): %s", url)
        return None

    article_type, title = _detect_and_strip_prefix(raw_title)
    if article_type == "infographic":
        logger.info("Bỏ qua (loại Infographic, không cào): %s", url)
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
        "source": "NHANDAN",
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
        bronze_path="bronze_nhandan.jsonl",
        silver_path="silver_nhandan.jsonl",
    )
