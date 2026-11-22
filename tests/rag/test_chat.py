"""Nối tool calling vào hàng đợi chat (không cần Postgres: db.connect được thay bằng kết nối giả)."""
from contextlib import nullcontext

from eventrank.rag import chat as C
from eventrank.rag.agent import ToolCallingPipeline
from eventrank.rag.pipeline import RAGPipeline


def cfg(enabled):
    return {'index_version': 'rag_v1', 'tool_calling': {'enabled': enabled}}


def test_chon_pipeline_theo_cau_hinh_va_dung_chung_ner_counter():
    ner, counter = object(), object()
    agent = C.build_pipeline(None, cfg(True), query_ner=ner, counter=counter)
    legacy = C.build_pipeline(None, cfg(False), query_ner=ner, counter=counter)
    assert isinstance(agent, ToolCallingPipeline) and agent.base.query_ner is ner and agent.counter is counter
    assert type(legacy) is RAGPipeline and legacy.query_ner is ner and legacy.counter is counter


class Pipe:
    def __init__(self, accepts):
        self.accepts_context, self.kw = accepts, None

    def ask(self, question, **kw):
        self.kw = kw
        return {'status': 'smalltalk'}

    def close(self):
        pass


def run(monkeypatch, pipe):
    monkeypatch.setattr(C.db, 'connect', lambda url: nullcontext(object()))
    w = C.ChatWorker('postgresql://fake', lambda conn: pipe)
    box = {}
    job = C.Job(message_id=9, question='Xin chào', filters={'source': 'tuoitre'}, user_id=7, conversation_id=3)
    w._execute(job, box)
    return box


def test_worker_truyen_nguoi_dung_va_cuoc_tro_chuyen_cho_pipeline_tool(monkeypatch):
    pipe = Pipe(True)
    assert run(monkeypatch, pipe)['result'] == {'status': 'smalltalk'}
    assert pipe.kw == {'source': 'tuoitre', 'date_from': None, 'date_to': None, 'user_id': 7,
                       'conversation_id': 3, 'message_id': 9}


def test_worker_khong_truyen_ngu_canh_cho_pipeline_cu(monkeypatch):
    pipe = Pipe(False)
    run(monkeypatch, pipe)
    assert pipe.kw == {'source': 'tuoitre', 'date_from': None, 'date_to': None}


def test_smalltalk_la_trang_thai_ket_qua_hop_le():
    assert 'smalltalk' in C.RESULT_STATUSES


def test_cau_bao_cho_pha_tool_calling():
    from eventrank.rag.pipeline import RAGUnavailableError
    assert C.error_for(RAGUnavailableError('generation')) == C.PHASE_MESSAGES['generation']


def test_cau_hinh_mac_dinh_bat_tool_calling():
    import yaml

    from eventrank.rag.agent import ToolCallingPipeline

    config = yaml.safe_load(C.CONFIG_PATH.read_text('utf-8'))
    assert config['tool_calling']['enabled'] is True
    assert isinstance(C.build_pipeline(None, config, counter=object()), ToolCallingPipeline)
