"""Offline VnExpress integration: no network, database or R2 calls."""

import json
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from api.main import create_app
from api.schemas import CrawlRequest
from automation.config import Settings
from automation.discovery import DiscoveryIncomplete, discover
from automation.http import SourceBlocked, SourceClient
from automation.job_manager import JobManager
from automation.pipeline import Pipeline
from automation.scheduler import VN_TZ
from automation.state import SourceState
from automation.storage import read_json, write_json
from crawler.common_utils import compute_article_id
from crawler.harvester_vnexpress import extract_article_urls, normalize_article_url
from crawler.silver_transformer_vnexpress import run_silver_transform, transform_record
from process_data.clean_record import clean_record

FIXTURES = Path(__file__).parent / "fixtures" / "crawlers" / "vnexpress"
ARTICLE = (FIXTURES / "article.html").read_text(encoding="utf-8")
LISTING = (FIXTURES / "listing.html").read_text(encoding="utf-8")
URL = "https://vnexpress.net/ke-hoach-ha-tang-moi-4567890.html"
OLD = "https://vnexpress.net/ke-hoach-cu-4567889.html"
CATEGORIES = {"https://vnexpress.net/kinh-doanh": "Kinh Tế"}


def bronze(html=ARTICLE):
    return {"url": URL, "category": "Kinh Tế", "raw_html": html}


def test_scoped_listing_links_and_url_filters():
    assert extract_article_urls(BeautifulSoup(LISTING, "html.parser")) == [URL, OLD]
    assert (
        normalize_article_url("http://www.vnexpress.net/tin-123.html?tracking=1#top")
        == "https://vnexpress.net/tin-123.html"
    )
    for href in (
        "/video/tin-123.html",
        "/podcast/tin-123.html",
        "/photo/tin-123.html",
        "/interactive/tin-123.html",
        "https://vnexpress.net.evil.test/tin-123.html",
        "https://user@vnexpress.net/tin-123.html",
        "/kinh-doanh-p2",
        "/tin.html",
        "javascript:alert(1)",
        "https://[broken/tin-123.html",
    ):
        assert normalize_article_url(href) is None


def test_nine_field_silver_date_author_and_body():
    record = transform_record(bronze())
    assert set(record) == {
        "article_id",
        "url",
        "source",
        "category",
        "title",
        "sapo",
        "author",
        "published_at",
        "content_text",
    }
    assert record["article_id"] == compute_article_id(URL)
    assert record["source"] == "vnexpress"
    assert record["published_at"] == "2026-11-09T08:30:00+07:00"
    assert record["author"] == "Người Viết"
    assert "Người Chụp" not in record["content_text"]
    assert "Người Viết" not in record["content_text"]
    assert "Đã duyệt." in record["content_text"]
    assert record["content_text"].count("Đoạn thông tin nhắc lại.") == 2
    assert "không lấy" not in record["content_text"]
    assert "Xem thêm" not in record["content_text"]


@pytest.mark.parametrize(
    "date_html,expected",
    [
        (
            '<meta itemprop="datePublished" content="2026-11-09T08:30:00">',
            "2026-11-09T08:30:00+07:00",
        ),
        ('<meta name="pubdate" content="2026-11-09T09:30:00+08:00">', "2026-11-09T08:30:00+07:00"),
        (
            '<span class="date">Thứ hai, 09/11/2026, 08:30 (GMT+7)</span>',
            "2026-11-09T08:30:00+07:00",
        ),
        (
            '<meta name="pubdate" content="bad"><span class="date">09/11/2026 08:30</span>',
            "2026-11-09T08:30:00+07:00",
        ),
    ],
)
def test_date_fallbacks_and_absent_author(date_html, expected):
    record = transform_record(bronze('<h1 class="title-detail">Tiêu đề bài báo</h1>' + date_html))
    assert record["published_at"] == expected
    assert record["author"] is None


@pytest.mark.parametrize(
    "html",
    [
        '<h1 class="title-detail">Không có ngày đăng</h1>',
        '<h1 class="title-detail">Ngày sai</h1><span class="date">31/02/2026 08:30</span>',
        '<meta name="pubdate" content="2026-11-09T08:30:00">',
    ],
)
def test_bad_required_metadata_is_rejected(html):
    assert transform_record(bronze(html)) is None


