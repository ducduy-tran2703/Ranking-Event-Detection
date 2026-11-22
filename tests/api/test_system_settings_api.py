"""`/api/admin/system/*` — trang Cài đặt hệ thống: lịch cào (proxy crawler), đồng bộ RAG, worker sự kiện.

Postgres tạm (TEST_DATABASE_URL). Không gọi crawler thật (`crawler_call` giả), không chạy sync thật (bộ lập lịch giả).
"""
import pytest
from fastapi.testclient import TestClient

from apps.api import system_settings as SS
from apps.api.main import create_app
from eventrank.accounts import cli
from eventrank.rag import auto_sync as RS

PW = "quan-tri-vien-456"
SCHED = {"enabled": True, "interval_minutes": 30, "sources": ["tuoitre", "vnexpress"], "timezone": "Asia/Ho_Chi_Minh",
         "active_job_id": None, "next_run_at": "2026-11-22T15:30:00+07:00", "last_slot": "x"}
JOB = {"id": "j1", "trigger": "manual", "status": "succeeded", "created_at": "2026-11-22T15:00:00+07:00",
       "started_at": "2026-11-22T15:00:01+07:00", "finished_at": "2026-11-22T15:04:00+07:00",
       "results": {"tuoitre": {"status": "succeeded", "phase": "done", "discovered": 5, "processed": 5, "clean": 4,
                               "rejected": 1, "failed": 0, "db": {"inserted": 3, "updated": 1}, "errors": []}}}


class FakeCrawler:
    def __init__(self):
        self.calls, self.up, self.sched = [], True, dict(SCHED)
        self.conflict = False

    def __call__(self, base, method, path, body=None, timeout=3.0):
        self.calls.append((method, path, body))
        if not self.up:
            raise SS.CrawlerUnavailable("URLError")
        if method == "GET" and path == "/crawl/schedule":
            return 200, self.sched
        if method == "GET" and path.startswith("/crawl/jobs"):
            return 200, {"total": 1, "items": [JOB]}
        if method == "PATCH":
            self.sched.update(body)
            return 200, self.sched
        if method == "POST" and path == "/crawl/jobs":
            if self.conflict:
                return 409, {"detail": "Job j0 is still running"}
            return 202, {"id": "j2", "status": "queued", "sources": body.get("sources", ["tuoitre"])}
        raise AssertionError((method, path))


class FakeScheduler:
    def __init__(self):
        self.triggered = 0

    def trigger_now(self):
        self.triggered += 1
        return True

    def wake(self):
        pass

    def status(self):
        return {"scheduler_running": False, "leader": False}


@pytest.fixture
def setup(pg_conn, pg_url, store, monkeypatch):
    crawler, sched = FakeCrawler(), FakeScheduler()
    monkeypatch.setattr(SS, "crawler_call", crawler)
    app = create_app(store, None, db_url=pg_url)
    app.state.rag_auto_sync_factory = lambda _app: sched
    app.state.rag_config = {"index_version": "rag_v1", "chunking": {"max_units": 320, "overlap_units": 48}}
    with RS.SYNC_LOCK:
        RS.SYNC_STATE.update(running=False, last_error=None, last_result=None, trigger=None)
    yield app, crawler, sched
    if app.state.db_pool is not None:
        app.state.db_pool.close()


def _login(app, pg_conn, role="admin", email="admin@example.com"):
    cli.create_user(pg_conn, email, "Quản trị", PW, role)
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"email": email, "password": PW, "remember": False}).status_code == 200
    return c


def send(c, method, path, body=None, csrf=True):
    headers = {"X-CSRF-Token": c.cookies.get("csrf_token") or ""} if csrf else {}
    return c.request(method, path, json=body, headers=headers)


def test_chi_admin_va_ghi_can_csrf(setup, pg_conn):
    app, _, _ = setup
    assert TestClient(app).get("/api/admin/system/settings").status_code == 401
    editor = _login(app, pg_conn, "editor", "bien-tap@example.com")
    assert editor.get("/api/admin/system/settings").status_code == 403
    admin = _login(app, pg_conn)
    assert send(admin, "PUT", "/api/admin/system/settings/rag-sync", {"mode": "off"}, csrf=False).status_code == 403


