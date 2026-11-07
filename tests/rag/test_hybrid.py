import copy
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from qdrant_client import models as qm

from eventrank.rag import dense, hybrid
from eventrank.rag.models import embedding_version, load_model_config

_HITS = json.loads(Path('tests/fixtures/rag/hybrid_hits.json').read_text('utf-8'))


def hit(number, rank, score):
    return {**_HITS[number - 1], 'rank': rank, 'score': score}


def test_rrf_uses_rank_deduplicates_and_keeps_branch_scores():
    a, b = hit(1, 1, 10000), hit(2, 2, 100)
    other_b, c = hit(2, 1, 0.9), hit(3, 2, 0.8)
    fused = hybrid.rrf_fuse({'bm25': [a, b, b], 'dense': [other_b, c]}, k=60)
    assert [r['chunk_id'] for r in fused] == [b['chunk_id'], a['chunk_id'], c['chunk_id']]
    assert fused[0]['rrf_score'] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[0]['branches'] == {'bm25': {'rank': 2, 'score': 100.0},
                                    'dense': {'rank': 1, 'score': 0.9}}
    assert len(fused) == 3


def test_rrf_ties_are_deterministic_and_branch_order_independent():
    a, b = hit(1, 1, 0.1), hit(2, 1, 10000)
    expected = hybrid.rrf_fuse({'bm25': [b], 'dense': [a]})
    assert hybrid.rrf_fuse({'dense': [a], 'bm25': [b]}) == expected
    assert [r['chunk_id'] for r in expected] == [a['chunk_id'], b['chunk_id']]


@pytest.mark.parametrize('rank,score', [(0, 1), (True, 1), (1, float('nan'))])
def test_invalid_branch_rank_or_score_rejected(rank, score):
    with pytest.raises(hybrid.HybridIntegrityError):
        hybrid.rrf_fuse({'bm25': [hit(1, rank, score)]})


@pytest.fixture
def retriever(monkeypatch):
    model = SimpleNamespace(config=load_model_config({}))
    binding = {'schema_version': 1, 'index_version': 'rag_v1', 'corpus_sha256': 'a' * 64,
               'documents': 3, 'dimension': 1024, 'input_view': dense.INPUT_VIEW,
               'chunking_versions': ['fixture'],
               'embedding_version': embedding_version(model.config['embedding'])}
    manifest = {'schema_version': 1, 'index_version': 'rag_v1', 'corpus_sha256': 'a' * 64,
                'documents': 3, 'analyzer': 'fixture', 'tantivy': 'fixture'}
    calls = []
    records = {h['chunk_id']: hybrid._normalize_record(h) for h in [hit(1, 1, 1), hit(2, 2, 1), hit(3, 3, 1)]}

    class Lexical:
        path = Path('snapshot-fixture')

        def __init__(self):
            self.manifest = manifest

        def search(self, query, **kwargs):
            calls.append(('bm25', kwargs))
            return [hit(1, 1, 9), hit(2, 2, 8)]

    def vector(*args, **kwargs):
        calls.append(('dense', kwargs))
        return [hit(2, 1, 0.9), hit(3, 2, 0.8)]

    q = SimpleNamespace(get_collection=lambda _: SimpleNamespace(
        config=SimpleNamespace(metadata={'binding': binding, 'published': True},
                               params=SimpleNamespace(vectors=qm.VectorParams(
                                   size=1024, distance='Cosine')))))
    monkeypatch.setattr(dense, 'search', vector)
    monkeypatch.setattr(hybrid, '_hydrate_candidates', lambda *a: {
        cid: (record, {'bm25': 'ready', 'dense': 'ready'}) for cid, record in records.items()})
    config = {'index_version': 'rag_v1', 'dense': {'collection': 'fixture', 'url': 'http://localhost:6333'},
              'bm25': {'root': 'unused'}, 'retrieval': {'branch_limit': 30, 'rrf_k': 60}}
    r = hybrid.HybridRetriever(None, config, bm25_index=Lexical(), qdrant=q, model=model)
    return r, calls, binding, records


def test_hybrid_hydrates_union_and_applies_same_filters(retriever):
    r, calls, _, _ = retriever
    result = r.search('khôi phục điện', source='VNEXPRESS', date_from='2026-09-10', date_to='2026-09-10')
    assert result['mode'] == 'hybrid' and not result['degraded']
    assert result['hits'][0]['chunk_id'] == hit(2, 1, 1)['chunk_id']
    assert len(result['trace']['candidates']) == len(result['hits']) == 3
    assert result['hits'][0]['url'] == 'https://example.test/2'
    for _, kwargs in calls:
        assert kwargs['limit'] == 30 and kwargs['source'] == 'vnexpress'
        assert kwargs['date_from'] == kwargs['date_to'] == '2026-09-10'


def test_dense_outage_requires_explicit_fallback_and_never_leaks_error(retriever, monkeypatch):
    r, _, _, _ = retriever

    def fail(*a, **kw):
        raise RuntimeError('https://secret:token@private.example')

    monkeypatch.setattr(dense, 'search', fail)
    with pytest.raises(hybrid.HybridUnavailableError):
        r.search('điện')
    result = r.search('điện', allow_fallback=True)
    assert result['mode'] == 'bm25_only' and result['degraded']
    assert result['trace']['branches']['dense']['status'] == 'error'
    assert 'token' not in str(result)
    assert len(result['hits']) == 2


