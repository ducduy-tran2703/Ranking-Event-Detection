"""Hợp đồng lớp Silver cho MỘT bài (docs/tong-hop.md mục 5.3): chuẩn hoá, kiểm tra, gắn cờ.

Mọi đường vào DB (crawler, `import-jsonl`, `replay`) đều đi qua `validate_article` — đây là chỗ duy
nhất quyết định một bài có hợp lệ không, để dữ liệu của sáu báo do sáu người cào trông như một.

Trả về `Article` (đã chuẩn hoá) HOẶC `Rejected` (mọi lỗi của bài, không chỉ lỗi đầu tiên) — không
ném ngoại lệ, để chạy theo lô không dừng cả lô vì một bài.

Loại bài (Rejected) chỉ khi dữ liệu không thể lưu đúng nghĩa: thiếu/sai `url` (khoá), `article_id`
không khớp `sha256(url)`, `source` lạ, thiếu `title`/`category`, `published_at` thiếu hoặc KHÔNG có
múi giờ (giờ "trần" lệch 7 tiếng tuỳ máy đọc — bẫy đã gặp). Phần còn lại theo nguyên tắc "đánh dấu,
không xoá" (mục 6.1): sapo rỗng, thân bài rỗng/ngắn, thiếu tác giả, ngày ở tương lai →
`quality_flags`.

Chuẩn hoá: NFC (bẫy 6, mục 6.5: NFD làm hỏng băm, so trùng, tách từ — kho thật có 264 trường NFD);
title/sapo/category/author gộp mọi khoảng trắng thành một dấu cách; content_text giữ xuống dòng
(đoạn văn), gộp khoảng trắng trong dòng, tối đa một dòng trống giữa hai đoạn. ⚠ Offset NER của Gold
(mục 5.4) tính trên văn bản Silver GỐC trên R2: với các bài NFD, văn bản trong DB dài khác bản gốc.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

SILVER_FIELDS = ("article_id", "url", "source", "category", "title", "sapo", "author",
                 "published_at", "content_text")
SHORT_BODY_WORDS = 80                    # 1–79 từ = thân bài quá ngắn (ngưỡng tab Chất lượng)
FUTURE_TOLERANCE = timedelta(hours=1)    # published_at > now + 1 giờ = ngày ở tương lai
VN = timezone(timedelta(hours=7))
_SOURCE = re.compile(r"^[a-z0-9_]+$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")


def article_id_for(url: str) -> str:
    """Khoá của một bài: sha256 của URL nguyên văn (UTF-8). Không chuẩn hoá URL ở đây — đổi URL là
    đổi khoá, mọi bảng phía sau mất liên kết."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def clean_line(s: Any) -> str:
    """NFC + gộp mọi khoảng trắng (cả xuống dòng, tab) thành một dấu cách."""
    if s is None:
        return ""
    return " ".join(unicodedata.normalize("NFC", str(s)).split())