def test_get_tra_ba_khoi_mac_dinh(setup, pg_conn):
    app, _, _ = setup
    body = _login(app, pg_conn).get("/api/admin/system/settings").json()
    assert body["settings_available"] is True
    cr = body["crawler"]
    assert cr["reachable"] and cr["interval_minutes"] == 30 and cr["sources"] == ["tuoitre", "vnexpress"]
    assert len(cr["all_sources"]) == 8 and cr["jobs"][0]["sources"][0]["inserted"] == 3
    rag = body["rag_sync"]
    assert rag["settings"] == {"mode": "after_crawl", "interval_minutes": 60, "max_articles_per_run": 200,
                               "min_mem_available_mb": 1500}
    assert rag["pending_articles"] == 0 and rag["recent_runs"] == [] and rag["running"] is False
    ev = body["event_worker"]
    assert ev["settings"] == {"enabled": True, "interval_seconds": 300} and ev["yaml_interval_seconds"] == 300
    assert ev["worker_alive"] is False and ev["last_run"] is None


def test_crawler_tat_get_van_200_con_ghi_thi_503_tieng_viet(setup, pg_conn):
    app, crawler, _ = setup
    crawler.up = False
    c = _login(app, pg_conn)
    resp = c.get("/api/admin/system/settings")
    assert resp.status_code == 200 and resp.json()["crawler"]["reachable"] is False
    for method, path, body in (("PATCH", "/api/admin/system/crawler/schedule", {"enabled": False}),
                               ("POST", "/api/admin/system/crawler/run", {})):
        r = send(c, method, path, body)
        assert r.status_code == 503 and "make crawler" in r.json()["detail"]


def test_doi_lich_cao_kiem_truoc_khi_gui(setup, pg_conn):
    app, crawler, _ = setup
    c = _login(app, pg_conn)
    for bad in ({"interval_minutes": 7}, {"sources": []}, {"sources": ["bao-la"]}, {}, {"enabled": None},
                {"enabled": True, "x": 1}):
        assert send(c, "PATCH", "/api/admin/system/crawler/schedule", bad).status_code == 422, bad
    assert not [x for x in crawler.calls if x[0] == "PATCH"]
    r = send(c, "PATCH", "/api/admin/system/crawler/schedule",
             {"interval_minutes": 15, "sources": ["dantri", "dantri", "qdnd"]})
    assert r.status_code == 200 and r.json()["interval_minutes"] == 15
    assert ("PATCH", "/crawl/schedule", {"interval_minutes": 15, "sources": ["dantri", "qdnd"]}) in crawler.calls


def test_cao_ngay_theo_bao_trong_lich_va_bao_trung_lap_job(setup, pg_conn):
    app, crawler, _ = setup
    c = _login(app, pg_conn)
    r = send(c, "POST", "/api/admin/system/crawler/run", {})
    assert r.status_code == 202 and r.json()["id"] == "j2"
    assert ("POST", "/crawl/jobs", {"sources": ["tuoitre", "vnexpress"]}) in crawler.calls
    crawler.conflict = True
    r = send(c, "POST", "/api/admin/system/crawler/run", {"sources": ["tuoitre"]})
    assert r.status_code == 409 and "đợi" in r.json()["detail"]


def test_luu_cai_dat_rag_va_worker_ghi_nguoi_sua(setup, pg_conn):
    app, _, _ = setup
    c = _login(app, pg_conn)
    bad = send(c, "PUT", "/api/admin/system/settings/rag-sync", {"mode": "interval", "interval_minutes": 45})
    assert bad.status_code == 422
    r = send(c, "PUT", "/api/admin/system/settings/rag-sync",
             {"mode": "interval", "interval_minutes": 120, "max_articles_per_run": 50, "min_mem_available_mb": 1000})
    assert r.status_code == 200 and r.json()["settings"]["interval_minutes"] == 120
    assert r.json()["updated_by"] == "Quản trị"
    assert RS.load_settings(pg_conn).value.mode == "interval"
    r = send(c, "PUT", "/api/admin/system/settings/event-worker", {"enabled": False, "interval_seconds": 900})
    assert r.status_code == 200 and r.json()["settings"] == {"enabled": False, "interval_seconds": 900}
    assert send(c, "PUT", "/api/admin/system/settings/event-worker", {"interval_seconds": 61}).status_code == 422
    got = c.get("/api/admin/system/settings").json()
    assert got["rag_sync"]["settings"]["max_articles_per_run"] == 50 and got["event_worker"]["settings"]["enabled"] is False


def test_dong_bo_ngay_goi_bo_lap_lich_va_tu_choi_khi_dang_chay(setup, pg_conn):
    app, _, sched = setup
    c = _login(app, pg_conn)
    r = send(c, "POST", "/api/admin/system/rag-sync/run")
    assert r.status_code == 202 and r.json()["status"] == "accepted" and sched.triggered == 1
    assert RS.begin_run("manual")
    r = send(c, "POST", "/api/admin/system/rag-sync/run")
    assert r.json()["status"] == "already_running" and sched.triggered == 1
    assert c.get("/api/admin/system/settings").json()["rag_sync"]["running"] is True


