import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eventrank.ingest import contract, sink
from eventrank.rag.prepare import build_chunks, import_ner

FIXTURES = Path("tests/fixtures/rag")


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def corpus(pg_conn):
    sink.sync_sources(pg_conn, [{"source": "vnexpress", "display_name": "VnExpress"}])
    arts = _rows(FIXTURES / "silver.jsonl")
    sink.upsert_articles(pg_conn, [contract.validate_article(
        a, known_sources={"vnexpress"}, now=datetime(2026, 11, 4, tzinfo=UTC))
        for a in arts[:2]], via="import_jsonl")
    return pg_conn


def _import(conn, **kwargs):
    return import_ner(conn, str(FIXTURES / "silver.jsonl"),
                      FIXTURES / "ner.jsonl", ner_version="ner-test", **kwargs)


def test_import_join_offset_idempotent_va_bai_ngoai_db(corpus):
    c = corpus
    first = _import(c)
    assert first["inserted"] == 2 and first["outside_db"] == 1
    before = c.execute("SELECT article_id,updated_at FROM article_ner ORDER BY article_id").fetchall()
    assert _import(c)["unchanged"] == 2
    assert c.execute("SELECT article_id,updated_at FROM article_ner ORDER BY article_id").fetchall() == before
    for text, entities in c.execute("SELECT canonical_text,entities FROM article_ner"):
        for e in entities:
            assert text[e["start_char"]:e["end_char"]] == e["text"]


def test_preflight_loi_entity_khong_ghi_nua_kho(corpus, tmp_path):
    rows = _rows(FIXTURES / "ner.jsonl")
    rows[1]["entities"][0]["start_char"] += 1
    bad = tmp_path / "ner.jsonl"
    bad.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    with pytest.raises(ValueError):
        import_ner(corpus, str(FIXTURES / "silver.jsonl"), bad, ner_version="test")
    assert corpus.execute("SELECT count(*) FROM article_ner").fetchone()[0] == 0


def test_khong_nhap_ner_cu_khi_bai_trong_db_da_sua(corpus):
    corpus.execute("UPDATE articles SET content_hash=%s", ("b" * 64,))
    with pytest.raises(ValueError, match="content_hash"):
        _import(corpus)
    assert corpus.execute("SELECT count(*) FROM article_ner").fetchone()[0] == 0


def test_dry_run_khong_ghi_db(corpus):
    assert _import(corpus, dry_run=True)["inserted"] == 2
    assert corpus.execute("SELECT count(*) FROM article_ner").fetchone()[0] == 0
    _import(corpus)
    assert build_chunks(corpus, max_units=15, overlap_units=3, dry_run=True)["inserted_chunks"] > 2
    assert corpus.execute("SELECT count(*) FROM rag_chunks").fetchone()[0] == 0


def test_chunk_va_status_pending_chay_lai_khong_reset_ready(corpus):
    _import(corpus)
    first = build_chunks(corpus, max_units=15, overlap_units=3)
    n = first["inserted_chunks"]
    assert n > 2
    assert corpus.execute("SELECT count(*) FROM rag_index_status WHERE bm25_status='pending' "
                          "AND qdrant_status='pending'").fetchone()[0] == n
    corpus.execute("UPDATE rag_index_status SET bm25_status='ready',qdrant_status='ready'")
    before = corpus.execute("SELECT chunk_id,updated_at FROM rag_index_status ORDER BY chunk_id").fetchall()
    again = build_chunks(corpus, max_units=15, overlap_units=3)
    assert again["inserted_chunks"] == 0 and again["unchanged_chunks"] == n
    assert _import(corpus)["unchanged"] == 2
    assert corpus.execute("SELECT chunk_id,updated_at FROM rag_index_status ORDER BY chunk_id").fetchall() == before
    assert corpus.execute("SELECT count(*) FROM rag_chunks c JOIN article_ner n USING(article_id) "
                          "WHERE c.text <> substring(n.canonical_text FROM c.start_char+1 "
                          "FOR c.end_char-c.start_char)").fetchone()[0] == 0


def test_doi_chunking_khi_pending_duoc_nhung_ready_phai_chan(corpus):
    _import(corpus)
    build_chunks(corpus, max_units=15, overlap_units=3)
    build_chunks(corpus, max_units=18, overlap_units=3)
    corpus.execute("UPDATE rag_index_status SET qdrant_status='ready'")
    before = corpus.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]
    with pytest.raises(ValueError, match="index"):
        build_chunks(corpus, max_units=20, overlap_units=3)
    assert corpus.execute("SELECT count(*) FROM rag_chunks").fetchone()[0] == before
