"""Offline checks for VietnamNet: HTML fixtures and mocked HTTP only."""

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
from crawler.harvester_vietnamnet import extract_article_urls, normalize_article_url
from crawler.silver_transformer_vietnamnet import run_silver_transform, transform_record
from process_data.clean_record import clean_record

FIXTURES = Path(__file__).parent / "fixtures" / "crawlers" / "vietnamnet"
ARTICLE = (FIXTURES / "article.html").read_text(encoding="utf-8")
LISTING = (FIXTURES / "listing.html").read_text(encoding="utf-8")
URL = "https://vietnamnet.vn/ke-hoach-ha-tang-moi-1234567.html"
OLD = "https://vietnamnet.vn/ke-hoach-cu-1234566.html"
CATEGORIES = {"https://vietnamnet.vn/kinh-doanh": "Kinh Tế"}


def bronze(html=ARTICLE):
    return {"url": URL, "category": "Kinh Tế", "raw_html": html}


def test_listing_canonicalizes_urls_and_filters_media_and_external_links():
    assert extract_article_urls(BeautifulSoup(LISTING, "html.parser")) == [URL, OLD]
    assert (
        normalize_article_url("http://www.vietnamnet.vn/tin-123.html?q=a#top")
        == "https://vietnamnet.vn/tin-123.html"
    )
    assert (
        normalize_article_url("tin-123.html", "https://vietnamnet.vn/kinh-doanh-page0")
        == "https://vietnamnet.vn/tin-123.html"
    )
    for href in (
        "/video/tin-123.html",
        "/podcast/tin-123.html",
        "/interactive/tin-123.html",
        "/multimedia/tin-123.html",
        "/talkshow/tin-123.html",
        "/tin-123.htm",
        "/kinh-doanh-page0",
        "https://vietnamnet.vn.evil.test/tin-123.html",
        "https://user@vietnamnet.vn/tin-123.html",
        "https://[broken/tin-123.html",
        "mailto:test@example.com",
        "javascript:alert(1)",
    ):
        assert normalize_article_url(href) is None


def test_silver_schema_date_conversion_authors_and_body():
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
    assert record["source"] == "vietnamnet"
    assert record["published_at"] == "2026-11-09T08:30:00+07:00"
    assert record["author"] == "Tác giả A, Tác giả B"
    assert "Đã duyệt." in record["content_text"]
    assert record["content_text"].count("Đoạn thông tin được nhắc lại.") == 2
    assert "không lấy" not in record["content_text"]
    assert "Xem thêm" not in record["content_text"]


@pytest.mark.parametrize(
    "date_html,expected",
    [
        (
            '<meta property="article:published_time" content="2026-11-09T01:30:00Z">',
            "2026-11-09T08:30:00+07:00",
        ),
        ('<meta name="pubdate" content="2026-11-09T08:30:00">', "2026-11-09T08:30:00+07:00"),
        (
            '<div class="bread-crumb-detail__time">Thứ hai, 09/11/2026 - 08:30 (GMT+7)</div>',
            "2026-11-09T08:30:00+07:00",
        ),
        ('<div class="publish-date">09/11/2026 08:30</div>', "2026-11-09T08:30:00+07:00"),
        (
            '<script type="application/ld+json">[{"@type":"NewsArticle","datePublished":"2026-11-09T09:30:00+08:00"}]</script>',
            "2026-11-09T08:30:00+07:00",
        ),
    ],
)
def test_date_fallbacks_and_missing_author(date_html, expected):
    html = '<h1 class="title">Tiêu đề bài báo</h1>' + date_html
    record = transform_record(bronze(html))
    assert record["published_at"] == expected
    assert record["author"] is None


def test_dom_author_precedence_and_maincontent_class_fallback():
    html = ARTICLE.replace('id="maincontent"', 'class="maincontent"')
    html += '<div class="article-detail-author"><span class="name"><a>Tác giả DOM</a></span></div>'
    record = transform_record(bronze(html))
    assert record["author"] == "Tác giả DOM"
    assert "Đã duyệt." in record["content_text"]


@pytest.mark.parametrize(
    "html",
    [
        '<h1 class="title">Không có ngày</h1>',
        '<h1 class="title">Ngày sai</h1><div class="publish-date">31/02/2026 08:30</div>',
        '<meta name="pubdate" content="2026-11-09T08:30:00">',
    ],
)
def test_missing_or_invalid_required_metadata_is_rejected(html):
    assert transform_record(bronze(html)) is None


