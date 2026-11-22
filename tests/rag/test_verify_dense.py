import pytest
import test_rag_dense as test_dense

from eventrank.rag import dense, verify_dense


@pytest.fixture
def corpus(monkeypatch):
    return test_dense.setup.__wrapped__(monkeypatch)


def test_resume_verification_fails_closed_for_missing_vectors(corpus, monkeypatch):
    q, encoder, _ = corpus
    dense.build_from_db(None, q, encoder, collection='guard')
    monkeypatch.setattr(q, 'retrieve', lambda *a, **kw: [])
    monkeypatch.setattr(verify_dense, '_statuses', lambda _: {'rows': 1, 'sha256': 'same'})
    config = {'index_version': 'rag_v1', 'dense': {'collection': 'guard', 'batch_size': 32}}
    with pytest.raises(ValueError, match='Resume attempted an embedding call'):
        verify_dense.verify_resume(None, q, config)
    assert q.count('guard').count == 1


def test_resume_verification_proves_no_embedding_or_status_change(corpus, monkeypatch):
    q, encoder, _ = corpus
    dense.build_from_db(None, q, encoder, collection='guard')
    monkeypatch.setattr(verify_dense, '_statuses', lambda _: {'rows': 1, 'sha256': 'same'})
    config = {'index_version': 'rag_v1', 'dense': {'collection': 'guard', 'batch_size': 32}}
    report = verify_dense.verify_resume(None, q, config)
    assert report['passed'] and report['embedding_calls'] == 0
    assert report['build_result']['embedded'] == report['build_result']['status_updated'] == 0


def test_resume_verification_detects_status_timestamp_change(corpus, monkeypatch):
    q, encoder, _ = corpus
    dense.build_from_db(None, q, encoder, collection='guard')
    fingerprints = iter([{'rows': 1, 'sha256': 'before'}, {'rows': 1, 'sha256': 'after'}])
    monkeypatch.setattr(verify_dense, '_statuses', lambda _: next(fingerprints))
    config = {'index_version': 'rag_v1', 'dense': {'collection': 'guard', 'batch_size': 32}}
    with pytest.raises(ValueError, match='DB status/error/updated_at changed'):
        verify_dense.verify_resume(None, q, config)
