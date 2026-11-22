"""API tài khoản (/api/auth, /api/me, /api/admin, báo sai) trên Postgres tạm — migration 003–006, apps/api/accounts.py.

Trọng tâm bảo mật: không lộ email đã đăng ký, khoá sau 5 lần sai, CSRF bắt buộc, phiên bị thu hồi đúng lúc, DB không
chứa mật khẩu/token dạng đọc được. Cần TEST_DATABASE_URL (tự skip khi thiếu).
"""
import hashlib

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from eventrank.accounts import cli
from eventrank.common import db

EVENT = "E20260913-aaaaaaaa"
EVENT_NAME = "Mưa lớn gây ngập nhiều tuyến phố Hà Nội"
PW = "mat-khau-dai-123"
ADMIN_PW = "quan-tri-vien-456"


@pytest.fixture
def app(pg_conn, pg_url, store):
    pg_conn.execute("INSERT INTO sources (source, display_name) VALUES ('tuoitre', 'Tuổi Trẻ'), ('vnexpress', 'VnExpress')")
    pg_conn.execute(
        "INSERT INTO events (event_id, first_seen, last_seen, size, n_sources, sources, display_name, name_source, "
        "category_std, algo_version, model_version) VALUES (%s, '2026-09-13 08:00+07', '2026-09-13 10:10+07', 3, 2, "
        "'{\"tuoitre\": 2, \"vnexpress\": 1}', %s, 'model', 'Thời sự', 'v1', 'm')", (EVENT, EVENT_NAME))
    a = create_app(store, None, db_url=pg_url)
    yield a
    if a.state.db_pool is not None:          # đóng pool để fixture xoá được DB tạm
        a.state.db_pool.close()


@pytest.fixture
def mk(app):
    return lambda: TestClient(app)


def send(c, method, path, body=None):
    """Như web: gửi lại cookie csrf_token trong header X-CSRF-Token."""
    return c.request(method, path, json=body, headers={"X-CSRF-Token": c.cookies.get("csrf_token") or ""})


def register(c, email="ban@example.com", name="Bạn Đọc", pw=PW, **kw):
    return c.post("/api/auth/register", json={"display_name": name, "email": email, "password": pw, **kw})


def login(c, email, pw, remember=False):
    return c.post("/api/auth/login", json={"email": email, "password": pw, "remember": remember})


def admin_client(mk, pg_conn, role="admin", email="admin@example.com"):
    cli.create_user(pg_conn, email, "Quản trị", ADMIN_PW, role)
    c = mk()
    assert login(c, email, ADMIN_PW).status_code == 200
    return c


def outbox_token(pg_conn, template):
    return pg_conn.execute("SELECT payload->>'token' FROM email_outbox WHERE template = %s ORDER BY email_id DESC "
                           "LIMIT 1", (template,)).fetchone()[0]


# ---------------------------------------------------------------------- đăng ký, xác minh
def test_dang_ky_dang_nhap_luon_va_xac_minh_email(mk, pg_conn):
    c = mk()
    r = register(c, email="  Ban@Example.COM ", name="  Bạn   Đọc ", role="admin")     # role gửi lên bị bỏ qua
    assert r.status_code == 204
    cookies = r.headers.get_list("set-cookie")
    sess = next(x for x in cookies if x.startswith("er_session="))
    assert "httponly" in sess.lower() and "samesite=lax" in sess.lower()
    assert not any("httponly" in x.lower() for x in cookies if x.startswith("csrf_token="))
    me = c.get("/api/auth/me").json()
    assert (me["email"], me["display_name"], me["role"], me["email_verified"]) == ("ban@example.com", "Bạn Đọc",
                                                                                   "user", False)
    assert isinstance(me["id"], str)
    token = outbox_token(pg_conn, "verify_email")
    assert send(c, "POST", "/api/auth/verify-email", {"token": token}).status_code == 204
    assert c.get("/api/auth/me").json()["email_verified"] is True
    r = c.post("/api/auth/verify-email", json={"token": token})                     # dùng lại → hết hiệu lực
    assert r.status_code == 400 and "không hợp lệ" in r.json()["detail"]
    assert c.get("/api/me/notifications").json()[0]["kind"] == "Hệ thống"


