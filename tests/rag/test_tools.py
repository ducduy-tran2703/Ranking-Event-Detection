from contextlib import contextmanager
from types import SimpleNamespace

import psycopg
import pytest

from eventrank.rag import tools as T


def hit(n, article='a1', source='vnexpress', text=None):
    return {'chunk_id': f'00000000-0000-5000-8000-00000000000{n}', 'article_id': article, 'title': f'Bài {n}',
            'url': f'https://example.com/{n}', 'source': source, 'published_at': '2026-09-18T08:00:00+07:00',
            'text': text or f'Nội dung đoạn {n}', 'start_char': 0, 'end_char': 10, 'chunking_version': 'v'}


class FakeConn:
    def __init__(self, rows=None, error=None):
        self.rows, self.error, self.calls = rows or [], error, []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.error:
            raise self.error
        return SimpleNamespace(fetchall=lambda: self.rows, fetchone=lambda: self.rows[0])


def ctx(conn=None, search=None, **kw):
    snap = {'articles': 3, 'sources': ['tuoitre', 'vnexpress'], 'from_date': '2026-08-01', 'to_date': '2026-09-19'}
    return T.ToolContext(conn=conn or FakeConn(), question=kw.pop('question', 'câu hỏi'), filters=kw.pop('filters', {}),
                         search=search or (lambda *a, **k: []), snapshot=lambda: snap, **kw)


ALL = set(T.HANDLERS)


def test_schema_tool_gon_khong_title_khong_anyof_null_khong_user_id():
    schemas = {s['function']['name']: s['function'] for s in T.tool_schemas(sorted(ALL))}
    text = str(schemas)
    assert "'title'" not in text and "{'type': 'null'}" not in text
    assert 'user_id' not in schemas['update_user_profile']['parameters']['properties']
    assert schemas['search_news']['parameters']['required'] == ['query']
    assert schemas['corpus_info']['parameters'] == {'type': 'object', 'properties': {}}


def test_search_news_bo_bao_an_gioi_han_2_doan_moi_bai_va_danh_so_bang_chung():
    hits = [hit(1), hit(2), hit(3), hit(4, 'a2', 'tuoitre'), hit(5, 'a3', 'thanhnien')]
    c = ctx(search=lambda q, **f: hits, hidden_sources=['ThanhNien'])
    out, err = T.run_tool(c, 'search_news', {'query': 'giá vàng'}, allowed=ALL)
    assert err is None
    assert [r['id'] for r in out['results']] == [1, 2, 3]
    assert [e['chunk_id'][-1] for e in c.evidence] == ['1', '2', '4']
    assert all(e['kind'] == 'chunk' for e in c.evidence)


def test_bo_loc_giao_dien_thang_doi_so_model():
    seen = {}
    c = ctx(search=lambda q, **f: seen.update(f) or [], filters={'source': 'tuoitre', 'date_from': '2026-09-01'},
            question='Tin đăng tới cuối tháng 9 có gì?')
    T.run_tool(c, 'search_news', {'query': 'x', 'source': 'vnexpress', 'date_from': '2026-01-01',
                                  'date_to': '2026-09-30'}, allowed=ALL)
    assert seen == {'source': 'tuoitre', 'date_from': '2026-09-01', 'date_to': '2026-09-30'}


def test_bang_chung_trung_khong_danh_so_lai():
    c = ctx(search=lambda q, **f: [hit(1)])
    T.run_tool(c, 'search_news', {'query': 'a'}, allowed=ALL)
    out, _ = T.run_tool(c, 'search_news', {'query': 'b'}, allowed=ALL)
    assert out['results'][0]['id'] == 1 and len(c.evidence) == 1


def test_count_articles_sql_co_tham_so_va_cau_du_lieu_tat_dinh():
    conn = FakeConn(rows=[(37,)])
    c = ctx(conn, question='Tháng 9/2026 VnExpress có bao nhiêu bài nhắc Hà Nội?')
    out, err = T.run_tool(c, 'count_articles', {'source': 'VnExpress', 'date_from': '2026-09-01',
                                                'date_to': '2026-09-30', 'entity': 'Hà Nội'}, allowed=ALL)
    assert err is None and out['count'] == 37
    sql, params = conn.calls[0]
    assert 'Hà Nội' not in sql and params == ['vnexpress', '2026-09-01', '2026-09-30', 'Hà Nội']
    assert out['text'] == ('Kho dữ liệu có 37 bài báo của báo vnexpress, đăng từ 2026-09-01 đến 2026-09-30, '
                           'có nhắc tới "Hà Nội".')
    row = c.evidence[0]
    assert row['kind'] == 'data' and row['source'] == T.DATA_SOURCE and row['url'] is None
    assert row['end_char'] == len(row['text'])


