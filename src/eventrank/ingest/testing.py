"""Bộ test hợp đồng cho người viết crawler: chạy crawler của BẠN trên fixture của BẠN, không mạng.

    from eventrank.ingest.testing import check_crawler, fixture_client_from_dir

    def test_tuoitre_qua_hop_dong():
        client = fixture_client_from_dir("tests/fixtures/crawlers/tuoitre")
        articles = check_crawler(TuoiTreRss(), client)
        assert len(articles) == 5

Fixture của một nguồn: thư mục `tests/fixtures/crawlers/<source>/` gồm file trang/RSS/sitemap đã lưu
và `routes.yaml` ánh xạ URL → file:

    routes:
      "https://tuoitre.vn/rss/tin-moi-nhat.rss": rss.xml
      "https://tuoitre.vn/bai-1.htm": bai-1.html
      "https://tuoitre.vn/robots.txt": robots.txt      # tuỳ chọn; thiếu = 404 = cho phép

URL không có trong routes → 404. Crawler đăng ký trong configs/sources.yaml mà thiếu thư mục này →
tests/ingest/test_crawler_contract.py FAIL (bắt buộc có fixture trước khi bật).

`check_crawler` kiểm: crawler khai báo đủ `source`/`name`/`parser_version`; sinh ≥ 1 bài; MỌI bài
qua `contract.validate_article` (đúng source của crawler); không trùng `article_id`. Sai →
AssertionError liệt kê mọi bài lỗi kèm lý do.
"""
from __future__ import annotations

import logging
import mimetypes
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from eventrank.ingest.base import CrawlContext, Crawler
from eventrank.ingest.contract import Article, Rejected, validate_article
from eventrank.ingest.fetch import PoliteClient

TEST_USER_AGENT = "PBL-EventLake-test/0.1 (fixture; +mailto:test@example.com)"
_CTYPES = {".xml": "application/xml", ".rss": "application/rss+xml", ".html": "text/html",
           ".htm": "text/html", ".txt": "text/plain", ".json": "application/json"}


class _NoWait:
    """Đồng hồ giả: sleep chỉ cộng thời gian, test chạy tức thì nhưng vẫn qua logic giãn cách."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def fixture_client(routes: Mapping[str, str | Path | httpx.Response],
                   base_dir: str | Path = ".") -> PoliteClient:
    """PoliteClient phục vụ file cục bộ thay cho mạng. Giá trị routes: đường dẫn file (tương đối
    base_dir) hoặc httpx.Response dựng sẵn (vd 302, 403 để thử ca xấu)."""
    base = Path(base_dir)
    requested: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        requested.append(url)
        target = routes.get(url)
        if target is None:
            return httpx.Response(404, text="không có trong routes")
        if isinstance(target, httpx.Response):
            return target
        p = base / target
        ctype = _CTYPES.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or "text/plain"
        return httpx.Response(200, content=p.read_bytes(), headers={"content-type": ctype})

    clk = _NoWait()
    client = PoliteClient(TEST_USER_AGENT, transport=httpx.MockTransport(handler), clock=clk,
                          sleep=clk.sleep)
    client.requested = requested           # type: ignore[attr-defined]  — để test xem đã gọi gì
    return client


def fixture_client_from_dir(directory: str | Path) -> PoliteClient:
    d = Path(directory)
    data = yaml.safe_load((d / "routes.yaml").read_text(encoding="utf-8")) or {}
    return fixture_client(data.get("routes") or {}, d)


def check_crawler(crawler: Crawler, client: PoliteClient | None, *, now: datetime | None = None,
                  since: datetime | None = None,
                  known_sources: set[str] | None = None) -> list[Article]:
    for attr in ("source", "name", "parser_version"):
        v = getattr(crawler, attr, None)
        assert isinstance(v, str) and v.strip(), f"crawler thiếu thuộc tính chuỗi `{attr}`"
    now = now or datetime.now(UTC)
    known = known_sources or {crawler.source}
    ctx = CrawlContext(client=client, now=now, source=crawler.source, since=since,
                       log=logging.getLogger(f"eventrank.crawler.{crawler.name}"))
    ok: list[Article] = []
    bad: list[str] = []
    for raw in crawler.crawl(ctx):
        res = validate_article(raw, known_sources=known, now=now, expected_source=crawler.source)
        if isinstance(res, Rejected):
            bad.append(f"  {res.ref}: " + "; ".join(res.errors))
        else:
            ok.append(res)
    assert not bad, f"{len(bad)} bài không qua hợp đồng Silver (mục 5.3):\n" + "\n".join(bad)
    assert ok, "crawler không sinh bài nào từ fixture"
    ids = [a.article_id for a in ok]
    dup = {a.url for a in ok if ids.count(a.article_id) > 1}
    assert not dup, f"crawler sinh trùng bài: {sorted(dup)}"
    return ok
