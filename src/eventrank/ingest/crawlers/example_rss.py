"""VÍ DỤ crawler RSS cho báo GIẢ `baovidu` (https://bao-vi-du.example) — đọc để biết cách viết.

KHÔNG đăng ký trong configs/sources.yaml, KHÔNG cào báo thật. Chạy offline trong
tests/ingest/test_crawler_contract.py trên fixture tests/fixtures/crawlers/baovidu/.

Luồng (đúng thứ tự ưu tiên mục 6.3: JSON-LD → meta → bỏ qua):
1. `ctx.client.get_xml(FEED)` — RSS. HTML thay XML → NotXmlError (khung ghi lần chạy `failed`).
2. Mỗi <item>: bỏ qua bài cũ hơn lần chạy trước (`ctx.since`, trừ hao 1 giờ) — cào tăng dần.
3. `ctx.client.get(link)` — trang bài (giãn cách, robots do client lo). 404 → bỏ bài, ghi log.
4. Tách JSON-LD `NewsArticle` (headline, description, datePublished, articleSection, author);
   thiếu JSON-LD → meta `og:title`/`og:description`/`article:published_time`/`article:section`.
   Thân bài = các <p> trong <div class="article-body">.
5. `yield` dict thô đúng tên trường Silver. KHÔNG tự chuẩn hoá NFC/khoảng trắng, KHÔNG tự loại bài
   ngắn — khung (`contract.validate_article`) làm và gắn cờ. Không có ngày đăng → vẫn yield, khung
   loại và đếm `published_at_missing` (thấy trong `ingest status`), đừng tự bịa ngày.

Chỉ dùng thư viện chuẩn để ví dụ dễ đọc; crawler thật nên dùng lxml (`resolve_entities=False`) /
trafilatura như mục 6.2. `xml.etree` không tải thực thể ngoài (không XXE).
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any

from eventrank.ingest.base import CrawlContext
from eventrank.ingest.fetch import DomainBlocked, FetchError

FEED = "https://bao-vi-du.example/rss/tin-moi.rss"


class _ArticlePage(HTMLParser):
    """Gom JSON-LD, thẻ meta và đoạn văn trong <div class="article-body">."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_ld: list[str] = []
        self.meta: dict[str, str] = {}
        self.paragraphs: list[str] = []
        self._in_ld = False
        self._body_depth = 0           # >0: đang ở trong article-body
        self._in_p = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld, self._buf = True, []
        elif tag == "meta" and (a.get("property") or a.get("name")):
            self.meta[a.get("property") or a.get("name", "")] = a.get("content", "")
        elif tag == "div" and ("article-body" in a.get("class", "").split() or self._body_depth):
            self._body_depth += 1
        elif tag == "p" and self._body_depth:
            self._in_p, self._buf = True, []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_ld:
            self.json_ld.append("".join(self._buf))
            self._in_ld = False
        elif tag == "div" and self._body_depth:
            self._body_depth -= 1
        elif tag == "p" and self._in_p:
            self.paragraphs.append("".join(self._buf))
            self._in_p = False

    def handle_data(self, data: str) -> None:
        if self._in_ld or self._in_p:
            self._buf.append(data)


def _news_article(blocks: list[str]) -> dict[str, Any]:
    for b in blocks:
        try:
            data = json.loads(b)
        except json.JSONDecodeError:
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict) and d.get("@type") in ("NewsArticle", "Article"):
                return d
    return {}


def _author(ld: dict[str, Any]) -> str | None:
    a = ld.get("author")
    if isinstance(a, list):
        a = a[0] if a else None
    if isinstance(a, dict):
        a = a.get("name")
    return a or None


class ExampleRssCrawler:
    source = "baovidu"
    name = "example_rss"
    parser_version = "example-rss-1"

    def crawl(self, ctx: CrawlContext) -> Iterator[dict[str, Any]]:
        assert ctx.client is not None, "crawler này cần PoliteClient"
        root = ET.fromstring(ctx.client.get_xml(FEED))
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            pub = item.findtext("pubDate")
            pub_dt = parsedate_to_datetime(pub) if pub else None
            if ctx.since and pub_dt and pub_dt < ctx.since - timedelta(hours=1):
                continue                                  # đã cào ở lần trước
            try:
                resp = ctx.client.get(link)
            except DomainBlocked:                         # báo chặn cả domain → dừng cả lần chạy
                raise
            except FetchError as e:                       # một bài 403/hết lượt thử → bỏ bài đó
                ctx.log.warning("bỏ %s: %s", link, e)
                continue
            if resp.status_code != 200:
                ctx.log.warning("bỏ %s: HTTP %s", link, resp.status_code)
                continue
            page = _ArticlePage()
            page.feed(resp.text)
            ld, meta = _news_article(page.json_ld), page.meta
            yield {
                "url": link,
                "source": self.source,
                "category": ld.get("articleSection") or meta.get("article:section"),
                "title": ld.get("headline") or meta.get("og:title") or item.findtext("title"),
                "sapo": ld.get("description") or meta.get("og:description")
                        or item.findtext("description"),
                "author": _author(ld),
                "published_at": ld.get("datePublished") or meta.get("article:published_time")
                                or (pub_dt.isoformat() if pub_dt else None),
                "content_text": "\n\n".join(page.paragraphs),
            }