def test_cleaning_missing_author_keeps_null():
    html = '<h1 class="title">Tiêu đề bài báo mẫu</h1><meta name="pubdate" content="2026-11-09T08:30:00">'
    html += '<div id="maincontent"><p>' + "Nội dung bài báo kiểm thử. " * 20 + "</p></div>"
    assert clean_record(transform_record(bronze(html)))[0]["author"] is None


def test_bootstrap_starts_at_page_zero_and_incremental_stops_after_two_known_pages(tmp_path):
    client = Mock()
    client.get.return_value = Mock(text=LISTING)
    settings, now = Settings(data_dir=tmp_path), datetime.now(VN_TZ)
    with patch("automation.discovery.vn.TARGET_CATEGORIES", CATEGORIES):
        found = list(discover("vietnamnet", client, set(), now, settings))
        assert (URL, "Kinh Tế") in found
        assert [call.args[0] for call in client.get.call_args_list] == [
            f"https://vietnamnet.vn/kinh-doanh-page{i}" for i in range(3)
        ]
        client.reset_mock()
        list(discover("vietnamnet", client, {URL, OLD}, now, settings))
        assert client.get.call_count == 2
        with pytest.raises(DiscoveryIncomplete, match="Reached 2 pages"):
            list(
                discover(
                    "vietnamnet",
                    client,
                    {OLD},
                    now,
                    replace(settings, max_listing_pages=2, bootstrap_listing_pages=2),
                )
            )


def test_single_known_page_does_not_hide_new_articles_on_next_page(tmp_path):
    client = Mock()
    known = f'<a href="{OLD}">Bài cũ</a>'
    client.get.side_effect = [
        Mock(text=known),
        Mock(text=LISTING),
        Mock(text=known),
        Mock(text=known),
    ]
    with patch("automation.discovery.vn.TARGET_CATEGORIES", CATEGORIES):
        found = list(
            discover("vietnamnet", client, {OLD}, datetime.now(VN_TZ), Settings(data_dir=tmp_path))
        )
    assert (URL, "Kinh Tế") in found
    assert client.get.call_count == 4


@pytest.mark.parametrize("html", ["", "<html>Challenge</html>"])
def test_empty_and_unrecognized_category_pages_are_failures(tmp_path, html):
    client = Mock()
    client.get.return_value = Mock(text=html)
    with (
        patch("automation.discovery.vn.TARGET_CATEGORIES", CATEGORIES),
        pytest.raises(DiscoveryIncomplete),
    ):
        list(
            discover("vietnamnet", client, set(), datetime.now(VN_TZ), Settings(data_dir=tmp_path))
        )


def test_partial_discovery_saves_urls_without_advancing_watermark(tmp_path):
    client = Mock()
    client.get.side_effect = [
        Mock(text=LISTING),
        Mock(text="<html>Challenge</html>"),
        Mock(text=ARTICLE),
        Mock(text=ARTICLE),
    ]
    pipeline = Pipeline(Settings(data_dir=tmp_path), threading.Event())
    with (
        patch("automation.discovery.vn.TARGET_CATEGORIES", CATEGORIES),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        result = pipeline.run_source("vietnamnet", "partial", lambda _: None)
    assert result["status"] == "partial", result
    assert result["clean"] == 2
    assert SourceState(tmp_path, "vietnamnet").value["last_discovery"] is None


def test_pipeline_export_resume_and_dedup(tmp_path):
    pipeline = Pipeline(Settings(data_dir=tmp_path), threading.Event())
    client = Mock()
    client.get.return_value = Mock(text=ARTICLE)
    with (
        patch(
            "automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế"), (URL, "Kinh Tế")])
        ),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        result = pipeline.run_source("vietnamnet", "first", lambda _: None)
    assert result["status"] == "completed", result
    assert result["clean"] == 1
    assert result["discovery_mode"] == "bootstrap_recent_pages"
    key = compute_article_id(URL)
    raw = read_json(pipeline.article_path("bronze", "vietnamnet", key))
    assert "application/ld+json" in raw["raw_html"]
    exported = json.loads(
        (tmp_path / "jobs/first/silver/vietnamnet.jsonl").read_text(encoding="utf-8")
    )
    assert exported["source"] == "vietnamnet"
    with (
        patch("automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế")])),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        assert pipeline.run_source("vietnamnet", "again", lambda _: None)["clean"] == 0
    assert client.get.call_count == 1
    replay = Pipeline(Settings(data_dir=tmp_path / "replay"), threading.Event())
    write_json(replay.article_path("bronze", "vietnamnet", key), raw)
    offline = Mock()
    offline.get.side_effect = AssertionError("Must reuse Bronze without network")
    assert replay.process_article("vietnamnet", key, {"url": URL}, offline) == ("clean", None)