def test_lich_su_rag_sync_va_worker_hien_tren_trang(setup, pg_conn):
    app, _, _ = setup
    pg_conn.execute("INSERT INTO worker_runs (step, status, finished_at, stats, versions, error) VALUES "
                    "('rag_sync', 'failed', now(), '{}', '{\"trigger\": \"auto\"}', 'RuntimeError: Qwen lỗi'), "
                    "('embed', 'ok', now(), '{\"n_articles\": 4}', '{}', NULL)")
    body = _login(app, pg_conn).get("/api/admin/system/settings").json()
    run = body["rag_sync"]["recent_runs"][0]
    assert run["status"] == "failed" and run["trigger"] == "auto" and body["rag_sync"]["last_error"] == run["error"]
    assert body["event_worker"]["last_run"]["step"] == "embed"


def test_test_khong_bao_gio_bat_bo_lap_lich(setup):
    app, _, _ = setup
    with TestClient(app):
        assert app.state.rag_auto_sync is None and app.state.rag_auto_sync_enabled is False
    assert create_app().state.rag_auto_sync_enabled is True       # chạy thật mới bật (RAG_AUTO_SYNC=0 vẫn tắt)


def test_db_chua_ap_011_get_van_chay_luu_thi_503(setup, pg_conn):
    app, _, _ = setup
    c = _login(app, pg_conn)
    pg_conn.execute("DROP TABLE system_settings")
    body = c.get("/api/admin/system/settings").json()
    assert body["settings_available"] is False and body["rag_sync"]["settings"]["mode"] == "after_crawl"
    r = send(c, "PUT", "/api/admin/system/settings/rag-sync", {"mode": "off"})
    assert r.status_code == 503 and "make db-migrate" in r.json()["detail"]


def test_loi_422_cua_crawler_khong_chuyen_nguyen_van(setup, pg_conn, monkeypatch):
    app, _, _ = setup

    def reject(base, method, path, body=None, timeout=3.0):
        if method == "PATCH":
            return 422, {"detail": [{"loc": ["body", "sources", 0], "msg": "Traceback /home/x/secret.py",
                                     "type": "literal_error"}]}
        return 200, SCHED if path == "/crawl/schedule" else {"items": []}
    monkeypatch.setattr(SS, "crawler_call", reject)
    r = send(_login(app, pg_conn), "PATCH", "/api/admin/system/crawler/schedule", {"sources": ["tuoitre"]})
    assert r.status_code == 400 and "danh sách báo" in r.json()["detail"] and "secret" not in r.text


def test_dong_bo_ngay_khi_bo_lap_lich_tat_ket_qua_hien_tren_get(setup, pg_conn):
    """RAG_AUTO_SYNC=0: lượt "Đồng bộ ngay" chạy tách riêng; bị bỏ vì RAM thấp thì GET /settings phải cho thấy."""
    import time as _t

    app, _, _ = setup
    url = app.state.db_url
    from eventrank.common import db as _db
    app.state.rag_auto_sync_factory = lambda _app: RS.AutoSync(
        connect=lambda: _db.connect(url), load_config=lambda: app.state.rag_config,
        sync_fn=lambda *a, **k: pytest.fail("không được chạy khi RAM thấp"), mem_fn=lambda: 100)
    c = _login(app, pg_conn)
    assert send(c, "POST", "/api/admin/system/rag-sync/run").json()["status"] == "accepted"
    deadline = _t.monotonic() + 5
    while _t.monotonic() < deadline:
        sched = c.get("/api/admin/system/settings").json()["rag_sync"]["scheduler"]
        if sched["last_decision"]:
            break
        _t.sleep(0.05)
    assert sched["last_decision"] == "low_memory" and sched["scheduler_running"] is False



def test_canh_bao_khi_qdrant_dang_go_publish(setup, pg_conn):
    app, _, _ = setup
    app.state.rag_config = {**app.state.rag_config, "dense": {"url": "http://qdrant.test", "collection": "c"}}
    c = _login(app, pg_conn)
    app.state.rag_qdrant_get = lambda path: {"result": {"config": {"metadata": {"published": False}}}}
    assert c.get("/api/admin/system/settings").json()["rag_sync"]["dense_published"] is False
    app.state.rag_qdrant_get = lambda path: {"result": {"config": {"metadata": {"published": True}}}}
    assert c.get("/api/admin/system/settings").json()["rag_sync"]["dense_published"] is True

    def down(path):
        raise OSError("refused")
    app.state.rag_qdrant_get = down
    assert c.get("/api/admin/system/settings").json()["rag_sync"]["dense_published"] is None
