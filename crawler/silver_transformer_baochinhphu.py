"""
Silver Transformer - Báo Điện tử Chính phủ (baochinhphu.vn)
--------------------------------------------------------------
Đọc bronze_baochinhphu.jsonl, parse raw_html (chỉ chứa nội dung trong
article.detail-mcontent) thành các trường có cấu trúc, ghi ra
silver_baochinhphu.jsonl.

Đặc điểm:
- Ghi đè toàn bộ file Silver mỗi lần chạy (Silver luôn có thể tái sinh
  100% từ Bronze, không cần cơ chế incremental ở giai đoạn train model).
- Bản ghi thiếu field bắt buộc (title, published_at không parse được)
  sẽ bị bỏ qua, có log cảnh báo kèm url. Thiếu sapo thì để "" (khung gắn cờ
  missing_sapo, không loại bài).
- author: có thể là None nếu bài không có dòng tác giả cuối bài.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

if __package__:
    from .common_utils import normalize_text as _normalize_text, compute_article_id as _compute_article_id
else:
    from common_utils import normalize_text as _normalize_text, compute_article_id as _compute_article_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("silver_transformer")

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
SAPO_PREFIX_RE = re.compile(r"^\(Chinhphu\.vn\)\s*[-–]\s*")


def _extract_title(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one("h1.detail-title")
    if tag is None:
        return None
    text = _normalize_text(tag.get_text(separator=" ", strip=True))
    return text or None


def _extract_sapo(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one("h2.detail-sapo")
    if tag is None:
        return None
    text = _normalize_text(tag.get_text(separator=" ", strip=True))
    if not text:
        return None
    return SAPO_PREFIX_RE.sub("", text).strip()


def _extract_published_at(soup: BeautifulSoup) -> str | None:
    """
    Trả về chuỗi ISO 8601 theo giờ Việt Nam (KHÔNG quy đổi UTC),
    hoặc None nếu không parse được.
    """
    div = soup.select_one('div[data-role="publishdate"]')
    if div is None:
        return None

    # Chỉ lấy text node con trực tiếp, bỏ qua span.icon lồng bên trong
    parts = [t.strip() for t in div.find_all(string=True, recursive=False) if t.strip()]
    if len(parts) < 2:
        return None

    datetime_str = " ".join(parts[:2])  # "16/09/2026 14:32"
    try:
        naive_dt = datetime.strptime(datetime_str, "%d/%m/%Y %H:%M")
    except ValueError:
        return None

    vn_dt = naive_dt.replace(tzinfo=VN_TZ)
    return vn_dt.isoformat()  # ví dụ: "2026-09-16T14:32:00+07:00"


def _extract_author_and_content(soup: BeautifulSoup) -> tuple[str | None, str]:
    container = soup.select_one("div.detail-content.afcbc-body.clearfix")
    if container is None:
        return None, ""

    all_p = container.find_all("p", recursive=False)
    if not all_p:
        return None, ""

    author = None
    content_paragraphs = all_p

    last_p = all_p[-1]
    style = last_p.get("style", "")
    if "right" in style :
        author = _normalize_text(last_p.get_text(separator=" ", strip=True))
        content_paragraphs = all_p[:-1]

    content_text = "\n".join(
        _normalize_text(p.get_text(separator=" ", strip=True))
        for p in content_paragraphs
        if p.get_text(strip=True)
    )
    return author, content_text


def transform_record(bronze_record: dict) -> dict | None:
    """Biến đổi 1 bản ghi Bronze thành 1 bản ghi Silver. Trả None nếu thiếu field bắt buộc."""
    url = bronze_record["url"]
    soup = BeautifulSoup(bronze_record["raw_html"], "html.parser")

    title = _extract_title(soup)
    if title is None:
        logger.warning("Bỏ qua (thiếu title): %s", url)
        return None

    sapo = _extract_sapo(soup)
    if not sapo:
        # Missing sapo is a quality flag, not a reject (same as the four older sources).
        logger.warning("Thiếu sapo, để rỗng (khung gắn cờ missing_sapo): %s", url)
        sapo = ""

    published_at = _extract_published_at(soup)
    if published_at is None:
        logger.warning("Bỏ qua (không parse được published_at): %s", url)
        return None

    author, content_text = _extract_author_and_content(soup)

    return {
        "article_id": _compute_article_id(url),
        "url": url,
        "source": "BAOCHINHPHU",
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
        bronze_path="bronze_baochinhphu.jsonl",
        silver_path="silver_baochinhphu.jsonl",
    )