def test_dang_ky_email_da_co_khong_lo_va_khong_dang_nhap(mk, pg_conn):
    assert register(mk()).status_code == 204
    c2 = mk()
    r = register(c2, email="BAN@example.com", name="Kẻ lạ", pw="mot-mat-khau-khac")
    assert r.status_code == 204 and "er_session" not in r.cookies
    assert c2.get("/api/auth/me").status_code == 401
    assert pg_conn.execute("SELECT count(*), min(display_name) FROM users").fetchone() == (1, "Bạn Đọc")


def test_mat_khau_yeu_va_du_lieu_sai_bi_tu_choi(mk):
    c = mk()
    assert register(c, pw="1234567").status_code == 400
    r = register(c, pw="12345678")
    assert r.status_code == 400 and "phổ biến" in r.json()["detail"]
    assert register(c, email="khong-phai-email").status_code == 400
    assert register(c, pw="x" * 300).status_code == 422


# ---------------------------------------------------------------------- đăng nhập, khoá
def test_sai_5_lan_bi_khoa_thong_bao_chung_va_admin_mo_khoa(mk, pg_conn):
    cli.create_user(pg_conn, "ban@example.com", "Bạn", PW)
    c = mk()
    unknown = login(c, "khong-co@example.com", PW)
    for _ in range(5):
        r = login(c, "ban@example.com", "sai-mat-khau")
        assert r.status_code == 401 and r.json()["detail"] == unknown.json()["detail"]   # không lộ email nào có thật
    assert login(c, "ban@example.com", PW).status_code == 423                         # đúng mật khẩu vẫn bị khoá
    a = admin_client(mk, pg_conn)
    uid = next(u["id"] for u in a.get("/api/admin/users").json() if u["email"] == "ban@example.com")
    assert next(u for u in a.get("/api/admin/users").json() if u["id"] == uid)["locked_until"] is not None
    assert send(a, "POST", f"/api/admin/users/{uid}/unlock").status_code == 204
    assert login(c, "ban@example.com", "sai-mat-khau").status_code == 401             # lần sai cũ không còn đếm
    assert login(c, "ban@example.com", PW).status_code == 200
    reasons = dict(pg_conn.execute("SELECT reason, count(*) FROM login_attempts GROUP BY 1").fetchall())
    assert reasons["bad_password"] == 6 and reasons["locked"] == 1 and reasons["unknown_email"] == 1


def test_csrf_bat_buoc_voi_thao_tac_ghi(mk):
    c = mk()
    register(c)
    assert c.post("/api/me/follows", json={"event_id": EVENT}).status_code == 403
    assert c.post("/api/me/follows", json={"event_id": EVENT}, headers={"X-CSRF-Token": "doan-bua"}).status_code == 403
    assert send(c, "POST", "/api/me/follows", {"event_id": EVENT}).status_code == 204
    assert c.post("/api/auth/logout").status_code == 403                               # cả đăng xuất


