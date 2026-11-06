import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_context_generation import Counter, records

from eventrank.rag import pipeline
from eventrank.rag.models import load_model_config

QA = json.loads(Path('tests/fixtures/rag/qa.json').read_text('utf-8'))


@pytest.fixture
def qa_pipeline():
    config = {'models': load_model_config({}), 'generation': {}, 'index_version': 'rag_v1'}
    calls = []

    class Retriever:
        def search(self, *a, **kw):
            calls.append('retrieve')
            return {'mode': 'hybrid', 'degraded': False, 'hits': records(), 'trace': {'versions': {}}}

    def chat(messages, *, max_tokens, response_schema=None, temperature=0.0):
        calls.append('generate')
        return {'content': json.dumps(QA['valid_generation']), 'finish_reason': 'stop', 'usage': {}}

    model = SimpleNamespace(config=config['models'], chat=chat)
    instance = pipeline.RAGPipeline(None, config, retriever=Retriever(), model=model,
                                     counter=Counter(), snapshot=QA['snapshot'])
    return instance, calls


def test_end_to_end_answer_has_checked_citations_and_budget(qa_pipeline):
    p, calls = qa_pipeline
    # Fixture counter counts characters rather than model tokens; enlarge only the test window.
    p.model.config['llm']['max_model_len'] = 20000
    result = p.ask(QA['question'])
    assert result['status'] == 'answered' and result['sources'][0]['citation_id'] == 1
    assert result['answer'].endswith('[1]')
    assert calls == ['retrieve', 'generate']
    assert result['trace']['context']['prompt_tokens'] + result['trace']['context']['output_reserve'] <= 20000


def test_no_hits_never_calls_tokenizer_or_generator(qa_pipeline):
    p, calls = qa_pipeline
    p.retriever.search = lambda *a, **kw: {'mode': 'hybrid', 'degraded': False, 'hits': [], 'trace': {}}
    p.counter = None
    result = p.ask(QA['question'])
    assert result['status'] == 'insufficient_evidence' and result['sources'] == []
    assert 'generate' not in calls


@pytest.mark.parametrize('question', ['Hôm nay có tin gì mới nhất?', 'Trong kho có bao nhiêu bài báo?'])
def test_unsupported_scope_does_not_retrieve_or_generate(qa_pipeline, question):
    p, calls = qa_pipeline
    result = p.ask(question)
    assert result['status'] == 'unsupported_query' and calls == []


def test_unknown_citation_is_not_exposed_as_answer(qa_pipeline):
    p, _ = qa_pipeline
    p.model.config['llm']['max_model_len'] = 20000
    body = json.loads(json.dumps(QA['valid_generation']))
    body['claims'][0]['evidence'][0]['id'] = 999
    p.model.chat = lambda *a, **kw: {'content': json.dumps(body), 'finish_reason': 'stop', 'usage': {}}
    result = p.ask(QA['question'])
    assert result['status'] == 'invalid_generation' and result['sources'] == []
    assert '999' not in result['answer']


def test_generation_timeout_is_sanitized_and_not_returned_as_answer(qa_pipeline):
    p, _ = qa_pipeline
    p.model.config['llm']['max_model_len'] = 20000

    def fail(*a, **kw):
        raise RuntimeError('private-token-example')

    p.model.chat = fail
    with pytest.raises(pipeline.RAGUnavailableError) as error:
        p.ask(QA['question'])
    assert 'private-token-example' not in str(error.value)


def test_truncated_model_response_is_not_accepted(qa_pipeline):
    p, _ = qa_pipeline
    p.model.config['llm']['max_model_len'] = 20000
    p.model.chat = lambda *a, **kw: {'content': json.dumps(QA['valid_generation']),
                                   'finish_reason': 'length', 'usage': {}}
    assert p.ask(QA['question'])['status'] == 'invalid_generation'


def test_no_context_fits_does_not_generate(qa_pipeline):
    p, calls = qa_pipeline
    p.counter.count = lambda messages: 8192
    result = p.ask(QA['question'])
    assert result['status'] == 'insufficient_evidence' and 'generate' not in calls
