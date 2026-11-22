"""Kiểm thử độc lập bảo mật + kiểm dữ liệu vào của `/api/admin/system/*` (mọi endpoint ghi, không chỉ một).

Postgres tạm (TEST_DATABASE_URL); crawler và bộ lập lịch giả (fixture `setup` của test_system_settings_api.py).
"""
import pytest
from fastapi.testclient import TestClient
from test_system_settings_api import _login, send, setup  # noqa: F401 -- setup là fixture

from apps.api import system_settings as SS

BASE = "/api/admin/system"
WRITES = [
    ("PUT", f"{BASE}/settings/rag-sync", {"mode": "off"}),
    ("PUT", f"{BASE}/settings/event-worker", {"enabled": False, "interval_seconds": 600}),
    ("PATCH", f"{BASE}/crawler/schedule", {"enabled": False}),
    ("POST", f"{BASE}/crawler/run", {}),
    ("POST", f"{BASE}/rag-sync/run", None),
]


def _no_side_effect(pg_conn, crawler, sched):
    assert pg_conn.execute("SELECT count(*) FROM system_settings").fetchone()[0] == 0
    assert not [c for c in crawler.calls if c[0] in ("PATCH", "POST")]
    assert sched.triggered == 0


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_moi_endpoint_ghi_chan_khach_bien_tap_va_thieu_sai_csrf(setup, pg_conn, method, path, body):  # noqa: F811
    app, crawler, sched = setup
    assert TestClient(app).request(method, path, json=body).status_code == 401
    editor = _login(app, pg_conn, "editor", "bien-tap@example.com")
    assert send(editor, method, path, body).status_code == 403
    admin = _login(app, pg_conn)
    assert send(admin, method, path, body, csrf=False).status_code == 403
    r = admin.request(method, path, json=body, headers={"X-CSRF-Token": "sai-ma"})
    assert r.status_code == 403
    _no_side_effect(pg_conn, crawler, sched)


def test_get_cung_chi_admin(setup, pg_conn):  # noqa: F811
    app, crawler, _ = setup
    viewer = _login(app, pg_conn, "user", "doc-gia@example.com")
    assert viewer.get(f"{BASE}/settings").status_code == 403
    assert crawler.calls == []          # chưa qua quyền thì không được chạm tới crawler


@pytest.mark.parametrize("bad", [
    {"mode": "sometimes"}, {"interval_minutes": 0}, {"interval_minutes": 45}, {"interval_minutes": "60x"},
    {"max_articles_per_run": 9}, {"max_articles_per_run": 1001}, {"max_articles_per_run": 10.5},
    {"min_mem_available_mb": -1}, {"min_mem_available_mb": 16385}, {"mode": "off", "extra": 1}, [],
])
def test_rag_sync_tu_choi_gia_tri_sai(setup, pg_conn, bad):  # noqa: F811
    app, _, _ = setup
    c = _login(app, pg_conn)
    assert send(c, "PUT", f"{BASE}/settings/rag-sync", bad).status_code == 422
    assert pg_conn.execute("SELECT count(*) FROM system_settings").fetchone()[0] == 0


@pytest.mark.parametrize("bad", [
    {"interval_seconds": 30}, {"interval_seconds": 7200}, {"enabled": "maybe"}, {"enabled": True, "x": 1},
])
def test_event_worker_tu_choi_gia_tri_sai(setup, pg_conn, bad):  # noqa: F811
    app, _, _ = setup
    c = _login(app, pg_conn)
    assert send(c, "PUT", f"{BASE}/settings/event-worker", bad).status_code == 422


@pytest.mark.parametrize("bad", [
    {"sources": ["../crawl/jobs"]}, {"sources": ["vnexpress?limit=1"]}, {"sources": ["VNEXPRESS"]},
    {"sources": "vnexpress"}, {"sources": []}, {"extra": True},
])
def test_cao_ngay_tu_choi_bao_la_va_khong_cho_chen_duong_dan(setup, pg_conn, bad):  # noqa: F811
    app, crawler, _ = setup
    c = _login(app, pg_conn)
    assert send(c, "POST", f"{BASE}/crawler/run", bad).status_code == 422
    assert not [x for x in crawler.calls if x[0] == "POST"]


def test_proxy_chi_goi_duong_dan_co_dinh(setup, pg_conn):  # noqa: F811
    app, crawler, _ = setup
    c = _login(app, pg_conn)
    c.get(f"{BASE}/settings")
    send(c, "PATCH", f"{BASE}/crawler/schedule", {"sources": ["dantri"], "enabled": True, "interval_minutes": 60})
    send(c, "POST", f"{BASE}/crawler/run", {"sources": ["qdnd"]})
    paths = {p.split("?")[0] for _, p, _ in crawler.calls}
    assert paths <= {"/crawl/schedule", "/crawl/jobs"}


def test_loi_crawler_khong_lo_url_noi_bo(setup, pg_conn, monkeypatch):  # noqa: F811
    app, _, _ = setup
    secret = "http://10.0.0.5:8002/home/hieu/data/state/schedule.json"

    def crawler_500(base, method, path, body=None, timeout=3.0):
        if method == "GET":
            return 500, {"detail": f"Traceback ... {secret}"}
        return 500, {"detail": f"Traceback ... {secret}"}
    monkeypatch.setattr(SS, "crawler_call", crawler_500)
    c = _login(app, pg_conn)
    got = c.get(f"{BASE}/settings")
    assert got.status_code == 200 and secret not in got.text
    r = send(c, "PATCH", f"{BASE}/crawler/schedule", {"enabled": True})
    assert r.status_code == 502 and secret not in r.text and "10.0.0.5" not in r.text


def test_crawler_tra_json_khong_phai_object_khong_lam_500(setup, pg_conn, monkeypatch):  # noqa: F811
    """Crawler (phiên bản khác/hỏng) trả 200 với JSON mảng cho /crawl/schedule: "Cào ngay" không được ném 500."""
    app, _, _ = setup

    def weird(base, method, path, body=None, timeout=3.0):
        if method == "GET" and path == "/crawl/schedule":
            return 200, ["không phải object"]
        if method == "GET":
            return 200, {"items": []}
        return 202, {"id": "j9", "status": "queued", "sources": ["tuoitre"]}
    monkeypatch.setattr(SS, "crawler_call", weird)
    c = _login(app, pg_conn)
    assert c.get(f"{BASE}/settings").json()["crawler"]["reachable"] is False
    r = send(c, "POST", f"{BASE}/crawler/run", {})
    assert r.status_code in (202, 502), r.status_code
