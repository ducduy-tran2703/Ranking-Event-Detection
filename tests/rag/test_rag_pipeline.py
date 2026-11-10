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

    def ping_embedding():
        calls.append('ping')
        return True

    model = SimpleNamespace(config=config['models'], chat=chat, ping_embedding=ping_embedding)
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
    assert [call for call in calls if call != 'ping'] == ['retrieve', 'generate']
    assert result['trace']['context']['prompt_tokens'] + result['trace']['context']['output_reserve'] <= 20000


def test_giu_qwen_song_den_khi_gemma_tra_xong(qa_pipeline):
    p, calls = qa_pipeline
    p.model.config['llm']['max_model_len'] = 20000
    result = p.ask(QA['question'])
    assert calls == ['retrieve', 'generate', 'ping']
    assert result['trace']['keepalive'] == {'pings': 1, 'failures': 0}


def test_bm25_only_khong_danh_thuc_qwen(qa_pipeline):
    p, calls = qa_pipeline
    p.model.config['llm']['max_model_len'] = 20000
    p.retriever.search = lambda *a, **kw: {'mode': 'bm25_only', 'degraded': True, 'hits': records(),
                                           'trace': {'versions': {}}}
    result = p.ask(QA['question'])
    assert 'ping' not in calls and 'keepalive' not in result['trace']


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


@pytest.mark.parametrize('question', ['Album này có bao nhiêu bài hát?', 'Đề toán có bao nhiêu bài thi?'])
def test_cau_hoi_bai_hat_khong_bi_chan_nham_la_thong_ke(qa_pipeline, question):
    p, calls = qa_pipeline
    p.model.config['llm']['max_model_len'] = 20000
    assert p.ask(question)['status'] != 'unsupported_query' and 'retrieve' in calls


def test_cau_hoi_dem_bai_ve_mot_chu_de_van_bi_chan(qa_pipeline):
    p, calls = qa_pipeline
    assert p.ask('Có bao nhiêu bài về giá vàng?')['status'] == 'unsupported_query' and calls == []


@pytest.mark.parametrize('filters, expected', [({'source': 'thanhnien'}, 8), ({}, 3)])
def test_gioi_han_nguon_chi_ap_dung_khi_khong_loc_mot_bao(qa_pipeline, monkeypatch, filters, expected):
    p, _ = qa_pipeline
    p.model.config['llm']['max_model_len'] = 20000
    seen = {}
    real = pipeline.select_context

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline, 'select_context', spy)
    p.ask(QA['question'], **filters)
    assert seen['per_source'] == expected


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


def test_trace_ghi_lai_quote_da_bo(qa_pipeline):
    p, _ = qa_pipeline
    p.model.config['llm']['max_model_len'] = 20000
    body = json.loads(json.dumps(QA['valid_generation']))
    body['claims'].append({'text': 'Ý bịa ra.', 'evidence': [{'id': 1, 'quote': 'Việt Nam thắng 4-0.'}]})
    p.model.chat = lambda *a, **kw: {'content': json.dumps(body, ensure_ascii=False), 'finish_reason': 'stop', 'usage': {}}
    result = p.ask(QA['question'])
    assert result['status'] == 'answered' and 'Ý bịa' not in result['answer']
    assert [d['quote'] for d in result['trace']['validation']['dropped']] == ['Việt Nam thắng 4-0.']


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