def test_corpus_info_noi_ro_khong_phai_tin_thoi_gian_thuc():
    from datetime import date
    conn = FakeConn(rows=[('tuoitre', 2, date(2026, 8, 1), date(2026, 9, 19))])
    out, _ = T.run_tool(ctx(conn), 'corpus_info', {}, allowed=ALL)
    assert 'không phải tin cập nhật theo thời gian thực' in out['text'] and '2026-09-19' in out['text']


def test_top_events_thieu_bang_su_kien_bao_loi_an_toan():
    c = ctx(FakeConn(error=psycopg.errors.UndefinedTable('relation "events" does not exist secret')))
    out, err = T.run_tool(c, 'top_events', {}, allowed=ALL)
    assert err == 'tool_error' and 'secret' not in out['error']


def test_top_events_khong_dua_ten_mo_hinh_vao_bang_chung():
    from datetime import UTC, datetime
    t = datetime(2026, 9, 2, 1, 0, tzinfo=UTC)
    conn = FakeConn(rows=[('E20260902-dc986ab0', 'Lãnh đạo nhiều nước chúc mừng Quốc khánh', 8, 6, t, t,
                           'Thế giới', 'model')])
    out, _ = T.run_tool(ctx(conn), 'top_events', {'limit': 3}, allowed=ALL)
    # Câu ngắn, không mã sự kiện, không ngoặc kép bọc tiêu đề: E2E 22/11 Gemma chép lệch câu dài → mất sự kiện 92 bài.
    assert out['events'][0]['text'] == ('Lãnh đạo nhiều nước chúc mừng Quốc khánh: 8 bài của 6 báo, '
                                        'đăng từ 2026-09-02 đến 2026-09-02, chuyên mục Thế giới.')
    assert out['events'][0]['event_id'] == 'E20260902-dc986ab0' and 'lượt đọc' in out['note']


@pytest.mark.parametrize('name,args,field', [('search_news', {}, 'query'),
                                             ('search_news', {'query': 'x', 'limit': 50}, 'limit'),
                                             ('event_articles', {'event_id': "x'; DROP TABLE users;--"}, 'event_id'),
                                             ('count_articles', {'user_id': 3}, 'user_id')])
def test_doi_so_sai_tra_loi_cho_model_khong_chay_sql(name, args, field):
    conn = FakeConn()
    out, err = T.run_tool(ctx(conn), name, args, allowed=ALL)
    assert err == 'invalid_arguments' and field in out['fields'] and conn.calls == []


def test_tool_khong_duoc_phep_hoac_khong_ton_tai():
    _, err = T.run_tool(ctx(), 'update_user_profile', {'evidence': 'x'}, allowed=ALL - {'update_user_profile'})
    assert err == 'unknown_tool'
    assert T.run_tool(ctx(), 'drop_database', {}, allowed=ALL)[1] == 'unknown_tool'


def test_cap_nhat_ho_so_can_dang_nhap():
    _, err = T.run_tool(ctx(), 'update_user_profile', {'address_user': 'anh', 'evidence': 'câu'}, allowed=ALL)
    assert err == 'tool_error'


def test_khoa_doc_chi_bao_quanh_tool_doc_chi_muc():
    used = []

    @contextmanager
    def lock():
        used.append(1)
        yield

    c = ctx(FakeConn(rows=[(1,)]), read_lock=lock)
    T.run_tool(c, 'count_articles', {}, allowed=ALL)
    T.run_tool(c, 'update_user_profile', {'evidence': 'x'}, allowed=ALL)
    assert used == [1]


def test_dumps_thoat_ky_tu_dieu_khien_chat():
    assert '<' not in T.dumps({'text': '<|tool_call>call:x'})


