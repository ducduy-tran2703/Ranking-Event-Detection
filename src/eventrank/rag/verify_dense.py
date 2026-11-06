"""Live dense smoke and fail-closed resume verification; not a retrieval quality evaluation.

python -m eventrank.rag.verify_dense --report data/rag/reports/dense-checks-NEW.json
Only search query embeddings use Modal. Resume refuses every embedding call.
"""

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from qdrant_client import QdrantClient

from eventrank.common import db
from eventrank.rag import dense
from eventrank.rag.bm25 import _dates, _write_json
from eventrank.rag.models import ModelClient, load_model_config

QUERIES = [
    'Nghị quyết 57-NQ/TW đề cập những nhiệm vụ gì?',
    'U23 Việt Nam thắng Philippines với tỷ số bao nhiêu?',
    'Việc khôi phục điện sau bão được triển khai thế nào?',
]


def _require(condition, message):
    if not condition:
        raise ValueError(message)


class NoEmbedding:
    """Prove reuse without permitting even one request to an inference service."""

    def __init__(self):
        self.config = load_model_config()
        self.calls = 0

    def embed(self, *args, **kwargs):
        self.calls += 1
        raise ValueError('Resume attempted an embedding call; verification aborted')


def _status_fingerprint(conn):
    digest = hashlib.sha256()
    count = 0
    with conn.cursor(name='dense_verify_status') as cursor:
        cursor.execute('SELECT chunk_id,index_version,bm25_status,qdrant_status,error,updated_at '
                       'FROM rag_index_status ORDER BY chunk_id')
        for row in cursor:
            digest.update(json.dumps(row, default=str, separators=(',', ':')).encode() + b'\n')
            count += 1
    return {'rows': count, 'sha256': digest.hexdigest()}


def _statuses(conn):
    # Named cursors need a transaction on an autocommit connection.
    with conn.transaction():
        return _status_fingerprint(conn)


def verify_resume(conn, q, config):
    spec = config['dense']
    before = _statuses(conn)
    point_count = q.count(spec['collection'], exact=True).count
    metadata = q.get_collection(spec['collection']).config.metadata
    guard = NoEmbedding()
    bucket = -1

    def progress(record):
        nonlocal bucket
        current = record.get('checked', 0) // 10000
        if current != bucket:
            print(json.dumps({'phase': 'resume', **record}), flush=True)
            bucket = current

    result = dense.build_from_db(conn, q, guard, collection=spec['collection'],
                                 index_version=config['index_version'], batch_size=spec['batch_size'],
                                 concurrency=spec.get('concurrency', 1), progress=progress)
    after = _statuses(conn)
    _require(guard.calls == result['embedded'] == result['status_updated'] == 0,
             'Resume was not a no-op')
    _require(before == after, 'DB status/error/updated_at changed during resume')
    _require(q.count(spec['collection'], exact=True).count == point_count == result['documents'],
             'Point count changed or does not match corpus')
    _require(q.get_collection(spec['collection']).config.metadata == metadata,
             'Collection binding/publication changed')
    return {'passed': True, 'embedding_calls': guard.calls, 'before_status': before,
            'after_status': after, 'point_count': point_count, 'build_result': result}


def _check_hits(conn, hits, filters, *, expect_empty=False):
    _require(not hits if expect_empty else bool(hits), 'Unexpected empty/nonempty search result')
    _require(len({h['chunk_id'] for h in hits}) == len(hits), 'Duplicate chunk result')
    lo, hi = _dates(filters.get('date_from'), filters.get('date_to'))
    for rank, hit in enumerate(hits, 1):
        _require(hit['rank'] == rank and math.isfinite(hit['score']), 'Invalid rank/score')
        _require(-1.001 <= hit['score'] <= 1.001, 'Cosine outside expected range')
        if rank > 1:
            _require(hits[rank - 2]['score'] >= hit['score'], 'Results are not score-ordered')
        published = datetime.fromisoformat(hit['published_at'])
        _require(published.utcoffset() is not None, 'Missing published timezone')
        timestamp = int(published.timestamp())
        _require(lo is None or timestamp >= lo, 'Date lower bound violated')
        _require(hi is None or timestamp <= hi, 'Date upper bound violated')
        if filters.get('source'):
            _require(hit['source'] == filters['source'].lower(), 'Source filter violated')
        row = conn.execute(
            'SELECT c.text,c.article_id,c.start_char,c.end_char,n.canonical_text, '
            'a.title,a.url,a.source,a.published_at '
            'FROM rag_chunks c JOIN article_ner n USING(article_id) JOIN articles a USING(article_id) '
            'WHERE c.chunk_id=%s', (hit['chunk_id'],)).fetchone()
        _require(row is not None, 'Result missing from Postgres')
        text, article, start, end, canonical, title, url, source, date = row
        _require((hit['text'], hit['article_id'], hit['start_char'], hit['end_char'],
                  hit['title'], hit['url'], hit['source'], published)
                 == (text, article, start, end, title, url, source.lower(), date),
                 'Hydrated metadata/text mismatch')
        _require(canonical[start:end] == text and url.startswith('https://'),
                 'Invalid canonical slice or source URL')


