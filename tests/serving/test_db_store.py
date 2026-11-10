"""API sự kiện đọc Postgres (`eventrank.serving.db_store.DbEventStore`) phải trả ĐÚNG như bản đọc thư mục run.

Cùng một run tí hon (tests/serving/test_db_import.make_run) → nạp vào DB tạm → so từng phương thức với `EventStore`.
Cần TEST_DATABASE_URL (tự skip khi thiếu).
"""
import math
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.api.event_reload import EventReloader
from apps.api.main import create_app
from eventrank.common import db
from eventrank.serving import db_import, db_store
from eventrank.serving import store as ES
from tests.serving.test_db_import import PUBLIC, SECRET_WORDS, make_run

WINDOW = ES.parse_hide_window(ES.DEFAULT_HIDE_WINDOW)


def same(a, b, path="$"):
    """So sâu. Số thực: DB lưu float4 rồi làm tròn như CSV (van_toc 4 chữ số) → giá trị sát ranh giới làm tròn lệch
    một đơn vị chữ số cuối (gặp trên run v2: 1.1151 / 1.1152) → cho lệch 1e-5 tương đối hoặc 1,5e-4 tuyệt đối."""
    if isinstance(a, float) or isinstance(b, float):
        assert a is not None and b is not None and math.isclose(a, b, rel_tol=1e-5, abs_tol=1.5e-4), f"{path}: {a} != {b}"
    elif isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), f"{path}: khoá {set(a) ^ set(b)}"
        for k in a:
            same(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list | tuple):
        assert len(a) == len(b), f"{path}: dài {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            same(x, y, f"{path}[{i}]")
    else:
        assert a == b, f"{path}: {a!r} != {b!r}"


@pytest.fixture
def stores(pg_conn, tmp_path):
    d, eid, _ = make_run(tmp_path, pg_conn)
    db_import.import_run(pg_conn, d, embeddings=d / "emb.npz", log=lambda s: None)
    return ES.EventStore(d, WINDOW), db_store.DbEventStore(pg_conn, WINDOW), eid


def test_moi_truy_van_giong_ban_doc_file(stores):
    fs, ds, _ = stores
    skip = {"loaded_at", "load_seconds", "ghi_chu"}
    same({k: v for k, v in fs.run_info().items() if k not in skip},
         {k: v for k, v in ds.run_info().items() if k not in skip})
    same(fs.trend_times(), ds.trend_times())
    for k in range(1, fs.n_steps + 1):
        same(fs.trending(k), ds.trending(k), f"trending({k})")
    for kw in [{}, {"min_size": 1}, {"sort": "newest"}, {"sort": "size"}, {"sort": "first_seen", "min_size": 1},
               {"q": "bai"}, {"source": "vnexpress", "min_size": 1}, {"date_from": "2026-09-14", "date_to": "2026-09-15"},
               {"category": "thoi su"}, {"page": 2, "page_size": 1}]:
        same(fs.list_events(**kw), ds.list_events(**kw), f"list_events({kw})")
    for eid in fs.events:
        a, b = fs.get_event(eid), ds.get_event(eid)
        urls = [x.pop("url") for x in b["bai"]]
        assert all(u and u.startswith("https://") for u in urls)            # URL lấy từ bảng articles
        for x in a["bai"]:
            x.pop("url")
        same(a, b, f"get_event({eid})")
    same(fs.stats(), ds.stats())
    same(fs.stats("2026-09-13"), ds.stats("2026-09-13"))
    assert ds.run_info()["ghi_chu"][-1].startswith("Nguồn dữ liệu: Postgres")


def test_cua_so_rong_hon_luc_nap_van_an_ten(stores, pg_conn):
    _, _, eid = stores
    wide = db_store.DbEventStore(pg_conn, ES.parse_hide_window("2026-09-13..2026-09-13"))
    e = wide.events[eid[PUBLIC]]                       # 13/09: không ẩn lúc nạp, nhưng giao cửa sổ của API
    assert (e.ten, e.nguon_ten, e.ten_bi_an) == ("Bài 1", "an", True)


