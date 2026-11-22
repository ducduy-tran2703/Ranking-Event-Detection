"""`sync_rag` trên Postgres tạm với NER/Qwen/Qdrant giả: bài bị sửa sau khi đã ready, giới hạn số bài, đếm bài chờ.

Không gọi GPU/Modal/mạng: Qdrant `:memory:`, embedding giả (`Encoder`), BM25 ghi vào tmp_path.
"""
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from qdrant_client import QdrantClient
from test_rag_dense import Encoder

from eventrank.ingest import contract, sink
from eventrank.rag import sync
from eventrank.rag.chunking import chunking_version

FIX = Path("tests/fixtures/rag")


class _Predictor:
    def __init__(self):
        self.texts = []

    def predict_texts(self, texts):
        self.texts += texts
        out = []
        for text in texts:
            s = text.find("Hà Nội")
            out.append([{"text": "Hà Nội", "label": "LOC", "start_char": s, "end_char": s + 6}] if s >= 0 else [])
        return out


def _cfg(tmp_path):
    return {"index_version": "rag_v1", "chunking": {"max_units": 40, "overlap_units": 8},
            "dense": {"url": "unused", "collection": "test", "batch_size": 8, "concurrency": 1},
            "bm25": {"root": str(tmp_path / "bm25"), "keep_snapshots": 2},
            "ner": {"ner_version": "fake"}, "sync": {"lock_wait_seconds": 0}}


@pytest.fixture
def corpus(pg_conn):
    sink.sync_sources(pg_conn, [{"source": "vnexpress", "display_name": "VnExpress"}])
    arts = [json.loads(line) for line in (FIX / "silver.jsonl").read_text(encoding="utf-8").splitlines()]
    sink.upsert_articles(pg_conn, [contract.validate_article(
        a, known_sources={"vnexpress"}, now=datetime(2026, 11, 4, tzinfo=UTC)) for a in arts], via="import_jsonl")
    return pg_conn


def _run(conn, tmp_path, q, **kw):
    return sync.sync_rag(conn, _cfg(tmp_path), ner_predictor=kw.pop("pred", _Predictor()), qdrant=q,
                         model_client=Encoder(), **kw)


def _summary(conn, tmp_path):
    cfg = _cfg(tmp_path)
    return sync.pending_summary(conn, index_version="rag_v1",
                                chunk_version=chunking_version(cfg["chunking"]["max_units"],
                                                               cfg["chunking"]["overlap_units"]))


def test_dong_bo_du_roi_chay_lai_khong_lam_gi(corpus, tmp_path):
    c, q = corpus, QdrantClient(":memory:")
    n = c.execute("SELECT count(*) FROM articles").fetchone()[0]
    assert n >= 2 and _summary(c, tmp_path) == {"pending_articles": n, "without_ner": n}
    res = _run(c, tmp_path, q)
    assert res["ner_articles"] == n and res["chunks_inserted"] > 0 and res["bm25_rebuilt"] is True
    assert res["qdrant_embedded"] == res["chunks_inserted"] and res["limited"] is False
    assert c.execute("SELECT count(*) FROM rag_index_status WHERE bm25_status <> 'ready' "
                     "OR qdrant_status <> 'ready'").fetchone()[0] == 0
    assert _summary(c, tmp_path)["pending_articles"] == 0
    again = _run(c, tmp_path, q)
    assert again["ner_articles"] == again["rechunk_articles"] == again["chunks_inserted"] == 0


def test_bai_crawler_sua_sau_khi_ready_duoc_quet_toan_kho_bat_lai(corpus, tmp_path):
    c, q = corpus, QdrantClient(":memory:")
    _run(c, tmp_path, q)
    aid = c.execute("SELECT article_id FROM articles ORDER BY article_id LIMIT 1").fetchone()[0]
    c.execute("UPDATE articles SET content_text = content_text || ' Bổ sung tin Hà Nội.', updated_at = now() "
              "WHERE article_id = %s", (aid,))
    assert _summary(c, tmp_path)["pending_articles"] == 1
    pred = _Predictor()
    res = _run(c, tmp_path, q, pred=pred)
    assert res["ner_articles"] == 1 and "Bổ sung tin Hà Nội." in pred.texts[0]
    canon = c.execute("SELECT canonical_text FROM article_ner WHERE article_id = %s", (aid,)).fetchone()[0]
    assert canon.endswith("Bổ sung tin Hà Nội.")
    assert _summary(c, tmp_path)["pending_articles"] == 0


def test_bai_sua_truong_khac_van_ban_chi_cham_updated_at_khong_chay_ner(corpus, tmp_path):
    c, q = corpus, QdrantClient(":memory:")
    _run(c, tmp_path, q)
    c.execute("UPDATE articles SET author = 'Phóng viên', updated_at = now() WHERE article_id = "
              "(SELECT min(article_id) FROM articles)")
    assert _summary(c, tmp_path)["pending_articles"] == 1
    res = _run(c, tmp_path, q)
    assert res["ner_articles"] == 0 and res["touched_articles"] == 1 and res["chunks_inserted"] == 0
    assert _summary(c, tmp_path)["pending_articles"] == 0


def test_max_articles_lay_bai_moi_dang_truoc_va_bao_con_lo_sau(corpus, tmp_path):
    c, q = corpus, QdrantClient(":memory:")
    n = c.execute("SELECT count(*) FROM articles").fetchone()[0]
    newest = c.execute("SELECT article_id FROM articles ORDER BY published_at DESC, article_id LIMIT %s",
                       (n - 1,)).fetchall()
    res = _run(c, tmp_path, q, max_articles=n - 1)
    assert res["ner_articles"] == n - 1 and res["limited"] is True
    done = {r[0] for r in c.execute("SELECT article_id FROM article_ner")}
    assert done == {r[0] for r in newest}
    assert _summary(c, tmp_path)["pending_articles"] == 1
    rest = _run(c, tmp_path, q, max_articles=n - 1)
    assert rest["ner_articles"] == 1 and rest["limited"] is False
    assert _summary(c, tmp_path)["pending_articles"] == 0


def test_chunk_thieu_dong_status_duoc_dung_lai_khong_lap_rong(corpus, tmp_path):
    """`_PENDING_WHERE` và `_CHUNK_INFO` cùng tiêu chí: chunk mất dòng rag_index_status → chia lại + index, một lượt là xong
    (trước đây bài bị coi là ready nhưng vẫn đếm là chờ → `limited` mãi, bộ lập lịch chạy rỗng mỗi phút)."""
    c, q = corpus, QdrantClient(":memory:")
    _run(c, tmp_path, q)
    c.execute("DELETE FROM rag_index_status WHERE chunk_id = (SELECT min(chunk_id::text)::uuid FROM rag_chunks)")
    assert _summary(c, tmp_path)["pending_articles"] == 1
    res = _run(c, tmp_path, q, max_articles=1)
    assert res["rechunk_articles"] == 1 and res["limited"] is False
    assert _summary(c, tmp_path)["pending_articles"] == 0