# ---------------------------------------------------------------------- "Của tôi"
def test_theo_doi_luu_chu_de_cai_dat(mk):
    c = mk()
    register(c)
    assert send(c, "POST", "/api/me/follows", {"event_id": "E20260101-00000000"}).status_code == 404
    assert send(c, "POST", "/api/me/follows", {"event_id": "khong-hop-le"}).status_code == 422
    for _ in range(2):
        assert send(c, "POST", "/api/me/follows", {"event_id": EVENT}).status_code == 204
    f = c.get("/api/me/follows").json()
    assert len(f) == 1 and {k: f[0][k] for k in ("event_id", "ten", "size", "n_sources", "chuyen_muc", "notify")} == {
        "event_id": EVENT, "ten": EVENT_NAME, "size": 3, "n_sources": 2, "chuyen_muc": "Thời sự", "notify": True}
    assert send(c, "PUT", f"/api/me/follows/{EVENT}", {"notify": False}).status_code == 204
    assert c.get("/api/me/follows").json()[0]["notify"] is False
    assert send(c, "DELETE", f"/api/me/follows/{EVENT}").status_code == 204
    assert c.get("/api/me/follows").json() == []

    assert send(c, "POST", "/api/me/bookmarks", {"event_id": EVENT, "note": "đọc tối nay"}).status_code == 204
    assert c.get("/api/me/bookmarks").json()[0]["note"] == "đọc tối nay"
    assert send(c, "DELETE", f"/api/me/bookmarks/{EVENT}").status_code == 204

    for v in ("Bão  Yagi", "bão yagi", "BÃO YAGI"):                                  # trùng không phân biệt hoa/thường
        assert send(c, "POST", "/api/me/subscriptions", {"kind": "keyword", "value": v}).status_code == 204
    send(c, "POST", "/api/me/subscriptions", {"kind": "category", "value": "Thể thao"})
    subs = c.get("/api/me/subscriptions").json()
    assert [(s["kind"], s["value"]) for s in subs] == [("keyword", "Bão Yagi"), ("category", "Thể thao")]
    for i in range(48):
        send(c, "POST", "/api/me/subscriptions", {"kind": "keyword", "value": f"chủ đề {i}"})
    r = send(c, "POST", "/api/me/subscriptions", {"kind": "keyword", "value": "một chủ đề nữa"})
    assert r.status_code == 400 and "50" in r.json()["detail"]
    assert send(c, "DELETE", f"/api/me/subscriptions/{subs[0]['id']}").status_code == 204
    assert len(c.get("/api/me/subscriptions").json()) == 49

    assert c.get("/api/me/settings").json() == {"push": True, "digest": "off", "quiet_from": "22:00",
                                                "quiet_to": "07:00", "hidden_sources": []}
    s = send(c, "PUT", "/api/me/settings", {"quiet_from": "23:30", "hidden_sources": ["vnexpress"], "digest": "daily"})
    assert s.json() == {"push": True, "digest": "daily", "quiet_from": "23:30", "quiet_to": "07:00",
                        "hidden_sources": ["vnexpress"]}
    assert send(c, "PUT", "/api/me/settings", {"quiet_to": "25:00"}).status_code == 422


def test_nhieu_thiet_bi_doi_mat_khau_va_dang_xuat_moi_noi(mk):
    c1, c2 = mk(), mk()
    register(c1)
    assert login(c2, "ban@example.com", PW, remember=True).status_code == 200
    ss = c1.get("/api/me/sessions").json()
    assert len(ss) == 2 and ss[0]["current"] and not ss[1]["current"]
    r = send(c1, "POST", "/api/auth/change-password", {"old_password": "sai", "new_password": "mat-khau-moi-789"})
    assert r.status_code == 400 and "hiện tại" in r.json()["detail"]
    assert send(c1, "POST", "/api/auth/change-password",
                {"old_password": PW, "new_password": "mat-khau-moi-789"}).status_code == 204
    assert c1.get("/api/auth/me").status_code == 200 and c2.get("/api/auth/me").status_code == 401
    c3 = mk()
    login(c3, "ban@example.com", "mat-khau-moi-789")
    other = next(s for s in c1.get("/api/me/sessions").json() if not s["current"])
    assert send(c1, "DELETE", f"/api/me/sessions/{other['id']}").status_code == 204
    assert c3.get("/api/auth/me").status_code == 401
    login(c3, "ban@example.com", "mat-khau-moi-789")
    assert send(c1, "POST", "/api/auth/logout-all").status_code == 204
    assert c1.get("/api/auth/me").status_code == 401 and c3.get("/api/auth/me").status_code == 401


