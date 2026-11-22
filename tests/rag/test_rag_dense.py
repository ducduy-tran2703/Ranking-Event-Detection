import json
import threading
import uuid
from contextlib import nullcontext
from pathlib import Path

import pytest
from qdrant_client import QdrantClient
from qdrant_client import models as qm

from eventrank.rag import dense
from eventrank.rag.models import load_model_config


class Encoder:
    config = load_model_config({})

    def __init__(self):
        self.calls = []

    def embed(self, texts, *, input_type):
        self.calls.append((texts, input_type))
        return [[1.0] + [0.0] * 1023 for _ in texts]


@pytest.fixture
def setup(monkeypatch):
    raw = json.loads(Path('tests/fixtures/rag/silver.jsonl').read_text(encoding='utf-8').splitlines()[0])
    records = [{'chunk_id': '00000000-0000-0000-0000-000000000001',
                    'article_id': raw['article_id'], 'text': raw['title'], 'start_char': 0,
                    'end_char': len(raw['title']), 'chunking_version': 'test', 'title': raw['title'],
                    'url': raw['url'], 'source': 'vnexpress', 'published_at': '2026-09-01T00:00:00+07:00'}]
    state = {}
    monkeypatch.setattr(dense, '_snapshot', lambda *a: records)
    monkeypatch.setattr(dense, '_preparation_lock', lambda *a: nullcontext())
    monkeypatch.setattr(dense, '_mark', lambda conn, ids, version, status, error=None:
                        sum(state.setdefault(cid, status) != status for cid in ids))
    return QdrantClient(':memory:'), Encoder(), records


def test_resume_and_search_filters(setup, monkeypatch):
    q, model, records = setup
    first = dense.build_from_db(None, q, model, collection='test', pilot=1)
    assert not first['published'] and first['embedded'] == 1
    with pytest.raises(ValueError, match='published'):
        dense.search(None, q, model, 'test', 'Hà Nội')
    result = dense.build_from_db(None, q, model, collection='test')
    assert result['published'] and result['embedded'] == 0
    assert len(model.calls) == 1
    monkeypatch.setattr(dense, '_hydrate', lambda conn, ids, version: {r['chunk_id']: r for r in records})
    hits = dense.search(None, q, model, 'test', 'Hà Nội', source='VNEXPRESS',
                        date_from='2026-09-01', date_to='2026-09-01')
    assert hits[0]['chunk_id'] == records[0]['chunk_id']
    assert model.calls[-1][1] == 'query'
    assert not dense.search(None, q, model, 'test', 'Hà Nội', date_from='2026-09-02')
    again = dense.build_from_db(None, q, model, collection='test')
    assert again['embedded'] == 0


def test_wrong_version_dimension_and_corpus_rejected(setup):
    q, model, records = setup
    dense.build_from_db(None, q, model, collection='test')
    records[0]['text'] += '!'
    records[0]['end_char'] += 1
    with pytest.raises(ValueError, match='binding'):
        dense.build_from_db(None, q, model, collection='test')
    q.create_collection('bad', vectors_config=qm.VectorParams(size=3, distance=qm.Distance.COSINE))
    with pytest.raises(ValueError, match='dimension'):
        dense.build_from_db(None, q, model, collection='bad')


def test_upsert_failure_never_ready(setup, monkeypatch):
    q, model, _ = setup
    marked = []
    monkeypatch.setattr(dense, '_mark', lambda *a, **kw: marked.append(a[3]) or 0)
    monkeypatch.setattr(q, 'upsert', lambda **kw: (_ for _ in ()).throw(RuntimeError('disk')))
    with pytest.raises(RuntimeError, match='disk'):
        dense.build_from_db(None, q, model, collection='test')
    assert marked == ['failed']
    assert not q.get_collection('test').config.metadata['published']


def test_status_failure_resumes_without_model(setup, monkeypatch):
    q, model, _ = setup
    monkeypatch.setattr(dense, '_mark', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('db')))
    with pytest.raises(RuntimeError, match='db'):
        dense.build_from_db(None, q, model, collection='test')
    monkeypatch.setattr(dense, '_mark', lambda *a, **kw: 0)
    assert dense.build_from_db(None, q, model, collection='test')['embedded'] == 0
    assert len(model.calls) == 1


def test_invalid_vector_rejected_before_upsert(setup, monkeypatch):
    q, model, _ = setup
    monkeypatch.setattr(model, 'embed', lambda *a, **kw: [[1.0]])
    with pytest.raises(ValueError, match='dimension'):
        dense.build_from_db(None, q, model, collection='test')
    assert q.count('test').count == 0


