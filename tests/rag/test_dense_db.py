import pytest
import test_bm25_db
from qdrant_client import QdrantClient
from test_dense import Encoder

from eventrank.rag import dense


@pytest.fixture
def indexed_corpus(pg_conn):
    return test_bm25_db.indexed_corpus.__wrapped__(pg_conn)


def test_real_status_hydration_and_reuse(indexed_corpus):
    c = indexed_corpus
    c.execute("UPDATE rag_index_status SET bm25_status='ready', error='bm25: retained'")
    q, model = QdrantClient(':memory:'), Encoder()
    count = c.execute('SELECT count(*) FROM rag_chunks').fetchone()[0]
    result = dense.build_from_db(c, q, model, collection='test')
    assert result['embedded'] == count and result['status_updated'] == count
    assert c.execute("SELECT count(*) FROM rag_index_status WHERE bm25_status='ready' "
                     "AND qdrant_status='ready' AND error='bm25: retained'").fetchone()[0] == count
    before = c.execute('SELECT chunk_id,updated_at FROM rag_index_status ORDER BY chunk_id').fetchall()
    assert dense.search(c, q, model, 'test', 'Hà Nội')
    again = dense.build_from_db(c, q, model, collection='test')
    assert again['embedded'] == again['status_updated'] == 0
    assert c.execute('SELECT chunk_id,updated_at FROM rag_index_status ORDER BY chunk_id').fetchall() == before
    c.execute("UPDATE articles SET title=title || ' changed'")
    with pytest.raises(ValueError, match='Stale'):
        dense.search(c, q, model, 'test', 'Hà Nội')


def test_real_failure_keeps_bm25_and_resumes(indexed_corpus, monkeypatch):
    c = indexed_corpus
    c.execute("UPDATE rag_index_status SET bm25_status='ready'")
    q, model = QdrantClient(':memory:'), Encoder()
    upsert = q.upsert
    monkeypatch.setattr(q, 'upsert', lambda **kw: (_ for _ in ()).throw(RuntimeError('disk')))
    with pytest.raises(RuntimeError):
        dense.build_from_db(c, q, model, collection='test')
    assert c.execute("SELECT count(*) FROM rag_index_status WHERE qdrant_status='failed' "
                     "AND bm25_status='ready' AND error='qdrant: RuntimeError'").fetchone()[0] > 0
    monkeypatch.setattr(q, 'upsert', upsert)
    assert dense.build_from_db(c, q, model, collection='test')['published']
    assert c.execute("SELECT count(*) FROM rag_index_status WHERE error IS NOT NULL").fetchone()[0] == 0
