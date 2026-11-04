"""`run_crawler`: ghi crawl_runs (bắt đầu/kết thúc/lỗi), validate, upsert theo lô, đếm.
Cần Postgres (TEST_DATABASE_URL)."""
from datetime import UTC, datetime

import pytest

from eventrank.ingest import base, fetch, sink, status

NOW = datetime(2026, 9, 20, tzinfo=UTC)


def item(i, **kw):
    r = {"url": f"https://tuoitre.vn/bai-{i}.htm", "source": "tuoitre", "category": "Thời sự",
         "title": f"Bài {i}", "sapo": "Sapo", "author": "A",
         "published_at": "2026-09-19T10:00:00+07:00", "content_text": "chữ " * 100}
    r.update(kw)
    return r


class ListCrawler:
    source = "tuoitre"
    name = "tuoitre_test"
    parser_version = "tt-0.1"

    def __init__(self, items, boom=None):
        self.items, self.boom = items, boom
        self.ctx = None

    def crawl(self, ctx):
        self.ctx = ctx
        yield from self.items
        if self.boom:
            raise self.boom


@pytest.fixture
def conn(pg_conn):
    sink.sync_sources(pg_conn, [{"source": "tuoitre", "display_name": "Tuổi Trẻ"}])
    return pg_conn


def run_row(conn):
    return conn.execute("SELECT status, n_seen, n_new, n_updated, n_unchanged, n_rejected, "
                        "reject_reasons, error, crawler, parser_version, finished_at "
                        "FROM crawl_runs ORDER BY run_id DESC LIMIT 1").fetchone()


def test_chay_thanh_cong_ghi_crawl_runs_va_bai(conn):
    c = ListCrawler([item(1), item(2), item(3, published_at="2026-09-19T10:00:00")])
    res = base.run_crawler(conn, c, client=None, now=NOW, batch_size=2)
    assert res.status == "ok"
    st, seen, new, upd, unch, rej, reasons, err, crawler, pv, fin = run_row(conn)
    assert (st, seen, new, upd, unch, rej) == ("ok", 3, 2, 0, 0, 1)
    assert reasons == {"published_at_naive": 1} and err is None and fin is not None
    assert (crawler, pv) == ("tuoitre_test", "tt-0.1")
    assert conn.execute("SELECT DISTINCT ingested_via, parser_version FROM articles"
                        ).fetchall() == [("crawler:tuoitre_test", "tt-0.1")]
    # lần chạy sau: context biết lần chạy thành công trước để cào tăng dần
    c2 = ListCrawler([item(1)])
    base.run_crawler(conn, c2, client=None, now=NOW)
    assert c2.ctx.since is not None and c2.ctx.source == "tuoitre"
    assert run_row(conn)[2:5] == (0, 0, 1)


def test_crawler_loi_giua_chung_van_luu_phan_da_cao(conn):
    c = ListCrawler([item(1), item(2)], boom=ValueError("parser vỡ"))
    res = base.run_crawler(conn, c, client=None, now=NOW, batch_size=10)
    assert res.status == "failed"
    st, seen, new, *_rest = run_row(conn)
    assert (st, seen, new) == ("failed", 2, 2)
    assert "parser vỡ" in run_row(conn)[7]
    assert conn.execute("SELECT count(*) FROM articles").fetchone()[0] == 2


def test_bao_chan_thi_trang_thai_blocked(conn):
    c = ListCrawler([item(1)], boom=fetch.DomainBlocked("tuoitre.vn trả 403 2 lần"))
    assert base.run_crawler(conn, c, client=None, now=NOW).status == "blocked"
    assert run_row(conn)[0] == "blocked"


def test_bai_cua_bao_khac_bi_loai(conn):
    sink.sync_sources(conn, [{"source": "thanhnien", "display_name": "Thanh Niên"}])
    c = ListCrawler([item(1, source="thanhnien")])
    res = base.run_crawler(conn, c, client=None, now=NOW)
    assert res.counts.reject_reasons == {"source_mismatch": 1}


def test_nguon_chua_dong_bo_thi_tu_choi(pg_conn):
    with pytest.raises(base.CrawlerError, match="sources sync"):
        base.run_crawler(pg_conn, ListCrawler([]), client=None, now=NOW)


def test_status_moi_bao(conn):
    base.run_crawler(conn, ListCrawler([item(1), item(2)]), client=None, now=NOW)
    rows = {r["source"]: r for r in status.source_status(conn)}
    tt = rows["tuoitre"]
    assert tt["last_status"] == "ok" and tt["new_24h"] == 2 and tt["total"] == 2
    text = status.format_status(conn)
    assert "tuoitre" in text and "real" in text


def test_gioi_han_so_bai_cho_lat_cat_thu(conn):
    res = base.run_crawler(conn, ListCrawler([item(i) for i in range(20)]), client=None, now=NOW,
                           max_articles=12)
    assert res.n_seen == 12 and res.counts.inserted == 12 and res.status == "ok"
