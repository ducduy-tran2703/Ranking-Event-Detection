"""Kiểm tra (đợt audit P1-api): xác thực — cookie, CSRF, khoá tài khoản, token một lần, liệt kê email, rate limit,
dữ liệu vào lạ (NUL, ký tự ngoài ASCII trong header).

Phần cần Postgres dùng DB tạm (fixture pg_url/pg_conn).
"""
import base64

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from apps.api import accounts
from apps.api.main import create_app
from eventrank.accounts import cli

PW = "mat-khau-dai-123"
EVENT = "E20260913-aaaaaaaa"


# ---------------------------------------------------------------------- không cần Postgres
def _request(headers: dict[str, str], host: str = "10.0.0.9") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw, "client": (host, 1234),
                    "scheme": "http", "server": ("t", 80), "query_string": b""})


@pytest.mark.xfail(strict=True, reason="AUDIT-P1-api-09: TRUST_PROXY_HEADERS=1 lấy phần tử ĐẦU của X-Forwarded-For "
                                       "(do client tự đặt) → giả IP, vượt giới hạn 30 lần sai/IP và 20 báo sai/giờ")
def test_ip_sau_proxy_khong_lay_phan_tu_client_tu_dat(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    # Client gửi sẵn "1.2.3.4"; reverse proxy (nginx $proxy_add_x_forwarded_for) nối IP thật 198.51.100.7 vào cuối.
    req = _request({"X-Forwarded-For": "1.2.3.4, 198.51.100.7"})
    assert accounts.client_ip(req) == "198.51.100.7"


def test_ip_khong_tin_header_khi_chua_bat_proxy(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    req = _request({"X-Forwarded-For": "1.2.3.4", "CF-Connecting-IP": "5.6.7.8"})
    assert accounts.client_ip(req) == "10.0.0.9"


@pytest.mark.xfail(strict=True, reason="AUDIT-P1-api-07: Basic auth với tên/mật khẩu ngoài ASCII → "
                                       "secrets.compare_digest ném TypeError → 500")
def test_basic_auth_ky_tu_ngoai_ascii_khong_500(store, monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "nhom")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "mat-khau-manh")
    c = TestClient(create_app(store), raise_server_exceptions=False)
    header = "Basic " + base64.b64encode("nhóm:mật-khẩu".encode()).decode()
    assert c.get("/api/health", headers={"Authorization": header}).status_code == 401


# ---------------------------------------------------------------------- Postgres tạm
@pytest.fixture
def app(pg_conn, pg_url, store):
    pg_conn.execute("INSERT INTO sources (source, display_name) VALUES ('tuoitre', 'Tuổi Trẻ')")
    pg_conn.execute(
        "INSERT INTO events (event_id, first_seen, last_seen, size, n_sources, sources, display_name, name_source, "
        "algo_version, model_version) VALUES (%s, '2026-09-13 08:00+07', '2026-09-13 10:10+07', 1, 1, "
        "'{\"tuoitre\": 1}', 'Sự kiện', 'model', 'v1', 'm')", (EVENT,))
    a = create_app(store, None, db_url=pg_url)
    a.state.rag_autostart = False
    yield a
    if a.state.db_pool is not None:
        a.state.db_pool.close()


def _client(app):
    return TestClient(app, raise_server_exceptions=False)


def _register(c, email, name="Bạn Đọc", pw=PW):
    return c.post("/api/auth/register", json={"display_name": name, "email": email, "password": pw})


def _login(c, email, pw=PW, remember=False):
    return c.post("/api/auth/login", json={"email": email, "password": pw, "remember": remember})


def _send(c, method, path, body=None):
    return c.request(method, path, json=body, headers={"X-CSRF-Token": c.cookies.get("csrf_token") or ""})


def _cookie_names(r):
    return sorted(h.split("=", 1)[0] for h in r.headers.get_list("set-cookie"))


def test_dang_ky_khong_lo_email_qua_cookie(app):
    new = _register(_client(app), "moi@example.com")
    again = _register(_client(app), "moi@example.com", name="Kẻ dò")
    assert new.status_code == again.status_code == 204
    assert _cookie_names(new) == _cookie_names(again)


@pytest.mark.xfail(strict=True, reason="AUDIT-P1-api-03: sau 5 lần sai, email có thật trả 423, email không có vẫn "
                                       "401 → liệt kê được email đã đăng ký")
def test_khoa_tai_khoan_khong_lo_email_co_that(app, pg_conn):
    cli.create_user(pg_conn, "that@example.com", "Thật", PW)
    c = _client(app)
    real = [_login(c, "that@example.com", "sai-mat-khau").status_code for _ in range(6)]
    fake = [_login(c, "khong-co@example.com", "sai-mat-khau").status_code for _ in range(6)]
    assert real == fake


def test_dang_ky_hang_loat_tu_mot_ip_bi_chan(app, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    c = _client(app)
    codes = [c.post("/api/auth/register", headers={"X-Forwarded-For": "203.0.113.5"},
                    json={"display_name": "Rác", "email": f"rac{i}@example.com", "password": PW}).status_code
             for i in range(31)]
    assert 429 in codes


@pytest.mark.parametrize("case", ["login", "register", "feedback", "forgot"])
@pytest.mark.xfail(strict=True, reason="AUDIT-P1-api-05: chuỗi chứa ký tự NUL (\\x00) lọt tới Postgres → psycopg "
                                       "DataError → 500 thay vì 400/422")
def test_ky_tu_nul_khong_gay_500(app, case):
    c = _client(app)
    if case == "login":
        r = _login(c, "a\x00b@example.com")
    elif case == "register":
        r = _register(c, "nul@example.com", name="Tên\x00lạ")
    elif case == "feedback":
        r = c.post(f"/api/events/{EVENT}/feedback", json={"kind": "other", "note": "ghi\x00chú"})
    else:
        r = c.post("/api/auth/forgot-password", json={"email": "a\x00@example.com"})
    assert r.status_code < 500, r.status_code


@pytest.mark.xfail(strict=True, reason="AUDIT-P1-api-05: câu hỏi RAG chứa NUL → 500 (cùng nguyên nhân)")
def test_ky_tu_nul_trong_cau_hoi_rag_khong_500(app, pg_conn):
    cli.create_user(pg_conn, "hoi@example.com", "Hỏi", PW)
    c = _client(app)
    _login(c, "hoi@example.com")
    assert _send(c, "POST", "/api/rag/messages", {"question": "Câu\x00hỏi"}).status_code < 500


@pytest.mark.xfail(strict=True, reason="AUDIT-P1-api-06: header X-CSRF-Token ngoài ASCII → compare_digest ném "
                                       "TypeError → 500 thay vì 403")
def test_csrf_ngoai_ascii_tra_403_khong_500(app, pg_conn):
    cli.create_user(pg_conn, "csrf@example.com", "CSRF", PW)
    c = _client(app)
    _login(c, "csrf@example.com")
    r = c.post("/api/me/follows", json={"event_id": EVENT}, headers={"X-CSRF-Token": "é".encode()})
    assert r.status_code == 403


def test_token_email_het_han_sai_muc_dich_dung_lai_bi_tu_choi(app, pg_conn):
    c = _client(app)
    _register(c, "tok@example.com")
    verify = pg_conn.execute("SELECT payload->>'token' FROM email_outbox WHERE template = 'verify_email'").fetchone()[0]
    assert c.post("/api/auth/reset-password", json={"token": verify, "password": "mat-khau-moi-789"}).status_code == 400
    pg_conn.execute("UPDATE auth_tokens SET expires_at = now() - interval '1 second' WHERE purpose = 'verify_email'")
    assert c.post("/api/auth/verify-email", json={"token": verify}).status_code == 400
    c.post("/api/auth/forgot-password", json={"email": "tok@example.com"})
    reset = pg_conn.execute("SELECT payload->>'token' FROM email_outbox WHERE template = 'reset_password'").fetchone()[0]
    assert c.post("/api/auth/verify-email", json={"token": reset}).status_code == 400
    pg_conn.execute("UPDATE auth_tokens SET expires_at = now() - interval '1 second' WHERE purpose = 'reset_password'")
    assert c.post("/api/auth/reset-password", json={"token": reset, "password": "mat-khau-moi-789"}).status_code == 400
    assert _login(_client(app), "tok@example.com").status_code == 200                 # mật khẩu cũ vẫn dùng được
    assert c.post("/api/auth/verify-email", json={"token": ""}).status_code == 400


def test_cookie_secure_theo_https_va_bien_moi_truong(app, pg_conn, monkeypatch):
    cli.create_user(pg_conn, "sec@example.com", "Sec", PW)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    r = _client(app).post("/api/auth/login", json={"email": "sec@example.com", "password": PW},
                          headers={"X-Forwarded-Proto": "https"})
    sess = next(h for h in r.headers.get_list("set-cookie") if h.startswith("er_session="))
    assert "secure" in sess.lower() and "httponly" in sess.lower() and "samesite=lax" in sess.lower()
    monkeypatch.setenv("COOKIE_SECURE", "0")
    r = _client(app).post("/api/auth/login", json={"email": "sec@example.com", "password": PW},
                          headers={"X-Forwarded-Proto": "https"})
    sess = next(h for h in r.headers.get_list("set-cookie") if h.startswith("er_session="))
    assert "secure" not in sess.lower()


@pytest.mark.xfail(strict=True, reason="AUDIT-P1-api-10: 'giữ đăng nhập' trượt hạn ở DB nhưng cookie không được cấp "
                                       "lại → trình duyệt vẫn xoá cookie sau 30 ngày kể từ lúc đăng nhập")
def test_giu_dang_nhap_cap_lai_cookie_khi_truot_han(app, pg_conn):
    cli.create_user(pg_conn, "nho@example.com", "Nhớ", PW)
    c = _client(app)
    assert _login(c, "nho@example.com", remember=True).status_code == 200
    pg_conn.execute("UPDATE user_sessions SET last_seen_at = now() - interval '10 days', "
                    "created_at = now() - interval '10 days'")
    r = c.get("/api/auth/me")
    assert r.status_code == 200 and "er_session" in _cookie_names(r)


@pytest.mark.xfail(strict=True, reason="AUDIT-P1-api-08: đổi mật khẩu không đếm/khoá khi sai mật khẩu cũ → ai giữ được "
                                       "cookie phiên dò được mật khẩu thật không giới hạn")
def test_doi_mat_khau_sai_nhieu_lan_bi_chan(app, pg_conn):
    cli.create_user(pg_conn, "doi@example.com", "Đổi", PW)
    c = _client(app)
    _login(c, "doi@example.com")
    codes = [_send(c, "POST", "/api/auth/change-password",
                   {"old_password": f"doan-{i}-xyz", "new_password": "mat-khau-moi-789"}).status_code for i in range(8)]
    assert codes[-1] in (423, 429)
