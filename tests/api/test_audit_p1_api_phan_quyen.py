"""Kiểm tra (đợt audit P1-api): phân quyền endpoint × vai trò, IDOR, khoá API (api_tokens).

Phần cần Postgres dùng DB tạm (fixture pg_url/pg_conn); DATABASE_URL bị trỏ tới cổng 1 để không bao giờ chạm DB chính
(route /api/rag/* của admin mở `db.connect()` riêng). /api/admin/system/* đã có test_system_settings_security.py.
"""
import pytest
from fastapi.testclient import TestClient

from apps.api import rag as R
from apps.api.main import create_app
from eventrank.accounts import cli

PW = "mat-khau-dai-123"
EVENT = "E20260913-aaaaaaaa"

ADMIN_ONLY = [
    ("GET", "/api/admin/users", None),
    ("PUT", "/api/admin/users/999999", {"role": "user"}),
    ("POST", "/api/admin/users/999999/unlock", None),
    ("GET", "/api/admin/outbox", None),
    ("GET", "/api/admin/api-tokens", None),
    ("POST", "/api/admin/api-tokens", {"label": "x"}),
    ("DELETE", "/api/admin/api-tokens/999999", None),
    ("GET", "/api/rag/sync/status", None),
    ("POST", "/api/rag/sync", {"article_ids": ["a" * 64]}),
    ("POST", "/api/rag/ask", {"question": "Tỷ số?"}),
]
EDITOR = [
    ("GET", "/api/admin/feedback", None),
    ("PUT", "/api/admin/feedback/999999", {"status": "resolved"}),
]
USER = [
    ("GET", "/api/auth/me", None),
    ("GET", "/api/me/notifications", None),
    ("GET", "/api/me/follows", None),
    ("GET", "/api/me/sessions", None),
    ("GET", "/api/me/settings", None),
    ("GET", "/api/rag/conversations", None),
    ("GET", "/api/rag/profile", None),
    ("GET", "/api/rag/messages/999999", None),
]


# ---------------------------------------------------------------------- không cần Postgres
def test_nap_lai_kho_can_quyen_quan_tri(store):
    c = TestClient(create_app(store))
    assert c.post("/api/admin/reload").status_code in (401, 403)


# ---------------------------------------------------------------------- Postgres tạm
class _NoDb:
    def connect(self, *a, **k):
        raise AssertionError("test không được mở kết nối DB chính")

    DatabaseConfigError = RuntimeError


class _FakePipeline:
    def ask(self, question, **kw):
        return {"status": "answered", "answer": "ok", "sources": [], "retrieval_mode": "hybrid", "degraded": False,
                "snapshot": {"from_date": None, "to_date": None, "articles": 0, "sources": []}, "trace": {}}