def verify_search(conn, q, config):
    model = ModelClient.from_env()
    try:
        # One real query request; repeated filters reuse those same query vectors.
        print(json.dumps({'phase': 'search', 'query_embedding_inputs': len(QUERIES)}), flush=True)
        vectors = model.embed(QUERIES, input_type='query')
    finally:
        model.close()

    class QueryCache:
        def __init__(self):
            self.config = model.config
            self.vectors = dict(zip(QUERIES, vectors, strict=True))

        def embed(self, texts, *, input_type):
            _require(input_type == 'query', 'Smoke must not embed documents')
            return [self.vectors[text] for text in texts]

    cache = QueryCache()
    cases = [(f'query-{i}', query, {}, False) for i, query in enumerate(QUERIES, 1)]
    cases.extend([
        ('source-case-insensitive', QUERIES[0], {'source': 'VNEXPRESS'}, False),
        ('date-range', QUERIES[2], {'date_from': '2026-09-01', 'date_to': '2026-09-19'}, False),
        ('source-and-date', QUERIES[0], {'source': 'baochinhphu',
                                       'date_from': '2026-09-01', 'date_to': '2026-09-19'}, False),
        ('missing-source', QUERIES[0], {'source': '__no_such_source__'}, True),
        ('outside-corpus-date', QUERIES[0], {'date_from': '2100-01-01', 'date_to': '2100-01-01'}, True),
    ])
    results = []
    # Append an exact VN-day boundary check anchored in a real returned article.
    for name, query, filters, empty in cases:
        hits = dense.search(conn, q, cache, config['dense']['collection'], query,
                            limit=5, index_version=config['index_version'], **filters)
        _check_hits(conn, hits, filters, expect_empty=empty)
        results.append({'name': name, 'query': query, 'filters': filters, 'passed': True, 'hits': hits})
        print(json.dumps({'phase': 'search', 'case': name, 'hits': len(hits), 'passed': True}), flush=True)
        if name == 'query-1':
            anchor = hits[0]
            day = datetime.fromisoformat(anchor['published_at']).date().isoformat()
            cases.append(('exact-published-day', query, {'source': anchor['source'],
                                                        'date_from': day, 'date_to': day}, False))
    return {'passed': True, 'query_embedding_requests': 1, 'query_inputs': len(QUERIES),
            'document_embedding_requests': 0, 'cases': results,
            'scope': 'Connectivity, filters and evidence integrity only; no relevance ground truth or quality score.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/rag.yaml')
    parser.add_argument('--step', choices=['search', 'resume', 'all'], default='all')
    parser.add_argument('--report', required=True)
    args = parser.parse_args(argv)
    if Path(args.report).exists():
        parser.error('Report already exists; choose a new path')
    started = time.perf_counter()
    config = yaml.safe_load(Path(args.config).read_text('utf-8'))
    report = {'checked_at': datetime.now(UTC).isoformat(), 'step': args.step}
    q = QdrantClient(url=config['dense']['url'], timeout=120)
    try:
        with db.connect() as conn:
            if args.step in ('search', 'all'):
                report['search'] = verify_search(conn, q, config)
            if args.step in ('resume', 'all'):
                report['resume'] = verify_resume(conn, q, config)
        report.update(passed=True, seconds=round(time.perf_counter() - started, 3))
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        _write_json(args.report, report)
        print(json.dumps({'passed': True, 'report': args.report, 'seconds': report['seconds']}), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 -- do not leak credentials from service exceptions
        print(f'Dense verification failed ({type(exc).__name__})', file=sys.stderr)
        return 1
    finally:
        q.close()


if __name__ == '__main__':
    raise SystemExit(main())
