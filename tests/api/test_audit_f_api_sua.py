"""Pha sửa (agent F-api): test đi kèm các bản sửa AUDIT-P1-api-01, 02, 04, 11, 13 — phần mà test audit pha 1 chưa phủ
(admin vẫn dùng được, CSRF, bộ đệm tách theo vai trò, giới hạn đăng ký chặn trước khi băm, đăng nhập sau đăng ký).

Postgres tạm (fixture pg_url/pg_conn); crawler giả (không gọi mạng).
"""
import pytest
from fastapi.testclient import TestClient
from test_system_settings_api import JOB, SCHED, _login, setup  # noqa: F401 -- setup là fixture

from apps.api import system_settings as SS
from apps.api.main import create_app
from eventrank.accounts import auth as AU
from eventrank.accounts import cli
from eventrank.serving import live_stats

PW = "mat-khau-dai-123"
SECRET = "/home/hieu/bi-mat/x.npy"


@pytest.fixture
def app(pg_conn, pg_url, store):
    a = create_app(store, None, db_url=pg_url)
    a.state.crawler_url = "http://127.0.0.1:9"
    a.state.rag_autostart = False
    yield a
    if a.state.db_pool is not None:
        a.state.db_pool.close()


def _client_as(app, pg_conn, role, email):
    cli.create_user(pg_conn, email, "Người dùng", PW, role)
    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/api/auth/login", json={"email": email, "password": PW, "remember": False}).status_code == 200
    return c


def _csrf(c):
    return {"X-CSRF-Token": c.cookies.get("csrf_token") or ""}


# ---------------------------------------------------------------------- AUDIT-P1-api-01: nạp lại kho
def test_nap_lai_kho_admin_co_csrf_moi_duoc(app, pg_conn):
    admin = _client_as(app, pg_conn, "admin", "admin@example.com")
    assert admin.post("/api/admin/reload").status_code == 403                       # thiếu CSRF
    r = admin.post("/api/admin/reload", headers=_csrf(admin))
    assert r.status_code == 200 and r.json()["rows"] == 5
    editor = _client_as(app, pg_conn, "editor", "bientap@example.com")
    assert editor.post("/api/admin/reload", headers=_csrf(editor)).status_code == 403


# ---------------------------------------------------------------------- AUDIT-P1-api-11: lỗi nội bộ trên /api/live
def _seed_errors(c):
    c.execute("INSERT INTO sources (source, display_name) VALUES ('qdnd', 'QĐND')")
    c.execute("INSERT INTO worker_runs (step, status, finished_at, error) VALUES ('embed', 'failed', now(), %s)",
              (f"FileNotFoundError: [Errno 2] No such file or directory: '{SECRET}'",))
    c.execute("INSERT INTO crawl_runs (source, crawler, status, finished_at, error) VALUES "
              "('qdnd', 'rss', 'failed', now(), %s)", ("OperationalError: connection to 10.9.8.7 failed",))


def test_khach_chi_thay_ten_lop_loi_admin_thay_du(app, pg_conn):
    _seed_errors(pg_conn)
    guest = TestClient(app)
    g = guest.get("/api/live/overview").json()
    assert g["worker"]["rounds"][0]["steps"]["embed"]["error"] == "FileNotFoundError"
    assert g["crawl_runs"][0]["error"] == "OperationalError"
    assert g["sources"][0]["last_error"] == "OperationalError"
    admin = _client_as(app, pg_conn, "admin", "admin@example.com")
    a = admin.get("/api/live/overview").json()                                    # trong 15 s đệm của khách
    assert SECRET in a["worker"]["rounds"][0]["steps"]["embed"]["error"]
    assert "10.9.8.7" in a["crawl_runs"][0]["error"] and "10.9.8.7" in a["sources"][0]["last_error"]
    assert SECRET not in guest.get("/api/live/overview").text                     # admin vừa nạp đệm → khách vẫn ẩn
    user = _client_as(app, pg_conn, "editor", "bientap@example.com")
    assert SECRET not in user.get("/api/live/overview").text