def clean_body(s: Any) -> str:
    """NFC cho thân bài, giữ cấu trúc đoạn văn."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFC", str(s)).replace("\r\n", "\n").replace("\r", "\n")
    lines = (" ".join(line.split()) for line in s.split("\n"))
    return _MANY_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def word_count(s: str) -> int:
    return len(s.split())


@dataclass(frozen=True)
class Article:
    article_id: str
    url: str
    source: str
    category: str
    title: str
    sapo: str
    author: str | None
    published_at: datetime          # luôn có múi giờ (UTC sau chuẩn hoá)
    content_text: str
    quality_flags: tuple[str, ...] = ()
    content_hash: str = field(default="", compare=False)

    def to_silver(self) -> dict[str, Any]:
        """Một dòng JSONL đúng hợp đồng 5.3 (published_at theo giờ Việt Nam, +07:00)."""
        d = {k: getattr(self, k) for k in SILVER_FIELDS}
        d["published_at"] = self.published_at.astimezone(VN).isoformat()
        return d


@dataclass(frozen=True)
class Rejected:
    ref: str                        # url (hoặc article_id) để tìm lại bài trong nguồn
    errors: tuple[str, ...]         # "<mã>: <chi tiết>"; mã dùng để thống kê lý do loại

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(e.split(":", 1)[0] for e in self.errors)


ValidationResult = Article | Rejected


def content_hash(category: str, title: str, sapo: str, author: str | None,
                 published_at: datetime, content_text: str) -> str:
    """sha256 các trường nội dung ĐÃ chuẩn hoá: cào lại bài không đổi → cùng hash → không UPDATE."""
    payload = json.dumps([category, title, sapo, author,
                          published_at.astimezone(UTC).isoformat(), content_text],
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_published(v: Any, errors: list[str]) -> datetime | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        errors.append("published_at_missing: thiếu ngày đăng")
        return None
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.strip())
        except ValueError:
            errors.append(f"published_at_invalid: không phải ISO 8601: {v[:40]!r}")
            return None
    else:
        errors.append(f"published_at_invalid: kiểu {type(v).__name__}")
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        errors.append("published_at_naive: ngày đăng không có múi giờ (cần +07:00)")
        return None
    return dt.astimezone(UTC)


def validate_article(raw: Any, *, known_sources: Collection[str], now: datetime,
                     expected_source: str | None = None) -> ValidationResult:
    """Kiểm tra + chuẩn hoá một bài thô (dict). `known_sources`: các source có trong bảng `sources`.
    `expected_source`: source của crawler sinh ra bài (bài của báo khác → loại). `now`: mốc so
    `future_date` (giờ thật khi cào/nhập; giờ giả lập khi replay)."""
    if not isinstance(raw, Mapping):
        return Rejected("?", (f"not_an_object: cần dict, nhận {type(raw).__name__}",))
    errors: list[str] = []

    url = raw.get("url")
    url = url.strip() if isinstance(url, str) else ""
    if not url:
        errors.append("url_missing: thiếu url")
    elif not url.startswith("https://"):
        errors.append(f"url_not_https: {url[:80]}")
    elif any(c.isspace() for c in url) or not urlsplit(url).netloc:
        errors.append(f"url_invalid: {url[:80]}")
    aid = article_id_for(url) if url else ""
    given = raw.get("article_id")
    if given not in (None, "") and url:
        g = str(given).strip().lower()
        if not _HEX64.match(g) or g != aid:
            errors.append(f"article_id_mismatch: {str(given)[:20]} ≠ sha256(url)")

    source = str(raw.get("source") or "").strip().lower()
    if not source:
        errors.append("source_missing: thiếu source")
    elif not _SOURCE.match(source) or source not in known_sources:
        errors.append(f"source_unknown: {source[:30]!r} không có trong bảng sources "
                      "(thêm vào configs/sources.yaml rồi `ingest sources sync`)")
    elif expected_source is not None and source != expected_source:
        errors.append(f"source_mismatch: bài ghi {source!r}, crawler là {expected_source!r}")

    category = clean_line(raw.get("category"))
    if not category:
        errors.append("category_missing: thiếu chuyên mục")
    title = clean_line(raw.get("title"))
    if not title:
        errors.append("title_missing: thiếu tiêu đề")
    published_at = _parse_published(raw.get("published_at"), errors)

    if errors:
        return Rejected(url or str(given or "?"), tuple(errors))
    assert published_at is not None

    sapo = clean_line(raw.get("sapo"))
    author = clean_line(raw.get("author")) or None
    body = clean_body(raw.get("content_text"))
    n_words = word_count(body)
    flags = []
    if not sapo:
        flags.append("missing_sapo")
    if n_words == 0:
        flags.append("no_body")
    elif n_words < SHORT_BODY_WORDS:
        flags.append("short_body")
    if author is None:
        flags.append("missing_author")
    if published_at > now + FUTURE_TOLERANCE:
        flags.append("future_date")
    return Article(
        article_id=aid, url=url, source=source, category=category, title=title, sapo=sapo,
        author=author, published_at=published_at, content_text=body,
        quality_flags=tuple(flags),
        content_hash=content_hash(category, title, sapo, author, published_at, body),
    )
