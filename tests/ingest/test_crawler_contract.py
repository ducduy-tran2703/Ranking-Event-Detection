"""Bộ test hợp đồng cho crawler (`eventrank.ingest.testing`), chạy offline trên fixture.

1. Crawler VÍ DỤ (báo giả `baovidu`) — minh hoạ cách test một crawler.
2. MỌI crawler đăng ký trong configs/sources.yaml phải có fixture tests/fixtures/crawlers/<source>/
   và qua hợp đồng — tự động, người viết crawler không phải sửa file này.
"""
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from eventrank.ingest import fetch, sources, testing
from eventrank.ingest.crawlers.example_rss import FEED, ExampleRssCrawler

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/crawlers"
NOW = datetime(2026, 9, 18, tzinfo=UTC)


def test_crawler_vi_du_qua_hop_dong():
    client = testing.fixture_client_from_dir(FIXTURES / "baovidu")
    arts = testing.check_crawler(ExampleRssCrawler(), client, now=NOW)
    by_title = {a.title: a for a in arts}
    assert len(arts) == 3                                    # bài 4 trả 404 → bỏ
    a1 = by_title["Hà Nội khởi công cầu mới bắc qua sông Hồng"]  # tiêu đề NFD đã về NFC
    assert unicodedata.is_normalized("NFC", a1.title) and a1.author == "Minh Thư"
    assert a1.category == "Thời sự" and a1.quality_flags == ()
    assert "đoạn thứ hai, có khoảng trắng thừa" in a1.content_text
    assert "Bản quyền" not in a1.content_text               # ngoài article-body
    a2 = by_title["Tuyển Việt Nam thắng 2-0"]
    assert set(a2.quality_flags) == {"short_body", "missing_author"}
    assert a2.sapo == "Video bàn thắng."                     # JSON-LD rỗng → lấy từ RSS
    a3 = by_title["Giá vàng tăng phiên thứ ba liên tiếp"]    # không JSON-LD → meta
    assert a3.category == "Kinh tế"
    assert "https://bao-vi-du.example/robots.txt" in client.requested


def test_crawler_vi_du_cao_tang_dan_theo_since():
    client = testing.fixture_client_from_dir(FIXTURES / "baovidu")
    arts = testing.check_crawler(ExampleRssCrawler(), client, now=NOW,
                                 since=datetime(2026, 9, 17, 0, 0, tzinfo=UTC))
    assert [a.category for a in arts] == ["Kinh tế"]


def test_rss_bi_chuyen_huong_ve_trang_chu_thi_loi_ro_rang():
    routes = {FEED: httpx.Response(302, headers={"location": "https://bao-vi-du.example/"}),
              "https://bao-vi-du.example/": httpx.Response(200, text="<html></html>",
                                                           headers={"content-type": "text/html"})}
    client = testing.fixture_client(routes)
    with pytest.raises(fetch.NotXmlError):
        testing.check_crawler(ExampleRssCrawler(), client, now=NOW)


def test_bo_test_bat_duoc_crawler_sai_hop_dong():
    class Sai:
        source, name, parser_version = "baovidu", "sai", "0"

        def crawl(self, ctx):
            yield {"url": "http://bao-vi-du.example/x", "source": "baovidu", "title": "x",
                   "category": "y", "published_at": "2026-09-16T07:00:00"}

    with pytest.raises(AssertionError, match="url_not_https.*published_at_naive"):
        testing.check_crawler(Sai(), None, now=NOW)


REGISTERED = [s for s in sources.load_sources() if s["crawler"]]


@pytest.mark.parametrize("src", REGISTERED, ids=[s["source"] for s in REGISTERED])
def test_moi_crawler_da_dang_ky_qua_hop_dong_tren_fixture(src):
    d = FIXTURES / src["source"]
    assert (d / "routes.yaml").exists(), (
        f"{src['source']}: crawler đã đăng ký nhưng thiếu {d}/routes.yaml + trang mẫu "
        "(docs/tong-hop.md mục 17.4.5)")
    crawler = sources.load_crawler(src["crawler"])
    assert crawler.source == src["source"]
    testing.check_crawler(crawler, testing.fixture_client_from_dir(d))