def test_api_doc_db_khong_lo_ten_bi_an(stores, store):
    _, ds, eid = stores
    c = TestClient(create_app(store, ds))
    texts = [c.get(u).text for u in ("/api/runs/current", "/api/trending/times", "/api/events?min_size=1&page_size=100",
                                      "/api/events/stats", *(f"/api/events/{e}" for e in eid.values()))]
    t = c.get("/api/trending/times").json()
    texts += [c.get("/api/trending", params={"t": x}).text for x in (t["dau"], t["cuoi"], t["mac_dinh"])]
    for x in texts:
        for w in SECRET_WORDS:
            assert w not in x.lower()
    assert c.get(f"/api/events/{eid[PUBLIC]}").json()["ten"] == PUBLIC


def test_chon_backend_qua_bien_moi_truong(pg_url, pg_conn, monkeypatch):
    monkeypatch.setattr(db, "load_dotenv", lambda *a, **k: False)     # không nạp .env thật vào os.environ
    monkeypatch.setenv("EVENTS_BACKEND", "khong-co")
    with pytest.raises(ES.RunNotFound, match="EVENTS_BACKEND"):
        db_store.event_store_from_env()
    monkeypatch.setenv("EVENTS_BACKEND", "db")
    monkeypatch.setenv("DATABASE_URL", pg_url)
    with pytest.raises(ES.RunNotFound, match="make db-import-run"):    # DB đã migrate nhưng chưa nạp run
        db_store.event_store_from_env()
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(ES.RunNotFound, match="DATABASE_URL"):
        db_store.event_store_from_env()


def _reloader(store_):
    return EventReloader(SimpleNamespace(state=SimpleNamespace(events=store_)), 60)


def test_nap_lai_khi_worker_co_du_lieu_moi(stores, pg_conn, pg_url, monkeypatch):
    monkeypatch.setattr(db, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("DATABASE_URL", pg_url)
    _, ds, _ = stores
    reloader = _reloader(ds)
    assert reloader.check_once() is False and reloader.app.state.events is ds
    pg_conn.execute("INSERT INTO worker_runs (step, status, finished_at) VALUES ('trend', 'ok', now())")
    assert reloader.check_once() is True
    assert reloader.app.state.events is not ds
    assert reloader.check_once() is False


def test_buoc_loi_khong_kich_hoat_nap_lai(stores, pg_conn, pg_url, monkeypatch):
    monkeypatch.setattr(db, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("DATABASE_URL", pg_url)
    _, ds, _ = stores
    pg_conn.execute("INSERT INTO worker_runs (step, status, finished_at) VALUES ('trend', 'failed', now())")
    assert _reloader(ds).check_once() is False


def test_khong_chay_nap_lai_khi_doc_tu_file(stores):
    fs, _, _ = stores
    assert EventReloader.start_if_db(SimpleNamespace(state=SimpleNamespace(events=fs))) is None


def test_luoi_moc_keo_dai_theo_diem_cua_worker(stores, pg_conn):
    _, ds, _ = stores
    version, last, eid = pg_conn.execute(
        "SELECT trend_version, t, event_id FROM trend_scores ORDER BY t DESC LIMIT 1").fetchone()
    later = last + timedelta(days=30)
    pg_conn.execute("INSERT INTO trend_scores (trend_version, t, event_id, score, rank, n_articles, n_articles_3h, "
                    "n_sources, n_sources_eff, velocity) VALUES (%s, %s, %s, 1, 1, 2, 1, 1, 1, 1)", (version, later, eid))
    fresh = db_store.DbEventStore(pg_conn, WINDOW)
    assert fresh.n_steps > ds.n_steps
    assert fresh.trend_times()["cuoi"][:10] == later.astimezone(ES.VN).isoformat()[:10]