def test_quen_va_dat_lai_mat_khau(mk, pg_conn):
    c = mk()
    register(c)
    assert c.post("/api/auth/forgot-password", json={"email": "khong-co@example.com"}).status_code == 204
    assert pg_conn.execute("SELECT count(*) FROM email_outbox WHERE template = 'reset_password'").fetchone()[0] == 0
    c.post("/api/auth/forgot-password", json={"email": "Ban@Example.com"})
    first = outbox_token(pg_conn, "reset_password")
    c.post("/api/auth/forgot-password", json={"email": "ban@example.com"})
    second = outbox_token(pg_conn, "reset_password")
    assert c.post("/api/auth/reset-password", json={"token": first, "password": "mat-khau-moi-789"}).status_code == 400
    assert c.post("/api/auth/reset-password", json={"token": second, "password": "12345678"}).status_code == 400
    assert c.post("/api/auth/reset-password", json={"token": second, "password": "mat-khau-moi-789"}).status_code == 204
    assert c.get("/api/auth/me").status_code == 401                                   # mọi phiên bị thu hồi
    assert login(mk(), "ban@example.com", PW).status_code == 401
    assert login(mk(), "ban@example.com", "mat-khau-moi-789").status_code == 200
    assert c.post("/api/auth/reset-password", json={"token": second, "password": "lan-nua-abc"}).status_code == 400
    for _ in range(3):
        c.post("/api/auth/forgot-password", json={"email": "ban@example.com"})
    assert pg_conn.execute("SELECT count(*) FROM email_outbox WHERE template = 'reset_password'").fetchone()[0] == 3


def test_xoa_tai_khoan_roi_dang_ky_lai(mk, pg_conn):
    c = mk()
    register(c)
    send(c, "POST", "/api/me/bookmarks", {"event_id": EVENT})
    assert send(c, "DELETE", "/api/me").status_code == 204
    assert c.get("/api/auth/me").status_code == 401
    assert login(mk(), "ban@example.com", PW).status_code == 401
    c2 = mk()
    assert register(c2, name="Người mới").status_code == 204 and c2.get("/api/auth/me").status_code == 200
    assert c2.get("/api/me/bookmarks").json() == []
    assert pg_conn.execute("SELECT count(*) FROM users").fetchone()[0] == 2


# ---------------------------------------------------------------------- báo sai, quản trị
def test_bao_sai_khach_gui_duoc_bien_tap_xu_ly(mk, pg_conn):
    g = mk()
    r = g.post(f"/api/events/{EVENT}/feedback", json={"kind": "wrong_name", "note": "Tên sai địa danh",
                                                       "event_name": "tên do trình duyệt gửi"})
    assert r.status_code == 204
    assert g.post("/api/events/E20260101-00000000/feedback", json={"kind": "other"}).status_code == 404
    u = mk()
    register(u)
    assert u.get("/api/admin/feedback").status_code == 403
    e = admin_client(mk, pg_conn, role="editor", email="bientap@example.com")
    items = e.get("/api/admin/feedback").json()
    assert [(i["who"], i["event_name"], i["status"]) for i in items] == [("khách", EVENT_NAME, "open")]
    assert send(e, "PUT", f"/api/admin/feedback/{items[0]['id']}", {"status": "resolved"}).status_code == 204
    assert e.get("/api/admin/feedback").json()[0]["status"] == "resolved"
    assert e.get("/api/admin/users").status_code == 403                               # editor không quản lý người dùng


def test_quan_tri_vai_tro_va_khoa_api(mk, pg_conn):
    u = mk()
    register(u)
    assert u.get("/api/admin/users").status_code == 403
    a = admin_client(mk, pg_conn)
    users = {x["email"]: x for x in a.get("/api/admin/users").json()}
    assert send(a, "PUT", f"/api/admin/users/{users['ban@example.com']['id']}", {"role": "editor"}).status_code == 204
    assert u.get("/api/auth/me").json()["role"] == "editor"
    r = send(a, "PUT", f"/api/admin/users/{users['admin@example.com']['id']}", {"role": "user"})
    assert r.status_code == 400                                                       # không tự hạ quyền
    r = send(a, "POST", "/api/admin/api-tokens", {"label": "crawler Tuổi Trẻ", "source": "tuoitre"})
    token = r.json()["token"]
    assert token.startswith("er_") and len(token) > 30
    listed = a.get("/api/admin/api-tokens").json()
    assert listed[0]["prefix"] == token[:10] and token not in str(listed)
    stored = pg_conn.execute("SELECT token_hash, scopes FROM api_tokens").fetchone()
    assert stored == (hashlib.sha256(token.encode()).hexdigest(), ["ingest:write"])
    assert send(a, "DELETE", f"/api/admin/api-tokens/{listed[0]['id']}").status_code == 204
    assert a.get("/api/admin/api-tokens").json()[0]["revoked"] is True
    assert send(a, "POST", "/api/admin/api-tokens", {"label": "x", "source": "khongco"}).status_code == 400
    actions = {x for (x,) in pg_conn.execute("SELECT action FROM audit_logs")}
    assert {"user.role_change", "api_token.create", "api_token.revoke", "user.login"} <= actions


