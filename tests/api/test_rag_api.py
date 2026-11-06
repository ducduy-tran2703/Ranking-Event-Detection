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
