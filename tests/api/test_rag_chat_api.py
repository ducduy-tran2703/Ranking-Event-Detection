"""Khung chat hỏi đáp (/api/rag/status|conversations|messages, migration 008, eventrank.rag.chat) trên Postgres tạm.

Pipeline RAG được thay bằng bản giả (không gọi Modal/Qdrant); worker chạy đồng bộ bằng `run_once()`.
Trọng tâm: bắt đăng nhập + CSRF, mỗi người chỉ thấy cuộc trò chuyện của mình, hàng đợi một lượt/người, hạn mức
24 giờ, lỗi dịch vụ lưu thành câu an toàn (không lộ chi tiết), nguồn được gắn sự kiện chứa bài.
"""
import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from eventrank.accounts import cli
from eventrank.rag import chat as C
from eventrank.rag.pipeline import RAGUnavailableError

PW = "mat-khau-dai-123"
AID = "a" * 64
EVENT = "E20260918-aaaaaaaa"
URL = "https://tuoitre.vn/u23-viet-nam-thang-philippines.htm"


def answer(**kw):
    return {"status": "answered", "answer": "U23 Việt Nam thắng 2-0. [1]",
            "sources": [{"citation_id": 1, "chunk_id": "00000000-0000-0000-0000-000000000001", "article_id": AID,
                         "title": "U23 Việt Nam thắng Philippines", "url": URL, "source": "tuoitre",
                         "published_at": "2026-09-18T12:30:00+07:00", "start_char": 0, "end_char": 40,
                         "chunking_version": "c1-test", "quotes": ["đánh bại Philippines 2-0"]}],
            "retrieval_mode": "hybrid", "degraded": False, "snapshot": {}, "trace": {"request_id": "r1"}, **kw}


class FakePipeline:
    def __init__(self, behaviour):
        self.behaviour, self.calls, self.closed = behaviour, [], 0

    def ask(self, question, **kw):
        self.calls.append((question, kw))
        if isinstance(self.behaviour, BaseException):
            raise self.behaviour
        return self.behaviour

    def close(self):
        self.closed += 1


@pytest.fixture
def env(pg_conn, pg_url, store):
    pg_conn.execute("INSERT INTO sources (source, display_name) VALUES ('tuoitre', 'Tuổi Trẻ')")
    pg_conn.execute(
        "INSERT INTO articles (article_id, url, source, category, title, sapo, published_at, content_text, "
        "ingested_via, content_hash) VALUES (%s, %s, 'tuoitre', 'the-thao', 'U23 Việt Nam thắng Philippines', '', "
        "'2026-09-18 12:30+07', 'nội dung', 'import_jsonl', %s)", (AID, URL, "b" * 64))
    pg_conn.execute(
        "INSERT INTO events (event_id, first_seen, last_seen, size, n_sources, sources, display_name, name_source, "
        "category_std, algo_version, model_version) VALUES (%s, '2026-09-18 08:00+07', '2026-09-18 20:00+07', 1, 1, "
        "'{\"tuoitre\": 1}', 'U23 Việt Nam thắng U23 Philippines', 'model', 'Thể thao', 'v1', 'm')", (EVENT,))
    pg_conn.execute("INSERT INTO event_articles (article_id, event_id, method) VALUES (%s, %s, 'import')", (AID, EVENT))
    app = create_app(store, None, db_url=pg_url)
    app.state.rag_autostart = False
    app.state.rag_readiness = lambda conn, config: C.readiness(conn, config, qdrant_get=lambda path: None, env={})
    fake = FakePipeline(answer())
    app.state.rag_pipeline_factory = lambda conn: fake
    yield app, fake
    if app.state.db_pool is not None:
        app.state.db_pool.close()


def client(app, pg_conn, email="ban@example.com", role="user"):
    cli.create_user(pg_conn, email, "Bạn Đọc", PW, role)
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"email": email, "password": PW, "remember": False}).status_code == 200
    return c


def send(c, method, path, body=None):
    return c.request(method, path, json=body, headers={"X-CSRF-Token": c.cookies.get("csrf_token") or ""})


def run_worker(app):
    """Chạy worker đồng bộ cho tới khi hàng đợi rỗng."""
    w = app.state.rag_worker
    assert w is not None, "worker phải được tạo ở yêu cầu đầu tiên"
    n = 0
    while w.run_once():
        n += 1
    return n


