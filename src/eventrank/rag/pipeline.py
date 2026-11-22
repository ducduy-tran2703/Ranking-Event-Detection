"""Single-turn snapshot RAG: hybrid retrieval → budgeted evidence → checked Gemma claims."""

import argparse
import json
import re
import time
import uuid
from contextlib import nullcontext
from pathlib import Path

import psycopg
import yaml

from eventrank.common import db
from eventrank.rag.bm25 import _VN, _write_json
from eventrank.rag.context import ContextBudgetError, select_context
from eventrank.rag.generation import NO_EVIDENCE, CitationError, output_schema, validate_answer
from eventrank.rag.hybrid import HybridError, HybridRetriever, _request
from eventrank.rag.models import ModelClient, keep_alive, load_model_config
from eventrank.rag.ner import SharedNER, ner_from_config
from eventrank.rag.prepare import IndexBusyError, index_read_lock
from eventrank.rag.query_ner import boost_candidates_with_ner, fetch_article_entities
from eventrank.rag.token_budget import GemmaTokenCounter


class RAGUnavailableError(RuntimeError):
    def __init__(self, phase, trace=None):
        super().__init__(f'RAG service unavailable during {phase}')
        self.phase, self.trace = phase, trace


def corpus_snapshot(conn, index_version):
    row = conn.execute(
        'SELECT min(a.published_at),max(a.published_at),count(DISTINCT a.article_id), '
        'array_agg(DISTINCT a.source ORDER BY a.source) '
        'FROM articles a JOIN rag_chunks c USING(article_id) JOIN rag_index_status s USING(chunk_id) '
        "WHERE s.index_version=%s AND (s.bm25_status='ready' OR s.qdrant_status='ready')",
        (index_version,)).fetchone()
    return {'from_date': row[0].astimezone(_VN).date().isoformat() if row[0] else None,
            'to_date': row[1].astimezone(_VN).date().isoformat() if row[1] else None,
            'articles': row[2], 'sources': row[3] or []}


def unsupported_reason(question, filters):
    lowered = question.casefold()
    if re.search(r'(bao nhiêu|tổng số|thống kê số)\s+'
                 r'(bài(?!\s+(hát|thi|học|tập|toán|văn|thơ|kiểm tra|phát biểu))|tin tức|nguồn tin|nguồn báo|sự kiện)',
                 lowered):
        return ('global_statistics', ('Câu hỏi thống kê toàn kho cần truy vấn dữ liệu riêng; '
                                      'không thể suy số lượng từ các đoạn tin truy xuất.'))
    if not (filters['date_from'] or filters['date_to']) and re.search(
            r'hôm nay|hôm qua|hiện nay|hiện tại|bây giờ|mới nhất|tuần này|tháng này', lowered):
        return ('relative_time', ('Kho đang dùng là snapshot lịch sử. Hãy chỉ rõ ngày hoặc khoảng ngày '
                                  'để tránh coi dữ liệu trong kho là tin hiện tại.'))
    return None


