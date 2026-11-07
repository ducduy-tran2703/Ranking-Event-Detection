"""BM25 + Qwen dense retrieval with RRF, Postgres evidence and explicit degradation.

No indexing, document embedding, generation, or schema changes are performed here.
"""

import argparse
import json
import math
import time
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml
from qdrant_client import QdrantClient

from eventrank.common import db
from eventrank.rag import dense
from eventrank.rag.bm25 import _VN, BM25Index, _dates, _normalize_record, _write_json, analyze
from eventrank.rag.models import ModelClient, embedding_version, load_model_config


class HybridError(RuntimeError):
    def __init__(self, message, trace=None):
        super().__init__(message)
        self.trace = trace


class HybridIntegrityError(HybridError):
    """Version/corpus/evidence disagreement must never silently degrade."""


class HybridUnavailableError(HybridError):
    """A branch is unavailable and fallback was not allowed, or both branches failed."""


def _expect(condition, message):
    if not condition:
        raise HybridIntegrityError(message)


def rrf_fuse(branches, *, k=60):
    """Ranks start at 1. Count a chunk once per branch, retaining its best rank.

    Sort equal fused scores by UUID, independent of dictionary/input iteration order.
    Native branch scores are diagnostic only; BM25 and cosine are never added.
    """
    if type(k) is not int or k < 1:
        raise ValueError('rrf_k must be a positive integer')
    candidates = {}
    for name in sorted(branches):
        for hit in branches[name]:
            try:
                cid = str(uuid.UUID(str(hit['chunk_id'])))
                rank, score = hit['rank'], float(hit['score'])
            except (KeyError, TypeError, ValueError):
                raise HybridIntegrityError('Invalid branch chunk ID/rank/score') from None
            _expect(type(rank) is int and rank >= 1 and math.isfinite(score),
                    'Invalid branch rank/score')
            candidate = candidates.setdefault(cid, {'chunk_id': cid, 'branches': {}})
            previous = candidate['branches'].get(name)
            if previous is None or (rank, -score) < (previous['rank'], -previous['score']):
                candidate['branches'][name] = {'rank': rank, 'score': score}
    for candidate in candidates.values():
        candidate['rrf_score'] = math.fsum(1 / (k + row['rank'])
                                           for row in candidate['branches'].values())
    ordered = sorted(candidates.values(), key=lambda row: (-row['rrf_score'], row['chunk_id']))
    return [dict(rank=rank, **row) for rank, row in enumerate(ordered, 1)]


def _hydrate_candidates(conn, ids, index_version):
    if not ids:
        return {}
    rows = conn.execute(
        'SELECT c.chunk_id,c.article_id,c.text,c.start_char,c.end_char,c.chunking_version, '
        'a.title,a.url,a.source,a.published_at,s.bm25_status,s.qdrant_status,n.canonical_text '
        'FROM rag_chunks c JOIN article_ner n USING(article_id) JOIN articles a USING(article_id) '
        'JOIN rag_index_status s USING(chunk_id) '
        'WHERE c.chunk_id=ANY(%s::uuid[]) AND s.index_version=%s', (ids, index_version)).fetchall()
    keys = ('chunk_id', 'article_id', 'text', 'start_char', 'end_char', 'chunking_version',
            'title', 'url', 'source', 'published_at')
    result = {}
    for row in rows:
        record = _normalize_record(dict(zip(keys, row[:10], strict=True)))
        _expect(row[12][record['start_char']:record['end_char']] == record['text'],
                'Postgres canonical slice mismatch')
        result[record['chunk_id']] = (record, {'bm25': row[10], 'dense': row[11]})
    return result


def _request(query, limit, source, date_from, date_to):
    if not isinstance(query, str):
        raise TypeError('query must be text')
    query = unicodedata.normalize('NFC', query).strip()
    if not query or len(query) > 2048:
        raise ValueError('query must contain 1..2048 characters')
    terms = set(analyze(query))
    if not terms or len(terms) > 128:
        raise ValueError('query must contain 1..128 searchable terms')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('limit must be 1..100')
    if source is not None and not isinstance(source, str):
        raise ValueError('source must be text')
    _dates(date_from, date_to)
    normalized_source = source.strip().lower() or None if source is not None else None
    return query, {'source': normalized_source,
                   'date_from': date_from, 'date_to': date_to}