def test_khach_khong_hoi_duoc_nhung_xem_duoc_trang_thai(env):
    app, fake = env
    c = TestClient(app)
    assert c.get("/api/rag/conversations").status_code == 401
    assert c.post("/api/rag/messages", json={"question": "Tỷ số?"}).status_code == 401
    st = c.get("/api/rag/status")
    assert st.status_code == 200
    body = st.json()
    assert body["used_today"] is None and body["daily_limit"] == C.DEFAULT_DAILY_LIMIT and body["single_turn"] is True
    assert body["available"] is False and body["problems"]          # DB tạm không có kho RAG
    assert fake.calls == []


def test_gui_cau_hoi_can_csrf(env, pg_conn):
    app, _ = env
    c = client(app, pg_conn)
    r = c.post("/api/rag/messages", json={"question": "Tỷ số?"})                       # không gửi X-CSRF-Token
    assert r.status_code == 403


def test_hoi_xep_hang_roi_worker_tra_loi_va_gan_su_kien(env, pg_conn):
    app, fake = env
    c = client(app, pg_conn)
    r = send(c, "POST", "/api/rag/messages", {"question": "  U23 Việt Nam thắng   U23 Philippines bao nhiêu? ",
                                              "source": "TuoiTre", "date_from": "2026-09-18", "date_to": "2026-09-19"})
    assert r.status_code == 202
    msg = r.json()
    assert msg["status"] == "queued" and msg["queue_position"] == 1 and msg["answer"] is None
    assert msg["question"] == "U23 Việt Nam thắng U23 Philippines bao nhiêu?"
    assert msg["filters"] == {"source": "tuoitre", "date_from": "2026-09-18", "date_to": "2026-09-19"}

    assert run_worker(app) == 1
    assert fake.calls == [("U23 Việt Nam thắng U23 Philippines bao nhiêu?",
                           {"source": "tuoitre", "date_from": "2026-09-18", "date_to": "2026-09-19"})]
    assert fake.closed == 1
    done = c.get(f"/api/rag/messages/{msg['message_id']}").json()
    assert done["status"] == "answered" and done["answer"].endswith("[1]") and done["seconds"] is not None
    src = done["sources"][0]
    assert src["event_id"] == EVENT and src["event_name"] == "U23 Việt Nam thắng U23 Philippines"
    assert src["url"] == URL and src["quotes"] == ["đánh bại Philippines 2-0"]
    assert "trace" not in done                                                         # trace không trả cho người dùng

    convs = c.get("/api/rag/conversations").json()
    assert len(convs) == 1 and convs[0]["n_messages"] == 1 and convs[0]["last_status"] == "answered"
    assert convs[0]["title"] == "U23 Việt Nam thắng U23 Philippines bao nhiêu?"
    detail = c.get(f"/api/rag/conversations/{msg['conversation_id']}").json()
    assert [m["message_id"] for m in detail["messages"]] == [msg["message_id"]]


def test_hoi_tiep_trong_cung_cuoc_tro_chuyen(env, pg_conn):
    app, _ = env
    c = client(app, pg_conn)
    first = send(c, "POST", "/api/rag/messages", {"question": "Câu một?"}).json()
    run_worker(app)
    second = send(c, "POST", "/api/rag/messages", {"question": "Câu hai?",
                                                   "conversation_id": first["conversation_id"]})
    assert second.status_code == 202 and second.json()["conversation_id"] == first["conversation_id"]
    run_worker(app)
    detail = c.get(f"/api/rag/conversations/{first['conversation_id']}").json()
    assert [m["question"] for m in detail["messages"]] == ["Câu một?", "Câu hai?"]
    assert len(c.get("/api/rag/conversations").json()) == 1


def test_moi_nguoi_mot_cau_dang_cho(env, pg_conn):
    app, _ = env
    c = client(app, pg_conn)
    assert send(c, "POST", "/api/rag/messages", {"question": "Câu một?"}).status_code == 202
    r = send(c, "POST", "/api/rag/messages", {"question": "Câu hai?"})
    assert r.status_code == 409 and "đang được trả lời" in r.json()["detail"]


def test_han_muc_24_gio(env, pg_conn, monkeypatch):
    monkeypatch.setenv("RAG_DAILY_LIMIT", "2")
    app, _ = env
    c = client(app, pg_conn)
    for q in ("Một?", "Hai?"):
        assert send(c, "POST", "/api/rag/messages", {"question": q}).status_code == 202
        run_worker(app)
    r = send(c, "POST", "/api/rag/messages", {"question": "Ba?"})
    assert r.status_code == 429
    st = c.get("/api/rag/status").json()
    assert st["daily_limit"] == 2 and st["used_today"] == 2
    admin = client(app, pg_conn, "admin@example.com", "admin")                       # admin không giới hạn
    assert c.get("/api/rag/status").json()["used_today"] == 2
    assert admin.get("/api/rag/status").json()["daily_limit"] is None