def response(status, text=""):
    result = requests.Response()
    result.status_code, result._content, result.encoding = status, text.encode(), "utf-8"
    return result


def test_robots_cached_and_delay_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "EventRank-Test/1.0 (+mailto:test@example.com)")
    client = SourceClient("vietnamnet", Settings(data_dir=tmp_path), threading.Event())
    assert client.delay >= 2
    with patch.object(
        client,
        "_get_raw",
        side_effect=[
            response(200, "User-agent: *\nCrawl-delay: 6\nDisallow: /video/"),
            response(200),
            response(200),
        ],
    ) as raw:
        client.get(URL)
        client.get(URL)
        assert raw.call_args_list[0].args[0] == "https://vietnamnet.vn/robots.txt"
        assert raw.call_count == 3
        assert client.delay == 6


@pytest.mark.parametrize("status", [301, 302, 403, 428, 429])
def test_article_block_or_redirect_stops_source(tmp_path, monkeypatch, status):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "EventRank-Test/1.0 (+mailto:test@example.com)")
    client = SourceClient("vietnamnet", Settings(data_dir=tmp_path), threading.Event())
    reply = response(status)
    reply.headers["Location"] = "/challenge"
    session = Mock()
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


def test_robots_disallow_and_missing_user_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "EventRank-Test/1.0 (+mailto:test@example.com)")
    client = SourceClient("vietnamnet", Settings(data_dir=tmp_path), threading.Event())
    with patch.object(
        client, "_get_raw", return_value=response(200, "User-agent: *\nDisallow: /")
    ) as raw:
        with pytest.raises(SourceBlocked, match="robots"):
            client.get(URL)
        assert raw.call_count == 1
    monkeypatch.delenv("CRAWLER_USER_AGENT")
    with pytest.raises(ValueError, match="CRAWLER_USER_AGENT"):
        SourceClient("vietnamnet", Settings(data_dir=tmp_path), threading.Event())


def test_api_jobs_and_saved_schedule(tmp_path):
    class QuietManager(JobManager):
        def _loop(self):
            self.stop.wait()

    settings = Settings(data_dir=tmp_path, scheduler_enabled=False)
    assert "vietnamnet" in CrawlRequest().sources
    client = Mock()
    client.get.return_value = Mock(text=ARTICLE)
    with (
        TestClient(create_app(settings, QuietManager)) as api,
        patch("automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế")])),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        job = api.post("/crawl/jobs", json={"sources": ["vietnamnet"]})
        assert job.status_code == 202
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = api.get("/crawl/jobs/" + job.json()["id"]).json()
            if result["status"] not in ("queued", "running"):
                break
            time.sleep(0.01)
        assert result["status"] == "completed", result
        assert result["results"]["vietnamnet"]["clean"] == 1
        assert api.patch("/crawl/schedule", json={"sources": ["qdnd"]}).status_code == 200
    with TestClient(create_app(settings, QuietManager)) as api:
        assert api.get("/crawl/schedule").json()["sources"] == ["qdnd"]
        assert (
            api.patch("/crawl/schedule", json={"sources": ["qdnd", "vietnamnet"]}).status_code
            == 200
        )


def test_offline_transform_never_overwrites_existing_output(tmp_path):
    source, target = tmp_path / "bronze.jsonl", tmp_path / "silver.jsonl"
    source.write_text(json.dumps(bronze()), encoding="utf-8")
    run_silver_transform(str(source), str(target))
    assert json.loads(target.read_text(encoding="utf-8"))["source"] == "vietnamnet"
    with pytest.raises(FileExistsError):
        run_silver_transform(str(source), str(target))