@pytest.fixture
def app(pg_conn, pg_url, store, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://khong-dung@127.0.0.1:1/khong")
    monkeypatch.setattr(R, "db", _NoDb())
    pg_conn.execute("INSERT INTO sources (source, display_name) VALUES ('tuoitre', 'Tuổi Trẻ')")
    pg_conn.execute(
        "INSERT INTO events (event_id, first_seen, last_seen, size, n_sources, sources, display_name, name_source, "
        "algo_version, model_version) VALUES (%s, '2026-09-13 08:00+07', '2026-09-13 10:10+07', 1, 1, "
        "'{\"tuoitre\": 1}', 'Sự kiện', 'model', 'v1', 'm')", (EVENT,))
    a = create_app(store, None, db_url=pg_url)
    a.state.rag_autostart = False
    a.dependency_overrides[R.get_pipeline] = lambda: _FakePipeline()
    yield a
    if a.state.db_pool is not None:
        a.state.db_pool.close()


def _login(app, pg_conn, role, email):
    cli.create_user(pg_conn, email, f"Người {role}", PW, role)
    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/api/auth/login", json={"email": email, "password": PW}).status_code == 200
    return c


def _send(c, method, path, body):
    return c.request(method, path, json=body, headers={"X-CSRF-Token": c.cookies.get("csrf_token") or ""})


def test_bang_phan_quyen_endpoint_vai_tro(app, pg_conn):
    guest = TestClient(app, raise_server_exceptions=False)
    user = _login(app, pg_conn, "user", "u@example.com")
    editor = _login(app, pg_conn, "editor", "e@example.com")
    admin = _login(app, pg_conn, "admin", "a@example.com")
    got = {}
    for method, path, body in ADMIN_ONLY + EDITOR + USER:
        got[(method, path)] = tuple(_send(c, method, path, body).status_code for c in (guest, user, editor, admin)
                                    if not (c is admin and path == "/api/rag/sync"))   # sync thật mở DB chính
    for method, path, _ in ADMIN_ONLY:
        g, u, e, *a = got[(method, path)]
        assert (g, u, e) == (401, 403, 403), (method, path, got[(method, path)])
        assert not a or a[0] not in (401, 403), (method, path, a)
    for method, path, _ in EDITOR:
        g, u, e, a = got[(method, path)]
        assert (g, u) == (401, 403) and e not in (401, 403) and a not in (401, 403), (method, path)
    for method, path, _ in USER:
        g, *rest = got[(method, path)]
        assert g == 401 and all(x not in (401, 403) for x in rest), (method, path, rest)


def test_router_admin_va_router_chat_chung_tien_to_khong_che_nhau(app, pg_conn):
    """/api/rag có hai router: admin (ask, sync, sync/status) và chat. Người dùng thường vẫn vào được chat."""
    user = _login(app, pg_conn, "user", "u@example.com")
    assert user.get("/api/rag/status").status_code == 200
    assert TestClient(app).get("/api/rag/status").status_code == 200                  # công khai
    r = _send(user, "POST", "/api/rag/messages", {"question": "Hôm nay có gì?"})
    assert r.status_code == 202
    assert user.get(f"/api/rag/messages/{r.json()['message_id']}").status_code == 200
    assert _send(user, "POST", "/api/rag/ask", {"question": "x"}).status_code == 403


def test_csrf_bat_buoc_cho_router_admin_rag(app, pg_conn):
    admin = _login(app, pg_conn, "admin", "a@example.com")
    assert admin.post("/api/rag/ask", json={"question": "x"}).status_code == 403
    assert admin.post("/api/rag/ask", json={"question": "x"}, headers={"X-CSRF-Token": "sai"}).status_code == 403
    assert _send(admin, "POST", "/api/rag/ask", {"question": "x"}).status_code == 200


def test_khoa_api_khong_mo_duoc_endpoint_nao(app, pg_conn):
    """api_tokens chỉ được tạo/thu hồi; không endpoint nào của API nhận `Authorization: Bearer`."""
    admin = _login(app, pg_conn, "admin", "a@example.com")
    token = _send(admin, "POST", "/api/admin/api-tokens", {"label": "crawler", "scope": "read"}).json()["token"]
    bearer = TestClient(app)
    for path in ("/api/auth/me", "/api/admin/users", "/api/me/follows", "/api/rag/conversations"):
        assert bearer.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 401, path


def test_idor_phien_va_chu_de_cua_nguoi_khac(app, pg_conn):
    a = _login(app, pg_conn, "user", "a1@example.com")
    b = _login(app, pg_conn, "user", "b1@example.com")
    sid_a = a.get("/api/me/sessions").json()[0]["id"]
    assert _send(a, "POST", "/api/me/subscriptions", {"kind": "keyword", "value": "bão"}).status_code == 204
    sub_a = a.get("/api/me/subscriptions").json()[0]["id"]
    assert _send(b, "DELETE", f"/api/me/sessions/{sid_a}", None).status_code == 204     # không lộ có/không
    assert _send(b, "DELETE", f"/api/me/subscriptions/{sub_a}", None).status_code == 204
    assert a.get("/api/auth/me").status_code == 200                                     # phiên A còn sống
    assert [s["id"] for s in a.get("/api/me/subscriptions").json()] == [sub_a]
    assert b.get("/api/auth/me").status_code == 200                                     # B không tự đăng xuất
    assert _send(b, "DELETE", "/api/me/sessions/99999999999999999999", None).status_code == 204   # id quá bigint


def test_idor_hoi_dap_cua_nguoi_khac(app, pg_conn):
    a = _login(app, pg_conn, "user", "a2@example.com")
    b = _login(app, pg_conn, "user", "b2@example.com")
    msg = _send(a, "POST", "/api/rag/messages", {"question": "Câu của A"}).json()
    cid, mid = msg["conversation_id"], msg["message_id"]
    assert b.get(f"/api/rag/conversations/{cid}").status_code == 404
    assert b.get(f"/api/rag/messages/{mid}").status_code == 404
    assert _send(b, "POST", f"/api/rag/messages/{mid}/cancel", None).status_code == 404
    assert _send(b, "DELETE", f"/api/rag/conversations/{cid}", None).status_code == 404
    assert _send(b, "POST", "/api/rag/messages", {"question": "chen", "conversation_id": cid}).status_code == 404
    assert a.get(f"/api/rag/messages/{mid}").json()["status"] == "queued"


def test_dependency_override_khong_lam_lot_quyen(app):
    """Bảo đảm override pipeline (dùng trong test) không thay thế kiểm quyền của router."""
    assert TestClient(app).post("/api/rag/ask", json={"question": "x"}).status_code == 401
