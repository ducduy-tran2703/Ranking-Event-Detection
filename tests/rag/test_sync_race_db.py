"""Kiểm thử độc lập `sync_rag` hai pha: tranh chấp với crawler, chạy chồng hai lượt, lỗi Qwen giữa pha ghi.

Postgres tạm (TEST_DATABASE_URL). Không gọi GPU/Modal/mạng: Qdrant `:memory:`, embedding giả, NER giả, BM25 trong tmp_path.
"Crawler" là một kết nối Postgres thứ hai sửa bài đúng lúc sync đang ở pha ghi (móc vào `qdrant.delete`, lệnh mạng đầu tiên
của pha ghi sau khi đã đọc lại hash dưới khoá).

Các test đánh dấu "LỖI THẬT" đang FAIL với code hiện tại — để nguyên cho agent code sửa, không sửa test cho xanh.
"""
import psycopg
import pytest
from qdrant_client import QdrantClient
from test_rag_dense import Encoder
from test_sync_db import _cfg, _Predictor, _run, _summary, corpus  # noqa: F401 -- corpus là fixture

from eventrank.rag import bm25, hybrid, prepare, sync
from eventrank.rag.text import build_full_text, text_hash


class _HookQdrant:
    """Bọc QdrantClient: gọi `hook()` một lần ở lần `delete` đầu tiên (đang giữ khoá ghi, sau `_current_hashes`)."""

    def __init__(self, q, hook):
        self._q, self._hook, self.fired = q, hook, False

    def delete(self, *a, **kw):
        if not self.fired:
            self.fired = True
            self._hook()
        return self._q.delete(*a, **kw)

    def __getattr__(self, name):
        return getattr(self._q, name)


class _FailingEncoder(Encoder):
    def embed(self, texts, *, input_type):
        raise RuntimeError("Model service returned HTTP 503")


def _ner_matches_text(conn, aid) -> bool:
    t, s, c, h = conn.execute(
        "SELECT a.title, a.sapo, a.content_text, n.text_hash FROM articles a JOIN article_ner n USING(article_id) "
        "WHERE a.article_id = %s", (aid,)).fetchone()
    return text_hash(build_full_text({"title": t, "sapo": s, "content_text": c})) == h


def _ids(conn):
    return [r[0] for r in conn.execute("SELECT article_id FROM articles ORDER BY article_id")]


# ---------------------------------------------------------------------- LỖI THẬT: sửa bài trong pha ghi bị mất
def test_crawler_sua_bai_trong_pha_ghi_thi_bai_van_phai_con_cho(corpus, pg_url, tmp_path):  # noqa: F811
    """LỖI THẬT (đang FAIL). Pha ghi đọc hash (`_current_hashes`) rồi mới ghi NER với `updated_at = now()` của transaction
    SAU ĐÓ. Crawler commit bản sửa vào khe giữa hai việc → `articles.updated_at` < `article_ner.updated_at` nên quét toàn
    kho (`a.updated_at > n.updated_at`) không bao giờ thấy bài nữa: NER/chunk của bản cũ nằm lại vĩnh viễn."""
    c, q = corpus, QdrantClient(":memory:")
    _run(c, tmp_path, q)
    aid = _ids(c)[0]
    c.execute("UPDATE articles SET content_text = content_text || ' Bản hai.', updated_at = now() "
              "WHERE article_id = %s", (aid,))
    with psycopg.connect(pg_url, autocommit=True) as crawler:
        def crawler_edit():
            crawler.execute("UPDATE articles SET content_text = content_text || ' Bản ba.', updated_at = now() "
                            "WHERE article_id = %s", (aid,))
        hq = _HookQdrant(q, crawler_edit)
        res = _run(c, tmp_path, hq)
    assert hq.fired and res["ner_articles"] == 1
    # Bất biến: NER không khớp văn bản hiện tại thì bài PHẢI còn trong danh sách chờ (lượt sau làm lại).
    assert not _ner_matches_text(c, aid)
    assert _summary(c, tmp_path)["pending_articles"] >= 1, (
        "bài bị crawler sửa trong pha ghi bị đánh dấu xong với NER của bản cũ")


