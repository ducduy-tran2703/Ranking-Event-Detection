"""Ghi bài vào Postgres (`eventrank.ingest.sink`): idempotent, chỉ UPDATE khi nội dung đổi, giữ
crawled_at đầu tiên. Cần TEST_DATABASE_URL (tự skip khi thiếu)."""
from datetime import UTC, datetime

from eventrank.ingest import contract, sink

NOW = datetime(2026, 9, 20, tzinfo=UTC)


def art(i=1, **kw):
    r = {"url": f"https://tuoitre.vn/bai-{i}.htm", "source": "tuoitre", "category": "Thời sự",
         "title": f"Bài {i}", "sapo": "Sapo.", "author": None,
         "published_at": "2026-09-16T07:00:00+07:00", "content_text": "Nội dung " * 100}
    r.update(kw)
    return contract.validate_article(r, known_sources={"tuoitre"}, now=NOW)


def seed(conn):
    sink.sync_sources(conn, [{"source": "tuoitre", "display_name": "Tuổi Trẻ",
                              "homepage": "https://tuoitre.vn", "enabled": False}])


def test_chay_hai_lan_khong_tao_ban_moi(pg_conn):
    seed(pg_conn)
    batch = [art(i) for i in range(5)]
    first = sink.upsert_articles(pg_conn, batch, via="import_jsonl")
    assert (first.inserted, first.updated, first.unchanged) == (5, 0, 0)
    again = sink.upsert_articles(pg_conn, batch, via="import_jsonl")
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 5)
    assert pg_conn.execute("SELECT count(*) FROM articles").fetchone()[0] == 5


def test_chi_cap_nhat_khi_noi_dung_doi_va_giu_crawled_at_dau(pg_conn):
    seed(pg_conn)
    sink.upsert_articles(pg_conn, [art(1)], via="import_jsonl", parser_version="v1")
    crawled0, updated0 = pg_conn.execute(
        "SELECT crawled_at, updated_at FROM articles").fetchone()
    res = sink.upsert_articles(pg_conn, [art(1, title="Bài 1 (cập nhật)")], via="crawler:tt",
                               parser_version="v2")
    assert (res.inserted, res.updated) == (0, 1)
    row = pg_conn.execute("SELECT title, crawled_at, updated_at, ingested_via, parser_version "
                          "FROM articles").fetchone()
    assert row[0] == "Bài 1 (cập nhật)"
    assert row[1] == crawled0 and row[2] > updated0
    assert row[3:] == ("crawler:tt", "v2")


def test_bai_bi_loai_chi_dem_khong_ghi(pg_conn):
    seed(pg_conn)
    bad = contract.validate_article({"url": "http://x"}, known_sources={"tuoitre"}, now=NOW)
    res = sink.upsert_articles(pg_conn, [art(1), bad, bad], via="import_jsonl")
    assert (res.inserted, res.rejected) == (1, 2)
    assert res.reject_reasons["url_not_https"] == 2


def test_trung_trong_cung_lo_khong_vo_lo(pg_conn):
    seed(pg_conn)
    res = sink.upsert_articles(pg_conn, [art(1), art(1), art(1, title="khác")], via="replay",
                               batch_size=10)
    assert res.inserted == 1 and res.unchanged == 1 and res.updated == 1
    assert pg_conn.execute("SELECT title FROM articles").fetchone()[0] == "khác"


def test_luu_dung_cac_cot_hop_dong(pg_conn):
    seed(pg_conn)
    a = art(1, sapo="", author="")
    sink.upsert_articles(pg_conn, [a], via="import_jsonl")
    row = pg_conn.execute("SELECT article_id, author, published_at, quality_flags, content_hash "
                          "FROM articles").fetchone()
    assert row[0] == a.article_id and row[1] is None
    assert row[2] == datetime(2026, 9, 16, 0, 0, tzinfo=UTC)
    assert set(row[3]) == {"missing_sapo", "missing_author"}
    assert row[4] == a.content_hash


def test_sync_sources_idempotent_va_khong_xoa(pg_conn):
    rows = [{"source": "tuoitre", "display_name": "Tuổi Trẻ", "enabled": False},
            {"source": "vnexpress", "display_name": "VnExpress", "enabled": True,
             "crawler": "pkg.mod:Lop", "notes": "chỉ RSS"}]
    assert sink.sync_sources(pg_conn, rows) == {"inserted": 2, "updated": 0, "unchanged": 0}
    assert sink.sync_sources(pg_conn, rows) == {"inserted": 0, "updated": 0, "unchanged": 2}
    rows[0]["enabled"] = True
    assert sink.sync_sources(pg_conn, rows[:1])["updated"] == 1
    assert pg_conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 2
    assert sink.known_sources(pg_conn) == {"tuoitre", "vnexpress"}
