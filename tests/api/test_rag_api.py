import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.api import rag
from apps.api.main import create_app
from eventrank.rag.generation import validate_answer
from eventrank.rag.pipeline import RAGUnavailableError

QA = json.loads(Path('tests/fixtures/rag/qa.json').read_text('utf-8'))


@pytest.fixture
def api_client():
    row = {**QA['articles'][0], 'id': 1, 'start_char': 0,
           'end_char': len(QA['articles'][0]['text']), 'chunking_version': 'fixture'}
    valid = validate_answer(json.dumps(QA['valid_generation']), [row])
    answer = {**valid, 'retrieval_mode': 'hybrid', 'degraded': False, 'snapshot': QA['snapshot'], 'trace': {}}
    calls = []

    def ask(question, **kwargs):
        calls.append((question, kwargs))
        return copy.deepcopy(answer)

    fake = SimpleNamespace(ask=ask)
    app = rag.create_rag_app()
    app.dependency_overrides[rag.get_pipeline] = lambda: fake
    with TestClient(app) as client:
        yield client, fake, calls


def test_api_returns_typed_answer_and_passes_filters(api_client):
    client, _, calls = api_client
    response = client.post('/api/rag/ask', json={'question': QA['question'], 'source': 'thanhnien',
                                               'date_from': '2026-09-18', 'date_to': '2026-09-18'})
    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'answered' and body['sources'][0]['citation_id'] == 1
    assert body['sources'][0]['url'] == QA['articles'][0]['url']
    assert calls[0][1]['date_from'] == calls[0][1]['date_to'] == '2026-09-18'
    assert calls[0][1]['allow_fallback'] is False


@pytest.mark.parametrize('payload', [{}, {'question': ''}, {'question': 'x', 'max_tokens': 1025},
                                    {'question': 'x', 'date_from': 'not-a-date'},
                                    {'question': 'x', 'date_from': '2026-09-19', 'date_to': '2026-09-18'}])
def test_invalid_request_never_calls_pipeline(api_client, payload):
    client, _, calls = api_client
    assert client.post('/api/rag/ask', json=payload).status_code == 422
    assert calls == []


def test_unavailable_service_is_a_sanitized_503(api_client):
    client, fake, _ = api_client

    def fail(*a, **kw):
        raise RAGUnavailableError('generation', {'private': 'not-for-public-error'})

    fake.ask = fail
    response = client.post('/api/rag/ask', json={'question': QA['question']})
    assert response.status_code == 503
    assert 'not-for-public-error' not in response.text


def test_api_rejects_additional_request_while_one_is_running(api_client):
    client, _, calls = api_client
    rag._REQUEST_SLOT.acquire()
    try:
        assert client.post('/api/rag/ask', json={'question': QA['question']}).status_code == 429
        assert calls == []
    finally:
        rag._REQUEST_SLOT.release()


def test_router_is_registered_in_main_app_with_response_model(store):
    schema = create_app(store, load_events=False).openapi()
    response = schema['paths']['/api/rag/ask']['post']['responses']['200']
    assert response['content']['application/json']['schema']['$ref'].endswith('/RAGAnswer')


def test_database_startup_failure_is_sanitized(monkeypatch):
    def fail():
        raise rag.psycopg.OperationalError('private-password-example')

    monkeypatch.setattr(rag.db, 'connect', fail)
    with TestClient(rag.create_rag_app()) as client:
        response = client.post('/api/rag/ask', json={'question': QA['question']})
    assert response.status_code == 503
    assert 'private-password-example' not in response.text


def test_sync_endpoint_returns_202_and_runs_worker(monkeypatch):
    plan = {
        'requested': 1,
        'missing_article_ids': [],
        'already_ready_ids': [],
        'need_ner_articles': [{'article_id': 'a' * 64}],
        'need_rechunk_articles': [],
        'pending_index_ids': [],
    }
    monkeypatch.setattr(rag, 'inspect_articles', lambda *a, **kw: plan)
    monkeypatch.setattr(rag.db, 'connect', lambda: _DummyConn())

    started = []

    class _FakeThread:
        def __init__(self, target, args, **kwargs):
            started.append(args[1])

        def start(self):
            with rag._SYNC_LOCK:
                rag._SYNC_STATE['running'] = False
                rag._SYNC_STATE['last_result'] = {'ner_articles': 1}

    monkeypatch.setattr(rag.threading, 'Thread', _FakeThread)
    with rag._SYNC_LOCK:
        rag._SYNC_STATE.update(running=False, last_result=None, last_error=None)

    with TestClient(rag.create_rag_app()) as client:
        resp = client.post('/api/rag/sync', json={'article_ids': ['a' * 64]})
        assert resp.status_code == 200
        body = resp.json()
        assert body['status'] == 'accepted' and body['queued_articles'] == 1
        assert started == [['a' * 64]]
        status_resp = client.get('/api/rag/sync/status')
        assert status_resp.status_code == 200
        assert status_resp.json()['running'] is False
        assert status_resp.json()['last_result'] == {'ner_articles': 1}


