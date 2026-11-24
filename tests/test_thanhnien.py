"""Offline Thanh Niên tests: synthetic HTML, no news website, database or R2."""

import json
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta
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
from crawler.harvester_thanhnien import extract_article_urls, normalize_article_url
from crawler.silver_transformer_thanhnien import run_silver_transform, transform_record
from process_data.clean_record import clean_record

FIXTURES = Path(__file__).parent / "fixtures" / "crawlers" / "thanhnien"
ARTICLE = (FIXTURES / "article.html").read_text(encoding="utf-8")
LISTING = (FIXTURES / "timeline.html").read_text(encoding="utf-8")
URL = "https://thanhnien.vn/ke-hoach-giao-thong-moi-185261109083000123.htm"
OLD = "https://thanhnien.vn/du-an-giao-thong-185261108080000111.htm"


def bronze(html=ARTICLE):
    return {"url": URL, "raw_html": html, "category": "Kinh Tế"}


def test_listing_titles_related_links_and_canonical_urls():
    assert extract_article_urls(BeautifulSoup(LISTING, "html.parser")) == [URL, OLD]
    assert (
        normalize_article_url("http://www.thanhnien.vn/tin-185123.htm?q=1#top")
        == "https://thanhnien.vn/tin-185123.htm"
    )
    for href in (
        "/video/tin-123.htm",
        "/longform/tin-123.htm",
        "/kinh-te.htm",
        "https://thanhnien.vn.evil.test/tin-123.htm",
        "https://user@thanhnien.vn/tin-123.htm",
        "javascript:alert(1)",
        "https://[broken/tin-123.htm",
    ):
        assert normalize_article_url(href) is None
    assert extract_article_urls(BeautifulSoup(f'<a href="{URL}">Tin</a>', "html.parser")) == [URL]


def test_nine_field_silver_preserves_text_and_source_specific_metadata():
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
    assert record["source"] == "thanhnien"
    assert record["published_at"] == "2026-11-09T08:30:00+07:00"
    assert record["title"].startswith("Công bố")
    assert record["author"] == "Tác giả A, Tác giả B"
    assert "Việt Nam" in record["content_text"]
    assert "Đã duyệt." in record["content_text"]
    assert "không có thuộc tính SEO" in record["content_text"]
    assert "không lấy" not in record["content_text"]
    assert "Xem thêm" not in record["content_text"]


@pytest.mark.parametrize(
    "html,expected",
    [
        (
            '<meta itemprop="datePublished" content="2026-11-09T01:30:00Z">',
            "2026-11-09T08:30:00+07:00",
        ),
        (
            '<time data-role="publishdate" datetime="2026-11-09T08:30:00"></time>',
            "2026-11-09T08:30:00+07:00",
        ),
        ('<div class="detail-time">09/11/2026 08:30 GMT+7</div>', "2026-11-09T08:30:00+07:00"),
        (
            '<time data-role="publishdate" datetime="bad"></time><div class="detail-date">09/11/2026 - 08:30</div>',
            "2026-11-09T08:30:00+07:00",
        ),
    ],
)
def test_date_and_meta_fallbacks(html, expected):
    record = transform_record(
        bronze('<meta property="og:title" content="Tiêu đề dự phòng">' + html)
    )
    assert record["published_at"] == expected
    assert record["title"] == "Tiêu đề dự phòng"
    assert record["author"] is None


def test_meta_author_body_fallback_and_null_author_cleaning():
    html = (
        '<h1 class="title-detail">Tiêu đề dự phòng</h1>'
        '<meta property="article:published_time" content="2026-11-09T08:30:00">'
        '<meta name="author" content="Tác giả meta">'
        '<div itemprop="articleBody"><p>' + "Nội dung kiểm thử bài báo. " * 20 + "</p></div>"
    )
    record = transform_record(bronze(html))
    assert record["author"] == "Tác giả meta"
    record = transform_record(
        bronze(html.replace('<meta name="author" content="Tác giả meta">', ""))
    )
    assert clean_record(record)[0]["author"] is None


