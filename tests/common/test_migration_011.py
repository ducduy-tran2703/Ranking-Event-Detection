"""Kiểm thử độc lập migration 011 (`system_settings` + bước `rag_sync`): áp lên DB đã có dữ liệu, chạy lại lần hai,
và tiến trình cũ/mới khi 011 chưa áp. Postgres tạm (TEST_DATABASE_URL), không đụng DATABASE_URL."""
import shutil

import psycopg
import pytest

from eventrank.common import db, settings_store
from eventrank.rag import auto_sync as RS
from eventrank.serving import worker_settings as WS

OLD_STEPS = ("import", "embed", "assign", "recluster", "name", "trend", "notify")
M011 = "011_system_settings.sql"


@pytest.fixture
def before_011(pg_url, tmp_path):
    """DB tạm đã áp 001…010 (chưa có 011) + mỗi bước cũ của worker_runs một dòng."""
    d = tmp_path / "mig"
    d.mkdir()
    for p in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if p.name != M011:
            shutil.copy(p, d / p.name)
    with db.connect(pg_url) as conn:
        db.migrate(conn, d)
        for step in OLD_STEPS:
            conn.execute("INSERT INTO worker_runs (step, status, stats) VALUES (%s, 'ok', '{\"n\": 1}')", (step,))
        yield conn, d


def test_ap_011_len_db_da_co_worker_runs_giu_du_lieu(before_011):
    conn, d = before_011
    assert not settings_store.available(conn)
    shutil.copy(db.MIGRATIONS_DIR / M011, d / M011)
    assert db.migrate(conn, d) == [M011]
    assert conn.execute("SELECT count(*) FROM worker_runs").fetchone()[0] == len(OLD_STEPS)
    conn.execute("INSERT INTO worker_runs (step) VALUES ('rag_sync')")
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO worker_runs (step) VALUES ('rag_prepare')")


def test_chay_lai_sql_011_lan_hai_khong_loi(pg_conn):
    sql = (db.MIGRATIONS_DIR / M011).read_text(encoding="utf-8")
    RS.save_settings(pg_conn, RS.RagSyncSettings(mode="off"))
    with pg_conn.transaction():
        pg_conn.execute(sql.encode())
    assert RS.load_settings(pg_conn).value.mode == "off"      # IF NOT EXISTS: không xoá cài đặt đã lưu


def test_chua_ap_011_doc_cai_dat_tra_mac_dinh_va_ket_noi_van_dung_duoc(before_011):
    conn, _ = before_011
    assert RS.load_settings(conn).from_db is False
    assert WS.load(conn).from_db is False
    assert RS.recent_runs(conn) == []                        # kết nối autocommit không bị kẹt transaction lỗi
    assert conn.execute("SELECT 1").fetchone()[0] == 1


def test_chua_ap_011_ghi_rag_sync_vao_worker_runs_bi_check_tu_choi_nhung_bo_lap_lich_van_chay(before_011):
    conn, _ = before_011
    run_id = RS.AutoSync._log_start(conn, {"index_version": "rag_v1"}, "forced", "forced", RS.RagSyncSettings())
    assert run_id is None
    assert conn.execute("SELECT 1").fetchone()[0] == 1


def test_worker_status_coi_011_la_tuy_chon(before_011):
    from eventrank.serving import worker as W
    conn, d = before_011
    shutil.copy(db.MIGRATIONS_DIR / M011, d / M011)
    states = {r["name"]: r["state"] for r in db.status(conn, d)}
    assert states[M011] == "pending" and M011 in W.OPTIONAL_MIGRATIONS
