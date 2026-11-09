"""Offline integration checks for the adapted Tuoi Tre crawler; no website calls."""

import json
import threading
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
from automation.config import SOURCES, Settings
from automation.discovery import DiscoveryIncomplete, discover
from automation.http import SourceBlocked, SourceClient
from automation.job_manager import JobManager
from automation.pipeline import Pipeline
from automation.scheduler import VN_TZ
from automation.storage import read_json
from crawler.common_utils import compute_article_id
from crawler.harvester_tuoitre import extract_article_urls, normalize_article_url
from crawler.silver_transformer_tuoitre import run_silver_transform, transform_record

FIXTURES = Path(__file__).parent / "fixtures" / "crawlers" / "tuoitre"
URL = "https://tuoitre.vn/kinh-te-phat-trien-20261109083000123.htm"
OLD = "https://tuoitre.vn/bai-cu-20261108080000111.htm"
ARTICLE = (FIXTURES / "article.html").read_text(encoding="utf-8")
LISTING = (FIXTURES / "timeline.html").read_text(encoding="utf-8")


def bronze(html=ARTICLE):
    return {"url": URL, "raw_html": html, "category": "Kinh Tế"}


def test_links_are_canonical_scoped_and_exclude_media():
    assert extract_article_urls(BeautifulSoup(LISTING, "html.parser")) == [URL, OLD]
    assert (
        normalize_article_url("http://www.tuoitre.vn/tin-123.htm?q=a#b")
        == "https://tuoitre.vn/tin-123.htm"
    )
    for href in (
        "javascript:alert(1)",
        "/video/tin-123.htm",
        "/thoi-su.htm",
        "https://tuoitre.vn.evil.test/tin-123.htm",
        "https://user@tuoitre.vn/tin-123.htm",
    ):
        assert normalize_article_url(href) is None


def test_fallback_links():
    soup = BeautifulSoup(f'<a href="{URL}">Tin</a><a href="{URL}">Trùng</a>', "html.parser")
    assert extract_article_urls(soup) == [URL]


def test_silver_contract_preserves_metadata_and_short_facts():
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
    assert record["source"] == "tuoitre"
    assert record["published_at"] == "2026-11-09T08:30:00+07:00"
    assert record["author"] == "Tác giả A, Tác giả B"
    assert "Đã thông qua." in record["content_text"]
    assert "Không đưa vào" not in record["content_text"]
    assert "Bài liên quan" not in record["content_text"]
    assert "Google" not in record["content_text"]


@pytest.mark.parametrize(
    "date_html,expected",
    [
        (
            '<meta property="article:published_time" content="2026-11-09T02:00:00+00:00">',
            "2026-11-09T09:00:00+07:00",
        ),
        (
            '<time data-role="publishdate">09/11/2026 08:15 GMT+7</time>',
            "2026-11-09T08:15:00+07:00",
        ),
        (
            '<time itemprop="datePublished" datetime="2026-11-09T08:15:00"></time>',
            "2026-11-09T08:15:00+07:00",
        ),
    ],
)
def test_date_fallback_and_missing_author(date_html, expected):
    html = '<h1 class="detail-title">Tiêu đề bài báo</h1>' + date_html
    record = transform_record(bronze(html))
    assert record["published_at"] == expected
    assert record["author"] is None


@pytest.mark.parametrize(
    "html",
    [
        '<h1 class="detail-title">Thiếu ngày đăng</h1>',
        '<time data-role="publishdate">31/02/2026 08:00</time><h1 class="detail-title">Sai ngày</h1>',
        '<script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-11-09"}</script>',
    ],
)
def test_missing_required_metadata_is_rejected(html):
    assert transform_record(bronze(html)) is None


def test_timeline_bootstrap_incremental_and_page_cap(tmp_path):
    settings = Settings(data_dir=tmp_path)
    client = Mock()
    client.get.return_value = Mock(text=LISTING)
    now = datetime.now(VN_TZ)
    with patch("automation.discovery.tt.TARGET_CATEGORIES", {"Kinh Tế": "11"}):
        found = list(discover("tuoitre", client, set(), now, settings))
        assert (URL, "Kinh Tế") in found
        assert client.get.call_count == 3
        client.reset_mock()
        list(discover("tuoitre", client, {URL, OLD}, now, settings))
        assert client.get.call_count == 2
        client.reset_mock()
        with pytest.raises(DiscoveryIncomplete, match="Reached 2 pages"):
            list(
                discover(
                    "tuoitre",
                    client,
                    {OLD},
                    now,
                    replace(settings, max_listing_pages=2, bootstrap_listing_pages=2),
                )
            )


def test_unrecognized_listing_is_not_silent_success(tmp_path):
    client = Mock()
    client.get.return_value = Mock(text="<html>Challenge</html>")
    with (
        patch("automation.discovery.tt.TARGET_CATEGORIES", {"Kinh Tế": "11"}),
        pytest.raises(DiscoveryIncomplete),
    ):
        list(discover("tuoitre", client, set(), datetime.now(VN_TZ), Settings(data_dir=tmp_path)))


