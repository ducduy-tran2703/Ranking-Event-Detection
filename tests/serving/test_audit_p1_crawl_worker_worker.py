"""Kiểm tra hệ thống (P1-crawl-worker): worker sự kiện đọc system_settings, ghi worker_runs, chịu lỗi giữa vòng.

`xfail(strict=True)` = lỗi đã xác nhận (AUDIT-P1-crawl-worker-<số>). Test cần Postgres dùng fixture pg_url/pg_conn
(DB tạm, tự xoá).
"""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import psycopg
import pytest
from psycopg.types.json import Jsonb

from eventrank.common import db, settings_store
from eventrank.ingest import clock, sink
from eventrank.ingest.contract import article_id_for, validate_article
from eventrank.ingest.sources import load_sources
from eventrank.serving import worker as W
from eventrank.serving import worker_settings as WS

NOW = datetime(2026, 11, 9, 10, 20, tzinfo=UTC)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _loop_cfg(seconds=60):
    return SimpleNamespace(worker={"interval_seconds": seconds})


# --------------------------------------------------------------------------- AUDIT-7: mất kết nối DB
def test_mat_ket_noi_db_thi_worker_ket_noi_lai_hoac_thoat(pg_url):
    conn = db.connect(pg_url)
    try:
        db.migrate(conn)
        pid = conn.info.backend_pid
        with psycopg.connect(pg_url, autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
        seen = []

        def run(c, _cfg):
            seen.append(c.closed)
            c.execute("SELECT 1")
            return {}

        t = _Clock()
        try:
            W.loop_forever(conn, _loop_cfg(), run=run, sleep=t.sleep, clock=t, max_rounds=4, logf=lambda _m: None)
        except psycopg.OperationalError:
            return                                   # thoát để trình giám sát khởi động lại: chấp nhận được
        # Không thoát thì phải chạy lại được trên một kết nối sống.
        assert any(closed is False for closed in seen[1:]), f"4 vòng đều trên kết nối đã đóng: {seen}"
    finally:
        conn.close()


# --------------------------------------------------------------------------- AUDIT-8: worker_runs treo 'running'
NOI_DUNG = "Nội dung bài báo phục vụ kiểm thử worker đủ dài. " * 15


def _add(conn, n, title, minutes=60):
    url = f"https://tuoitre.vn/bai-audit-{n}.htm"
    raw = {"article_id": article_id_for(url), "url": url, "source": "tuoitre", "category": "Thời sự",
           "title": title, "sapo": "Sapo đủ dài.", "author": "A",
           "published_at": (NOW - timedelta(minutes=minutes)).isoformat(), "content_text": NOI_DUNG}
    res = validate_article(raw, known_sources=sink.known_sources(conn), now=datetime(2030, 1, 1, tzinfo=UTC))
    assert sink.upsert_articles(conn, [res], "test").inserted == 1


@pytest.fixture
def wcfg(tmp_path):
    return W.WorkerConfig(
        cluster={"algo_version": "v1", "model_version": "m1", "model": "khong-co", "prep": "raw", "algo": "agglo",
                 "threshold": 0.83, "window_hours": 48},
        naming={**W.naming.DEFAULTS, "naming_version": "n1", "model": "khong-co", "cache_dir": str(tmp_path)},
        trending={**W.trending.DEFAULTS, "trend_version": "t2"},
        hide_window=W.ES.parse_hide_window(None))


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
def test_bi_ngat_giua_buoc_thi_worker_runs_khong_treo_running(pg_conn, wcfg, exc):
    sink.sync_sources(pg_conn, load_sources())
    clock.set_replay(pg_conn, NOW, 60)
    _add(pg_conn, 1, "Bão số 13 đổ bộ")

    def interrupted(_texts):
        raise exc()

    with pytest.raises(exc):
        W.run_cycle(pg_conn, wcfg, encoder=interrupted, logf=lambda _m: None)
    status = pg_conn.execute("SELECT status FROM worker_runs WHERE step = 'embed'").fetchone()[0]
    assert status != "running"


def test_khoi_dong_worker_don_dong_running_cu_cua_worker_khong_dung_rag_sync(pg_url, pg_conn, monkeypatch):
    """AUDIT-P1-crawl-worker-8: tiến trình bị giết cứng (kill -9, mất điện) thì _step không kịp ghi gì; lần khởi động sau
    (đã giữ advisory lock nên chắc chắn không còn worker nào khác) dọn các dòng 'running' của bước worker."""
    for step in ("embed", "recluster", "name", "trend", "rag_sync", "import"):
        pg_conn.execute("INSERT INTO worker_runs (step) VALUES (%s)", (step,))
    monkeypatch.setenv("AUDIT_WORKER_DB", pg_url)
    monkeypatch.setattr(W, "run_cycle", lambda *_a, **_k: {})
    assert W.main(["--once", "--db-env", "AUDIT_WORKER_DB"]) == 0
    rows = dict(pg_conn.execute("SELECT step, status FROM worker_runs").fetchall())
    assert rows == {"embed": "failed", "recluster": "failed", "name": "failed", "trend": "failed",
                    "rag_sync": "running", "import": "running"}
    errors = {r[0] for r in pg_conn.execute("SELECT error FROM worker_runs WHERE status = 'failed'")}
    assert errors == {"worker khởi động lại"}
    assert pg_conn.execute("SELECT count(*) FROM worker_runs WHERE status = 'failed' AND finished_at IS NULL"
                           ).fetchone()[0] == 0


def test_mat_ket_noi_db_thi_main_thoat_ma_loi_rieng(pg_url, pg_conn, monkeypatch, capsys):
    """AUDIT-P1-crawl-worker-7: loop_forever ném lỗi kết nối ra ngoài → main in lỗi ngắn, trả mã 2 (không traceback)."""
    monkeypatch.setenv("AUDIT_WORKER_DB", pg_url)

    def lost(*_a, **_k):
        raise psycopg.OperationalError("server closed the connection unexpectedly")

    monkeypatch.setattr(W, "loop_forever", lost)
    assert W.main(["--loop", "--db-env", "AUDIT_WORKER_DB"]) == 2
    assert "mất kết nối Postgres" in capsys.readouterr().err


def test_loi_thuong_giua_buoc_duoc_ghi_failed_va_vong_sau_chay_lai(pg_conn, wcfg):
    sink.sync_sources(pg_conn, load_sources())
    clock.set_replay(pg_conn, NOW, 60)
    _add(pg_conn, 1, "Bão số 13 đổ bộ")

    def broken(_texts):
        raise ValueError("vector hỏng")

    with pytest.raises(ValueError):
        W.run_cycle(pg_conn, wcfg, encoder=broken, logf=lambda _m: None)
    assert pg_conn.execute("SELECT status FROM worker_runs").fetchall() == [("failed",)]

    def enc(texts):
        out = np.zeros((len(texts), 4), dtype=np.float32)
        out[:, 0] = 1
        return out

    res = W.run_cycle(pg_conn, wcfg, encoder=enc, generator=lambda xs: ["Tên" for _ in xs], logf=lambda _m: None)
    assert res["assigned"] == 1
    assert pg_conn.execute("SELECT count(*) FROM worker_runs WHERE status = 'running'").fetchone()[0] == 0


# --------------------------------------------------------------------------- AUDIT-9: một trường hỏng bật lại worker
# AUDIT-P1-crawl-worker-9 đã sửa ở settings_store.load (F-api, kiểm từng trường) → bỏ xfail.
@pytest.mark.parametrize("bad", [45, "300", None])
def test_mot_truong_hong_khong_lam_mat_trang_thai_tam_dung(pg_conn, bad):
    pg_conn.execute("INSERT INTO system_settings (key, value) VALUES ('event_worker', %s)",
                    (Jsonb({"enabled": False, "interval_seconds": bad}),))
    stored = WS.load(pg_conn, WS.default_settings(300))
    assert stored.from_db and stored.value.enabled is False


def test_gia_tri_la_nhung_hop_le_theo_pydantic(pg_conn):
    pg_conn.execute("INSERT INTO system_settings (key, value) VALUES ('event_worker', %s)",
                    (Jsonb({"enabled": "false", "interval_seconds": 600, "thua": 1}),))
    s = W.current_settings(pg_conn, _loop_cfg(300))
    assert (s.enabled, s.interval) == (False, 600.0)


def test_value_khong_phai_object_bi_db_tu_choi(pg_conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        pg_conn.execute("INSERT INTO system_settings (key, value) VALUES ('event_worker', '[1]'::jsonb)")


# --------------------------------------------------------------------------- vòng lặp: tạm dừng, lỗi lạ
def _seq(monkeypatch, values):
    it = iter(values)
    last = {"v": values[0]}

    def load(conn, default=None):
        last["v"] = next(it, last["v"])
        return settings_store.Stored(last["v"], from_db=True)

    monkeypatch.setattr(W.WS, "load", load)


def test_tam_dung_giua_vong_chi_co_hieu_luc_tu_vong_sau(monkeypatch):
    """Ghi lại: cài đặt đọc ĐẦU vòng; tắt trong lúc run_cycle đang chạy không ngắt vòng đó (vòng sau mới bỏ)."""
    on = WS.EventWorkerSettings(enabled=True, interval_seconds=60)
    off = WS.EventWorkerSettings(enabled=False, interval_seconds=60)
    _seq(monkeypatch, [on, on, off])
    runs = []
    t = _Clock()
    W.loop_forever(None, _loop_cfg(), run=lambda c, k: runs.append(1) or {}, sleep=t.sleep, clock=t,
                   max_rounds=3, logf=lambda _m: None)
    assert len(runs) == 1


@pytest.mark.xfail(strict=True, raises=KeyError,
                   reason="AUDIT-P1-crawl-worker-10: loop_forever chỉ bắt (psycopg.Error, ValueError, RuntimeError, "
                          "OSError); KeyError/TypeError/AssertionError trong một vòng làm chết hẳn `make worker`")
def test_loi_lap_trinh_trong_mot_vong_khong_giet_vong_lap(monkeypatch):
    on = WS.EventWorkerSettings(enabled=True, interval_seconds=60)
    _seq(monkeypatch, [on])
    calls = []

    def run(c, k):
        calls.append(1)
        if len(calls) == 1:
            raise KeyError("event_id")
        return {}

    t = _Clock()
    W.loop_forever(None, _loop_cfg(), run=run, sleep=t.sleep, clock=t, max_rounds=2, logf=lambda _m: None)
    assert len(calls) == 2


# --------------------------------------------------------------------------- event_id ổn định qua gom lại
A, B, C, D = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)


def _day(_aid):
    return "20261109"


def test_hai_su_kien_gop_thanh_mot_cum_giu_id_su_kien_lon_hon_va_danh_dau_gop():
    prev = {A: "E1", B: "E1", C: "E2"}
    plan = W.reconcile([A, B, C], [0, 0, 0], prev, {"E1": 2, "E2": 1}, _day, lock_min_size=W.NO_LOCK)
    assert plan.new_events == {}
    assert plan.assign == {C: ("E1", "recluster")}
    assert plan.merges == {"E2": "E1"}


def test_tach_cum_phan_lon_giu_id_phan_nho_ra_id_moi():
    prev = {A: "E1", B: "E1", C: "E1"}
    plan = W.reconcile([A, B, C], [0, 0, 1], prev, {"E1": 3}, _day, lock_min_size=W.NO_LOCK)
    assert plan.assign == {C: (f"E20261109-{C[:8]}", "recluster")}
    assert plan.merges == {}


def test_gom_lai_khong_doi_gi_thi_khong_co_ke_hoach():
    prev = {A: "E1", B: "E1", C: "E2", D: "E2"}
    plan = W.reconcile([A, B, C, D], [5, 5, 9, 9], prev, {"E1": 2, "E2": 2}, _day, lock_min_size=W.NO_LOCK)
    assert (plan.assign, plan.new_events, plan.merges) == ({}, {}, {})


def test_nhan_cum_doi_so_khong_doi_event_id():
    prev = {A: "E1", B: "E1"}
    first = W.reconcile([A, B], [0, 0], prev, {"E1": 2}, _day, lock_min_size=W.NO_LOCK)
    second = W.reconcile([A, B], [7, 7], prev, {"E1": 2}, _day, lock_min_size=W.NO_LOCK)
    assert first.assign == second.assign == {}