def test_author_credit_and_photo_author_fallback():
    html = ARTICLE.replace("Người Viết</strong>", "Người ViếtẢnh: Credit lẫn</strong>")
    assert transform_record(bronze(html))["author"] == "Người Viết"
    html = ARTICLE.replace("<strong>Người Viết</strong>", "")
    html += (
        '<div class="width-detail-photo"><p class="author"><strong>Tác giả ảnh</strong></p></div>'
    )
    assert transform_record(bronze(html))["author"] == "Tác giả ảnh"
    html = ARTICLE.replace("<strong>Người Viết</strong>", "")
    assert clean_record(transform_record(bronze(html)))[0]["author"] is None


def test_category_pagination_bootstrap_incremental_and_cap(tmp_path):
    settings, now = Settings(data_dir=tmp_path), datetime.now(VN_TZ)
    client = Mock()
    client.get.return_value = Mock(text=LISTING)
    with patch("automation.discovery.vne.TARGET_CATEGORIES", CATEGORIES):
        assert (URL, "Kinh Tế") in list(discover("vnexpress", client, set(), now, settings))
        assert [c.args[0] for c in client.get.call_args_list] == [
            "https://vnexpress.net/kinh-doanh",
            "https://vnexpress.net/kinh-doanh-p2",
            "https://vnexpress.net/kinh-doanh-p3",
        ]
        client.reset_mock()
        list(discover("vnexpress", client, {URL, OLD}, now, settings))
        assert client.get.call_count == 2
        with pytest.raises(DiscoveryIncomplete, match="Reached 2 pages"):
            list(
                discover(
                    "vnexpress",
                    client,
                    {OLD},
                    now,
                    replace(settings, max_listing_pages=2, bootstrap_listing_pages=2),
                )
            )


@pytest.mark.parametrize("html", ["", "<html>Challenge</html>"])
def test_unrecognized_category_is_not_silent_success(tmp_path, html):
    client = Mock()
    client.get.return_value = Mock(text=html)
    with (
        patch("automation.discovery.vne.TARGET_CATEGORIES", CATEGORIES),
        pytest.raises(DiscoveryIncomplete),
    ):
        list(discover("vnexpress", client, set(), datetime.now(VN_TZ), Settings(data_dir=tmp_path)))


def test_pipeline_export_dedup_and_bronze_resume(tmp_path):
    pipeline = Pipeline(Settings(data_dir=tmp_path), threading.Event())
    client = Mock()
    client.get.return_value = Mock(text=ARTICLE)
    with (
        patch(
            "automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế"), (URL, "Kinh Tế")])
        ),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        result = pipeline.run_source("vnexpress", "first", lambda _: None)
    assert result["status"] == "completed", result
    assert result["clean"] == 1
    assert result["discovery_mode"] == "bootstrap_recent_pages"
    key = compute_article_id(URL)
    raw = read_json(pipeline.article_path("bronze", "vnexpress", key))
    assert 'name="pubdate"' in raw["raw_html"]
    record = json.loads(
        (tmp_path / "jobs/first/silver/vnexpress.jsonl").read_text(encoding="utf-8")
    )
    assert record["source"] == "vnexpress"
    with (
        patch("automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế")])),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        assert pipeline.run_source("vnexpress", "again", lambda _: None)["clean"] == 0
    assert client.get.call_count == 1
    replay = Pipeline(Settings(data_dir=tmp_path / "replay"), threading.Event())
    write_json(replay.article_path("bronze", "vnexpress", key), raw)
    offline = Mock()
    offline.get.side_effect = AssertionError("Must reuse Bronze")
    assert replay.process_article("vnexpress", key, {"url": URL}, offline) == ("clean", None)