def test_pipeline_export_replay_dedup_and_bronze_metadata(tmp_path):
    client = Mock()
    client.get.return_value = Mock(text=ARTICLE)
    pipeline = Pipeline(Settings(data_dir=tmp_path, scheduler_enabled=False), threading.Event())
    with (
        patch(
            "automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế"), (URL, "Kinh Tế")])
        ),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        result = pipeline.run_source("tuoitre", "first", lambda _: None)
    assert result["status"] == "completed", result
    assert result["clean"] == 1
    key = compute_article_id(URL)
    raw = read_json(pipeline.article_path("bronze", "tuoitre", key))
    assert "application/ld+json" in raw["raw_html"]
    exported = json.loads(
        (tmp_path / "jobs/first/silver/tuoitre.jsonl").read_text(encoding="utf-8")
    )
    assert exported["article_id"] == key
    assert exported["published_at"].endswith("+07:00")
    with (
        patch("automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế")])),
        patch("automation.pipeline.SourceClient", return_value=client),
    ):
        result = pipeline.run_source("tuoitre", "second", lambda _: None)
    assert result["clean"] == 0
    assert client.get.call_count == 1
    # A different state directory can replay old full-HTML Bronze without network.
    replay = Pipeline(Settings(data_dir=tmp_path / "replay"), threading.Event())
    from automation.storage import write_json

    write_json(replay.article_path("bronze", "tuoitre", key), raw)
    offline = Mock()
    offline.get.side_effect = AssertionError("Replay must not download")
    assert replay.process_article("tuoitre", key, {"url": URL}, offline) == ("clean", None)


def response(status, text=""):
    result = requests.Response()
    result.status_code = status
    result._content = text.encode()
    result.encoding = "utf-8"
    return result


def test_robots_disallow_and_honest_user_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "EventRank-Test/1.0 (+mailto:test@example.com)")
    client = SourceClient("tuoitre", Settings(data_dir=tmp_path), threading.Event())
    assert client.delay >= 2
    with patch.object(
        client, "_get_raw", return_value=response(200, "User-agent: *\nDisallow: /")
    ) as raw:
        with pytest.raises(SourceBlocked, match="robots.txt"):
            client.get(URL)
        assert raw.call_count == 1
        assert raw.call_args.args[0] == "https://tuoitre.vn/robots.txt"
    monkeypatch.delenv("CRAWLER_USER_AGENT")
    with pytest.raises(ValueError, match="CRAWLER_USER_AGENT"):
        SourceClient("tuoitre", Settings(data_dir=tmp_path), threading.Event())


def test_robots_cached_and_crawl_delay_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "EventRank-Test/1.0 (+mailto:test@example.com)")
    client = SourceClient("tuoitre", Settings(data_dir=tmp_path), threading.Event())
    with patch.object(
        client,
        "_get_raw",
        side_effect=[
            response(200, "User-agent: *\nCrawl-delay: 7\nDisallow: /video/"),
            response(200, ARTICLE),
            response(200, ARTICLE),
        ],
    ) as raw:
        client.get(URL)
        client.get(URL)
        assert raw.call_count == 3
        assert client.delay == 7


@pytest.mark.parametrize("status", [302, 403, 429])
def test_block_or_redirect_stops_source(tmp_path, monkeypatch, status):
    monkeypatch.setenv("CRAWLER_USER_AGENT", "EventRank-Test/1.0 (+mailto:test@example.com)")
    client = SourceClient("tuoitre", Settings(data_dir=tmp_path), threading.Event())
    session = Mock()
    reply = response(status)
    reply.headers["Location"] = "/challenge"
    session.get.return_value = reply
    with patch.object(client, "_session", return_value=session):
        with pytest.raises(SourceBlocked):
            client.get(URL)
        with pytest.raises(SourceBlocked):
            client.get(URL)
    assert session.get.call_count == 1


def test_api_accepts_new_source_and_preserves_existing_schedule(tmp_path):
    class QuietManager(JobManager):
        def _loop(self):
            self.stop.wait()

    settings = Settings(data_dir=tmp_path, scheduler_enabled=False)
    assert "tuoitre" in CrawlRequest().sources
    assert set(CrawlRequest().sources) == set(SOURCES)
    with TestClient(create_app(settings, QuietManager)) as api:
        assert "tuoitre" in api.get("/crawl/schedule").json()["sources"]
        assert api.patch("/crawl/schedule", json={"sources": ["tuoitre"]}).status_code == 200
    with TestClient(create_app(settings, QuietManager)) as api:
        assert api.get("/crawl/schedule").json()["sources"] == ["tuoitre"]


def test_offline_transform_never_overwrites_output(tmp_path):
    source, target = tmp_path / "bronze.jsonl", tmp_path / "silver.jsonl"
    source.write_text(json.dumps(bronze()), encoding="utf-8")
    run_silver_transform(str(source), str(target))
    assert json.loads(target.read_text(encoding="utf-8"))["source"] == "tuoitre"
    with pytest.raises(FileExistsError):
        run_silver_transform(str(source), str(target))
