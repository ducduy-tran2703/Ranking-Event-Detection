import os
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values

from eventrank.common.config import LakeConfig
from eventrank.lake.reader import SilverStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def local_cfg() -> LakeConfig:
    """Đọc dữ liệu mẫu cục bộ — test không bao giờ chạm vào R2."""
    return LakeConfig(backend="local", bucket="", silver_glob="silver/*/*.jsonl",
                      local_root="tests/fixtures")


@pytest.fixture(scope="session")
def store(local_cfg) -> SilverStore:
    s = SilverStore(local_cfg)
    s.reload()
    return s


# ---------------------------------------------------------------------- Postgres (test `db`)
def _test_database_url() -> str | None:
    """TEST_DATABASE_URL từ môi trường, không thì từ .env (chỉ lấy đúng biến này, không nạp cả file
    vào os.environ — tránh LAKE_BACKEND=r2 của .env lọt vào các test khác). Đặt RỖNG tường minh
    (`TEST_DATABASE_URL= make test`) = tắt test Postgres dù .env có biến."""
    if "TEST_DATABASE_URL" in os.environ:
        return os.environ["TEST_DATABASE_URL"] or None
    env_file = ROOT / ".env"
    return (dotenv_values(env_file).get("TEST_DATABASE_URL") or None) if env_file.exists() else None


def pytest_collection_modifyitems(config, items):
    # Test nào dùng Postgres (trực tiếp hay qua fixture khác) tự mang nhãn `db` → `pytest -m db`.
    for item in items:
        if "pg_url" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.db)


@pytest.fixture
def pg_url():
    """Một database TẠM, rỗng, riêng cho mỗi test; xoá sau test.

    Cần TEST_DATABASE_URL trỏ tới role có quyền CREATEDB. Không có biến → skip, để `make test` vẫn
    xanh trên máy không cài Postgres.
    """
    base = _test_database_url()
    if not base:
        pytest.skip("Chưa đặt TEST_DATABASE_URL (xem .env.example) — bỏ qua test cần Postgres")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    name = f"eventrank_test_{uuid.uuid4().hex[:12]}"
    try:
        with psycopg.connect(base, autocommit=True, connect_timeout=5) as c:
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except psycopg.Error as e:
        # Đã đặt biến mà không dùng được → FAIL rõ ràng (không skip: cấu hình sai phải thấy được).
        # Thông báo của psycopg có host/cổng/role, không có mật khẩu.
        pytest.fail(f"TEST_DATABASE_URL đã đặt nhưng không tạo được DB tạm: {e}".strip()
                    + " — kiểm tra role (cần CREATEDB) và mật khẩu, hoặc chạy "
                      "`TEST_DATABASE_URL= make test` để bỏ qua test Postgres.", pytrace=False)
    try:
        yield make_conninfo(base, dbname=name)
    finally:
        # KHÔNG dùng `WITH (FORCE)`: FORCE ngắt cả worker autovacuum (của superuser) đang vào DB mới tạo
        # → role thường bị "permission denied to terminate process" (gặp 04/11/2026, chập chờn).
        # DROP thường tự huỷ autovacuum; kết nối của test đã đóng → chỉ cần thử lại khi còn sót.
        import time

        drop = sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name))
        with psycopg.connect(base, autocommit=True) as c:
            for attempt in range(10):
                try:
                    c.execute(drop)
                    break
                except psycopg.errors.ObjectInUse:
                    if attempt == 9:
                        raise
                    time.sleep(0.2)


@pytest.fixture
def pg_conn(pg_url):
    """Kết nối autocommit tới database tạm ĐÃ áp mọi migration trong infra/db/migrations/."""
    from eventrank.common import db

    with db.connect(pg_url) as conn:
        db.migrate(conn)
        yield conn