def test_crawler_sua_bai_luc_cham_updated_at_thi_bai_van_phai_con_cho(corpus, pg_url, tmp_path):  # noqa: F811
    """LỖI THẬT (đang FAIL). Nhánh "chạm" (`touch`): bài B chỉ đổi tác giả → pha ghi chỉ `UPDATE article_ner SET
    updated_at = now()`. Nếu crawler sửa NỘI DUNG B sau `_current_hashes` mà trước lệnh chạm, lệnh chạm che mất bản sửa."""
    c, q = corpus, QdrantClient(":memory:")
    _run(c, tmp_path, q)
    a, b = _ids(c)[:2]
    c.execute("UPDATE articles SET content_text = content_text || ' Bản hai.', updated_at = now() "
              "WHERE article_id = %s", (a,))                       # A cần NER lại → pha ghi có qdrant.delete
    c.execute("UPDATE articles SET author = 'Phóng viên', updated_at = now() WHERE article_id = %s", (b,))
    with psycopg.connect(pg_url, autocommit=True) as crawler:
        def crawler_edit():
            crawler.execute("UPDATE articles SET content_text = content_text || ' Sửa nội dung.', updated_at = now() "
                            "WHERE article_id = %s", (b,))
        res = _run(c, tmp_path, _HookQdrant(q, crawler_edit))
    assert res["touched_articles"] == 1
    assert not _ner_matches_text(c, b)
    assert _summary(c, tmp_path)["pending_articles"] >= 1, "lệnh chạm updated_at che mất bản sửa nội dung của crawler"


# ---------------------------------------------------------------------- LỖI THẬT: Qwen lỗi sau khi DB đã commit
def test_qwen_loi_sau_khi_thay_chunk_khong_duoc_lam_hybrid_nem_integrity(corpus, tmp_path):  # noqa: F811
    """LỖI THẬT (đang FAIL). Bài đã ready bị sửa → pha ghi xoá chunk cũ + point Qdrant cũ, commit chunk mới, rồi
    `dense.sync_delta` lỗi (Modal 503) → BM25 KHÔNG được dựng lại. Snapshot BM25 trên đĩa vẫn trỏ chunk_id cũ đã bị xoá
    khỏi Postgres → mọi câu hỏi trúng bài đó ném `HybridIntegrityError` (kể cả allow_fallback) cho tới lượt sync thành
    công sau (after_crawl: đợi lượt cào kế tiếp)."""
    c, q = corpus, QdrantClient(":memory:")
    cfg = _cfg(tmp_path)
    _run(c, tmp_path, q)
    aid = c.execute("SELECT article_id FROM articles WHERE title LIKE 'Hà Nội%%' LIMIT 1").fetchone()[0]
    c.execute("UPDATE articles SET content_text = content_text || ' Bổ sung tin Hà Nội.', updated_at = now() "
              "WHERE article_id = %s", (aid,))
    with pytest.raises(RuntimeError):
        sync.sync_rag(c, cfg, ner_predictor=_Predictor(), qdrant=q, model_client=_FailingEncoder())
    retr = hybrid.HybridRetriever(c, {**cfg, "dense": {**cfg["dense"], "url": "http://localhost:6333"},
                                      "retrieval": {"branch_limit": 30, "rrf_k": 60}},
                                  bm25_index=bm25.BM25Index(cfg["bm25"]["root"]), qdrant=q, model=Encoder())
    try:
        retr.search("Hà Nội tuyến buýt", allow_fallback=True)
    except hybrid.HybridIntegrityError as exc:
        pytest.fail(f"sync lỗi giữa chừng để lại chỉ mục lệch, chat ném HybridIntegrityError: {exc}")


