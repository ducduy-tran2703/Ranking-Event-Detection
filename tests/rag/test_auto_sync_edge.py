"""Kiểm thử độc lập bộ lập lịch `eventrank.rag.auto_sync`: trường hợp biên của `decide`, luồng nền, nút "Đồng bộ ngay".

Không DB, không sync thật (`sync_fn` giả). Test đánh dấu "LỖI THẬT" đang FAIL với code hiện tại — để cho agent code sửa.
"""
import threading
import time
from datetime import timedelta, timezone

from test_auto_sync import CFG, T0, D, S, _Conn, _sched, env, run  # noqa: F401 -- env là fixture

from eventrank.rag import auto_sync as A


# ---------------------------------------------------------------------- decide (hàm thuần)
def test_after_crawl_lan_truoc_loi_va_co_luot_cao_moi_thi_chay():
    d = D(S(), last_run=run("failed", minute=5), last_crawl_at=T0 + timedelta(minutes=20))
    assert d.run and d.reason == "after_crawl"


def test_after_crawl_lan_truoc_loi_khong_cao_moi_thi_khong_chay_lai_ngay():
    """Lỗi (Modal tắt…) không được thành vòng chạy liên tục: đợi lượt cào kế tiếp.

    Chỉnh theo yêu cầu L2 của điều phối (thử lại lượt lỗi có giãn chờ 5 → 15 → 45 phút, tối đa 3 lần mỗi đợt): "không
    chạy lại ngay" nghĩa là chưa hết thời gian giãn chờ, hoặc đã hết lượt thử của đợt thì đợi lượt cào kế tiếp."""
    d = D(S(), last_run=run("failed", minute=29, limited=True), last_crawl_at=T0)
    assert not d.run and d.reason == "retry_wait"
    wave = [{**run("failed", minute=m), "reason": "retry_failed"} for m in (25, 20, 10)] + [run("failed", minute=5)]
    d = D(S(), last_run=wave[0], history=wave, last_crawl_at=T0)
    assert not d.run and d.reason == "retries_exhausted"


def test_lo_bi_cat_nhung_dang_cao_thi_doi_cao_xong():
    d = D(S(), last_run=run("ok", minute=5, limited=True), crawl_busy=True)
    assert not d.run and d.reason == "crawl_running"


def test_lan_truoc_van_running_tien_trinh_chet_khong_coi_la_lo_bi_cat():
    d = D(S(), last_run=run("running", minute=5, limited=True), last_crawl_at=T0)
    assert not d.run and d.reason == "waiting_crawl"


def test_moc_gio_khac_mui_van_so_sanh_dung():
    """Postgres trả timestamptz theo múi phiên (vd +07:00): so sánh với mốc UTC phải theo thời điểm tuyệt đối."""
    vn = timezone(timedelta(hours=7))
    crawl_vn = (T0 + timedelta(minutes=1)).astimezone(vn)
    assert D(S(), last_crawl_at=crawl_vn).reason == "after_crawl"
    assert D(S(), last_crawl_at=(T0 - timedelta(minutes=1)).astimezone(vn)).reason == "waiting_crawl"


def test_interval_lan_truoc_loi_van_doi_du_chu_ky():
    """Chỉnh theo yêu cầu L2: lượt lỗi được thử lại có giãn chờ trong chu kỳ; HẾT lượt thử thì đợi đủ chu kỳ (tính từ
    lượt mở đợt)."""
    s = S(mode="interval", interval_minutes=60)
    wave = [{**run("failed", minute=m), "reason": "retry_failed"} for m in (50, 20, 5)] + [run("failed", minute=0)]
    assert D(s, last_run=wave[0], history=wave, now=T0 + timedelta(minutes=59)).reason == "retries_exhausted"
    assert D(s, last_run=wave[0], history=wave, now=T0 + timedelta(minutes=60)).reason == "interval_due"
    assert D(s, last_run=run("failed", minute=0), now=T0 + timedelta(minutes=3)).reason == "retry_wait"


def test_tat_nhung_bam_dong_bo_ngay_van_chay_ke_ca_khong_co_bai_cho():
    assert D(S(mode="off"), pending=0, force=True).reason == "forced"


def test_crawl_busy_chi_hoi_khi_can():
    called = []

    def busy():
        called.append(1)
        return False
    D(S(), pending=0, crawl_busy=busy)
    D(S(mode="interval"), crawl_busy=busy)
    assert called == []