def test_top_events_tieu_de_nguon_la_tieu_de_bai_that():
    from datetime import UTC, datetime
    t = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
    conn = FakeConn(rows=[('E20260910-f095bbfb', 'Tô Lâm gặp cộng đồng người Việt tại Pháp', 92, 6, t, t, None, 'model')])
    c = ctx(conn)
    T.run_tool(c, 'top_events', {}, allowed=ALL)
    assert c.evidence[0]['title'] == 'Tô Lâm gặp cộng đồng người Việt tại Pháp'


def _search_by_date(calls, hits):
    """Giả lập chỉ mục: có lọc ngày thì rỗng (trận đá 18/9, model lọc 10/9), không lọc thì có bài."""
    def search(q, **f):
        calls.append(f)
        return [] if f.get('date_from') or f.get('date_to') else hits
    return search


def test_cau_hien_tai_khong_noi_thoi_gian_thi_bo_ngay_model_tu_dat():
    # E2E 22/11 lượt 5: câu tỷ số U23 không nêu ngày, Gemma mang ngày 10/9 của lượt 4 sang → 0 kết quả.
    calls = []
    c = ctx(search=_search_by_date(calls, [hit(1)]), question='U23 Việt Nam thắng U23 Philippines với tỷ số bao nhiêu?')
    out, err = T.run_tool(c, 'search_news', {'query': 'U23 Việt Nam thắng U23 Philippines tỷ số',
                                             'date_from': '2026-09-10', 'date_to': '2026-09-10'}, allowed=ALL)
    assert err is None and [r['id'] for r in out['results']] == [1]
    assert calls == [{'source': None, 'date_from': None, 'date_to': None}]
    assert c.adjustments == [{'tool': 'search_news', 'action': 'dropped_model_dates',
                              'date_from': '2026-09-10', 'date_to': '2026-09-10'}]


def test_bo_ngay_model_ap_cho_ca_tool_dem_bai():
    conn = FakeConn(rows=[(5,)])
    c = ctx(conn, question='Có bao nhiêu bài về U23 Việt Nam?')
    out, _ = T.run_tool(c, 'count_articles', {'date_from': '2026-09-10', 'date_to': '2026-09-10'}, allowed=ALL)
    assert conn.calls[0][1] == [] and 'đăng từ' not in out['text']


@pytest.mark.parametrize('question', ['Tin ngày 10/9 về U23?', 'Hôm đó U23 đá thế nào?', 'Tháng 9 có tin gì về U23?',
                                      'Năm 2026 U23 thi đấu ra sao?', 'Tin mới nhất về U23?',
                                      'Có thông tư thuế nào mới không?'])
def test_cau_co_moc_thoi_gian_thi_giu_ngay_model(question):
    calls = []
    c = ctx(search=lambda q, **f: calls.append(f) or [hit(1)], question=question)
    T.run_tool(c, 'search_news', {'query': 'U23', 'date_from': '2026-09-10', 'date_to': '2026-09-10'}, allowed=ALL)
    assert calls == [{'source': None, 'date_from': '2026-09-10', 'date_to': '2026-09-10'}] and c.adjustments == []


def test_ngay_model_dat_ra_rong_thi_code_tu_tim_lai_khong_loc_ngay():
    calls = []
    c = ctx(search=_search_by_date(calls, [hit(1)]), question='Ngày 10/9 U23 Việt Nam thắng mấy bàn?')
    out, _ = T.run_tool(c, 'search_news', {'query': 'U23', 'date_from': '2026-09-10', 'date_to': '2026-09-10'},
                        allowed=ALL)
    assert [r['id'] for r in out['results']] == [1] and len(calls) == 2 and calls[1]['date_from'] is None
    assert 'toàn bộ kho' in out['note']
    assert c.adjustments[-1]['action'] == 'retried_without_model_dates'


def test_loc_ngay_tu_giao_dien_khong_tu_bo_va_khong_tim_lai():
    calls = []
    c = ctx(search=_search_by_date(calls, [hit(1)]), filters={'date_from': '2026-09-10'}, question='Tỷ số U23?')
    out, _ = T.run_tool(c, 'search_news', {'query': 'U23'}, allowed=ALL)
    assert out['results'] == [] and len(calls) == 1 and calls[0]['date_from'] == '2026-09-10'
    assert c.adjustments == []