class HybridRetriever:
    def __init__(self, conn, config, *, bm25_index=None, qdrant=None, model=None):
        self.conn, self.config = conn, config
        self.bm25, self.q, self.model = bm25_index, qdrant, model
        self._owns_q, self._owns_model = qdrant is None, model is None

    def close(self):
        if self._owns_model and self.model is not None:
            self.model.close()
        if self._owns_q and self.q is not None:
            self.q.close()

    @staticmethod
    def _error(trace, name, exc, kind):
        # Error strings from network/DB clients can contain credentials or private URLs.
        trace['branches'][name] = {'status': 'error', 'hits': [],
                                   'error': {'kind': kind, 'exception': type(exc).__name__}}

    def _lexical(self, query, filters, branch_limit, trace):
        try:
            if self.bm25 is None:
                self.bm25 = BM25Index(self.config['bm25']['root'])
            manifest = self.bm25.manifest
            _expect(all(key in manifest for key in ('index_version', 'corpus_sha256', 'documents')),
                    'BM25 binding is incomplete')
            _expect(type(manifest['documents']) is int and manifest['documents'] > 0
                    and isinstance(manifest['corpus_sha256'], str) and len(manifest['corpus_sha256']) == 64,
                    'BM25 corpus binding is invalid')
            _expect(manifest['index_version'] == self.config['index_version'], 'BM25 index version mismatch')
            trace['versions']['bm25'] = {**manifest, 'snapshot': self.bm25.path.name}
            return self.bm25.search(query, limit=branch_limit, **filters)
        except HybridError as exc:
            self._error(trace, 'bm25', exc, 'bm25_integrity')
            raise
        except ValueError:
            raise HybridIntegrityError('Invalid BM25 snapshot or search data') from None
        except Exception as exc:  # noqa: BLE001 -- branch boundary; errors are sanitized
            self._error(trace, 'bm25', exc, 'bm25_unavailable')
            return None

    def _vector(self, query, filters, branch_limit, trace):
        try:
            if self.q is None:
                self.q = QdrantClient(url=self.config['dense']['url'], timeout=15)
            collection = self.config['dense']['collection']
            metadata = self.q.get_collection(collection).config.metadata or {}
            if not metadata.get('published'):
                self._error(trace, 'dense', RuntimeError(), 'dense_not_published')
                return None
            binding = metadata.get('binding', {})
            try:
                spec = (self.model.config if self.model is not None else load_model_config())['embedding']
                _expect(binding.get('schema_version') == 1
                        and binding.get('index_version') == self.config['index_version']
                        and binding.get('input_view') == dense.INPUT_VIEW
                        and binding.get('dimension') == spec['dimension']
                        and binding.get('embedding_version') == embedding_version(spec),
                        'Dense model/index/input view version mismatch')
                dense._check_collection(self.q, collection, binding)
            except ValueError:
                raise HybridIntegrityError('Dense collection/model configuration mismatch') from None
            trace['versions']['dense'] = {'collection': collection, **binding}
            bm25_version = trace['versions'].get('bm25')
            if trace['branches']['bm25']['status'] == 'ok':
                _expect(all(binding.get(key) == bm25_version[key]
                            for key in ('index_version', 'corpus_sha256', 'documents')),
                        'BM25 and dense corpus binding mismatch')
            if self.model is None:
                try:
                    self.model = ModelClient.from_env()
                except ValueError as exc:
                    self._error(trace, 'dense', exc, 'embedding_client_unavailable')
                    return None
            try:
                return dense.search(self.conn, self.q, self.model, collection, query,
                                    limit=branch_limit, index_version=self.config['index_version'], **filters)
            except ValueError:
                raise HybridIntegrityError('Dense search returned stale or invalid evidence') from None
        except HybridError as exc:
            self._error(trace, 'dense', exc, 'dense_integrity')
            raise
        except Exception as exc:  # noqa: BLE001 -- branch boundary; errors are sanitized
            self._error(trace, 'dense', exc, 'dense_unavailable')
            return None

    def search(self, query, *, limit=10, source=None, date_from=None, date_to=None, allow_fallback=False):
        query, filters = _request(query, limit, source, date_from, date_to)
        settings = self.config.get('retrieval', {})
        branch_limit, k = settings.get('branch_limit', 30), settings.get('rrf_k', 60)
        if type(branch_limit) is not int or not 1 <= branch_limit <= 100:
            raise ValueError('branch_limit must be 1..100')
        if type(k) is not int or k < 1:
            raise ValueError('rrf_k must be positive')
        if type(allow_fallback) is not bool:
            raise ValueError('allow_fallback must be boolean')
        started = time.perf_counter()
        trace = {'created_at': datetime.now(UTC).isoformat(), 'query': query, 'filters': filters,
                 'date_semantics': 'published_at; inclusive VN calendar dates',
                 'parameters': {'branch_limit': branch_limit, 'rrf_k': k, 'limit': limit,
                                'allow_fallback': allow_fallback},
                 'versions': {'index_version': self.config['index_version']},
                 'branches': {name: {'status': 'not_run', 'hits': []} for name in ('bm25', 'dense')}}
        try:
            branches = {}
            for name, run in (('bm25', self._lexical), ('dense', self._vector)):
                hits = run(query, filters, branch_limit, trace)
                if hits is None:
                    if not allow_fallback:
                        raise HybridUnavailableError(f'{name} unavailable; explicit fallback is required')
                else:
                    branches[name] = hits
                    try:
                        valid = rrf_fuse({name: hits}, k=k)
                    except HybridIntegrityError as exc:
                        self._error(trace, name, exc, 'invalid_branch_results')
                        raise
                    trace['branches'][name] = {'status': 'ok', 'hits': [
                        {'chunk_id': hit['chunk_id'], **hit['branches'][name]}
                        for hit in sorted(valid, key=lambda h: (h['branches'][name]['rank'], h['chunk_id']))]}
            if not branches:
                raise HybridUnavailableError('Both retrieval branches are unavailable')
            fused = rrf_fuse(branches, k=k)
            trace['candidates'] = fused
            try:
                hydrated = _hydrate_candidates(self.conn, [h['chunk_id'] for h in fused],
                                                 self.config['index_version'])
            except HybridError:
                raise
            except Exception:  # noqa: BLE001 -- sanitize database driver failures
                raise HybridUnavailableError('Postgres evidence hydration failed') from None
            lower, upper = _dates(date_from, date_to)
            for name, hits in branches.items():
                for hit in hits:
                    cid = str(uuid.UUID(str(hit['chunk_id'])))
                    _expect(cid in hydrated, 'Retrieval chunk missing from current Postgres corpus')
                    record, statuses = hydrated[cid]
                    _expect(statuses[name] == 'ready', 'Retrieval branch status is not ready')
                    try:
                        normalized = _normalize_record(hit)
                    except (KeyError, TypeError, ValueError):
                        raise HybridIntegrityError('Invalid branch evidence metadata/text') from None
                    _expect(normalized == record, 'Stale branch evidence differs from Postgres')
                    # Both indexes filter integer epoch seconds, including the whole last second.
                    stamp = int(datetime.fromisoformat(record['published_at']).timestamp())
                    _expect(not filters['source'] or record['source'] == filters['source'],
                            'Source filter disagreement')
                    _expect((lower is None or stamp >= lower) and (upper is None or stamp <= upper),
                            'Published date filter disagreement')
            mode = 'hybrid' if len(branches) == 2 else next(iter(branches)) + '_only'
            trace.update(mode=mode, candidates=fused,
                         seconds=round(time.perf_counter() - started, 3))
            evidence = []
            for row in fused[:limit]:
                record = dict(hydrated[row['chunk_id']][0])
                record['published_at'] = datetime.fromisoformat(record['published_at']).astimezone(_VN).isoformat()
                evidence.append({**record, **row})
            return {'query': query, 'mode': mode, 'degraded': mode != 'hybrid', 'hits': evidence, 'trace': trace}
        except HybridError as exc:
            trace.update(mode='failed', seconds=round(time.perf_counter() - started, 3),
                         failure={'kind': type(exc).__name__, 'message': str(exc)})
            exc.trace = trace
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/rag.yaml')
    commands = parser.add_subparsers(dest='command', required=True)
    find = commands.add_parser('search')
    find.add_argument('query')
    find.add_argument('--limit', type=int, default=10)
    find.add_argument('--source')
    find.add_argument('--date-from')
    find.add_argument('--date-to')
    find.add_argument('--allow-fallback', action='store_true')
    find.add_argument('--full-text', action='store_true')
    find.add_argument('--trace', help='New local JSON trace file, never overwritten')
    args = parser.parse_args(argv)
    if args.trace and Path(args.trace).exists():
        parser.error('Trace already exists; choose a new path')
    retriever = None
    exit_code = 0
    try:
        config = yaml.safe_load(Path(args.config).read_text('utf-8'))
        with db.connect() as conn:
            retriever = HybridRetriever(conn, config)
            result = retriever.search(args.query, limit=args.limit, source=args.source,
                                      date_from=args.date_from, date_to=args.date_to,
                                      allow_fallback=args.allow_fallback)
    except HybridError as exc:
        exit_code = 1
        result = {'mode': 'failed', 'error': type(exc).__name__, 'message': str(exc), 'trace': exc.trace}
    except Exception as exc:  # noqa: BLE001 -- avoid exposing credentials from infrastructure errors
        exit_code = 1
        result = {'mode': 'failed', 'error': type(exc).__name__}
    finally:
        if retriever is not None:
            retriever.close()
    if args.trace:
        Path(args.trace).parent.mkdir(parents=True, exist_ok=True)
        _write_json(args.trace, result)
    if not args.full_text:
        for hit in result.get('hits', []):
            hit['snippet'] = hit.pop('text')[:320]
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
