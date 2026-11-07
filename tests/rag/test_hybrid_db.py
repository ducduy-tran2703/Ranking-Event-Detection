import pytest
import test_bm25_db
from qdrant_client import QdrantClient
from test_dense import Encoder

from eventrank.rag import bm25, dense, hybrid


@pytest.fixture
def prepared_hybrid(pg_conn, tmp_path):
    conn = test_bm25_db.indexed_corpus.__wrapped__(pg_conn)
    root = tmp_path / 'bm25'
    bm25.build_from_db(conn, root)
    q, model = QdrantClient(':memory:'), Encoder()
    dense.build_from_db(conn, q, model, collection='fixture')
    config = {'index_version': 'rag_v1', 'bm25': {'root': str(root)},
              'dense': {'url': 'http://localhost:6333', 'collection': 'fixture'},
              'retrieval': {'branch_limit': 30, 'rrf_k': 60}}
    r = hybrid.HybridRetriever(conn, config, bm25_index=bm25.BM25Index(root), qdrant=q, model=model)
    yield conn, r
    q.close()


def test_real_engines_hydrate_filters_and_leave_status_unchanged(prepared_hybrid):
    c, r = prepared_hybrid
    before = c.execute('SELECT * FROM rag_index_status ORDER BY chunk_id').fetchall()
    result = r.search('Hà Nội', limit=10)
    assert result['mode'] == 'hybrid' and result['hits']
    ids = {h['chunk_id'] for h in result['trace']['candidates']}
    expected = {h['chunk_id'] for b in result['trace']['branches'].values() for h in b['hits']}
    assert ids == expected
    first = result['hits'][0]
    day = first['published_at'][:10]
    filtered = r.search('Hà Nội', source='VNEXPRESS', date_from=day, date_to=day)
    assert filtered['hits']
    assert all(h['source'] == 'vnexpress' and h['published_at'].startswith(day) for h in filtered['hits'])
    empty = r.search('Hà Nội', source='__absent__')
    assert empty['mode'] == 'hybrid' and empty['hits'] == []
    assert c.execute('SELECT * FROM rag_index_status ORDER BY chunk_id').fetchall() == before


def test_bm25_fallback_does_not_require_qdrant_ready(prepared_hybrid, monkeypatch):
    c, r = prepared_hybrid
    c.execute("UPDATE rag_index_status SET qdrant_status='failed'")
    monkeypatch.setattr(r.q, 'get_collection', lambda *a: (_ for _ in ()).throw(ConnectionError()))
    result = r.search('Hà Nội', allow_fallback=True)
    assert result['mode'] == 'bm25_only' and result['hits']
    assert c.execute("SELECT count(*) FROM rag_index_status WHERE qdrant_status='failed'").fetchone()[0] > 0


def test_changed_article_metadata_cannot_be_returned_as_current_evidence(prepared_hybrid):
    c, r = prepared_hybrid
    c.execute("UPDATE articles SET title=title || ' changed'")
    with pytest.raises(hybrid.HybridIntegrityError):
        r.search('Hà Nội', allow_fallback=True)