def test_khong_xem_duoc_cua_nguoi_khac(env, pg_conn):
    app, _ = env
    a = client(app, pg_conn, "a@example.com")
    b = client(app, pg_conn, "b@example.com")
    msg = send(a, "POST", "/api/rag/messages", {"question": "Của A?"}).json()
    assert b.get(f"/api/rag/conversations/{msg['conversation_id']}").status_code == 404
    assert b.get(f"/api/rag/messages/{msg['message_id']}").status_code == 404
    assert send(b, "DELETE", f"/api/rag/conversations/{msg['conversation_id']}").status_code == 404
    assert send(b, "POST", "/api/rag/messages", {"question": "Chen vào?",
                                                 "conversation_id": msg["conversation_id"]}).status_code == 404
    assert b.get("/api/rag/conversations").json() == []


def test_loi_dich_vu_luu_cau_an_toan(env, pg_conn):
    app, fake = env
    fake.behaviour = RAGUnavailableError("generation", {"secret": "https://private-modal-url.example"})
    c = client(app, pg_conn)
    msg = send(c, "POST", "/api/rag/messages", {"question": "Tỷ số?"}).json()
    run_worker(app)
    r = c.get(f"/api/rag/messages/{msg['message_id']}")
    body = r.json()
    assert body["status"] == "failed" and body["error"] == C.PHASE_MESSAGES["generation"]
    assert "private-modal-url" not in r.text
    # lượt lỗi không chặn câu tiếp theo
    assert send(c, "POST", "/api/rag/messages", {"question": "Hỏi lại?"}).status_code == 202


def test_loi_bat_ky_khong_lo_chi_tiet(env, pg_conn):
    app, fake = env
    fake.behaviour = RuntimeError("postgresql://user:matkhau@host/db")
    c = client(app, pg_conn)
    msg = send(c, "POST", "/api/rag/messages", {"question": "Tỷ số?"}).json()
    run_worker(app)
    r = c.get(f"/api/rag/messages/{msg['message_id']}")
    assert r.json()["error"] == C.GENERIC_ERROR and "matkhau" not in r.text


def test_khoi_dong_lai_doi_luot_dang_chay_thanh_failed(env, pg_conn, pg_url):
    app, _ = env
    c = client(app, pg_conn)
    msg = send(c, "POST", "/api/rag/messages", {"question": "Tỷ số?"}).json()
    assert C.claim_next(pg_conn).message_id == msg["message_id"]                  # đang chạy thì máy chủ tắt
    assert C.recover_stale(pg_conn) == 1
    body = c.get(f"/api/rag/messages/{msg['message_id']}").json()
    assert body["status"] == "failed" and body["error"] == C.RESTART_ERROR


def test_xoa_cuoc_tro_chuyen(env, pg_conn):
    app, _ = env
    c = client(app, pg_conn)
    msg = send(c, "POST", "/api/rag/messages", {"question": "Tỷ số?"}).json()
    run_worker(app)
    assert send(c, "DELETE", f"/api/rag/conversations/{msg['conversation_id']}").status_code == 204
    assert c.get("/api/rag/conversations").json() == []
    assert pg_conn.execute("SELECT count(*) FROM rag_messages").fetchone()[0] == 0


@pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": "x" * 2049},
                                     {"question": "x", "date_from": "2026-09-19", "date_to": "2026-09-18"},
                                     {"question": "x", "extra": 1}, {"question": "x", "conversation_id": 0}])
def test_yeu_cau_sai_khong_vao_hang_doi(env, pg_conn, payload):
    app, _ = env
    c = client(app, pg_conn)
    assert send(c, "POST", "/api/rag/messages", payload).status_code == 422
    assert pg_conn.execute("SELECT count(*) FROM rag_messages").fetchone()[0] == 0


def test_ask_dong_bo_tren_app_chinh_chi_cho_admin(env, pg_conn):
    app, _ = env
    assert TestClient(app).post("/api/rag/ask", json={"question": "Tỷ số?"}).status_code == 401
    user = client(app, pg_conn)
    assert send(user, "POST", "/api/rag/ask", {"question": "Tỷ số?"}).status_code == 403


