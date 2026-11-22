import json
from types import SimpleNamespace

import pytest
from test_context_generation import Counter, records

from eventrank.rag import agent
from eventrank.rag.models import load_model_config
from eventrank.rag.pipeline import RAGUnavailableError

SNAP = {'from_date': '2026-08-01', 'to_date': '2026-09-19', 'articles': 3, 'sources': ['thanhnien', 'vnexpress']}


def call(name, args, cid='c1'):
    return {'id': cid, 'name': name, 'arguments': args, 'error': None}


def reply(content='', tool_calls=(), finish='stop'):
    return {'content': content, 'tool_calls': list(tool_calls), 'finish_reason': finish,
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}


def answer(claims=(), status='answered', message=None):
    body = {'status': status, 'claims': list(claims)}
    if message is not None:
        body['message'] = message
    return reply(json.dumps(body, ensure_ascii=False))


class Model:
    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.config = load_model_config({})
        self.config['llm']['max_model_len'] = 50000

    def chat(self, messages, **kw):
        self.requests.append({'messages': json.loads(json.dumps(messages, default=str)), **kw})
        return self.script.pop(0)

    def ping_embedding(self):
        return True


class Conn:
    """Postgres giả: trả số đếm cho count_articles, lịch sử hội thoại và hồ sơ theo câu SQL."""

    def __init__(self, count=37, history=(), profile=None):
        self.count, self.history, self.profile, self.sql = count, list(history), profile, []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if 'FROM rag_messages' in sql:
            rows = list(reversed(self.history))
        elif 'FROM rag_user_profiles' in sql:
            rows = [self.profile] if self.profile else []
        elif 'hidden_sources' in sql:
            rows = [(['thanhnien'],)]
        elif sql.startswith('SELECT count(*) FROM articles'):
            rows = [(self.count,)]
        elif 'advisory' in sql:
            rows = [(True,)]
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchall=lambda: rows, fetchone=lambda: rows[0] if rows else None)

    def transaction(self):
        from contextlib import nullcontext
        return nullcontext()


def build(script, conn=None, hits=None, **cfg):
    config = {'index_version': 'rag_v1', 'generation': {}, 'models': load_model_config({}),
              'tool_calling': {'max_rounds': 3, 'round_max_tokens': 256, 'history_turns': 2, **cfg},
              'profile': {'categories': ['Kinh tế', 'Thể thao']}}
    model = Model(script)
    searches = []

    def search(query, **filters):
        searches.append((query, filters))
        return hits if hits is not None else records()

    p = agent.ToolCallingPipeline(conn or Conn(), config, model=model, counter=Counter(), snapshot=SNAP, search=search)
    return p, model, searches


def test_dem_bai_qua_tool_va_so_lieu_duoc_kiem_bang_quote():
    p, model, _ = build([
        reply(tool_calls=[call('count_articles', {'source': 'vnexpress', 'date_from': '2026-09-01',
                                                  'date_to': '2026-09-19'})]),
        reply('Đủ bằng chứng.'),
        answer([{'text': 'VnExpress có 37 bài trong khoảng này.',
                 'evidence': [{'id': 1, 'quote': 'có 37 bài báo của báo vnexpress'}]}]),
    ])
    out = p.ask('Có bao nhiêu bài VnExpress từ 1/9 đến 19/9?')
    assert out['status'] == 'answered' and out['answer'].endswith('[1]')
    assert out['sources'][0]['kind'] == 'data' and out['sources'][0]['tool'] == 'count_articles'
    assert [r['tool_calls'][0]['name'] for r in out['trace']['tool_rounds'] if r['tool_calls']] == ['count_articles']
    # Lượt gọi tool có tools, lượt cuối KHÔNG có tools mà ép JSON schema.
    assert model.requests[0]['tools'] and model.requests[0].get('response_schema') is None
    assert model.requests[-1].get('tools') is None and model.requests[-1]['response_schema']
    # Câu thống kê không còn bị chặn bởi unsupported_query.
    assert out['retrieval_mode'] is None and out['degraded'] is False


def test_so_lieu_bia_sai_bi_tu_choi():
    p, _, _ = build([
        reply(tool_calls=[call('count_articles', {})]),
        reply('xong'),
        answer([{'text': 'Có 73 bài.', 'evidence': [{'id': 1, 'quote': 'có 73 bài báo'}]}]),
    ])
    assert p.ask('Kho có bao nhiêu bài?')['status'] == 'invalid_generation'