def test_bm25_outage_falls_back_to_dense_only(retriever, monkeypatch):
    r, _, _, _ = retriever
    r.bm25 = None
    monkeypatch.setattr(hybrid, 'BM25Index', lambda _: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(hybrid.HybridUnavailableError):
        r.search('điện')
    result = r.search('điện', allow_fallback=True)
    assert result['mode'] == 'dense_only' and result['degraded']


def test_both_branches_down_is_an_error(retriever, monkeypatch):
    r, _, _, _ = retriever
    r.bm25 = None
    monkeypatch.setattr(hybrid, 'BM25Index', lambda _: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(dense, 'search', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(hybrid.HybridUnavailableError):
        r.search('điện', allow_fallback=True)


def test_version_mismatch_never_falls_back_or_calls_model(retriever):
    r, calls, binding, _ = retriever
    binding['corpus_sha256'] = 'b' * 64
    with pytest.raises(hybrid.HybridIntegrityError):
        r.search('điện', allow_fallback=True)
    assert not any(name == 'dense' for name, _ in calls)


def test_stale_bm25_evidence_is_rejected(retriever):
    r, _, _, records = retriever
    records[hit(1, 1, 1)['chunk_id']]['title'] = 'changed'
    with pytest.raises(hybrid.HybridIntegrityError):
        r.search('điện', allow_fallback=True)


@pytest.mark.parametrize('kwargs', [{'limit': 0}, {'date_from': 'bad'},
                                    {'date_from': '2026-09-12', 'date_to': '2026-09-10'}])
def test_invalid_request_does_not_run_branches(retriever, kwargs):
    r, calls, _, _ = retriever
    with pytest.raises(ValueError):
        r.search('điện', **kwargs)
    assert not calls


def test_model_version_mismatch_is_integrity_error(retriever):
    r, calls, _, _ = retriever
    r.model = SimpleNamespace(config=copy.deepcopy(r.model.config))
    r.model.config['embedding']['revision'] = '0' * 40
    with pytest.raises(hybrid.HybridIntegrityError):
        r.search('điện', allow_fallback=True)
    assert not any(name == 'dense' for name, _ in calls)


def test_empty_healthy_branch_does_not_mean_fallback(retriever, monkeypatch):
    r, _, _, _ = retriever
    monkeypatch.setattr(r.bm25, 'search', lambda *a, **kw: [])
    result = r.search('điện')
    assert result['mode'] == 'hybrid' and not result['degraded']
    assert result['trace']['branches']['bm25'] == {'status': 'ok', 'hits': []}


def test_database_failure_keeps_branch_trace_but_never_uses_stored_text(retriever, monkeypatch):
    r, _, _, _ = retriever

    def fail(*a):
        raise RuntimeError('postgresql://secret:password@private')

    monkeypatch.setattr(hybrid, '_hydrate_candidates', fail)
    with pytest.raises(hybrid.HybridUnavailableError) as error:
        r.search('điện', allow_fallback=True)
    trace = error.value.trace
    assert all(trace['branches'][b]['status'] == 'ok' for b in ('bm25', 'dense'))
    assert len(trace['candidates']) == 3 and trace['mode'] == 'failed'
    assert 'password' not in str(trace)


def test_invalid_backend_score_is_not_written_as_nan_in_trace(retriever, monkeypatch):
    r, _, _, _ = retriever
    monkeypatch.setattr(r.bm25, 'search', lambda *a, **kw: [hit(1, 1, float('nan'))])
    with pytest.raises(hybrid.HybridIntegrityError) as error:
        r.search('điện', allow_fallback=True)
    json.dumps(error.value.trace, allow_nan=False)
    assert error.value.trace['branches']['bm25']['status'] == 'error'


def test_cli_writes_failed_trace_and_refuses_overwrite(tmp_path, monkeypatch, capsys):
    trace_path = tmp_path / 'trace.json'
    monkeypatch.setattr(hybrid.db, 'connect', lambda: nullcontext(None))

    class Failing:
        def __init__(self, *a):
            pass

        def search(self, *a, **kw):
            raise hybrid.HybridUnavailableError('Dense unavailable', {'mode': 'failed'})

        def close(self):
            pass

    monkeypatch.setattr(hybrid, 'HybridRetriever', Failing)
    assert hybrid.main(['search', 'điện', '--trace', str(trace_path)]) == 1
    saved = trace_path.read_bytes()
    assert json.loads(saved)['mode'] == 'failed'
    with pytest.raises(SystemExit):
        hybrid.main(['search', 'điện', '--trace', str(trace_path)])
    assert trace_path.read_bytes() == saved
    capsys.readouterr()


def test_inclusive_day_filter_keeps_fractional_last_second(retriever, monkeypatch):
    r, _, _, records = retriever
    published = '2026-09-10T23:59:59.500000+07:00'
    lexical = [{**hit(1, 1, 9), 'published_at': published}]
    vector = [{**hit(1, 1, 0.9), 'published_at': published}]
    records[lexical[0]['chunk_id']] = hybrid._normalize_record(lexical[0])
    monkeypatch.setattr(r.bm25, 'search', lambda *a, **kw: lexical)
    monkeypatch.setattr(dense, 'search', lambda *a, **kw: vector)
    result = r.search('điện', date_from='2026-09-10', date_to='2026-09-10')
    assert len(result['hits']) == 1
    assert result['hits'][0]['published_at'].startswith('2026-09-10T23:59:59.500000')