def test_readiness_bao_tung_thieu_sot(pg_conn, tmp_path):
    config = {"index_version": "rag_v1", "bm25": {"root": "bm25"},
              "dense": {"url": "http://127.0.0.1:1", "collection": "c"}}
    r = C.readiness(pg_conn, config, qdrant_get=lambda path: None, env={}, root=tmp_path)
    assert r["available"] is False and len(r["problems"]) == 5
    (tmp_path / "bm25").mkdir()
    (tmp_path / "bm25/CURRENT.json").write_text("{}")
    (tmp_path / "data/rag/tokenizers").mkdir(parents=True)
    (tmp_path / "data/rag/tokenizers/x").write_text("")
    env = {k: "x" for k in C.MODEL_ENV}
    r = C.readiness(pg_conn, config, qdrant_get=lambda p: {"result": {"config": {"metadata": {"published": True}}}},
                    env=env, root=tmp_path)
    assert r["problems"] == ["Kho RAG trong Postgres chưa có dữ liệu."]


def test_worker_nen_tu_tra_loi_khi_bat_autostart(env, pg_conn):
    """Như chạy thật: luồng nền khởi động ở yêu cầu đầu tiên, được đánh thức khi có câu hỏi mới."""
    import time

    app, fake = env
    app.state.rag_autostart = True
    c = client(app, pg_conn)
    msg = send(c, "POST", "/api/rag/messages", {"question": "Tỷ số?"}).json()
    try:
        deadline = time.monotonic() + 10
        status = msg["status"]
        while status in C.PENDING and time.monotonic() < deadline:
            time.sleep(0.05)
            status = c.get(f"/api/rag/messages/{msg['message_id']}").json()["status"]
        assert status == "answered" and len(fake.calls) == 1
    finally:
        app.state.rag_worker.stop()


