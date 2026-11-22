"""Bộ lập lịch đồng bộ RAG tự động (`eventrank.rag.auto_sync`): quyết định chạy, chặn RAM, ghi worker_runs, không chết.

Không chạy sync thật: `sync_fn` giả. Phần `db` chạy trên DB tạm (TEST_DATABASE_URL).
"""
import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from eventrank.common import settings_store
from eventrank.rag import auto_sync as A

T0 = datetime(2026, 11, 22, 8, 0, tzinfo=UTC)
CFG = {"index_version": "rag_v1", "chunking": {"max_units": 40, "overlap_units": 8}}


def S(**kw):
    return A.RagSyncSettings(**kw)


def run(status="ok", minute=0, **stats):
    return {"run_id": 1, "status": status, "started_at": T0 + timedelta(minutes=minute), "stats": stats}


def D(settings, **kw):
    base = {"now": T0 + timedelta(minutes=30), "pending": 5, "last_run": None, "last_crawl_at": None,
            "crawl_busy": False, "started_at": T0}
    return A.decide(settings, **{**base, **kw})


# ---------------------------------------------------------------------- decide
def test_mac_dinh_la_cung_nhip_cao_bao():
    s = A.RagSyncSettings()
    assert (s.mode, s.interval_minutes, s.max_articles_per_run, s.min_mem_available_mb) == ("after_crawl", 60, 200, 1500)


@pytest.mark.parametrize("bad", [{"mode": "x"}, {"interval_minutes": 45}, {"max_articles_per_run": 5},
                                 {"max_articles_per_run": 1001}, {"thua": 1}])
def test_cai_dat_sai_bi_tu_choi(bad):
    with pytest.raises(ValueError):
        A.RagSyncSettings(**bad)


def test_tat_thi_khong_chay_ke_ca_co_bai_cho():
    assert D(S(mode="off"), last_crawl_at=T0 + timedelta(minutes=10)).reason == "off"


def test_khong_co_bai_cho_thi_khong_chay():
    assert D(S(), pending=0, last_crawl_at=T0 + timedelta(minutes=10)).reason == "no_pending"


def test_chua_tung_sync_moc_la_luc_khoi_dong_khong_chay_ngay():
    # Lượt cào xong TRƯỚC lúc bật API → không tự đốt GPU khi vừa khởi động.
    assert D(S(), last_crawl_at=T0 - timedelta(minutes=5)).reason == "waiting_crawl"
    assert D(S(), last_crawl_at=T0 + timedelta(minutes=5)) == A.Decision(True, "after_crawl")


def test_sau_cao_bao_chi_chay_khi_co_luot_cao_moi_hon_lan_sync_truoc():
    last = run(minute=20)
    assert D(S(), last_run=last, last_crawl_at=T0 + timedelta(minutes=10)).reason == "waiting_crawl"
    assert D(S(), last_run=last, last_crawl_at=T0 + timedelta(minutes=25)).run


def test_dang_cao_thi_cho_va_chi_hoi_crawler_khi_can():
    calls = []

    def busy():
        calls.append(1)
        return True
    assert D(S(), last_crawl_at=T0 + timedelta(minutes=5), crawl_busy=busy).reason == "crawl_running"
    assert D(S(), pending=0, crawl_busy=busy).reason == "no_pending" and len(calls) == 1


def test_lo_truoc_bi_cat_boi_max_articles_thi_chay_tiep_luon():
    last = run(minute=29, limited=True)
    assert D(S(), last_run=last).reason == "continue_batch"
    assert D(S(mode="interval"), last_run=last).reason == "continue_batch"
    # Lượt lỗi không phải "lô bị cắt": không chạy tiếp ngay, chỉ thử lại sau thời gian giãn chờ (5 phút cho lần 1).
    assert D(S(), last_run=run(status="failed", minute=29, limited=True)).reason == "retry_wait"


