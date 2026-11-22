"""Tool cho chatbot RAG (vLLM tool calling, parser gemma4).

Nguyên tắc:
- Mọi tool CHỈ ĐỌC, dùng SQL viết sẵn có tham số; model không bao giờ viết SQL hay truyền user_id.
- Đối số kiểm bằng Pydantic (extra='forbid'); sai → trả lỗi ngắn cho model sửa, không ném ra ngoài.
- Kết quả tool thành BẰNG CHỨNG đánh số chung cho cả lượt: chunk bài báo (kind='chunk', có URL/offset) hoặc
  câu dữ liệu sinh tất định từ SQL (kind='data'). Lượt trả lời cuối phải trích nguyên văn từ bằng chứng,
  nên con số trong câu dữ liệu được kiểm như quote của bài báo.
- Tên sự kiện do ViT5 sinh (~12% sai) KHÔNG đưa vào bằng chứng; dùng tiêu đề bài đại diện (bài thật).
- Bộ lọc người dùng chọn trên giao diện (nguồn/ngày) thắng đối số model tự đặt.
- Ngày do MODEL tự đặt chỉ được dùng khi câu hiện tại có mốc thời gian (`has_time_reference`); `search_news` lọc
  theo ngày model đặt mà rỗng thì code tự tìm lại không lọc ngày. Bằng chứng: E2E 22/11 lần 4–5 (Gemma,
  temperature=0) lượt "tỷ số U23" bị lọc nhầm ngày 10/9 của lượt trước → 0 kết quả; luật prompt và ghi chú
  "hãy gọi lại không lọc ngày" đều không làm Gemma tự sửa. Mọi lần code chỉnh ngày ghi vào `ctx.adjustments`.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Any

import psycopg
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from eventrank.rag import profile as P

_VN = 'Asia/Ho_Chi_Minh'
DATA_SOURCE = 'kho_du_lieu'
EventId = Annotated[str, StringConstraints(pattern=r'^E\d{8}-[0-9a-f]{8}$')]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Mốc thời gian trong câu người dùng: từ chỉ thời gian, hoặc ngày/tháng dạng số (10/9, 10-9), hoặc năm 19xx/20xx.
# Không dùng "có chữ số" vì tên riêng như "U23" cũng có số.
# "mới" tính là mốc ("thông tư nào mới" = tin gần đây): E2E 22/11 lần 1 lượt 1 bị bỏ khoảng ngày model đặt
# theo cuối kho; nếu lọc nhầm thì search_news vẫn tự tìm lại không lọc ngày.
_TIME_REFERENCE = re.compile(
    r'\b(ngày|tháng|năm|tuần|hôm|hồi|dịp|quý|sáng|trưa|chiều|tối|đêm|bữa|mới|gần đây|gần nhất|hiện nay|'
    r'hiện tại|bây giờ|lúc này|dạo này|vừa qua|sắp tới)\b|\b\d{1,2}\s*[/-]\s*\d{1,4}\b|\b(19|20)\d{2}\b')


def has_time_reference(text: str) -> bool:
    return bool(_TIME_REFERENCE.search(' '.join((text or '').casefold().split())))


class ToolError(ValueError):
    """Lỗi an toàn để báo lại model (không chứa thông điệp driver/URL)."""


class _Args(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SearchNewsArgs(_Args):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)] = Field(
        description='Câu truy vấn tiếng Việt, nêu rõ chủ thể/sự việc cần tìm.')
    source: Text | None = Field(None, description='Mã báo, ví dụ vnexpress, tuoitre, thanhnien.')
    date_from: date | None = Field(None, description='Ngày ĐĂNG bài từ (YYYY-MM-DD, giờ Việt Nam).')
    date_to: date | None = Field(None, description='Ngày ĐĂNG bài đến (YYYY-MM-DD).')
    limit: int = Field(6, ge=1, le=8)


class CorpusInfoArgs(_Args):
    pass


class CountArticlesArgs(_Args):
    source: Text | None = None
    date_from: date | None = None
    date_to: date | None = None
    category: Text | None = Field(None, description='Chuyên mục, ví dụ "Kinh tế", "Thể thao".')
    entity: Text | None = Field(None, description='Tên riêng phải xuất hiện trong bài (người, tổ chức, địa danh...).')


class TopEventsArgs(_Args):
    date_from: date | None = None
    date_to: date | None = None
    category: Text | None = None
    limit: int = Field(5, ge=1, le=10)


class EventArticlesArgs(_Args):
    event_id: EventId = Field(description='Mã sự kiện dạng E20260917-ec294af2 (lấy từ top_events).')
    per_source: int = Field(1, ge=1, le=2)
    limit: int = Field(6, ge=1, le=8)


SPECS: dict[str, tuple[type[BaseModel], str]] = {
    'search_news': (SearchNewsArgs, ('Tìm đoạn bài báo liên quan để trả lời câu hỏi chi tiết (ai, gì, khi nào, '
                                     'số liệu, phát biểu). Trả về các đoạn có id bằng chứng.')),
    'corpus_info': (CorpusInfoArgs, ('Phạm vi kho dữ liệu: khoảng ngày đăng, số bài, từng báo. Dùng khi câu hỏi nói '
                                     '"mới nhất", "hôm nay", "hiện nay" hoặc cần biết kho có dữ liệu tới ngày nào.')),
    'count_articles': (CountArticlesArgs, ('Đếm số bài báo trong kho theo báo, khoảng ngày đăng, chuyên mục, '
                                           'tên riêng. Dùng cho câu hỏi "bao nhiêu bài".')),
    'top_events': (TopEventsArgs, ('Các sự kiện được nhiều báo đưa nhất trong khoảng ngày (theo điểm xu hướng, '
                                   'chưa phải lượt đọc). Dùng cho "tin nổi bật", "có gì hot".')),
    'event_articles': (EventArticlesArgs, ('Các bài của một sự kiện từ nhiều báo khác nhau (đoạn mở đầu mỗi bài). '
                                           'Dùng sau top_events hoặc khi cần nhiều nguồn cho cùng một sự kiện.')),
    'update_user_profile': (P.ProfileUpdate, ('Ghi nhận điều người dùng nói VỀ CHÍNH HỌ hoặc cách muốn chatbot '
                                              'nói chuyện (nghề, xưng hô, giọng, độ dài, chuyên mục quan tâm). '
                                              'Không dùng cho người khác hay nội dung bài báo.')),
}


def _clean_schema(schema: dict) -> dict:
    """JSON schema Pydantic → dạng gọn cho tool: bỏ title, gộp anyOf[X, null] thành X (giảm token, dễ cho model)."""
    if isinstance(schema, dict):
        schema = {k: _clean_schema(v) for k, v in schema.items() if k != 'title'}
        options = schema.get('anyOf')
        if isinstance(options, list):
            real = [o for o in options if o != {'type': 'null'}]
            if len(real) == 1:
                schema = {**{k: v for k, v in schema.items() if k != 'anyOf'}, **real[0]}
        if schema.get('default', 0) is None:
            schema.pop('default')
        return schema
    if isinstance(schema, list):
        return [_clean_schema(v) for v in schema]
    return schema


def tool_schemas(names) -> list[dict]:
    out = []
    for name in names:
        model, description = SPECS[name]
        params = _clean_schema(model.model_json_schema())
        params.pop('additionalProperties', None)
        params.setdefault('properties', {})
        out.append({'type': 'function', 'function': {'name': name, 'description': description, 'parameters': params}})
    return out


@dataclass
class ToolContext:
    conn: Any
    question: str
    filters: dict
    search: Callable[..., list[dict]]
    snapshot: Callable[[], dict]
    categories: list[str] = field(default_factory=list)
    hidden_sources: list[str] = field(default_factory=list)
    user_id: int | None = None
    message_id: int | None = None
    read_lock: Callable[[], Any] | None = None
    evidence: list[dict] = field(default_factory=list)
    profile_plans: list[P.UpdatePlan] = field(default_factory=list)
    adjustments: list[dict] = field(default_factory=list)

    def add(self, row: dict) -> int:
        key = row['chunk_id'] if row['kind'] == 'chunk' else ('data', row['text'])
        for existing in self.evidence:
            if (existing['chunk_id'] if existing['kind'] == 'chunk' else ('data', existing['text'])) == key:
                return existing['id']
        row = {**row, 'id': len(self.evidence) + 1}
        if row['kind'] == 'data':
            n = row['id']
            row.update(chunk_id=f'data-{n}', article_id=f'data-{n}', source=DATA_SOURCE, url=None,
                       published_at=None, start_char=0, end_char=len(row['text']), chunking_version='data')
        self.evidence.append(row)
        return row['id']


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone().isoformat()
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def _day(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        from zoneinfo import ZoneInfo
        return value.astimezone(ZoneInfo(_VN)).date().isoformat()
    return str(value)[:10]


def _model_dates(ctx: ToolContext, args, tool: str) -> tuple[str | None, str | None]:
    """Ngày model tự đặt; bỏ (và ghi lại) khi câu hiện tại không có mốc thời gian nào."""
    date_from = args.date_from.isoformat() if getattr(args, 'date_from', None) else None
    date_to = args.date_to.isoformat() if getattr(args, 'date_to', None) else None
    if (date_from or date_to) and not has_time_reference(ctx.question):
        ctx.adjustments.append({'tool': tool, 'action': 'dropped_model_dates', 'date_from': date_from,
                                'date_to': date_to})
        return None, None
    return date_from, date_to


def _filters(ctx: ToolContext, args, tool: str) -> tuple[str | None, str | None, str | None]:
    """Bộ lọc giao diện thắng đối số model; trả (source, date_from, date_to) dạng chuỗi."""
    f = ctx.filters or {}
    source = f.get('source') or getattr(args, 'source', None)
    model_from, model_to = _model_dates(ctx, args, tool)
    date_from = f.get('date_from') or model_from
    date_to = f.get('date_to') or model_to
    if date_from and date_to and date_from > date_to:
        raise ToolError('date_from must be <= date_to')
    return (source.strip().lower() if source else None), date_from, date_to


def _describe(source, date_from, date_to, category=None, entity=None) -> str:
    parts = []
    if source:
        parts.append(f'của báo {source}')
    if date_from and date_to:
        parts.append(f'đăng từ {date_from} đến {date_to}')
    elif date_from:
        parts.append(f'đăng từ {date_from}')
    elif date_to:
        parts.append(f'đăng đến {date_to}')
    if category:
        parts.append(f'chuyên mục {category}')
    if entity:
        parts.append(f'có nhắc tới "{entity}"')
    return (' ' + ', '.join(parts)) if parts else ''


# ---------------------------------------------------------------------- các tool
def search_news(ctx: ToolContext, args: SearchNewsArgs) -> dict:
    source, date_from, date_to = _filters(ctx, args, 'search_news')
    hidden = {s.lower() for s in ctx.hidden_sources}
    hits = ctx.search(args.query, source=source, date_from=date_from, date_to=date_to)
    ui = ctx.filters or {}
    note = None
    if (date_from or date_to) and not ui.get('date_from') and not ui.get('date_to')             and not any(h['source'] not in hidden for h in hits):
        # Ngày do model đặt (không phải người dùng) làm rỗng kết quả → tìm lại trên toàn bộ kho.
        ctx.adjustments.append({'tool': 'search_news', 'action': 'retried_without_model_dates',
                                'date_from': date_from, 'date_to': date_to})
        hits = ctx.search(args.query, source=source, date_from=None, date_to=None)
        note = (f'Không có bài đăng từ {date_from or "đầu kho"} đến {date_to or "cuối kho"}; kết quả dưới đây '
                'tìm trên toàn bộ kho, hãy để ý ngày đăng của từng đoạn.')
    per_article, results = {}, []
    for hit in hits:
        if hit['source'] in hidden or per_article.get(hit['article_id'], 0) >= 2:
            continue
        per_article[hit['article_id']] = per_article.get(hit['article_id'], 0) + 1
        row = {key: hit[key] for key in ('chunk_id', 'article_id', 'title', 'url', 'source', 'published_at',
                                         'text', 'start_char', 'end_char', 'chunking_version')}
        eid = ctx.add({**row, 'kind': 'chunk', 'tool': 'search_news'})
        results.append({'id': eid, 'title': hit['title'], 'source': hit['source'],
                        'published': _day(hit['published_at']), 'text': hit['text'][:700]})
        if len(results) >= args.limit:
            break
    if not results:
        note = 'Không tìm thấy đoạn bài phù hợp.'
    return {'results': results, 'note': note}


def corpus_info(ctx: ToolContext, args: CorpusInfoArgs) -> dict:
    snap = ctx.snapshot()
    rows = ctx.conn.execute(
        f"SELECT a.source, count(*), min((a.published_at AT TIME ZONE '{_VN}')::date), "
        f"max((a.published_at AT TIME ZONE '{_VN}')::date) FROM articles a "
        'WHERE EXISTS (SELECT 1 FROM rag_chunks c WHERE c.article_id = a.article_id) '
        'GROUP BY a.source ORDER BY a.source').fetchall()
    per_source = '; '.join(f'{s}: {n} bài, từ {lo} đến {hi}' for s, n, lo, hi in rows)
    text = (f"Kho dữ liệu có {snap['articles']} bài của {len(snap['sources'])} báo, đăng từ {snap['from_date']} "
            f"đến {snap['to_date']}. Đây là dữ liệu lưu sẵn, không phải tin cập nhật theo thời gian thực. "
            f'Từng báo: {per_source}.')
    eid = ctx.add({'kind': 'data', 'tool': 'corpus_info', 'title': 'Phạm vi kho dữ liệu', 'text': text})
    return {'id': eid, 'text': text}


def count_articles(ctx: ToolContext, args: CountArticlesArgs) -> dict:
    source, date_from, date_to = _filters(ctx, args, 'count_articles')
    where, params = [], []
    if source:
        where.append('lower(a.source) = %s')
        params.append(source)
    if date_from:
        where.append(f"(a.published_at AT TIME ZONE '{_VN}')::date >= %s::date")
        params.append(date_from)
    if date_to:
        where.append(f"(a.published_at AT TIME ZONE '{_VN}')::date <= %s::date")
        params.append(date_to)
    if args.category:
        where.append('(lower(a.category) = lower(%s) OR EXISTS (SELECT 1 FROM category_map m WHERE '
                     'm.source = a.source AND m.category_raw = a.category AND lower(m.category_std) = lower(%s)))')
        params += [args.category, args.category]
    if args.entity:
        where.append("EXISTS (SELECT 1 FROM article_ner n, jsonb_array_elements(n.entities) e "
                     "WHERE n.article_id = a.article_id AND lower(e->>'text') = lower(%s))")
        params.append(args.entity)
    sql = 'SELECT count(*) FROM articles a' + (' WHERE ' + ' AND '.join(where) if where else '')
    count = int(ctx.conn.execute(sql, params).fetchone()[0])
    text = f'Kho dữ liệu có {count} bài báo{_describe(source, date_from, date_to, args.category, args.entity)}.'
    eid = ctx.add({'kind': 'data', 'tool': 'count_articles', 'title': 'Đếm bài trong kho', 'text': text})
    return {'id': eid, 'count': count, 'text': text}


def top_events(ctx: ToolContext, args: TopEventsArgs) -> dict:
    _, date_from, date_to = _filters(ctx, args, 'top_events')
    where, params = ["e.status IN ('open', 'closed')", 'e.size >= 2'], []
    if date_from:
        where.append(f"(e.last_seen AT TIME ZONE '{_VN}')::date >= %s::date")
        params.append(date_from)
    if date_to:
        where.append(f"(e.first_seen AT TIME ZONE '{_VN}')::date <= %s::date")
        params.append(date_to)
    if args.category:
        where.append('lower(e.category_std) = lower(%s)')
        params.append(args.category)
    params.append(args.limit)
    try:
        rows = ctx.conn.execute(
            'SELECT e.event_id, e.medoid_title, e.size, e.n_sources, e.first_seen, e.last_seen, e.category_std, '
            'e.name_source FROM events e WHERE ' + ' AND '.join(where) +
            ' ORDER BY e.total_score DESC NULLS LAST, e.size DESC, e.event_id LIMIT %s', params).fetchall()
    except psycopg.errors.UndefinedTable:
        raise ToolError('Kho chưa có dữ liệu sự kiện (bảng events).') from None
    events = []
    for event_id, title, size, n_sources, first, last, category, name_source in rows:
        # Câu ngắn để Gemma trích nguyên văn được: không mã sự kiện, không ngoặc kép bọc tiêu đề
        # (E2E 22/11: câu dài kiểu "Sự kiện E… (tiêu đề bài đại diện: "…") gồm…" bị chép lệch → mất sự kiện 92 bài).
        text = (f'{title}: {size} bài của {n_sources} báo, đăng từ {_day(first)} đến {_day(last)}'
                + (f', chuyên mục {category}' if category else '') + '.')
        # Tiêu đề nguồn = tiêu đề bài thật, để danh sách nguồn trên web đọc được (không phải 8 dòng "Sự kiện nổi bật").
        eid = ctx.add({'kind': 'data', 'tool': 'top_events', 'title': title or 'Sự kiện nổi bật', 'text': text})
        events.append({'id': eid, 'event_id': event_id, 'text': text})
    note = ('Thứ tự theo điểm xu hướng nội bộ (số báo đưa tin, tốc độ), CHƯA phải lượt đọc thực tế. '
            'Mỗi dòng mở đầu bằng tiêu đề bài đại diện (bài thật); tên sự kiện do mô hình sinh không dùng.')
    return {'events': events, 'note': note if events else 'Không có sự kiện nhiều báo trong phạm vi này.'}


def event_articles(ctx: ToolContext, args: EventArticlesArgs) -> dict:
    try:
        rows = ctx.conn.execute(
            'SELECT c.chunk_id, c.article_id, c.text, c.start_char, c.end_char, c.chunking_version, '
            'a.title, a.url, a.source, a.published_at FROM event_articles ea '
            'JOIN articles a USING (article_id) '
            'JOIN LATERAL (SELECT * FROM rag_chunks c WHERE c.article_id = ea.article_id '
            '              ORDER BY c.chunk_index LIMIT 1) c ON true '
            'WHERE ea.event_id = %s '
            'ORDER BY ea.is_medoid DESC, ea.similarity DESC NULLS LAST, a.published_at, a.article_id',
            (args.event_id,)).fetchall()
    except psycopg.errors.UndefinedTable:
        raise ToolError('Kho chưa có dữ liệu sự kiện (bảng event_articles).') from None
    hidden = {s.lower() for s in ctx.hidden_sources}
    per_source, articles = {}, []
    keys = ('chunk_id', 'article_id', 'text', 'start_char', 'end_char', 'chunking_version',
            'title', 'url', 'source', 'published_at')
    for raw in rows:
        row = dict(zip(keys, raw, strict=True))
        row['chunk_id'], row['published_at'] = str(row['chunk_id']), _iso(row['published_at'])
        if row['source'] in hidden or per_source.get(row['source'], 0) >= args.per_source:
            continue
        per_source[row['source']] = per_source.get(row['source'], 0) + 1
        eid = ctx.add({**row, 'kind': 'chunk', 'tool': 'event_articles'})
        articles.append({'id': eid, 'title': row['title'], 'source': row['source'],
                         'published': _day(row['published_at']), 'text': row['text'][:500]})
        if len(articles) >= args.limit:
            break
    return {'articles': articles, 'note': None if articles else 'Không tìm thấy bài của sự kiện này.'}


def update_user_profile(ctx: ToolContext, args: P.ProfileUpdate) -> dict:
    if ctx.user_id is None:
        raise ToolError('Người dùng chưa đăng nhập; không lưu hồ sơ.')
    plan = P.apply_update(ctx.conn, ctx.user_id, args, user_message=ctx.question,
                          categories=ctx.categories, message_id=ctx.message_id)
    ctx.profile_plans.append(plan)
    return {'applied': plan.applied, 'pending_confirmation': plan.pending, 'rejected': plan.rejected,
            'note': ('Đổi nghề/nhóm người dùng cần người dùng xác nhận; hãy nhắc họ xác nhận trong mục Hồ sơ.'
                     if plan.pending else None)}


HANDLERS = {'search_news': search_news, 'corpus_info': corpus_info, 'count_articles': count_articles,
            'top_events': top_events, 'event_articles': event_articles, 'update_user_profile': update_user_profile}
READS_INDEX = {'search_news', 'corpus_info', 'count_articles', 'event_articles'}


def run_tool(ctx: ToolContext, name: str, arguments: dict, *, allowed) -> tuple[dict, str | None]:
    """Chạy một tool; trả (kết quả cho model, mã lỗi hoặc None). Không ném lỗi nghiệp vụ ra ngoài."""
    if name not in allowed or name not in HANDLERS:
        return {'error': f'unknown_tool: {name}'}, 'unknown_tool'
    model, _ = SPECS[name]
    try:
        args = model.model_validate(arguments)
    except ValidationError as exc:
        fields = sorted({'.'.join(map(str, e['loc'])) or 'arguments' for e in exc.errors()})
        return {'error': 'invalid_arguments', 'fields': fields}, 'invalid_arguments'
    try:
        if ctx.read_lock is not None and name in READS_INDEX:
            with ctx.read_lock():
                return HANDLERS[name](ctx, args), None
        return HANDLERS[name](ctx, args), None
    except ToolError as exc:
        return {'error': str(exc)}, 'tool_error'


def dumps(result: dict) -> str:
    # Thoát < > như context.messages_for: chặn văn bản bài báo giả token điều khiển chat (<|tool_call> ...).
    text = json.dumps(result, ensure_ascii=False, default=str)
    return text.replace('<', r'\u003c').replace('>', r'\u003e')