@pytest.mark.parametrize(
    "html",
    [
        '<h1 class="detail-title">Không có ngày đăng</h1>',
        '<h1 class="detail-title">Ngày sai</h1><div class="detail-date">31/02/2026 08:30</div>',
        '<time data-role="publishdate" datetime="2026-11-09T08:30:00"></time>',
    ],
)
def test_bad_required_metadata_is_rejected(html):
    assert transform_record(bronze(html)) is None


def test_incremental_timeline_bootstrap_and_page_cap(tmp_path):
    client = Mock()
    client.get.return_value = Mock(text=LISTING)
    # `since` matches the fixture IDs (09/11/2026); with the real clock they would be skipped as old (AUDIT-6).
    settings, now = Settings(data_dir=tmp_path), datetime(2026, 11, 9, 9, 0, tzinfo=VN_TZ)
    with patch("automation.discovery.tn.TARGET_CATEGORIES", {"Kinh Tế": "18549"}):
        assert (URL, "Kinh Tế") in list(discover("thanhnien", client, set(), now, settings))
        assert client.get.call_count == 3
        assert client.get.call_args.args[0] == "https://thanhnien.vn/timelinelist/18549/3.htm"
        client.reset_mock()
        list(discover("thanhnien", client, {URL, OLD}, now, settings))
        assert client.get.call_count == 2
        with pytest.raises(DiscoveryIncomplete, match="Reached 2 pages"):
            list(
                discover(
                    "thanhnien",
                    client,
                    {OLD},
                    now,
                    replace(settings, max_listing_pages=2, bootstrap_listing_pages=2),
                )
            )


def test_discovery_failure_preserves_watermark_and_processes_found_urls(tmp_path):
    client = Mock()
    client.get.side_effect = [
        Mock(text=LISTING),
        Mock(text="<html>Unrecognized response</html>"),
        Mock(text=ARTICLE),
        Mock(text=ARTICLE),
    ]
    pipeline = Pipeline(Settings(data_dir=tmp_path), threading.Event())
    with (
        patch("automation.discovery.tn.TARGET_CATEGORIES", {"Kinh Tế": "18549"}),
        patch("automation.pipeline.SourceClient", return_value=client),
        # This test is about the watermark; fixture IDs (09/11/2026) must not be cut off by the real clock (AUDIT-6).
        patch("automation.discovery.TIMELINE_ID_SLACK", timedelta(days=36500)),
    ):
        result = pipeline.run_source("thanhnien", "partial", lambda _: None)
    assert result["status"] == "partial", result
    assert result["clean"] == 2
    assert SourceState(tmp_path, "thanhnien").value["last_discovery"] is None


def test_pipeline_exports_resume_and_deduplicate(tmp_path):
    client = Mock()
    client.get.return_value = Mock(text=ARTICLE)
    pipeline = Pipeline(Settings(data_dir=tmp_path), threading.Event())
    with (
        patch(
            "automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế"), (URL, "Kinh Tế")])
        ),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        result = pipeline.run_source("thanhnien", "first", lambda _: None)
    assert result["clean"] == 1
    assert result["discovery_mode"] == "bootstrap_recent_pages"
    key = compute_article_id(URL)
    raw = read_json(pipeline.article_path("bronze", "thanhnien", key))
    assert "article:published_time" in raw["raw_html"]
    assert (
        json.loads((tmp_path / "jobs/first/silver/thanhnien.jsonl").read_text(encoding="utf-8"))[
            "source"
        ]
        == "thanhnien"
    )
    with (
        patch("automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế")])),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        assert pipeline.run_source("thanhnien", "again", lambda _: None)["clean"] == 0
    assert client.get.call_count == 1
    replay = Pipeline(Settings(data_dir=tmp_path / "resume"), threading.Event())
    write_json(replay.article_path("bronze", "thanhnien", key), raw)
    offline = Mock()
    offline.get.side_effect = AssertionError("Must replay without download")
    assert replay.process_article("thanhnien", key, {"url": URL}, offline) == ("clean", None)