def test_theo_chu_ky():
    s = S(mode="interval", interval_minutes=60)
    assert D(s, now=T0 + timedelta(minutes=59)).reason == "waiting_interval"
    assert D(s, now=T0 + timedelta(minutes=60)).reason == "interval_due"
    assert D(s, now=T0 + timedelta(minutes=100), last_run=run(minute=50)).reason == "waiting_interval"


def test_bam_dong_bo_ngay_bo_qua_dieu_kien():
    assert D(S(mode="off"), pending=0, force=True) == A.Decision(True, "forced")


# ---------------------------------------------------------------------- tick với kết nối giả
class _Conn:
    def __init__(self):
        self.runs = {}
        self.closed = False

    def execute(self, sql, params=None):
        if sql.startswith("SELECT now()"):
            return SimpleNamespace(fetchone=lambda: (T0 + timedelta(minutes=30),))
        if sql.startswith("INSERT INTO worker_runs"):
            rid = len(self.runs) + 1
            self.runs[rid] = {"versions": params[0].obj, "status": "running"}
            return SimpleNamespace(fetchone=lambda: (rid,))
        if sql.startswith("UPDATE worker_runs"):
            status, stats, error, rid = params
            self.runs[rid].update(status=status, stats=stats.obj, error=error)
            return SimpleNamespace(rowcount=1)
        if "pg_try_advisory_lock" in sql:
            return SimpleNamespace(fetchone=lambda: (True,))
        raise AssertionError(sql)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def env(monkeypatch):
    state = {"settings": S(), "pending": 5, "last": [], "crawl_at": T0 + timedelta(minutes=10), "busy": False}
    monkeypatch.setattr(A.settings_store, "available", lambda conn: True)
    monkeypatch.setattr(A, "load_settings", lambda conn: settings_store.Stored(state["settings"]))
    monkeypatch.setattr(A, "pending_count", lambda conn, cfg: state["pending"])
    monkeypatch.setattr(A, "recent_runs", lambda conn, limit=5: state["last"])
    monkeypatch.setattr(A, "last_crawl_finished_at", lambda conn: state["crawl_at"])
    monkeypatch.setattr(A, "crawl_in_progress", lambda conn: state["busy"])
    with A.SYNC_LOCK:
        A.SYNC_STATE.update(running=False, last_result=None, last_error=None, trigger=None)
    yield state
    with A.SYNC_LOCK:
        A.SYNC_STATE.update(running=False, last_result=None, last_error=None, trigger=None)


def _sched(sync_fn, mem=10_000, **kw):
    s = A.AutoSync(connect=_Conn, load_config=lambda: CFG, ner_factory=lambda cfg: "NER", sync_fn=sync_fn,
                   mem_fn=lambda: mem, **kw)
    s.started_at = T0
    return s


def test_tick_chay_ghi_worker_runs_ok_va_dung_ner_chung(env):
    seen = {}

    def fake_sync(conn, cfg, **kw):
        seen.update(kw)
        return {"ner_articles": 3, "limited": False}
    conn = _Conn()
    d = _sched(fake_sync).tick(conn)
    assert d == A.Decision(True, "ok")
    assert seen == {"ner_predictor": "NER", "max_articles": 200}
    (row,) = conn.runs.values()
    assert row["status"] == "ok" and row["stats"]["ner_articles"] == 3
    assert row["versions"]["trigger"] == "auto" and row["versions"]["reason"] == "after_crawl"
    assert A.state_snapshot()["running"] is False and A.state_snapshot()["last_result"]["ner_articles"] == 3


def test_tick_loi_ghi_failed_loi_da_lam_sach(env):
    import psycopg

    def boom(conn, cfg, **kw):
        raise psycopg.OperationalError('password authentication failed for user "eventrank" host=bi-mat')
    conn = _Conn()
    d = _sched(boom).tick(conn)
    assert d.reason == "failed" and d.error == "OperationalError"
    (row,) = conn.runs.values()
    assert row["status"] == "failed" and "bi-mat" not in row["error"]
    assert A.state_snapshot()["last_error"] == "OperationalError"


