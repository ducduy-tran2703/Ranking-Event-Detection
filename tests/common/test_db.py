"""Kết nối + bộ áp migration (`eventrank.common.db`). Phần cần Postgres tự skip khi thiếu
TEST_DATABASE_URL (fixture `pg_url` trong tests/conftest.py)."""
import pytest

from eventrank.common import db


def _write(d, name, sql):
    p = d / name
    p.write_text(sql, encoding="utf-8")
    return p


# ---------------------------------------------------------------------- không cần DB
def test_thieu_database_url_bao_loi_ro_rang(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "load_dotenv", lambda *a, **k: False)
    with pytest.raises(db.DatabaseConfigError, match="DATABASE_URL"):
        db.database_url()


def test_loi_cau_hinh_khong_lo_gia_tri(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql://u:bi-mat@h/x")
    monkeypatch.setattr(db, "load_dotenv", lambda *a, **k: False)
    with pytest.raises(db.DatabaseConfigError) as e:
        db.database_url()
    assert "bi-mat" not in str(e.value)


def test_tim_migration_theo_thu_tu_so(tmp_path):
    _write(tmp_path, "002_hai.sql", "SELECT 2;")
    _write(tmp_path, "001_mot.sql", "SELECT 1;")
    _write(tmp_path, "README.md", "không phải migration")
    found = db.discover_migrations(tmp_path)
    assert [m.name for m in found] == ["001_mot.sql", "002_hai.sql"]
    assert len(found[0].sha256) == 64


def test_ten_migration_sai_mau_hoac_trung_so_bi_tu_choi(tmp_path):
    _write(tmp_path, "1_thieu-so.sql", "SELECT 1;")
    with pytest.raises(db.MigrationError, match="1_thieu-so.sql"):
        db.discover_migrations(tmp_path)
    (tmp_path / "1_thieu-so.sql").unlink()
    _write(tmp_path, "001_a.sql", "SELECT 1;")
    _write(tmp_path, "001_b.sql", "SELECT 1;")
    with pytest.raises(db.MigrationError, match="001"):
        db.discover_migrations(tmp_path)


def test_migration_that_cua_repo_hop_le():
    names = [m.name for m in db.discover_migrations()]
    assert names[0] == "001_ingest.sql"


# ---------------------------------------------------------------------- cần Postgres
def test_migrate_ap_theo_thu_tu_va_chay_lai_khong_lam_gi(pg_url, tmp_path):
    _write(tmp_path, "001_t.sql", "CREATE TABLE t (x int);")
    _write(tmp_path, "002_u.sql", "INSERT INTO t VALUES (1), (2);")
    with db.connect(pg_url) as conn:
        assert db.migrate(conn, tmp_path) == ["001_t.sql", "002_u.sql"]
        assert db.migrate(conn, tmp_path) == []
        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 2
        rows = conn.execute("SELECT filename, length(sha256) FROM schema_migrations "
                            "ORDER BY filename").fetchall()
        assert rows == [("001_t.sql", 64), ("002_u.sql", 64)]


def test_file_loi_rollback_ca_file_va_khong_ghi_nhan(pg_url, tmp_path):
    _write(tmp_path, "001_ok.sql", "CREATE TABLE a (x int);")
    _write(tmp_path, "002_loi.sql", "CREATE TABLE b (x int); SELECT khong_co_cot FROM a;")
    with db.connect(pg_url) as conn:
        with pytest.raises(db.MigrationError, match="002_loi.sql"):
            db.migrate(conn, tmp_path)
        applied = [r[0] for r in conn.execute("SELECT filename FROM schema_migrations")]
        assert applied == ["001_ok.sql"]
        # bảng b tạo trong file lỗi phải bị rollback cùng file
        assert conn.execute("SELECT to_regclass('b')").fetchone()[0] is None


def test_file_da_ap_bi_sua_thi_bao_loi(pg_url, tmp_path):
    p = _write(tmp_path, "001_t.sql", "CREATE TABLE t (x int);")
    with db.connect(pg_url) as conn:
        db.migrate(conn, tmp_path)
        p.write_text("CREATE TABLE t (x bigint);", encoding="utf-8")
        with pytest.raises(db.MigrationError, match="đã bị sửa: 001_t.sql"):
            db.migrate(conn, tmp_path)
        st = db.status(conn, tmp_path)
        assert st[0]["state"] == "modified"


def test_file_moi_chen_truoc_file_da_ap_bi_tu_choi(pg_url, tmp_path):
    _write(tmp_path, "002_sau.sql", "SELECT 1;")
    with db.connect(pg_url) as conn:
        db.migrate(conn, tmp_path)
        _write(tmp_path, "001_truoc.sql", "SELECT 1;")
        with pytest.raises(db.MigrationError, match="001_truoc.sql"):
            db.migrate(conn, tmp_path)


def test_status_liet_ke_da_ap_va_chua_ap(pg_url, tmp_path):
    _write(tmp_path, "001_a.sql", "SELECT 1;")
    with db.connect(pg_url) as conn:
        db.migrate(conn, tmp_path)
        _write(tmp_path, "002_b.sql", "SELECT 1;")
        st = {r["name"]: r["state"] for r in db.status(conn, tmp_path)}
        assert st == {"001_a.sql": "applied", "002_b.sql": "pending"}


def test_migration_that_tao_du_bang(pg_conn):
    tables = {r[0] for r in pg_conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")}
    assert {"schema_migrations", "sources", "articles", "crawl_runs", "app_clock"} <= tables
    mode, sim_now = pg_conn.execute("SELECT mode, sim_now FROM app_clock").fetchone()
    assert (mode, sim_now) == ("real", None)