def test_tim_tin_roi_tra_loi_co_url_tu_db():
    first = records()[0]
    quote = first['text'][:40]
    p, _, searches = build([
        reply(tool_calls=[call('search_news', {'query': 'U23 Việt Nam Philippines'})]),
        reply(''),
        answer([{'text': 'Kết quả trận đấu.', 'evidence': [{'id': 1, 'quote': quote}]}]),
    ])
    out = p.ask('U23 Việt Nam thắng Philippines mấy bàn?')
    assert out['status'] == 'answered' and out['sources'][0]['url'] == first['url']
    assert searches[0][0] == 'U23 Việt Nam Philippines' and out['retrieval_mode'] == 'hybrid'


def test_gioi_han_so_vong_goi_tool():
    loop = [reply(tool_calls=[call('count_articles', {'source': f's{i}'}, f'c{i}')]) for i in range(5)]
    p, model, _ = build([*loop[:3], answer(status='insufficient_evidence')], max_rounds=3)
    out = p.ask('Đếm mãi?')
    assert len([r for r in out['trace']['tool_rounds'] if r['tool_calls']]) == 3
    assert out['status'] == 'insufficient_evidence' and len(model.requests) == 4


def test_doi_so_sai_bao_lai_model_de_sua():
    p, model, _ = build([
        reply(tool_calls=[call('search_news', {'limit': 99})]),
        reply(tool_calls=[call('count_articles', {}, 'c2')]),
        reply('xong'),
        answer(status='insufficient_evidence'),
    ])
    out = p.ask('Hỏi gì đó')
    tool_msg = next(m for m in model.requests[1]['messages'] if m['role'] == 'tool')
    assert 'invalid_arguments' in tool_msg['content'] and 'query' in tool_msg['content']
    assert out['trace']['tool_rounds'][0]['tool_calls'][0]['error'] == 'invalid_arguments'


def test_chao_hoi_khong_can_bang_chung():
    p, _, _ = build([reply('Chào bạn'), answer(status='smalltalk', message='Chào bạn! Mình có thể giúp gì?')])
    out = p.ask('Xin chào')
    assert out['status'] == 'smalltalk' and out['answer'] == 'Chào bạn! Mình có thể giúp gì?' and out['sources'] == []


@pytest.mark.parametrize('message', ['Kho có 37 bài.', 'Xem https://example.com'])
def test_smalltalk_khong_duoc_chua_so_lieu_hay_url(message):
    p, _, _ = build([reply(''), answer(status='smalltalk', message=message)])
    assert p.ask('Xin chào')['status'] == 'invalid_generation'


def test_smalltalk_sau_khi_da_tra_cuu_thanh_thieu_bang_chung():
    p, _, _ = build([reply(tool_calls=[call('count_articles', {})]), reply(''),
                     answer(status='smalltalk', message='Chào bạn')])
    assert p.ask('Có bao nhiêu bài?')['status'] == 'insufficient_evidence'


def test_lich_su_hoi_thoai_va_ho_so_vao_prompt():
    conn = Conn(history=[('Giá vàng 10/9?', 'Giá vàng tăng [1].', 'answered')],
                profile=('ke_toan', None, 'chị Lan', 'em', None, 'ngan', ['Kinh tế'], {}))
    p, model, _ = build([reply(''), answer(status='insufficient_evidence')], conn=conn)
    p.ask('Còn hôm sau thì sao?', user_id=7, conversation_id=3, message_id=10)
    msgs = model.requests[0]['messages']
    assert msgs[1] == {'role': 'user', 'content': 'Giá vàng 10/9?'}
    assert msgs[2] == {'role': 'assistant', 'content': 'Giá vàng tăng.'}  # bỏ [n] của lượt cũ
    assert 'chị Lan' in msgs[0]['content'] and 'kế toán' in msgs[0]['content']
    assert 'update_user_profile' in {t['function']['name'] for t in model.requests[0]['tools']}


def test_khach_khong_dang_nhap_khong_co_tool_ho_so():
    p, model, _ = build([reply(''), answer(status='insufficient_evidence')])
    p.ask('Xin chào')
    assert 'update_user_profile' not in {t['function']['name'] for t in model.requests[0]['tools']}


def test_bao_an_cua_nguoi_dung_ap_vao_tim_kiem():
    hits = [{**records()[0], 'source': 'thanhnien'}]
    p, _, _ = build([reply(tool_calls=[call('search_news', {'query': 'x'})]), reply(''),
                     answer(status='insufficient_evidence')], hits=hits)
    out = p.ask('Tin gì?', user_id=7)
    assert out['trace']['evidence'] == []


def test_dong_bo_chi_muc_khi_dang_goi_tool_tra_index_sync():
    from eventrank.rag.prepare import IndexBusyError

    p, _, _ = build([reply(tool_calls=[call('search_news', {'query': 'x'})])])

    def busy(*a, **k):
        raise IndexBusyError('busy')

    p.search = busy
    with pytest.raises(RAGUnavailableError) as err:
        p.ask('Tin gì?')
    assert err.value.phase == 'index_sync'


