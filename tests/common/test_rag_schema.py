"""Kiểm ràng buộc RAG bằng Postgres thật trong database tạm của fixture pg_conn."""
import hashlib
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb


@pytest.fixture
def rag_article(pg_conn):
    conn = pg_conn
    aid = hashlib.sha256(b"https://example.test/rag").hexdigest()
    conn.execute("INSERT INTO sources (source, display_name) VALUES ('sample', 'Sample')")
    conn.execute(
        "INSERT INTO articles (article_id, url, source, category, title, sapo, "
        "published_at, content_text, ingested_via, parser_version, content_hash) "
        "VALUES (%s, 'https://example.test/rag', 'sample', 'Tin', 'Tin', '', "
        "now(), 'Hà Nội', 'import_jsonl', 'sample', %s)", (aid, "a" * 64))
    text = "Tiêu đề: Hà Nội"
    conn.execute(
        "INSERT INTO article_ner (article_id, canonical_text, text_hash, ner_version, entities) "
        "VALUES (%s, %s, %s, 'ner-test', %s)",
        (aid, text, hashlib.sha256(text.encode()).hexdigest(),
         Jsonb([{"text": "Hà Nội", "label": "LOC", "start_char": 9, "end_char": 15}])))
    return conn, aid


def _chunk(conn, aid, **overrides):
    values = {"chunk_id": uuid.uuid4(), "article_id": aid, "chunk_index": 0,
              "text": "Hà Nội", "start_char": 9, "end_char": 15, "chunking_version": "c1"}
    values.update(overrides)
    conn.execute(
        "INSERT INTO rag_chunks (chunk_id, article_id, chunk_index, text, start_char, "
        "end_char, chunking_version) VALUES (%(chunk_id)s, %(article_id)s, %(chunk_index)s, "
        "%(text)s, %(start_char)s, %(end_char)s, %(chunking_version)s)", values)
    return values["chunk_id"]


def test_ner_chunk_status_join_and_retry(rag_article):
    conn, aid = rag_article
    cid = _chunk(conn, aid)
    conn.execute("INSERT INTO rag_index_status (chunk_id, index_version) VALUES (%s, 'i1')", (cid,))
    assert conn.execute(
        "SELECT a.article_id, n.ner_version, c.text, s.bm25_status, s.qdrant_status "
        "FROM articles a JOIN article_ner n USING (article_id) "
        "JOIN rag_chunks c USING (article_id) JOIN rag_index_status s USING (chunk_id)"
    ).fetchone() == (aid, "ner-test", "Hà Nội", "pending", "pending")
    conn.execute("UPDATE rag_index_status SET bm25_status='ready', qdrant_status='failed', "
                 "error='qdrant: timeout', updated_at=now() WHERE chunk_id=%s", (cid,))
    conn.execute("UPDATE rag_index_status SET qdrant_status='ready', error=NULL, "
                 "updated_at=now() WHERE chunk_id=%s", (cid,))
    assert conn.execute("SELECT bm25_status,qdrant_status,error FROM rag_index_status "
                        "WHERE chunk_id=%s", (cid,)).fetchone() == ("ready", "ready", None)


@pytest.mark.parametrize("overrides", [
    {"start_char": -1}, {"end_char": 9}, {"text": "sai độ dài"},
    {"chunk_index": -1}, {"chunking_version": " "},
])
def test_reject_invalid_chunk(rag_article, overrides):
    conn, aid = rag_article
    with pytest.raises(psycopg.errors.CheckViolation):
        _chunk(conn, aid, **overrides)


def test_foreign_keys_and_unique_chunk(rag_article):
    conn, aid = rag_article
    cid = _chunk(conn, aid)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _chunk(conn, aid)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _chunk(conn, "b" * 64)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("INSERT INTO rag_index_status (chunk_id,index_version) VALUES (%s,'i1')",
                     (uuid.uuid4(),))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("DELETE FROM article_ner WHERE article_id=%s", (aid,))
    conn.execute("INSERT INTO rag_index_status (chunk_id,index_version) VALUES (%s,'i1')", (cid,))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE rag_index_status SET bm25_status='unknown' WHERE chunk_id=%s", (cid,))


def test_ner_requires_array_and_sha256(rag_article):
    conn, aid = rag_article
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE article_ner SET entities='{}'::jsonb WHERE article_id=%s", (aid,))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE article_ner SET text_hash='bad' WHERE article_id=%s", (aid,))
