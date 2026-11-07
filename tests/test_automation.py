"""Offline tests: never request a real news website."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from api.main import create_app
from automation.config import Settings
from automation.discovery import discover, DiscoveryIncomplete
from automation.http import SourceClient, SourceBlocked
from automation.job_manager import JobManager, JobConflict
from automation.pipeline import Pipeline
from automation.scheduler import slot_at, next_slot, VN_TZ
from automation.state import SourceState
from automation.storage import read_json, write_json, ProcessLock
from crawler.common_utils import compute_article_id

ARTICLE = '''<div class="article-detail"><h1 class="post-title">Tiêu đề bài báo kiểm thử</h1>
<div class="post-summary">Nội dung giới thiệu.</div>
<span class="post-subinfo">Thứ sáu, 06/11/2026 - 08:00</span>
<div itemprop="articleBody"><p>''' + "Nội dung bài báo phục vụ kiểm thử. " * 20 + '''</p></div></div>'''
URL = "https://www.qdnd.vn/kinh-te/bai-viet-123"


class QuietManager(JobManager):
    """Manual clock ticks to keep tests deterministic."""
    def _loop(self):
        self.stop.wait()


class FixtureClient:
    calls = 0

    def __init__(self, *args):
        pass

    def check(self):
        pass

    def get(self, url):
        type(self).calls += 1
        return Mock(text=ARTICLE)

    def close(self):
        pass


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(data_dir=self.root, scheduler_enabled=False)

    def wait_job(self, manager, job_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = manager.get(job_id)
            if job["status"] not in ("running", "queued"):
                return job
            time.sleep(0.01)
        self.fail("Job did not finish")

    def test_half_hour_slots(self):
        now = datetime(2026, 11, 6, 8, 45, tzinfo=VN_TZ)
        self.assertEqual(slot_at(now).isoformat(), "2026-11-06T08:30:00+07:00")
        self.assertEqual(next_slot(now).hour, 9)
        self.assertEqual(next_slot(now).minute, 0)
        self.assertEqual(slot_at(now.replace(minute=30)).minute, 30)

    def test_process_lock_blocks_second_instance_and_releases(self):
        first = ProcessLock(self.root / "instance.lock")
        second = ProcessLock(self.root / "instance.lock")
        first.acquire()
        try:
            with self.assertRaises(RuntimeError):
                second.acquire()
        finally:
            first.release()
        second.acquire()
        second.release()

    def test_api_pipeline_dedup_and_clean_export(self):
        FixtureClient.calls = 0
        with patch("automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế")])), \
             patch("automation.pipeline.SourceClient", FixtureClient):
            with TestClient(create_app(self.settings, QuietManager)) as client:
                response = client.post("/crawl/jobs", json={"sources": ["qdnd"]})
                self.assertEqual(response.status_code, 202)
                job_id = response.json()["id"]
                job = self.wait_job(client.app.state.manager, job_id)
                self.assertEqual(job["status"], "completed", job)
                self.assertEqual(job["results"]["qdnd"]["clean"], 1)
                export = self.root / "jobs" / job_id / "clean_silver" / "qdnd.jsonl"
                import json
                record = json.loads(export.read_text(encoding="utf-8"))
                self.assertEqual(record["article_id"], compute_article_id(URL))
                self.assertTrue(record["published_at"].endswith("+07:00"))
                self.assertEqual(client.get(f"/crawl/jobs/{job_id}").status_code, 200)
                self.assertEqual(client.get("/crawl/jobs").json()["total"], 1)
                self.assertEqual(client.get("/crawl/jobs/invalid").status_code, 404)
                self.assertEqual(client.post("/crawl/jobs", json={"sources": []}).status_code, 422)
                self.assertEqual(client.post("/crawl/jobs", json={"sources": ["unknown"]}).status_code, 422)
                self.assertEqual(client.patch("/crawl/schedule", json={"enabled": None}).status_code, 422)
                self.assertEqual(client.patch("/crawl/schedule", json={"interval_minutes": 17}).status_code, 422)
                self.assertEqual(client.get("/crawl/schedule").json()["interval_minutes"], 30)
                self.assertEqual(client.get("/health").status_code, 200)
                with patch("automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế")])):
                    again = client.post("/crawl/jobs", json={"sources": ["qdnd"]}).json()
                    self.assertEqual(self.wait_job(client.app.state.manager, again["id"])["status"], "completed")
        self.assertEqual(FixtureClient.calls, 1)

    def test_resume_bronze_without_network_and_reject_short_content(self):
        key = compute_article_id(URL)
        state = SourceState(self.root, "qdnd")
        state.add(URL, "Kinh Tế")
        raw = ARTICLE.replace("Nội dung bài báo phục vụ kiểm thử. " * 20, "ngắn")
        write_json(self.root / "bronze" / "qdnd" / f"{key}.json",
                   {"url": URL, "raw_html": raw, "category": "Kinh Tế", "crawled_at": "test"})
        FixtureClient.calls = 0
        with patch("automation.pipeline.discover", return_value=iter([])), \
             patch("automation.pipeline.SourceClient", FixtureClient):
            result = Pipeline(self.settings, threading.Event()).run_source("qdnd", "resume", lambda x: None)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(FixtureClient.calls, 0)
        saved = SourceState(self.root, "qdnd").articles[key]
        self.assertEqual(saved["last_error"], "content_too_short")

    def test_clean_file_written_before_crash_is_reconciled(self):
        state = SourceState(self.root, "qdnd")
        key = state.add(URL, "Kinh Tế")
        write_json(self.root / "clean_silver" / "qdnd" / f"{key}.json", {"article_id": key})
        with patch("automation.pipeline.discover", return_value=iter([])), \
             patch("automation.pipeline.SourceClient", FixtureClient):
            result = Pipeline(self.settings, threading.Event()).run_source("qdnd", "replay", lambda x: None)
        self.assertEqual(result["clean"], 1)
        self.assertEqual(SourceState(self.root, "qdnd").articles[key]["status"], "clean")

    def test_failed_url_retried_next_job_even_after_discovery_advances(self):
        class BrokenClient(FixtureClient):
            def get(self, url):
                raise requests.Timeout("offline")
        with patch("automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế")])), \
             patch("automation.pipeline.SourceClient", BrokenClient):
            result = Pipeline(self.settings, threading.Event()).run_source("qdnd", "fail", lambda x: None)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["failed"], 1)
        with patch("automation.pipeline.discover", return_value=iter([])), \
             patch("automation.pipeline.SourceClient", FixtureClient):
            result = Pipeline(self.settings, threading.Event()).run_source("qdnd", "retry", lambda x: None)
        self.assertEqual(result["clean"], 1)

    def test_discovery_failure_does_not_advance_watermark(self):
        def broken(*args):
            yield URL, "Kinh Tế"
            raise DiscoveryIncomplete("page cap")
        with patch("automation.pipeline.discover", broken), patch("automation.pipeline.SourceClient", FixtureClient):
            result = Pipeline(self.settings, threading.Event()).run_source("qdnd", "partial", lambda x: None)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["clean"], 1)
        self.assertIsNone(SourceState(self.root, "qdnd").value["last_discovery"])

    def test_conflict_skip_slot_catchup_and_restart_recovery(self):
        entered, release = threading.Event(), threading.Event()

        class HoldingPipeline:
            def __init__(self, *args):
                pass

            def run(self, job, report, retry_failed):
                entered.set()
                release.wait(5)
                return {source: {"status": "completed"} for source in job["sources"]}

        manager = QuietManager(self.settings, HoldingPipeline)
        manager.start()
        try:
            manager.schedule["enabled"] = True
            manager.tick(datetime(2026, 11, 6, 8, 12, tzinfo=VN_TZ))
            self.assertTrue(entered.wait(2))
            job_id = manager.active_id
            self.assertEqual(manager.get(job_id)["trigger"], "catch_up")
            with self.assertRaises(JobConflict):
                manager.submit()
            manager.tick(datetime(2026, 11, 6, 8, 30, tzinfo=VN_TZ))
            self.assertEqual(manager.schedule["last_event"]["action"], "skipped")
            release.set()
            self.wait_job(manager, job_id)
            # Waking after several missed slots creates ONE job.
            manager.tick(datetime(2026, 11, 6, 12, 45, tzinfo=VN_TZ))
            next_id = manager.schedule["last_event"]["job_id"]
            self.wait_job(manager, next_id)
            manager.tick(datetime(2026, 11, 6, 12, 46, tzinfo=VN_TZ))
            self.assertEqual(manager.list_jobs()["total"], 2)
        finally:
            release.set()
            manager.close()
        record = manager.get(next_id)
        record["status"] = "running"  # Simulate a process dying mid-job.
        write_json(manager.job_path(next_id), record)
        resumed = QuietManager(self.settings, HoldingPipeline)
        resumed.start()
        try:
            self.assertEqual(resumed.get(next_id)["status"], "interrupted")
            self.assertIsNone(resumed.schedule["last_slot"])
        finally:
            resumed.close()

    def test_http_block_stops_source_without_retry(self):
        settings = Settings(data_dir=self.root, delays={s: 0 for s in ("qdnd", "dantri", "nhandan", "baochinhphu")})
        client = SourceClient("qdnd", settings, threading.Event())
        session = Mock()
        session.get.return_value = Mock(status_code=429)
        with patch.object(client, "_session", return_value=session):
            with self.assertRaises(SourceBlocked):
                client.get(URL)
            with self.assertRaises(SourceBlocked):
                client.get(URL)
        self.assertEqual(session.get.call_count, 1)

    def test_source_parallelism_and_failure_isolation(self):
        barrier = threading.Barrier(2)

        class ParallelPipeline(Pipeline):
            def run_source(self, source, *args):
                barrier.wait(timeout=2)
                if source == "qdnd":
                    raise ValueError("fixture failure")
                return {"status": "completed"}

        result = ParallelPipeline(self.settings, threading.Event()).run(
            {"id": "parallel", "sources": ["qdnd", "dantri"]}, lambda *args: None)
        self.assertEqual(result["qdnd"]["status"], "failed")
        self.assertEqual(result["dantri"]["status"], "completed")

    def test_listing_does_not_stop_on_single_known_pinned_article(self):
        base = "https://baochinhphu.vn"
        old, new = base + "/old.htm", base + "/new.htm"
        html = '<div class="list__listing"><a class="box-stream-link-title" href="/old.htm">x</a></div>'
        fragment = '<div class="box-stream-item"><a class="box-stream-link-title" href="/new.htm">x</a></div>'
        known_fragment = fragment.replace("/new.htm", "/old.htm")
        client = Mock()
        client.get.side_effect = [Mock(text=html), Mock(text=fragment), Mock(text=known_fragment), Mock(text=known_fragment)]
        with patch("automation.discovery.CP_CATEGORIES", [{"category_url": base, "zone_id": 1, "category_label": "test"}]):
            found = list(discover("baochinhphu", client, {old}, datetime.now(VN_TZ), self.settings))
        self.assertIn((new, "test"), found)
        self.assertEqual(client.get.call_count, 4)

    def test_http_source_rate_limit_is_shared_between_threads(self):
        settings = Settings(data_dir=self.root, delays={"qdnd": .04, "dantri": 0, "nhandan": 0, "baochinhphu": 0})
        client = SourceClient("qdnd", settings, threading.Event())
        starts = []
        session = Mock()

        def get(*args, **kwargs):
            starts.append(time.monotonic())
            response = requests.Response()
            response.status_code = 200
            return response

        session.get.side_effect = get
        with patch.object(client, "_session", return_value=session):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(client.get, [URL] * 3))
        self.assertEqual(len(starts), 3)
        self.assertTrue(all(b - a >= .035 for a, b in zip(starts, starts[1:])), starts)

    def test_sitemap_overlap_crosses_month_and_filters_old_articles(self):
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        index = f'''<sitemapindex xmlns="{ns}">
        <sitemap><loc>https://dantri.com.vn/Article-2026-11-01.xml</loc></sitemap>
        <sitemap><loc>https://dantri.com.vn/Article-2026-10-01.xml</loc></sitemap>
        <sitemap><loc>https://dantri.com.vn/Article-2026-09-01.xml</loc></sitemap></sitemapindex>'''
        new = "https://dantri.com.vn/kinh-doanh/tin-20261101080000.htm"
        old = "https://dantri.com.vn/kinh-doanh/tin-20261001080000.htm"
        politics = "https://dantri.com.vn/thoi-su/tin-20261031235900.htm"
        def sitemap(urls):
            return f'<urlset xmlns="{ns}">' + ''.join(f'<url><loc>{u}</loc></url>' for u in urls) + '</urlset>'
        client = Mock()
        client.get.side_effect = [Mock(content=index.encode()), Mock(content=sitemap([new]).encode()),
                                  Mock(content=sitemap([old, politics]).encode())]
        since = datetime(2026, 10, 31, 12, tzinfo=VN_TZ)
        result = list(discover("dantri", client, set(), since, self.settings))
        self.assertEqual(result, [(new, "Kinh Tế"), (politics, "Chính Trị")])
        self.assertEqual(client.get.call_count, 3)

    def test_dantri_politics_classification_keeps_bronze_and_rejects_other_news(self):
        url = "https://dantri.com.vn/thoi-su/tin-20261106080000.htm"
        key = compute_article_id(url)
        html = '<script>ggCatList = "thoi-su/xa-hoi";</script><div class="dt-flex dt-flex-col dt-space-y-6">text</div>'
        client = Mock()
        client.get.return_value = Mock(text=html)
        pipeline = Pipeline(self.settings, threading.Event())
        status, reason = pipeline.process_article("dantri", key, {"url": url, "category": "Chính Trị"}, client)
        self.assertEqual((status, reason), ("rejected", "not_target_category"))
        self.assertTrue(pipeline.article_path("bronze", "dantri", key).exists())
        self.assertEqual(client.get.call_count, 1)

    def test_api_conflict_and_schedule_persistence(self):
        release = threading.Event()
        class HoldingPipeline:
            def __init__(self, *args):
                pass
            def run(self, job, report, retry_failed):
                release.wait(5)
                return {source: {"status": "completed"} for source in job["sources"]}
        factory = lambda settings: QuietManager(settings, HoldingPipeline)
        try:
            with TestClient(create_app(self.settings, factory)) as client:
                response = client.patch("/crawl/schedule", json={"sources": ["qdnd"], "interval_minutes": 15})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(client.post("/crawl/jobs", json={"sources": ["qdnd"]}).status_code, 202)
                self.assertEqual(client.post("/crawl/jobs", json={"sources": ["qdnd"]}).status_code, 409)
                release.set()
        finally:
            release.set()
        with TestClient(create_app(self.settings, QuietManager)) as client:
            schedule = client.get("/crawl/schedule").json()
            self.assertEqual(schedule["sources"], ["qdnd"])
            self.assertEqual(schedule["interval_minutes"], 15)

    def test_article_workers_run_concurrently(self):
        barrier = threading.Barrier(2)
        class WorkerPipeline(Pipeline):
            def process_article(self, source, key, entry, client):
                barrier.wait(timeout=2)
                return "rejected", "fixture"
        with patch("automation.pipeline.discover", return_value=iter([(URL, "Kinh Tế"), (URL + "2", "Kinh Tế")])), \
             patch("automation.pipeline.SourceClient", FixtureClient):
            result = WorkerPipeline(self.settings, threading.Event()).run_source("qdnd", "threads", lambda x: None)
        self.assertEqual(result["rejected"], 2)

    def test_bootstrap_does_not_backfill_all_listing_history(self):
        html = '<div class="list__listing"><a class="box-stream-link-title" href="/old.htm">x</a></div>'
        fragment = '<div class="box-stream-item"><a class="box-stream-link-title" href="/new.htm">x</a></div>'
        client = Mock()
        client.get.side_effect = [Mock(text=html), Mock(text=fragment), Mock(text=fragment)]
        with patch("automation.discovery.CP_CATEGORIES", [{"category_url": "https://baochinhphu.vn", "zone_id": 1, "category_label": "test"}]):
            list(discover("baochinhphu", client, set(), datetime.now(VN_TZ), self.settings))
        self.assertEqual(client.get.call_count, self.settings.bootstrap_listing_pages)

    def test_all_four_source_parsers_produce_clean_records(self):
        body = "Nội dung kiểm thử bài báo. " * 20
        fixtures = {
            "qdnd": ARTICLE,
            "baochinhphu": f'''<article class="detail-mcontent">
            <h1 class="detail-title">Tiêu đề bài báo kiểm thử</h1>
            <h2 class="detail-sapo">(Chinhphu.vn) - Giới thiệu.</h2>
            <div data-role="publishdate">06/11/2026<span></span>08:00</div>
            <div class="detail-content afcbc-body clearfix"><p>{body}</p></div></article>''',
            "nhandan": f'''<div class="article"><h1 class="article__title cms-title">Tiêu đề bài báo kiểm thử</h1>
            <div class="article__sapo cms-desc">Giới thiệu.</div>
            <meta class="cms-date" itemprop="datePublished" content="2026-11-06T08:00:00+07:00">
            <div class="article__body zce-content-body cms-body"><p>{body}</p></div></div>''',
            "dantri": f'''<article class="e-magazine bg-wrap d-magazine">
            <h1 class="e-magazine__title">Tiêu đề bài báo kiểm thử</h1>
            <h2 class="e-magazine__sapo">(Dân trí) - Giới thiệu.</h2>
            <time class="dt-flex dt-items-center dt-font-Inter dt-text-13px dt-leading-5 dt-text-common-sapo" datetime="2026-11-06 08:00"></time>
            <div class="e-magazine__body dnews__body"><p>{body}</p></div></article>''',
        }
        pipeline = Pipeline(self.settings, threading.Event())
        for source, html in fixtures.items():
            with self.subTest(source=source):
                from automation.http import HOSTS
                host = sorted(HOSTS[source])[0]
                url = f"https://{host}/kinh-te/tin"
                key = compute_article_id(url)
                client = Mock()
                client.get.return_value = Mock(text=html)
                self.assertEqual(pipeline.process_article(source, key, {"url": url, "category": "Kinh Tế"}, client), ("clean", None))
                self.assertEqual(read_json(pipeline.article_path("clean_silver", source, key))["article_id"], key)


if __name__ == "__main__":
    unittest.main()