def test_sync_endpoint_up_to_date(monkeypatch):
    plan = {
        'requested': 1,
        'missing_article_ids': [],
        'already_ready_ids': ['a' * 64],
        'need_ner_articles': [],
        'need_rechunk_articles': [],
        'pending_index_ids': [],
    }
    monkeypatch.setattr(rag, 'inspect_articles', lambda *a, **kw: plan)
    monkeypatch.setattr(rag.db, 'connect', lambda: _DummyConn())
    with rag._SYNC_LOCK:
        rag._SYNC_STATE['running'] = False

    with TestClient(rag.create_rag_app()) as client:
        resp = client.post('/api/rag/sync', json={'article_ids': ['a' * 64]})
        assert resp.status_code == 200
        assert resp.json()['status'] == 'up_to_date'
        assert resp.json()['already_ready'] == 1


class _DummyConn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


# ---------------------------------------------------------------- BamiBERT dùng chung, nạp khi khởi động
class _CountingNER:
    def predict_texts(self, texts):
        return [[] for _ in texts]


@pytest.fixture
def ner_factory(monkeypatch):
    built = []

    def factory(cfg):
        built.append(cfg['model_dir'])
        return _CountingNER()

    monkeypatch.setattr(rag, 'ner_from_config', factory)
    monkeypatch.setattr(rag, '_NER', None)
    return built


def test_khoi_dong_rag_app_nap_bamibert_mot_lan(ner_factory, monkeypatch):
    monkeypatch.setattr(rag, '_ner_checkpoint_exists', lambda cfg: True)
    with TestClient(rag.create_rag_app(preload=True)):
        assert len(ner_factory) == 1
        assert rag.shared_ner().loaded is True
        rag.shared_ner().predict_texts(['câu 1'])
        rag.shared_ner().predict_texts(['câu 2'])
    assert len(ner_factory) == 1


def test_khong_preload_khi_thieu_checkpoint(ner_factory, monkeypatch):
    monkeypatch.setattr(rag, '_ner_checkpoint_exists', lambda cfg: False)
    with TestClient(rag.create_rag_app(preload=True)):
        assert ner_factory == []


def test_moi_request_dung_chung_mot_ban_ner(ner_factory, monkeypatch):
    # Không phụ thuộc checkpoint thật có trên máy chạy test.
    monkeypatch.setattr(rag, '_ner_checkpoint_exists', lambda cfg: True)
    monkeypatch.setattr(rag.db, 'connect', lambda: _DummyConn())
    first, second = rag.get_pipeline(), rag.get_pipeline()
    a, b = next(first), next(second)
    assert a.query_ner is b.query_ner is rag.shared_ner()
    first.close()
    second.close()


def test_index_dang_dong_bo_tra_503_ro_rang(api_client):
    client, fake, _ = api_client

    def busy(*a, **kw):
        raise RAGUnavailableError('index_sync')

    fake.ask = busy
    response = client.post('/api/rag/ask', json={'question': QA['question']})
    assert response.status_code == 503
    assert 'đồng bộ' in response.json()['detail']


# ---------------------------------------------------------------- sync: không lộ lỗi hạ tầng, cùng tiêu chí chunk
def test_loi_sync_khong_lo_thong_diep_ha_tang(monkeypatch):
    def fail(*a, **kw):
        raise rag.psycopg.OperationalError('password authentication failed secret-xyz')

    monkeypatch.setattr(rag, 'sync_rag', fail)
    monkeypatch.setattr(rag.db, 'connect', lambda: _DummyConn())
    monkeypatch.setattr(rag, '_NER', None)
    monkeypatch.setattr(rag, 'ner_from_config', lambda cfg: _CountingNER())
    rag._run_sync_worker({'ner': {'model_dir': 'x'}}, None)
    with rag._SYNC_LOCK:
        error = rag._SYNC_STATE['last_error']
    assert error == 'OperationalError' and 'secret-xyz' not in error


def test_trigger_sync_dung_cung_chunk_version_voi_worker(monkeypatch):
    from eventrank.rag.chunking import chunking_version
    seen = {}

    def inspect(conn, ids, **kw):
        seen.update(kw)
        return {'requested': 0, 'missing_article_ids': [], 'already_ready_ids': [],
                'need_ner_articles': [], 'need_rechunk_articles': [], 'pending_index_ids': []}

    monkeypatch.setattr(rag, 'inspect_articles', inspect)
    monkeypatch.setattr(rag.db, 'connect', lambda: _DummyConn())
    with rag._SYNC_LOCK:
        rag._SYNC_STATE['running'] = False
    with TestClient(rag.create_rag_app()) as client:
        assert client.post('/api/rag/sync', json={'article_ids': None}).status_code == 200
    assert seen['chunk_version'] == chunking_version(320, 48)
