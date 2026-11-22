"""Kiểm thử độc lập tool chat (`count_articles`, `top_events`, `corpus_info`) và truy vấn bài chờ của sync trên Postgres tạm.

- Tiêu chí "đã vào kho RAG" phải trùng `pipeline.corpus_snapshot` (index_version hiện hành, BM25 HOẶC Qdrant ready).
- Đo hiệu năng trên ~30 nghìn bài tổng hợp: chỉ chạy khi đặt `EVENTRANK_PERF=1` (tốn ~10–20 s), in EXPLAIN ANALYZE.
"""
import os
import time

import pytest
from test_tools_db import _ctx, kho  # noqa: F401 -- kho là fixture

from eventrank.rag import sync
from eventrank.rag import tools as T
from eventrank.rag.chunking import chunking_version
from eventrank.rag.pipeline import corpus_snapshot


def _count(conn, **kw):
    out, err = T.run_tool(_ctx(conn, **kw), "count_articles", {}, allowed=set(T.HANDLERS))
    assert err is None
    return out["count"]


def test_index_version_khac_khong_duoc_tinh_giong_snapshot(kho):  # noqa: F811
    kho.execute("UPDATE rag_index_status SET index_version = 'rag_v0'")
    assert corpus_snapshot(kho, "rag_v1")["articles"] == 0
    assert _count(kho) == 0


def test_chi_qdrant_ready_van_tinh_giong_snapshot(kho):  # noqa: F811
    kho.execute("UPDATE rag_index_status SET bm25_status = 'pending', qdrant_status = 'ready'")
    snap = corpus_snapshot(kho, "rag_v1")["articles"]
    assert snap == _count(kho) == 2


def test_an_bao_khong_phan_biet_hoa_thuong_va_khoang_trang(kho):  # noqa: F811
    assert _count(kho, hidden_sources=["  VnExpress "]) == 0
    assert _count(kho, hidden_sources=["", "   "]) == 1


def test_pham_vi_kho_khong_liet_ke_bao_nguoi_dung_an(kho):  # noqa: F811
    """THEO ĐỀ BÀI (đang FAIL): `corpus_info` cũng phải loại báo người dùng ẩn. Tài liệu nhánh (rag-tool-calling-issues.md,
    lỗi 15) chỉ cam kết `count_articles`/`top_events`, nên đây là chỗ lệch giữa yêu cầu và code: người ẩn VnExpress vẫn
    được chatbot báo "vnexpress: 1 bài" và tổng `snapshot()['articles']` gồm cả báo ẩn."""
    out, _ = T.run_tool(_ctx(kho, hidden_sources=["vnexpress"]), "corpus_info", {}, allowed=set(T.HANDLERS))
    assert "vnexpress" not in out["text"].lower(), out["text"]


# ---------------------------------------------------------------------- hiệu năng ~30 nghìn bài
N_ART, N_PENDING, CHUNKS = 30_000, 1_000, 3


@pytest.fixture
def kho_lon(pg_conn):
    c, cv = pg_conn, chunking_version(320, 48)
    c.execute("INSERT INTO sources (source, display_name) VALUES ('vnexpress', 'VnExpress'), ('tuoitre', 'Tuổi Trẻ')")
    c.execute(
        "INSERT INTO articles (article_id, url, source, category, title, sapo, published_at, content_text, ingested_via,"
        " content_hash) SELECT encode(sha256(('u' || i)::bytea), 'hex'), 'https://x.test/' || i,"
        " CASE WHEN i %% 2 = 0 THEN 'vnexpress' ELSE 'tuoitre' END, 'Thời sự', 'Tiêu đề ' || i, '',"
        " now() - i * interval '1 minute', 'Nội dung bài số ' || i, 'import_jsonl', encode(sha256(('h' || i)::bytea), 'hex')"
        " FROM generate_series(1, %s) i", (N_ART,))
    c.execute(
        "INSERT INTO article_ner (article_id, canonical_text, text_hash, ner_version, entities)"
        " SELECT article_id, 'x', encode(sha256(article_id::bytea), 'hex'), 'v', '[]' FROM articles"
        " ORDER BY published_at LIMIT %s", (N_ART - N_PENDING,))
    c.execute(
        "INSERT INTO rag_chunks (chunk_id, article_id, chunk_index, text, start_char, end_char, chunking_version)"
        " SELECT md5(n.article_id || k)::uuid, n.article_id, k, 'abc', 0, 3, %s"
        " FROM article_ner n, generate_series(0, %s) k", (cv, CHUNKS - 1))
    c.execute("INSERT INTO rag_index_status (chunk_id, index_version, bm25_status, qdrant_status)"
              " SELECT chunk_id, 'rag_v1', 'ready', 'ready' FROM rag_chunks")
    c.execute("ANALYZE")
    return c, cv


def _timed(fn):
    t = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - t


@pytest.mark.skipif(os.environ.get("EVENTRANK_PERF") != "1", reason="đặt EVENTRANK_PERF=1 để đo trên ~30 nghìn bài")
def test_hieu_nang_tren_30_nghin_bai(kho_lon):
    c, cv = kho_lon
    summary, t_pending = _timed(lambda: sync.pending_summary(c, index_version="rag_v1", chunk_version=cv))
    assert summary == {"pending_articles": N_PENDING, "without_ner": N_PENDING}
    plan, t_inspect = _timed(lambda: sync.inspect_articles(c, None, index_version="rag_v1", chunk_version=cv,
                                                           max_articles=200))
    assert len(plan["need_ner_articles"]) == 200 and plan["limited"] is True
    snap = corpus_snapshot(c, "rag_v1")
    ctx = T.ToolContext(conn=c, question="?", filters={}, search=lambda *a, **k: [], snapshot=lambda: snap,
                        hidden_sources=["tuoitre"])
    out, t_count = _timed(lambda: T.run_tool(ctx, "count_articles", {}, allowed=set(T.HANDLERS))[0])
    assert out["count"] == (N_ART - N_PENDING) // 2
    _, t_info = _timed(lambda: T.run_tool(ctx, "corpus_info", {}, allowed=set(T.HANDLERS)))
    _, t_snap = _timed(lambda: corpus_snapshot(c, "rag_v1"))
    where = sync._PENDING_WHERE
    plan_txt = "\n".join(r[0] for r in c.execute(
        "EXPLAIN (ANALYZE, BUFFERS OFF) SELECT count(*) FROM articles a LEFT JOIN article_ner n USING(article_id) "
        "WHERE " + where, {"iv": "rag_v1", "cv": cv}))
    count_txt = "\n".join(r[0] for r in c.execute(
        "EXPLAIN ANALYZE SELECT count(*) FROM articles a WHERE " + T._IN_RAG + " AND " + T._NOT_HIDDEN,
        ["rag_v1", ["tuoitre"]]))
    print(f"\npending_summary {t_pending:.3f}s | inspect(max=200) {t_inspect:.3f}s | count_articles {t_count:.3f}s"
          f" | corpus_info {t_info:.3f}s | corpus_snapshot {t_snap:.3f}s")
    print("--- EXPLAIN pending_summary\n" + plan_txt + "\n--- EXPLAIN count_articles\n" + count_txt)
    assert max(t_pending, t_inspect, t_count, t_info) < 3.0