def test_thu_he_thong_va_db_khong_chua_bi_mat(mk, pg_conn):
    c = mk()
    register(c)
    a = admin_client(mk, pg_conn)
    mails = a.get("/api/admin/outbox").json()
    assert [(m["to"], m["kind"], m["used"]) for m in mails] == [("ban@example.com", "verify", False)]
    send(c, "POST", "/api/auth/verify-email", {"token": mails[0]["token"]})
    assert a.get("/api/admin/outbox").json()[0]["used"] is True
    pw_hash = pg_conn.execute("SELECT password_hash FROM users WHERE email = 'ban@example.com'").fetchone()[0]
    assert pw_hash.startswith("$argon2id$") and PW not in pw_hash
    cookie = c.cookies.get("er_session")
    hashes = {h.strip() for (h,) in pg_conn.execute("SELECT token_hash FROM user_sessions")}
    assert cookie not in hashes and hashlib.sha256(cookie.encode()).hexdigest() in hashes
    dump = " ".join(str(r) for t in ("users", "user_sessions", "auth_tokens", "audit_logs", "login_attempts")
                    for r in pg_conn.execute(f"SELECT * FROM {t}").fetchall())
    assert PW not in dump and ADMIN_PW not in dump and cookie not in dump


def test_thieu_database_url_tra_503(store, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "load_dotenv", lambda *a, **k: False)
    c = TestClient(create_app(store, None))
    r = c.get("/api/auth/me")
    assert r.status_code == 503 and "DATABASE_URL" in r.json()["detail"]
    assert c.get("/api/health").status_code == 200                                     # phần còn lại vẫn chạy


def test_cleanup_an_danh_tai_khoan_da_xoa_qua_30_ngay(pg_conn):
    uid = cli.create_user(pg_conn, "cu@example.com", "Người cũ", PW)
    pg_conn.execute("UPDATE users SET deleted_at = now() - interval '31 days' WHERE user_id = %s", (uid,))
    pg_conn.execute("INSERT INTO login_attempts (email_tried, succeeded, reason, at) VALUES "
                    "('cu@example.com', false, 'bad_password', now() - interval '40 days')")
    cid = pg_conn.execute("INSERT INTO rag_conversations (user_id, title) VALUES (%s, 'Câu hỏi cũ') "
                          "RETURNING conversation_id", (uid,)).fetchone()[0]
    pg_conn.execute("INSERT INTO rag_messages (conversation_id, user_id, question) VALUES (%s, %s, 'Câu hỏi cũ?')",
                    (cid, uid))
    out = cli.cleanup(pg_conn)
    assert pg_conn.execute("SELECT count(*) FROM rag_messages WHERE user_id = %s", (uid,)).fetchone()[0] == 0
    assert out["users (ẩn danh)"] == 1 and out["login_attempts"] == 1
    email, name, pw = pg_conn.execute("SELECT email, display_name, password_hash FROM users WHERE user_id = %s",
                                      (uid,)).fetchone()
    assert (email, name, pw) == (f"da-xoa-{uid}@an-danh.invalid", "Tài khoản đã xoá", None)
    assert cli.cleanup(pg_conn)["users (ẩn danh)"] == 0