def test_loi_trong_job_crawler_cung_an_voi_khach(app, pg_conn, monkeypatch):
    job = {**JOB, "results": {"tuoitre": {**JOB["results"]["tuoitre"], "errors": [f"OSError: {SECRET}"]}}}
    monkeypatch.setattr(live_stats, "_http_json",
                        lambda url, timeout: SCHED if "schedule" in url else {"total": 1, "items": [job]})
    g = TestClient(app).get("/api/live/overview").json()
    src = g["crawler"]["jobs"][0]["sources"][0]
    assert src["errors"] == ["OSError"] and src["n_errors"] == 1


def test_loi_khong_ro_dang_khong_lo_nguyen_van():
    assert live_stats.public_error('connection to server at "10.9.8.7" failed: FATAL') == "Lỗi"
    assert live_stats.public_error("HTTP 503") == "HTTP 503"
    assert live_stats.public_error(None) is None


# ---------------------------------------------------------------------- AUDIT-P1-api-13: crawler trả sai kiểu
@pytest.mark.parametrize("sched,jobs", [
    ({**SCHED, "active_job_id": 7}, {"total": "x", "items": [{**JOB, "id": 42}]}),
    (SCHED, {"total": 1, "items": [{**JOB, "results": {"tuoitre": {**JOB["results"]["tuoitre"], "clean": None}}}]}),
])
def test_cai_dat_he_thong_crawler_tra_sai_kieu_coi_nhu_khong_tra_loi(setup, pg_conn, monkeypatch, sched,  # noqa: F811
                                                                    jobs):
    app, _, _ = setup
    monkeypatch.setattr(SS, "crawler_call", lambda base, method, path, body=None, timeout=3.0:
                        (200, sched if path == "/crawl/schedule" else jobs))
    c = _login(app, pg_conn)
    c = TestClient(app, raise_server_exceptions=False, cookies=dict(c.cookies))
    r = c.get("/api/admin/system/settings")
    assert r.status_code == 200
    assert r.json()["crawler"]["reachable"] in (True, False)


def test_live_crawler_ngay_sai_coi_nhu_khong_tra_loi(app, monkeypatch):
    monkeypatch.setattr(live_stats, "_http_json",
                        lambda url, timeout: {**SCHED, "next_run_at": "không phải ngày"} if "schedule" in url
                        else {"items": []})
    r = TestClient(app, raise_server_exceptions=False).get("/api/live/overview")
    assert r.status_code == 200 and r.json()["crawler"] is None


# ---------------------------------------------------------------------- AUDIT-P1-api-02 + 04: đăng ký
def _register(c, email, ip=None, name="Bạn Đọc"):
    headers = {"X-Forwarded-For": ip} if ip else {}
    return c.post("/api/auth/register", headers=headers, json={"display_name": name, "email": email, "password": PW})


def test_dang_ky_khong_dang_nhap_nhung_dang_nhap_duoc_ngay(app, pg_conn):
    c = TestClient(app)
    r = _register(c, "moi@example.com")
    assert r.status_code == 204 and r.headers.get_list("set-cookie") == []
    assert c.get("/api/auth/me").status_code == 401
    assert pg_conn.execute("SELECT count(*) FROM user_sessions").fetchone()[0] == 0
    assert pg_conn.execute("SELECT count(*) FROM email_outbox WHERE template = 'verify_email'").fetchone()[0] == 1
    assert c.post("/api/auth/login", json={"email": "moi@example.com", "password": PW}).status_code == 200
    assert c.get("/api/auth/me").json()["email_verified"] is False


def test_dang_ky_vuot_nguong_ip_bi_chan_truoc_khi_bam(app, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    hashed = []
    real_hash = AU.S.hash_password
    monkeypatch.setattr(AU.S, "hash_password", lambda pw: hashed.append(1) or real_hash(pw))
    c = TestClient(app)
    codes = [_register(c, f"rac{i}@example.com", "203.0.113.5").status_code for i in range(AU.REGISTER_PER_IP_HOUR)]
    assert codes == [204] * AU.REGISTER_PER_IP_HOUR
    n = len(hashed)
    r = _register(c, "them@example.com", "203.0.113.5")
    assert r.status_code == 429 and "giờ" in r.json()["detail"]
    r = _register(c, "rac0@example.com", "203.0.113.5")                              # email đã có cũng bị chặn
    assert r.status_code == 429
    assert len(hashed) == n                                                         # không băm Argon2 khi đã chặn
    assert _register(c, "khac@example.com", "198.51.100.9").status_code == 204       # IP khác không bị ảnh hưởng