def test_blocked_discovery_stops_source_and_preserves_pending_urls(tmp_path):
    def blocked(*args):
        yield URL, "Kinh Tế"
        raise SourceBlocked("VnExpress HTTP 302")

    client = Mock()
    pipeline = Pipeline(Settings(data_dir=tmp_path), threading.Event())
    with (
        patch("automation.pipeline.discover", side_effect=blocked),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        result = pipeline.run_source("vnexpress", "blocked", lambda _: None)
    assert result["status"] == "blocked"
    assert client.get.call_count == 0
    state = SourceState(tmp_path, "vnexpress")
    assert state.value["last_discovery"] is None
    assert state.articles[compute_article_id(URL)]["status"] == "pending"


def response(status, text=""):
    reply = requests.Response()
    reply.status_code, reply._content, reply.encoding = status, text.encode(), "utf-8"
    return reply


@pytest.mark.parametrize("status", [301, 302, 307, 308, 403, 428, 429])
def test_http_redirect_or_block_is_never_followed(tmp_path, monkeypatch, status):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "EventRank-Test/1.0 (+mailto:test@example.com)")
    client = SourceClient("vnexpress", Settings(data_dir=tmp_path), threading.Event())
    session = Mock()
    reply = response(status)
    reply.headers["Location"] = "/challenge"
    session.get.return_value = reply
    with (
        patch.object(client, "_check_robots"),
        patch.object(client, "_session", return_value=session),
    ):
        with pytest.raises(SourceBlocked):
            client.get(URL)
        with pytest.raises(SourceBlocked):
            client.get(URL)
    assert session.get.call_count == 1
    assert session.get.call_args.kwargs["allow_redirects"] is False


def test_robots_checked_cached_and_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "EventRank-Test/1.0 (+mailto:test@example.com)")
    client = SourceClient("vnexpress", Settings(data_dir=tmp_path), threading.Event())
    assert client.delay >= 2
    with patch.object(
        client,
        "_get_raw",
        side_effect=[
            response(200, "User-agent: *\nCrawl-delay: 5\nDisallow: /photo/"),
            response(200),
            response(200),
        ],
    ) as raw:
        client.get(URL)
        client.get(URL)
        assert raw.call_args_list[0].args[0] == "https://vnexpress.net/robots.txt"
        assert raw.call_count == 3
        assert client.delay == 5
    denied = SourceClient("vnexpress", Settings(data_dir=tmp_path), threading.Event())
    with patch.object(
        denied, "_get_raw", return_value=response(200, "User-agent: *\nDisallow: /")
    ) as raw:
        with pytest.raises(SourceBlocked, match="robots"):
            denied.get(URL)
        assert raw.call_count == 1
    monkeypatch.delenv("CRAWLER_USER_AGENT")
    with pytest.raises(ValueError, match="CRAWLER_USER_AGENT"):
        SourceClient("vnexpress", Settings(data_dir=tmp_path), threading.Event())


def test_api_job_and_saved_schedule(tmp_path):
    class QuietManager(JobManager):
        def _loop(self):
            self.stop.wait()

    settings = Settings(data_dir=tmp_path, scheduler_enabled=False)
    assert "vnexpress" in CrawlRequest().sources
    client = Mock()
    client.get.return_value = Mock(text=ARTICLE)
    with (
        TestClient(create_app(settings, QuietManager)) as api,
        patch("automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế")])),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        job = api.post("/crawl/jobs", json={"sources": ["vnexpress"]})
        assert job.status_code == 202
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = api.get("/crawl/jobs/" + job.json()["id"]).json()
            if result["status"] not in ("queued", "running"):
                break
            time.sleep(0.01)
        assert result["status"] == "completed", result
        assert result["results"]["vnexpress"]["clean"] == 1
        assert api.patch("/crawl/schedule", json={"sources": ["qdnd"]}).status_code == 200
    with TestClient(create_app(settings, QuietManager)) as api:
        assert api.get("/crawl/schedule").json()["sources"] == ["qdnd"]
        assert (
            api.patch("/crawl/schedule", json={"sources": ["qdnd", "vnexpress"]}).status_code == 200
        )


def test_offline_transform_does_not_overwrite(tmp_path):
    source, target = tmp_path / "bronze.jsonl", tmp_path / "silver.jsonl"
    source.write_text(json.dumps(bronze()), encoding="utf-8")
    run_silver_transform(str(source), str(target))
    assert json.loads(target.read_text(encoding="utf-8"))["source"] == "vnexpress"
    with pytest.raises(FileExistsError):
        run_silver_transform(str(source), str(target))
