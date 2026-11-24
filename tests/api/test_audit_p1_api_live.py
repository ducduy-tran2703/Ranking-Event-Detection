"""Kiểm tra (đợt audit P1-api): `GET /api/live/overview` (eventrank.serving.live_stats) với dữ liệu lạ, lộ thông tin
cho khách, và dữ liệu lạ từ dịch vụ crawler qua cả /api/live/overview lẫn /api/admin/system/settings.

Postgres tạm (fixture pg_url/pg_conn); crawler giả (không gọi mạng).
"""
import hashlib
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from test_system_settings_api import JOB, SCHED, _login, setup  # noqa: F401 -- setup là fixture

from apps.api import system_settings as SS
from apps.api.main import create_app
from eventrank.serving import live_stats

SECRET_PATH = "/home/hieu/personal/semeter7/pbl/Ranking-Event-Detection/data/runs/x.npy"
SECRET_HOST = 'connection to server at "10.9.8.7", port 5432 failed: FATAL: password authentication failed for user "ev"'


def _article(conn, source, url, published, crawled):
    aid = hashlib.sha256(url.encode()).hexdigest()
    conn.execute(
        "INSERT INTO articles (article_id, url, source, category, title, sapo, published_at, content_text, crawled_at, "
        "ingested_via, content_hash) VALUES (%s, %s, %s, 'Thời sự', 'Tiêu đề', '', %s, '', %s, 'import_jsonl', %s)",
        (aid, url, source, published, crawled, aid))
    return aid


@pytest.fixture
def live(pg_conn, pg_url, store):
    app = create_app(store, None, db_url=pg_url)
    app.state.crawler_url = "http://127.0.0.1:9"
    yield app, pg_conn
    if app.state.db_pool is not None:
        app.state.db_pool.close()


def test_db_rong_van_200(live):
    app, _ = live
    r = TestClient(app).get("/api/live/overview")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["totals"]["articles"] == 0 and d["sources"] == [] and d["worker"]["rounds"] == []


def test_ngay_tuong_lai_rat_cu_va_buoc_dang_chay_khong_lam_hong(live):
    app, c = live
    now = c.execute("SELECT now()").fetchone()[0]
    c.execute("INSERT INTO sources (source, display_name) VALUES ('tuoitre', 'Tuổi Trẻ'), ('qdnd', 'QĐND')")
    _article(c, "tuoitre", "https://tuoitre.vn/tuong-lai", now + timedelta(days=400), now)       # giờ đăng tương lai
    _article(c, "tuoitre", "https://tuoitre.vn/xua", now - timedelta(days=9000), now - timedelta(days=9000))
    c.execute("INSERT INTO worker_runs (step, status) VALUES ('embed', 'running')")              # chưa xong
    c.execute("INSERT INTO worker_runs (step, status, stats) VALUES ('recluster', 'failed', '{}')")
    c.execute("INSERT INTO crawl_runs (source, crawler, status) VALUES ('qdnd', 'rss', 'running')")
    r = TestClient(app).get("/api/live/overview")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["totals"]["articles"] == 2
    assert sum(sum(s["published"]) for s in d["hourly"]["series"]) == 0      # bài tương lai không rơi vào cột 48 giờ
    assert d["worker"]["rounds"][0]["status"] in ("running", "failed")


def test_khach_khong_thay_loi_noi_bo(live):
    app, c = live
    c.execute("INSERT INTO sources (source, display_name) VALUES ('qdnd', 'QĐND')")
    c.execute("INSERT INTO worker_runs (step, status, finished_at, error) VALUES ('embed', 'failed', now(), %s)",
              (f"FileNotFoundError: [Errno 2] No such file or directory: '{SECRET_PATH}'",))
    c.execute("INSERT INTO crawl_runs (source, crawler, status, finished_at, error) VALUES "
              "('qdnd', 'rss', 'failed', now(), %s)", (f"OperationalError: {SECRET_HOST}",))
    r = TestClient(app).get("/api/live/overview")                                # khách, không cookie
    assert r.status_code == 200
    assert "/home/" not in r.text and "10.9.8.7" not in r.text


WEIRD_SCHED = [{**SCHED, "next_run_at": "không phải ngày"}]
WEIRD_JOBS = [{"total": 1, "items": [{**JOB, "id": 42}]},
              {"total": 1, "items": [{**JOB, "results": {"tuoitre": {"discovered": None, "db": {}}}}]}]


@pytest.mark.parametrize("sched,jobs", [(WEIRD_SCHED[0], {"items": []}),
                                        (SCHED, WEIRD_JOBS[0]), (SCHED, WEIRD_JOBS[1])])
def test_live_crawler_tra_truong_sai_kieu_khong_500(live, monkeypatch, sched, jobs):
    app, _ = live
    monkeypatch.setattr(live_stats, "_http_json", lambda url, timeout: sched if "schedule" in url else jobs)
    r = TestClient(app, raise_server_exceptions=False).get("/api/live/overview")
    assert r.status_code == 200


def test_cai_dat_he_thong_crawler_tra_ngay_sai_khong_500(setup, pg_conn, monkeypatch):  # noqa: F811
    app, _, _ = setup

    def weird(base, method, path, body=None, timeout=3.0):
        if path == "/crawl/schedule":
            return 200, {**SCHED, "next_run_at": "không phải ngày"}
        return 200, {"total": 0, "items": []}
    monkeypatch.setattr(SS, "crawler_call", weird)
    c = _login(app, pg_conn)
    c = TestClient(app, raise_server_exceptions=False, cookies=dict(c.cookies))
    assert c.get("/api/admin/system/settings").status_code == 200

