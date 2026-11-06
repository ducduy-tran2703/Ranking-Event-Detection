import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eventrank.ingest import contract, sink
from eventrank.rag import bm25
from eventrank.rag.prepare import build_chunks, import_ner


@pytest.fixture
def indexed_corpus(pg_conn):
    root = Path("tests/fixtures/rag")
    sink.sync_sources(pg_conn, [{"source": "vnexpress", "display_name": "VnExpress"}])
    articles = [json.loads(line) for line in (root / "silver.jsonl").read_text(encoding="utf-8").splitlines()]
    sink.upsert_articles(pg_conn, [contract.validate_article(
        a, known_sources={"vnexpress"}, now=datetime(2026, 11, 4, tzinfo=UTC))
        for a in articles[:2]], via="import_jsonl")
    import_ner(pg_conn, str(root / "silver.jsonl"), root / "ner.jsonl", ner_version="sample")
    build_chunks(pg_conn, max_units=15, overlap_units=3)
    return pg_conn


def test_publish_ready_reuse_va_giu_nguyen_qdrant(indexed_corpus, tmp_path):
    c = indexed_corpus
    c.execute("UPDATE rag_index_status SET qdrant_status='failed',error='qdrant: timeout'")
    n = c.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]
    first = bm25.build_from_db(c, tmp_path / "bm25")
    assert first["documents"] == n and first["status_updated"] == n and not first["reused"]
    assert bm25.BM25Index(tmp_path / "bm25").search("Hà Nội")
    assert c.execute("SELECT count(*) FROM rag_index_status WHERE bm25_status='ready' "
                     "AND qdrant_status='failed' AND error='qdrant: timeout'").fetchone()[0] == n
    before = c.execute("SELECT chunk_id,updated_at FROM rag_index_status ORDER BY chunk_id").fetchall()
    second = bm25.build_from_db(c, tmp_path / "bm25")
    assert second["reused"] and second["status_updated"] == 0
    assert second["index_dir"] == first["index_dir"]
    assert c.execute("SELECT chunk_id,updated_at FROM rag_index_status ORDER BY chunk_id").fetchall() == before


def test_build_loi_giu_index_cu_va_khong_bao_ready(indexed_corpus, tmp_path, monkeypatch):
    c = indexed_corpus
    root = tmp_path / "bm25"
    bm25.build_from_db(c, root)
    pointer = (root / "CURRENT.json").read_bytes()
    c.execute("UPDATE articles SET title=title || ' mới'")
    c.execute("UPDATE rag_index_status SET bm25_status='pending'")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(bm25, "create_index", fail)
    with pytest.raises(OSError, match="disk full"):
        bm25.build_from_db(c, root)
    assert (root / "CURRENT.json").read_bytes() == pointer
    assert bm25.BM25Index(root).search("Hà Nội")
    assert c.execute("SELECT count(*) FROM rag_index_status WHERE bm25_status='ready'").fetchone()[0] == 0


def test_corpus_doi_trong_luc_build_khong_publish(indexed_corpus, tmp_path, monkeypatch):
    c = indexed_corpus
    create = bm25.create_index

    def changed(*args, **kwargs):
        manifest = create(*args, **kwargs)
        c.execute("UPDATE articles SET title=title || ' sửa'")
        return manifest

    monkeypatch.setattr(bm25, "create_index", changed)
    with pytest.raises(ValueError, match="corpus"):
        bm25.build_from_db(c, tmp_path / "bm25")
    assert not (tmp_path / "bm25" / "CURRENT.json").exists()
    assert c.execute("SELECT count(*) FROM rag_index_status WHERE bm25_status='ready'").fetchone()[0] == 0


def test_index_version_khong_khop_phai_chan(indexed_corpus, tmp_path):
    indexed_corpus.execute("UPDATE rag_index_status SET index_version='khac'")
    with pytest.raises(ValueError, match="index_version"):
        bm25.build_from_db(indexed_corpus, tmp_path / "bm25")
    assert not (tmp_path / "bm25" / "CURRENT.json").exists()