# ---------------------------------------------------------------------- dừng hỏi (migration 009)
def test_dung_luot_dang_xep_hang(env, pg_conn):
    app, fake = env
    c = client(app, pg_conn)
    msg = send(c, "POST", "/api/rag/messages", {"question": "Tỷ số?"}).json()
    r = send(c, "POST", f"/api/rag/messages/{msg['message_id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert run_worker(app) == 0 and fake.calls == []                                 # worker không nhận lượt đã dừng
    conv = c.get(f"/api/rag/conversations/{msg['conversation_id']}").json()["conversation"]
    assert conv["last_status"] == "cancelled"
    assert send(c, "POST", "/api/rag/messages", {"question": "Hỏi tiếp?"}).status_code == 202   # không còn bị 409


def test_dung_luot_dang_chay_giai_phong_hang_doi_va_bo_ket_qua(env, pg_conn):
    """Pipeline đang chờ mô hình (bị chặn) → người dùng dừng → worker bỏ luồng, chạy ngay câu kế tiếp;
    khi lời gọi cũ trả về muộn, kết quả của nó không ghi đè trạng thái `cancelled`."""
    import threading

    app, _ = env
    release, started = threading.Event(), threading.Event()

    class Slow:
        def __init__(self):
            self.n = 0

        def ask(self, question, **kw):
            self.n += 1
            if question == "Chậm?":
                started.set()
                release.wait(10)
            return answer()

        def close(self):
            pass

    slow = Slow()
    app.state.rag_pipeline_factory = lambda conn: slow
    app.state.rag_cancel_poll = 0.05
    c = client(app, pg_conn)
    first = send(c, "POST", "/api/rag/messages", {"question": "Chậm?"}).json()
    w = app.state.rag_worker
    runner = threading.Thread(target=w.run_once)
    runner.start()
    assert started.wait(5)
    assert c.get(f"/api/rag/messages/{first['message_id']}").json()["status"] == "running"
    r = send(c, "POST", f"/api/rag/messages/{first['message_id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    runner.join(5)
    assert not runner.is_alive()                                                     # worker không còn kẹt
    second = send(c, "POST", "/api/rag/messages", {"question": "Nhanh?", "conversation_id": first["conversation_id"]})
    assert second.status_code == 202
    assert w.run_once() is True
    assert c.get(f"/api/rag/messages/{second.json()['message_id']}").json()["status"] == "answered"
    release.set()                                                                     # lời gọi cũ trả về muộn
    for t in list(w._abandoned):
        t.join(5)
    late = c.get(f"/api/rag/messages/{first['message_id']}").json()
    assert late["status"] == "cancelled" and late["answer"] is None
    C.finish(pg_conn, first["message_id"], answer())                                  # ghi muộn cũng bị chặn
    assert c.get(f"/api/rag/messages/{first['message_id']}").json()["status"] == "cancelled"


def test_khong_dung_duoc_luot_da_xong_hoac_cua_nguoi_khac(env, pg_conn):
    app, _ = env
    a = client(app, pg_conn, "a@example.com")
    b = client(app, pg_conn, "b@example.com")
    msg = send(a, "POST", "/api/rag/messages", {"question": "Của A?"}).json()
    assert send(b, "POST", f"/api/rag/messages/{msg['message_id']}/cancel").status_code == 404
    assert a.post(f"/api/rag/messages/{msg['message_id']}/cancel").status_code == 403   # thiếu CSRF
    run_worker(app)
    r = send(a, "POST", f"/api/rag/messages/{msg['message_id']}/cancel")
    assert r.status_code == 409 and "đã có kết quả" in r.json()["detail"]


def test_loi_dang_dong_bo_chi_muc_co_cau_bao_rieng():
    msg = C.error_for(RAGUnavailableError('index_sync'))
    assert msg != C.GENERIC_ERROR and 'đồng bộ' in msg
    assert C.error_for(RAGUnavailableError('index_lock')) == C.PHASE_MESSAGES['snapshot']


# ---------------------------------------------------------------- hồ sơ cá nhân hoá (migration 010)
def test_ho_so_xem_sua_xac_nhan_xoa(env, pg_conn):
    app, _ = env
    c = client(app, pg_conn)
    assert c.get("/api/rag/profile").json()["persona"] is None
    r = send(c, "PUT", "/api/rag/profile", {"address_user": "chị Lan", "tone": "trang_trong",
                                             "interests": ["Kinh tế"]})
    assert r.status_code == 200 and r.json()["address_user"] == "chị Lan" and r.json()["interests"] == ["Kinh tế"]
    assert send(c, "PUT", "/api/rag/profile", {"interests": ["Chứng khoán ảo"]}).status_code == 422
    uid = pg_conn.execute("SELECT user_id FROM users WHERE email = 'ban@example.com'").fetchone()[0]
    pg_conn.execute("UPDATE rag_user_profiles SET pending = '{\"persona\": \"ke_toan\"}' WHERE user_id = %s", (uid,))
    assert c.get("/api/rag/profile").json()["pending"] == {"persona": "ke_toan"}
    r = send(c, "POST", "/api/rag/profile/confirm", {"accept": True})
    assert r.json()["persona"] == "ke_toan" and r.json()["pending"] == {}
    assert send(c, "DELETE", "/api/rag/profile").status_code == 204
    assert c.get("/api/rag/profile").json()["address_user"] is None


def test_ho_so_can_dang_nhap(env):
    app, _ = env
    assert TestClient(app).get("/api/rag/profile").status_code == 401


def test_luot_chat_tool_calling_luu_nguon_du_lieu_va_smalltalk(env, pg_conn):
    app, fake = env
    c = client(app, pg_conn)
    fake.behaviour = {"status": "answered", "answer": "Có 37 bài. [1]", "retrieval_mode": None, "degraded": False,
                      "snapshot": {}, "trace": {}, "sources": [
                          {"citation_id": 1, "kind": "data", "tool": "count_articles", "title": "Đếm bài trong kho",
                           "text": "Kho dữ liệu có 37 bài báo.", "quotes": ["có 37 bài báo"]}]}
    msg = send(c, "POST", "/api/rag/messages", {"question": "Có bao nhiêu bài?"}).json()
    run_worker(app)
    body = c.get(f"/api/rag/messages/{msg['message_id']}").json()
    assert body["status"] == "answered" and body["sources"][0]["kind"] == "data"
    assert body["sources"][0]["url"] is None and body["sources"][0]["event_id"] is None
    fake.behaviour = {"status": "smalltalk", "answer": "Chào bạn!", "sources": [], "retrieval_mode": None,
                      "degraded": False, "snapshot": {}, "trace": {}}
    msg = send(c, "POST", "/api/rag/messages", {"question": "Xin chào", "conversation_id": msg["conversation_id"]}).json()
    run_worker(app)
    assert c.get(f"/api/rag/messages/{msg['message_id']}").json()["status"] == "smalltalk"