def test_ram_thap_thi_bo_qua_khong_goi_sync(env):
    d = _sched(lambda *a, **k: pytest.fail("không được chạy"), mem=900).tick(_Conn())
    assert d.reason == "low_memory"


def test_dang_co_luot_sync_tay_thi_bo_qua(env):
    assert A.begin_run("manual")
    d = _sched(lambda *a, **k: pytest.fail("không được chạy")).tick(_Conn())
    assert d.reason == "already_running"


def test_chua_ap_migration_011_thi_khong_tu_chay(env, monkeypatch):
    monkeypatch.setattr(A.settings_store, "available", lambda conn: False)
    assert _sched(lambda *a, **k: pytest.fail("x")).tick(_Conn()).reason == "missing_migration"


def test_luong_nen_khong_chet_khi_loi_va_gian_thoi_gian_cho(env):
    calls = []

    def broken_connect():
        calls.append(time.monotonic())
        raise RuntimeError("Postgres tắt")
    s = A.AutoSync(connect=broken_connect, load_config=lambda: CFG, poll_seconds=0.01)
    s.start()
    deadline = time.monotonic() + 3
    while len(calls) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert s.running and s.consecutive_failures >= 2 and s.last_decision.reason == "failed"
    s.stop()
    assert not s.running


def test_dong_bo_ngay_khi_luong_dang_chay_danh_thuc_va_bo_qua_che_do(env):
    env["settings"], env["pending"] = S(mode="off"), 0
    ran = threading.Event()

    def fake_sync(conn, cfg, **kw):
        ran.set()
        return {"limited": False}
    s = _sched(fake_sync, poll_seconds=30)
    s.start()
    try:
        deadline = time.monotonic() + 3
        while s.last_decision is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert s.last_decision.reason == "off" and not ran.is_set()
        assert s.trigger_now()
        assert ran.wait(3)
    finally:
        s.stop()


def test_dong_bo_ngay_khi_bo_lap_lich_tat_chay_luong_rieng(env):
    ran = threading.Event()
    s = _sched(lambda conn, cfg, **kw: ran.set() or {"limited": False})
    assert not s.running and s.trigger_now()
    assert ran.wait(3)


def test_doc_memavailable(tmp_path):
    p = tmp_path / "meminfo"
    p.write_text("MemTotal:       7000000 kB\nMemAvailable:    2048000 kB\n", encoding="ascii")
    assert A.mem_available_mb(p) == 2000
    assert A.mem_available_mb(tmp_path / "khong-co") is None


def test_cong_tac_moi_truong(monkeypatch):
    monkeypatch.setenv("RAG_AUTO_SYNC", "0")
    assert A.enabled_from_env() is False
    monkeypatch.setenv("RAG_AUTO_SYNC", "1")
    assert A.enabled_from_env() is True


# ---------------------------------------------------------------------- Postgres tạm
def test_db_sau_cao_bao_ghi_rag_sync_va_lan_sau_cho_luot_cao_moi(pg_conn, monkeypatch):
    c = pg_conn
    monkeypatch.setattr(A, "pending_count", lambda conn, cfg: 7)
    c.execute("INSERT INTO sources (source, display_name) VALUES ('tuoitre', 'Tuổi Trẻ')")
    s = A.AutoSync(connect=lambda: None, load_config=lambda: CFG, sync_fn=lambda conn, cfg, **kw: {"limited": False},
                   mem_fn=lambda: None)
    s.started_at = c.execute("SELECT now() - interval '1 hour'").fetchone()[0]
    with A.SYNC_LOCK:
        A.SYNC_STATE["running"] = False
    assert s.tick(c).reason == "waiting_crawl"
    c.execute("INSERT INTO crawl_runs (source, crawler, started_at, status) VALUES ('tuoitre', 'x', now(), 'running')")
    c.execute("INSERT INTO crawl_runs (source, crawler, started_at, finished_at, status) "
              "VALUES ('tuoitre', 'import_jsonl', now(), now(), 'ok')")
    assert s.tick(c).reason == "crawl_running"
    c.execute("UPDATE crawl_runs SET status = 'ok', finished_at = now() WHERE status = 'running'")
    assert s.tick(c) == A.Decision(True, "ok")
    runs = A.recent_runs(c)
    assert len(runs) == 1 and runs[0]["status"] == "ok" and runs[0]["trigger"] == "auto"
    assert s.tick(c).reason == "waiting_crawl"           # không có lượt cào mới hơn lần sync vừa rồi
    A.save_settings(c, S(mode="off"))
    assert s.tick(c).reason == "off"                       # đọc lại cài đặt mỗi vòng


