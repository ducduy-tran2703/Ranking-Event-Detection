"""Kho cài đặt `system_settings` (migration 011) + nới CHECK `worker_runs.step` thêm 'rag_sync'.

Phần không cần DB dùng kết nối giả; phần `db` chạy trên DB tạm (TEST_DATABASE_URL), tự skip khi thiếu.
"""
from types import SimpleNamespace
from typing import Literal

import psycopg
import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eventrank.common import settings_store as S


class Demo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["a", "b"] = "a"
    n: int = Field(5, ge=1, le=10)


class _Conn:
    def __init__(self, row=None, error=None):
        self.row, self.error = row, error

    def execute(self, sql, params=None):
        if self.error:
            raise self.error
        return SimpleNamespace(fetchone=lambda: self.row)


def test_thieu_bang_tra_mac_dinh_khong_loi():
    got = S.load(_Conn(error=psycopg.errors.UndefinedTable("relation does not exist")), "demo", Demo)
    assert got.value == Demo() and got.from_db is False


def test_chua_co_dong_tra_mac_dinh_truyen_vao():
    assert S.get(_Conn(row=None), "demo", Demo, Demo(n=7)).n == 7


def test_truong_thua_bi_bo_truong_thieu_lay_mac_dinh():
    got = S.load(_Conn(row=({"mode": "b", "cu": 1}, None, None)), "demo", Demo, Demo(n=3))
    assert got.value == Demo(mode="b", n=3) and got.from_db


def test_gia_tri_sai_thi_dung_mac_dinh():
    assert S.get(_Conn(row=({"n": 999}, None, None)), "demo", Demo) == Demo()


def test_ghi_gia_tri_sai_bi_tu_choi_truoc_khi_cham_db():
    bad = Demo.model_construct(mode="z", n=1)
    with pytest.raises(ValidationError):
        S.save(_Conn(error=AssertionError("không được chạm DB")), "demo", bad)


# ---------------------------------------------------------------------- Postgres tạm
def test_ghi_doc_va_nguoi_sua(pg_conn):
    uid = pg_conn.execute("INSERT INTO users (email, display_name, password_hash, role, terms_accepted_at) VALUES "
                          "('a@example.com', 'A', 'x', 'admin', now()) RETURNING user_id").fetchone()[0]
    assert S.available(pg_conn)
    assert S.load(pg_conn, "demo", Demo).from_db is False
    saved = S.save(pg_conn, "demo", Demo(mode="b", n=9), uid)
    assert saved.updated_by == uid
    got = S.load(pg_conn, "demo", Demo)
    assert got.value == Demo(mode="b", n=9) and got.updated_by == uid and got.updated_at is not None
    S.save(pg_conn, "demo", Demo(n=2))
    assert S.get(pg_conn, "demo", Demo) == Demo(n=2)
    S.save(pg_conn, "demo", Demo(n=4), uid)
    pg_conn.execute("DELETE FROM users WHERE user_id = %s", (uid,))   # xoá người sửa → updated_by NULL, dòng còn
    after = S.load(pg_conn, "demo", Demo)
    assert after.value.n == 4 and after.updated_by is None


def test_worker_runs_chap_nhan_rag_sync_va_van_chan_buoc_la(pg_conn):
    pg_conn.execute("INSERT INTO worker_runs (step) VALUES ('rag_sync')")
    with pytest.raises(psycopg.errors.CheckViolation):
        pg_conn.execute("INSERT INTO worker_runs (step) VALUES ('khong_co')")


def test_key_va_value_phai_dung_dang(pg_conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        pg_conn.execute("INSERT INTO system_settings (key, value) VALUES ('Sai Key', '{}')")
    with pytest.raises(psycopg.errors.CheckViolation):
        pg_conn.execute("INSERT INTO system_settings (key, value) VALUES ('ok', '[]')")


def test_011_backfill_source_updated_at_chi_cho_ner_da_khop_ban_hien_tai(pg_url, tmp_path):
    """Dòng NER mới hơn bài → backfill = articles.updated_at (không thành bài chờ); NER cũ hơn bài → để NULL (vẫn chờ)."""
    import shutil

    from eventrank.common import db
    d = tmp_path / "mig"
    d.mkdir()
    for p in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if p.name != "011_system_settings.sql":
            shutil.copy(p, d / p.name)
    with db.connect(pg_url) as c:
        db.migrate(c, d)
        c.execute("INSERT INTO sources (source, display_name) VALUES ('tuoitre', 'Tuổi Trẻ')")
        for aid in ("a" * 64, "b" * 64):
            c.execute("INSERT INTO articles (article_id, url, source, category, title, sapo, published_at, content_text,"
                      " ingested_via, content_hash, updated_at) VALUES (%s, %s, 'tuoitre', 'x', 't', '', now(), 'n',"
                      " 'import_jsonl', %s, now() - interval '1 hour')", (aid, f"https://x.test/{aid[0]}", aid))
        c.execute("INSERT INTO article_ner (article_id, canonical_text, text_hash, ner_version, updated_at) VALUES "
                  "(%s, 'x', %s, 'v', now()), (%s, 'x', %s, 'v', now() - interval '2 hours')",
                  ("a" * 64, "0" * 64, "b" * 64, "0" * 64))
        shutil.copy(db.MIGRATIONS_DIR / "011_system_settings.sql", d / "011_system_settings.sql")
        db.migrate(c, d)
        got = dict(c.execute("SELECT n.article_id, n.source_updated_at = a.updated_at FROM article_ner n "
                             "JOIN articles a USING (article_id)").fetchall())
        assert got == {"a" * 64: True, "b" * 64: None}