def test_model_version_guard_before_query_embedding(setup):
    import copy

    q, model, _ = setup
    dense.build_from_db(None, q, model, collection='test')
    model.config = copy.deepcopy(model.config)
    model.config['embedding']['revision'] = '0' * 40
    calls = len(model.calls)
    with pytest.raises(ValueError, match='version'):
        dense.search(None, q, model, 'test', 'Hà Nội')
    assert len(model.calls) == calls


def test_corrupt_point_rejected_on_resume(setup):
    q, model, records = setup
    dense.build_from_db(None, q, model, collection='test', pilot=1)
    q.set_payload('test', {'text_sha256': 'bad'}, points=[records[0]['chunk_id']])
    with pytest.raises(ValueError, match='hash/version'):
        dense.build_from_db(None, q, model, collection='test')
    assert not q.get_collection('test').config.metadata['published']


def test_corpus_change_during_embedding_blocks_publication(setup, monkeypatch):
    q, model, records = setup
    embed = model.embed

    def changed(*args, **kwargs):
        vectors = embed(*args, **kwargs)
        records[0]['title'] += ' changed'
        return vectors

    monkeypatch.setattr(model, 'embed', changed)
    with pytest.raises(ValueError, match='corpus changed'):
        dense.build_from_db(None, q, model, collection='test')
    assert not q.get_collection('test').config.metadata['published']


@pytest.mark.parametrize('transient_status', [408, 503])
def test_transient_retry_and_no_retry_for_token_limit(setup, monkeypatch, transient_status):
    q, model, _ = setup
    embed = model.embed
    attempts = []
    monkeypatch.setattr(dense.time, 'sleep', lambda _: None)

    def flaky(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError(f'Model service returned HTTP {transient_status}')
        return embed(*args, **kwargs)

    monkeypatch.setattr(model, 'embed', flaky)
    assert dense.build_from_db(None, q, model, collection='retry')['published']
    assert len(attempts) == 2
    attempts.clear()

    def too_long(*args, **kwargs):
        attempts.append(1)
        raise RuntimeError('Model service returned HTTP 413')

    monkeypatch.setattr(model, 'embed', too_long)
    with pytest.raises(RuntimeError, match='413'):
        dense.build_from_db(None, q, model, collection='token-limit')
    assert len(attempts) == 1


def test_four_batches_in_parallel_single_writer_and_resume(setup, monkeypatch):
    q, model, records = setup
    original = records[0]
    records[:] = [{**original, 'chunk_id': str(uuid.UUID(int=i))} for i in range(1, 9)]
    barrier = threading.Barrier(4)
    main_thread = threading.get_ident()
    workers = set()

    def embed(texts, *, input_type):
        workers.add(threading.get_ident())
        barrier.wait(timeout=5)
        return [[1.0] + [0.0] * 1023 for _ in texts]

    monkeypatch.setattr(model, 'embed', embed)
    upsert = q.upsert

    def write(**kwargs):
        assert threading.get_ident() == main_thread
        return upsert(**kwargs)

    monkeypatch.setattr(q, 'upsert', write)
    result = dense.build_from_db(None, q, model, collection='parallel', batch_size=1, concurrency=4)
    assert result['published'] and result['embedded'] == 8
    assert len(workers) == 4
    monkeypatch.setattr(model, 'embed', lambda *a, **kw: pytest.fail('Must reuse vectors'))
    assert dense.build_from_db(None, q, model, collection='parallel', concurrency=4)['embedded'] == 0


def test_parallel_failure_drains_successful_inflight_batches(setup, monkeypatch):
    q, model, records = setup
    records[:] = [{**records[0], 'chunk_id': str(uuid.UUID(int=i)),
                   'text': str(i), 'end_char': 1} for i in range(1, 9)]
    barrier = threading.Barrier(4)

    def embed(texts, *, input_type):
        barrier.wait(timeout=5)
        if texts == ['1']:
            raise ValueError('bad input')
        return [[1.0] + [0.0] * 1023 for _ in texts]

    monkeypatch.setattr(model, 'embed', embed)
    with pytest.raises(ValueError, match='bad input'):
        dense.build_from_db(None, q, model, collection='parallel', batch_size=1, concurrency=4)
    assert q.count('parallel').count >= 3
    assert not q.get_collection('parallel').config.metadata['published']