# ---------------------------------------------------------------------- luồng nền
class _NotLeaderConn(_Conn):
    def execute(self, sql, params=None):
        if "pg_try_advisory_lock" in sql:
            from types import SimpleNamespace
            return SimpleNamespace(fetchone=lambda: (False,))
        return super().execute(sql, params)


def test_khong_giu_khoa_thi_khong_tu_chay(env):  # noqa: F811
    s = A.AutoSync(connect=_NotLeaderConn, load_config=lambda: CFG, sync_fn=lambda *a, **k: {"limited": False},
                   mem_fn=lambda: 10_000, poll_seconds=30)
    s.start()
    try:
        deadline = time.monotonic() + 3
        while s.last_decision is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert s.last_decision.reason == "other_scheduler" and s.leader is False
    finally:
        s.stop()


def test_dong_bo_ngay_o_tien_trinh_khong_giu_khoa_khong_bi_nuot(env):  # noqa: F811
    """LỖI THẬT (đang FAIL). Chạy 2 tiến trình API: tiến trình B không giữ khoá bộ lập lịch nhưng luồng nền vẫn chạy
    (`running = True`) → `trigger_now()` chỉ bật cờ `_force`; vòng lặp `_take_force()` lấy cờ rồi bỏ đi vì không phải
    leader. API vẫn trả "accepted" mà không có lượt đồng bộ nào chạy."""
    ran = threading.Event()
    s = A.AutoSync(connect=_NotLeaderConn, load_config=lambda: CFG, mem_fn=lambda: 10_000, poll_seconds=30,
                   sync_fn=lambda *a, **k: ran.set() or {"limited": False})
    s.start()
    try:
        deadline = time.monotonic() + 3
        while s.last_decision is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert s.trigger_now() is True
        assert ran.wait(2), "trigger_now() trả True nhưng lượt đồng bộ bị nuốt ở tiến trình không giữ khoá"
    finally:
        s.stop()


def test_stop_khong_treo_khi_dang_co_luot_sync_dai(env):  # noqa: F811
    """Tắt API trong lúc đang sync (BamiBERT vài phút): `stop()` phải trả về trong thời gian chờ, không treo lifespan."""
    started, release = threading.Event(), threading.Event()

    def slow_sync(conn, cfg, **kw):
        started.set()
        release.wait(10)
        return {"limited": False}
    s = _sched(slow_sync, poll_seconds=0.01)
    s.start()
    try:
        assert started.wait(3)
        t = time.monotonic()
        s.stop(timeout=0.3)
        assert time.monotonic() - t < 1.0
    finally:
        release.set()
        if s._thread is not None:
            s._thread.join(3)
    assert not s.running and A.state_snapshot()["running"] is False


def test_lo_bi_cat_lien_tuc_chay_moi_vong_nhung_dung_khi_het_bai(env):  # noqa: F811
    """Còn bài chờ và lượt trước `limited` → chạy mỗi vòng; hết bài chờ → dừng (không đốt GPU khi không còn việc)."""
    calls = []

    def fake_sync(conn, cfg, **kw):
        calls.append(1)
        env["last"] = [run("ok", minute=40, limited=len(calls) < 3)]
        if len(calls) >= 3:
            env["pending"] = 0
        return {"limited": len(calls) < 3}
    env["last"] = [run("ok", minute=5, limited=True)]
    s = _sched(fake_sync, poll_seconds=0.01)
    s.start()
    try:
        deadline = time.monotonic() + 3
        while len(calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.2)
    finally:
        s.stop()
    assert len(calls) == 3 and s.last_decision.reason == "no_pending"


def test_ngoai_le_trong_tick_sau_begin_run_khong_ket_running(env, monkeypatch):  # noqa: F811
    """ĐỘ BỀN (đang FAIL, mức nhẹ). `AutoSync._run` gọi `begin_run` rồi `_log_start`/`_log_end` NGOÀI try/finally; hai hàm
    này chỉ bắt psycopg.Error. Lỗi khác (vd. stats không tuần tự hoá được JSON ở `_log_end`) để SYNC_STATE kẹt
    running=True → mọi lượt sau, cả `/api/rag/sync` tay, báo already_running tới khi khởi động lại API."""
    def bad_log_start(*a, **k):
        raise TypeError("lỗi bất ngờ")
    monkeypatch.setattr(A.AutoSync, "_log_start", staticmethod(bad_log_start))
    s = _sched(lambda *a, **k: {"limited": False})
    try:
        s.tick(_Conn())
    except TypeError:
        pass
    assert A.state_snapshot()["running"] is False, "SYNC_STATE kẹt running=True sau ngoại lệ"