def test_moi_lan_tim_kiem_deu_loi_ha_tang_thi_bao_unavailable():
    p, _, _ = build([reply(tool_calls=[call('search_news', {'query': 'x'})]), reply(''),
                     answer(status='insufficient_evidence')])

    def down(*a, **k):
        raise ConnectionError('qdrant down http://secret')

    p.search = down
    with pytest.raises(RAGUnavailableError) as err:
        p.ask('Tin gì?')
    assert err.value.phase == 'retrieval' and 'secret' not in json.dumps(err.value.trace, default=str)


def test_cho_xac_nhan_doi_nghe_duoc_noi_ro_trong_cau_tra_loi(monkeypatch):
    from eventrank.rag import profile as P
    monkeypatch.setattr(P, 'apply_update', lambda *a, **k: P.UpdatePlan(pending={'persona': 'ke_toan'}))
    p, _, _ = build([reply(tool_calls=[call('update_user_profile', {'persona': 'ke_toan', 'evidence': 'kế toán'})]),
                     reply(''), answer(status='smalltalk', message='Cảm ơn bạn đã chia sẻ!')])
    out = p.ask('Mình là kế toán', user_id=7)
    assert out['status'] == 'smalltalk' and 'xác nhận' in out['answer']
    assert out['profile_update']['pending'] == {'persona': 'ke_toan'}


def test_tim_kiem_mac_dinh_ghi_trace_ner_cua_moi_lan_tim():
    # Lần đầu viết agent, trace NER của search_news bị bỏ (truyền {} rồi vứt) → không chứng minh được NER đã chạy.
    hits = [{**records()[0], 'rank': 1, 'rrf_score': 0.03}]

    class Retriever:
        def search(self, query, **kw):
            return {'mode': 'hybrid', 'degraded': False, 'hits': hits, 'trace': {}}

    p, _, _ = build([reply(tool_calls=[call('search_news', {'query': 'U23 Việt Nam'})]), reply(''),
                     answer(status='insufficient_evidence')])
    p.search = p._default_search
    p.base.retriever = Retriever()
    p.base.conn = None
    p.config['query_ner'] = {'enabled': True}
    p.base.query_ner = SimpleNamespace(predict_texts=lambda texts: [[{'text': 'U23 Việt Nam', 'label': 'ORG',
                                                                      'start_char': 0, 'end_char': 12}]])
    out = p.ask('U23 Việt Nam thắng mấy bàn?')
    ner = out['trace']['query_ner']
    assert ner[0]['query'] == 'U23 Việt Nam' and ner[0]['status'] == 'ok'
    assert ner[0]['entities'][0]['text'] == 'U23 Việt Nam'


def test_luot_cuoi_bat_buoc_xung_ho_theo_ho_so():
    # E2E 22/11: lượt 3–4 (đếm bài, top sự kiện) không gọi "chị Lan" dù hồ sơ đã lưu.
    conn = Conn(profile=(None, None, 'chị Lan', 'em', None, None, [], {}))
    p, model, _ = build([reply(''), answer(status='insufficient_evidence')], conn=conn)
    p.ask('Có bao nhiêu bài?', user_id=7)
    final_system = model.requests[-1]['messages'][0]['content']
    assert 'BẮT BUỘC' in final_system and 'chị Lan' in final_system and '"em"' in final_system


def test_khong_co_xung_ho_thi_khong_them_luat():
    p, model, _ = build([reply(''), answer(status='insufficient_evidence')])
    p.ask('Có bao nhiêu bài?')
    assert 'BẮT BUỘC gọi người dùng' not in model.requests[-1]['messages'][0]['content']


def test_luat_xung_ho_khong_thay_the_noi_dung_tra_loi():
    # E2E 22/11 lần 3: luật xưng hô khiến Gemma trả "Chào chị Lan, các tin nổi bật gồm: [1]…[8]" không nêu tin nào.
    conn = Conn(profile=(None, None, 'chị Lan', 'em', None, None, [], {}))
    p, model, _ = build([reply(''), answer(status='insufficient_evidence')], conn=conn)
    p.ask('Tin nổi bật?', user_id=7)
    final_system = model.requests[-1]['messages'][0]['content']
    assert 'vẫn phải nêu cụ thể' in final_system


def test_prompt_tool_chi_loc_ngay_khi_cau_hien_tai_neu_ngay():
    p, model, _ = build([reply(''), answer(status='insufficient_evidence')])
    p.ask('Tỷ số trận U23?')
    assert 'CÂU HIỆN TẠI' in model.requests[0]['messages'][0]['content']