class RAGPipeline:
    def __init__(self, conn, config, *, retriever=None, model=None, counter=None,
                 snapshot=None, query_ner=None):
        self.conn, self.config = conn, config
        self.retriever, self.model, self.counter = retriever, model, counter
        self.snapshot = snapshot
        self.query_ner = query_ner
        self._owns_generator = False

    def _read_lock(self):
        # Test/fixture không có Postgres thì không có lượt ghi nào để tránh.
        return nullcontext() if self.conn is None else index_read_lock(self.conn)

    def _apply_query_ner(self, question, candidates, trace):
        """Soft boost theo thực thể; NER lỗi/thiếu chỉ tắt boost và ghi rõ vào trace."""
        qner_cfg = self.config.get('query_ner', {})
        if not qner_cfg.get('enabled', False):
            return candidates
        predictor = self.query_ner
        if predictor is None:
            ner_cfg = self.config.get('ner', {})
            if not ner_cfg.get('model_dir') or not Path(ner_cfg['model_dir']).exists():
                trace['query_ner'] = {'enabled': True, 'status': 'model_missing'}
                return candidates
            predictor = self.query_ner = SharedNER(lambda: ner_from_config(ner_cfg))
        try:
            q_entities = predictor.predict_texts([question])[0]
            art_entities = fetch_article_entities(self.conn, [h['article_id'] for h in candidates])
        except Exception as exc:  # noqa: BLE001 -- boost là tuỳ chọn; chỉ ghi tên lỗi
            trace['query_ner'] = {'enabled': True, 'status': 'error', 'exception': type(exc).__name__}
            return candidates
        boosted = boost_candidates_with_ner(
            candidates, q_entities, art_entities,
            in_chunk_boost=float(qner_cfg.get('in_chunk_boost', 0.008)),
            in_article_boost=float(qner_cfg.get('in_article_boost', 0.003)),
            label_match_multiplier=float(qner_cfg.get('label_match_multiplier', 1.0)),
            text_only_multiplier=float(qner_cfg.get('text_only_multiplier', 0.4)),
        )
        moved = [{key: row[key] for key in ('chunk_id', 'rrf_rank', 'rank', 'ner_boost')}
                 for row in boosted if row.get('ner_boost', 0.0) > 0]
        trace['query_ner'] = {'enabled': True, 'status': 'ok', 'entities': q_entities,
                              'boosted_chunks': len(moved), 'boosted': moved}
        return boosted

    def close(self):
        if self.retriever is not None and hasattr(self.retriever, 'close'):
            self.retriever.close()
        if self._owns_generator and self.model is not None:
            self.model.close()

    def _client(self):
        if self.model is None:
            self.model = getattr(self.retriever, 'model', None)
        if self.model is None:
            self.model = ModelClient.from_env()
            self._owns_generator = True
        return self.model

    def ask(self, question, *, source=None, date_from=None, date_to=None,
            allow_fallback=False, max_tokens=None):
        question, filters = _request(question, 60, source, date_from, date_to)
        spec = (self.model.config if self.model is not None else load_model_config())['llm']
        reserve = spec['max_output_tokens'] if max_tokens is None else max_tokens
        if type(reserve) is not int or not 1 <= reserve <= spec['max_output_tokens']:
            raise ValueError('max_tokens exceeds the configured generator output limit')
        started = time.perf_counter()
        trace = {'request_id': str(uuid.uuid4()), 'question': question, 'filters': filters,
                 'single_turn': True, 'index_version': self.config['index_version']}
        try:
            snapshot = self.snapshot if self.snapshot is not None else corpus_snapshot(self.conn, self.config['index_version'])
        except Exception:  # noqa: BLE001 -- sanitize database failures
            raise RAGUnavailableError('snapshot', trace) from None
        trace['snapshot'] = snapshot
        mode, degraded = None, False

        def finish(status, answer, sources=None, reason=None):
            trace['seconds'] = round(time.perf_counter() - started, 3)
            if reason:
                trace['reason'] = reason
            return {'status': status, 'answer': answer, 'sources': sources or [],
                    'retrieval_mode': mode, 'degraded': degraded, 'snapshot': snapshot, 'trace': trace}

        unsupported = unsupported_reason(question, filters)
        if unsupported:
            return finish('unsupported_query', unsupported[1], reason=unsupported[0])
        outside = ((filters['source'] and filters['source'] not in snapshot.get('sources', []))
                   or (date_from and snapshot.get('to_date') and date_from > snapshot['to_date'])
                   or (date_to and snapshot.get('from_date') and date_to < snapshot['from_date']))
        if snapshot['articles'] == 0 or outside:
            return finish('insufficient_evidence', NO_EVIDENCE, reason='outside_snapshot_or_source')
        if self.retriever is None:
            self.retriever = HybridRetriever(self.conn, self.config, model=self.model)
        settings = self.config.get('generation', {})
        try:
            # Giữ khoá đọc tới khi lấy xong evidence + entity: sync không được ghi xen giữa.
            with self._read_lock():
                try:
                    retrieved = self.retriever.search(question, limit=settings.get('candidate_limit', 60),
                                                      allow_fallback=allow_fallback, **filters)
                except Exception as exc:  # noqa: BLE001 -- keep only safe retrieval trace
                    if isinstance(exc, HybridError):
                        trace['retrieval'] = exc.trace
                    raise RAGUnavailableError('retrieval', trace) from None
                trace['retrieval'] = retrieved['trace']
                mode, degraded = retrieved['mode'], retrieved['degraded']
                if not retrieved['hits']:
                    return finish('insufficient_evidence', NO_EVIDENCE, reason='empty_retrieval')
                candidates = self._apply_query_ner(question, retrieved['hits'], trace)
        except IndexBusyError:
            raise RAGUnavailableError('index_sync', trace) from None
        except psycopg.Error:  # lấy/nhả khoá đọc lỗi; không lộ thông điệp driver
            raise RAGUnavailableError('index_lock', trace) from None
        if self.counter is None:
            try:
                self.counter = GemmaTokenCounter(spec)
            except Exception:  # noqa: BLE001 -- hide paths/tokens in tokenizer library failures
                raise RAGUnavailableError('tokenizer; run token_budget prepare first', trace) from None
        max_chunks = settings.get('max_context_chunks', 8)
        try:
            # Source diversity is meaningless once the request is restricted to one source.
            selected = select_context(question, candidates, self.counter, snapshot=snapshot,
                                       window=spec['max_model_len'], max_output_tokens=reserve,
                                       max_chunks=max_chunks,
                                       per_article=settings.get('max_per_article', 2),
                                       per_source=max_chunks if filters['source']
                                       else settings.get('max_per_source', 3))
        except ContextBudgetError:
            return finish('insufficient_evidence', NO_EVIDENCE, reason='context_budget')
        trace['context'] = {'prompt_tokens': selected.prompt_tokens, 'output_reserve': reserve,
                            'max_model_len': spec['max_model_len'], 'tokenizer': self.counter.version,
                            'selected': [{key: row[key] for key in ('id', 'chunk_id', 'article_id',
                                                                   'start_char', 'end_char', 'chunking_version')}
                                         for row in selected.evidence], 'dropped': selected.dropped}
        if not selected.evidence:
            return finish('insufficient_evidence', NO_EVIDENCE, reason='no_context_fits')
        try:
            client = self._client()

            def generate():
                return client.chat(selected.messages, max_tokens=reserve,
                                   response_schema=output_schema(), temperature=0.0)

            if mode == 'bm25_only':  # Qwen was never reached; do not wake a GPU for it.
                generated = generate()
            else:
                keep = client.config['keepalive']
                with keep_alive(client.ping_embedding, interval=keep['interval_seconds'],
                                max_seconds=keep['max_seconds']) as pings:
                    trace['keepalive'] = pings
                    generated = generate()
        except Exception:  # noqa: BLE001 -- sanitize remote model failures
            raise RAGUnavailableError('generation', trace) from None
        trace['generator'] = {'model': spec['model'], 'revision': spec['revision'],
                              'finish_reason': generated.get('finish_reason'), 'usage': generated.get('usage', {})}
        try:
            if generated.get('finish_reason') != 'stop':
                raise CitationError('generation_not_finished')
            validated = validate_answer(generated.get('content', ''), selected.evidence)
        except CitationError as exc:
            trace['validation'] = {'passed': False, 'reason': str(exc)}
            return finish('invalid_generation', 'Chưa thể xuất câu trả lời vì nội dung hoặc citation '
                          'không vượt qua kiểm tra bằng chứng.', reason='generation_validation_failed')
        trace['validation'] = {'passed': True, 'checks': ['citation_ids', 'verbatim_quotes', 'metadata_urls'],
                               'quote_normalization': 'NFC, case, whitespace, punctuation outside numbers',
                               'dropped': validated['dropped'],
                               'semantic_entailment': 'not independently scored'}
        return finish(validated['status'], validated['answer'], validated['sources'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/rag.yaml')
    sub = parser.add_subparsers(dest='command', required=True)
    ask = sub.add_parser('ask')
    ask.add_argument('question')
    ask.add_argument('--source')
    ask.add_argument('--date-from')
    ask.add_argument('--date-to')
    ask.add_argument('--max-tokens', type=int)
    ask.add_argument('--allow-fallback', action='store_true')
    ask.add_argument('--trace', help='New local JSON result/trace, never overwritten')
    args = parser.parse_args(argv)
    if args.trace and Path(args.trace).exists():
        parser.error('Trace exists; choose a new path')
    pipeline, result = None, None
    try:
        config = yaml.safe_load(Path(args.config).read_text('utf-8'))
        with db.connect() as conn:
            pipeline = RAGPipeline(conn, config)
            result = pipeline.ask(args.question, source=args.source, date_from=args.date_from,
                                   date_to=args.date_to, max_tokens=args.max_tokens,
                                   allow_fallback=args.allow_fallback)
    except RAGUnavailableError as exc:
        result = {'status': 'unavailable', 'phase': exc.phase, 'trace': exc.trace}
    except Exception as exc:  # noqa: BLE001 -- never echo infrastructure secrets
        result = {'status': 'unavailable', 'error': type(exc).__name__}
    finally:
        if pipeline is not None:
            pipeline.close()
    if args.trace:
        Path(args.trace).parent.mkdir(parents=True, exist_ok=True)
        _write_json(args.trace, result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 1 if result['status'] in ('unavailable', 'invalid_generation') else 0


if __name__ == '__main__':
    raise SystemExit(main())