# ---------------------------------------------------------------------- xác nhận thiết kế (đang PASS)
def test_pha_ner_khong_giu_khoa_ghi_chat_van_doc_duoc(corpus, pg_url, tmp_path):  # noqa: F811
    """Trong lúc BamiBERT chạy, một kết nối khác lấy được khoá ĐỌC chia sẻ (chat không bị báo bận)."""
    c, q = corpus, QdrantClient(":memory:")
    seen = []

    class _Probe(_Predictor):
        def predict_texts(self, texts):
            with psycopg.connect(pg_url, autocommit=True) as chat:
                ok = chat.execute("SELECT pg_try_advisory_lock_shared(%s)", (prepare._LOCK,)).fetchone()[0]
                seen.append(ok)
                if ok:
                    chat.execute("SELECT pg_advisory_unlock_shared(%s)", (prepare._LOCK,))
            return super().predict_texts(texts)

    _run(c, tmp_path, q, pred=_Probe())
    assert seen and all(seen)


def test_hai_luot_sync_chong_nhau_ket_qua_van_nhat_quan(corpus, pg_url, tmp_path):  # noqa: F811
    """Mô phỏng hai tiến trình (API khác/CLI `make rag-sync`): lượt B chạy trọn vẹn trong lúc lượt A đang NER.
    A vào pha ghi sau và làm lại cùng bài — tốn công nhưng kết quả cuối phải nhất quán, hybrid tìm được."""
    c, q = corpus, QdrantClient(":memory:")
    cfg = _cfg(tmp_path)

    class _NestedB(_Predictor):
        def predict_texts(self, texts):
            if not hasattr(self, "_done"):
                self._done = True
                with psycopg.connect(pg_url, autocommit=True) as other:
                    sync.sync_rag(other, cfg, ner_predictor=_Predictor(), qdrant=q, model_client=Encoder())
            return super().predict_texts(texts)

    _run(c, tmp_path, q, pred=_NestedB())
    assert _summary(c, tmp_path)["pending_articles"] == 0
    n_chunks = c.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]
    assert q.count(cfg["dense"]["collection"], exact=True).count == n_chunks
    assert c.execute("SELECT count(*) FROM rag_index_status WHERE bm25_status <> 'ready' "
                     "OR qdrant_status <> 'ready'").fetchone()[0] == 0
    retr = hybrid.HybridRetriever(c, {**cfg, "dense": {**cfg["dense"], "url": "http://localhost:6333"},
                                      "retrieval": {"branch_limit": 30, "rrf_k": 60}},
                                  bm25_index=bm25.BM25Index(cfg["bm25"]["root"]), qdrant=q, model=Encoder())
    assert retr.search("Hà Nội")["hits"]


def test_bai_doi_giua_hai_pha_bi_bo_qua_va_bao_limited(corpus, pg_url, tmp_path):  # noqa: F811
    """Bài bị sửa trong lúc NER (trước pha ghi) → `skipped_changed`, `limited=True`, NER bản cũ KHÔNG được ghi."""
    c, q = corpus, QdrantClient(":memory:")
    aid = _ids(c)[0]

    class _EditDuringNer(_Predictor):
        def predict_texts(self, texts):
            with psycopg.connect(pg_url, autocommit=True) as crawler:
                crawler.execute("UPDATE articles SET content_text = content_text || ' Mới.', updated_at = now() "
                                "WHERE article_id = %s", (aid,))
            return super().predict_texts(texts)

    res = _run(c, tmp_path, q, pred=_EditDuringNer())
    assert res["skipped_changed"] == 1 and res["limited"] is True
    assert c.execute("SELECT count(*) FROM article_ner WHERE article_id = %s", (aid,)).fetchone()[0] == 0
    again = _run(c, tmp_path, q)
    assert again["ner_articles"] == 1 and _ner_matches_text(c, aid)
    assert _summary(c, tmp_path)["pending_articles"] == 0