def response(code, text=""):
    reply = requests.Response()
    reply.status_code, reply._content, reply.encoding = code, text.encode(), "utf-8"
    return reply


def test_robots_checked_before_request_and_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "EventRank-Test/1.0 (+mailto:test@example.com)")
    client = SourceClient("thanhnien", Settings(data_dir=tmp_path), threading.Event())
    assert client.delay >= 2
    with patch.object(
        client,
        "_get_raw",
        side_effect=[
            response(200, "User-agent: *\nCrawl-delay: 5\nDisallow: /video/"),
            response(200),
            response(200),
        ],
    ) as raw:
        client.get(URL)
        client.get(URL)
        assert raw.call_args_list[0].args[0] == "https://thanhnien.vn/robots.txt"
        assert raw.call_count == 3
        assert client.delay == 5


@pytest.mark.parametrize("status", [301, 302, 403, 428, 429])
def test_source_stops_on_block_and_redirect(tmp_path, monkeypatch, status):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "EventRank-Test/1.0 (+mailto:test@example.com)")
    client = SourceClient("thanhnien", Settings(data_dir=tmp_path), threading.Event())
    reply = response(status)
    reply.headers["Location"] = "/challenge"
    session = Mock()
    session.get.return_value = reply
    with patch.object(client, "_session", return_value=session):
        with pytest.raises(SourceBlocked):
            client.get(URL)
        with pytest.raises(SourceBlocked):
            client.get(URL)
    assert session.get.call_count == 1


def test_disallowed_robots_and_missing_user_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "EventRank-Test/1.0 (+mailto:test@example.com)")
    client = SourceClient("thanhnien", Settings(data_dir=tmp_path), threading.Event())
    with patch.object(
        client, "_get_raw", return_value=response(200, "User-agent: *\nDisallow: /")
    ) as raw:
        with pytest.raises(SourceBlocked, match="robots"):
            client.get(URL)
        assert raw.call_count == 1
    monkeypatch.delenv("CRAWLER_USER_AGENT")
    with pytest.raises(ValueError, match="CRAWLER_USER_AGENT"):
        SourceClient("thanhnien", Settings(data_dir=tmp_path), threading.Event())


def test_api_jobs_and_existing_schedule(tmp_path):
    class QuietManager(JobManager):
        def _loop(self):
            self.stop.wait()

    settings = Settings(data_dir=tmp_path, scheduler_enabled=False)
    assert "thanhnien" in CrawlRequest().sources
    client = Mock()
    client.get.return_value = Mock(text=ARTICLE)
    with (
        TestClient(create_app(settings, QuietManager)) as api,
        patch("automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế")])),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        job = api.post("/crawl/jobs", json={"sources": ["thanhnien"]})
        assert job.status_code == 202
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = api.get("/crawl/jobs/" + job.json()["id"]).json()
            if result["status"] not in ("queued", "running"):
                break
            time.sleep(0.01)
        assert result["status"] == "completed", result
        assert result["results"]["thanhnien"]["clean"] == 1
        assert api.patch("/crawl/schedule", json={"sources": ["qdnd"]}).status_code == 200
    with TestClient(create_app(settings, QuietManager)) as api:
        assert api.get("/crawl/schedule").json()["sources"] == ["qdnd"]
        assert (
            api.patch("/crawl/schedule", json={"sources": ["qdnd", "thanhnien"]}).status_code == 200
        )


def test_offline_conversion_does_not_replace_output(tmp_path):
    source, target = tmp_path / "bronze.jsonl", tmp_path / "silver.jsonl"
    source.write_text(json.dumps(bronze()), encoding="utf-8")
    run_silver_transform(str(source), str(target))
    assert json.loads(target.read_text(encoding="utf-8"))["source"] == "thanhnien"
    with pytest.raises(FileExistsError):
        run_silver_transform(str(source), str(target))