# ---------------------------------------------------------------------- thử lại lượt lỗi có giãn chờ, có trần
def _fail(minute, reason=None):
    return {**run("failed", minute=minute), "reason": reason}


@pytest.mark.parametrize("mode", ["after_crawl", "interval"])
def test_luot_loi_thu_lai_5_15_45_phut_roi_thoi(mode):
    s = S(mode=mode, interval_minutes=1440)
    wave = [_fail(0, "after_crawl")]
    at = lambda m: T0 + timedelta(minutes=m)
    assert D(s, history=wave, last_run=wave[0], now=at(4)).reason == "retry_wait"
    assert D(s, history=wave, last_run=wave[0], now=at(5)) == A.Decision(True, "retry_failed")
    wave = [_fail(5, "retry_failed")] + wave
    assert D(s, history=wave, last_run=wave[0], now=at(19)).reason == "retry_wait"
    assert D(s, history=wave, last_run=wave[0], now=at(20)).run
    wave = [_fail(20, "retry_failed")] + wave
    assert D(s, history=wave, last_run=wave[0], now=at(64)).reason == "retry_wait"
    assert D(s, history=wave, last_run=wave[0], now=at(65)).run
    wave = [_fail(65, "retry_failed")] + wave                       # lỗi lần 4: hết lượt thử của đợt này
    assert D(s, history=wave, last_run=wave[0], now=at(600)).reason == "retries_exhausted"


def test_het_luot_thu_thi_doi_dot_sau():
    wave = [_fail(65, "retry_failed"), _fail(20, "retry_failed"), _fail(5, "retry_failed"), _fail(0, "after_crawl")]
    # after_crawl: lượt cào mới sau lần thử cuối mở đợt mới
    assert D(S(), history=wave, last_run=wave[0], now=T0 + timedelta(minutes=90),
             last_crawl_at=T0 + timedelta(minutes=80)).reason == "after_crawl"
    # interval: tính chu kỳ từ lượt MỞ ĐỢT (phút 0), không từ lần thử cuối
    s = S(mode="interval", interval_minutes=120)
    assert D(s, history=wave, last_run=wave[0], now=T0 + timedelta(minutes=119)).reason == "retries_exhausted"
    assert D(s, history=wave, last_run=wave[0], now=T0 + timedelta(minutes=120)).reason == "interval_due"


def test_dot_tinh_tu_luot_mo_dot_luot_ok_truoc_do_khong_tinh():
    hist = [_fail(30, "after_crawl"), run("ok", minute=0), _fail(-10), _fail(-20)]
    assert A.failed_wave(hist) == hist[:1]
    assert A.failed_wave([run("ok", minute=0)] + hist) == []


def test_db_dong_luot_ket_running_khi_khoi_dong(pg_conn):
    pg_conn.execute("INSERT INTO worker_runs (step, started_at) VALUES ('rag_sync', now() - interval '1 hour')")
    pg_conn.execute("INSERT INTO worker_runs (step) VALUES ('rag_sync')")          # lượt của tiến trình hiện tại
    before = pg_conn.execute("SELECT now() - interval '1 minute'").fetchone()[0]
    assert A.recover_stale_runs(pg_conn, before) == 1
    runs = A.recent_runs(pg_conn)
    assert [r["status"] for r in runs] == ["running", "failed"] and runs[1]["error"] == A.STALE_RUN_ERROR
