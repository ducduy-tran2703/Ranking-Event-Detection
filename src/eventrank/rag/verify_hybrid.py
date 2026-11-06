"""Live hybrid smoke: union/RRF, filters, repeated query, explicit fallback and DB invariance.

Uses three query embeddings once. Fault injection replaces clients; live services keep running.
This checks retrieval mechanics, not relevance/answer quality.
"""

import argparse
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml
from qdrant_client import QdrantClient

from eventrank.common import db
from eventrank.rag import hybrid
from eventrank.rag.bm25 import BM25Index, _write_json
from eventrank.rag.models import ModelClient
from eventrank.rag.verify_dense import QUERIES, _check_hits, _require, _statuses


def _check_result(conn, result, filters, *, empty=False):
    trace = result['trace']
    candidates = trace['candidates']
    expected = {}
    k = trace['parameters']['rrf_k']
    for name, branch in trace['branches'].items():
        for hit in branch['hits']:
            expected.setdefault(hit['chunk_id'], {})[name] = hit
    _require({h['chunk_id'] for h in candidates} == set(expected), 'Candidate union lost or added IDs')
    for rank, row in enumerate(candidates, 1):
        _require(row['rank'] == rank, 'Incorrect fused rank')
        reference = math.fsum(1 / (k + hit['rank']) for hit in expected[row['chunk_id']].values())
        _require(math.isclose(row['rrf_score'], reference, abs_tol=1e-14), 'Incorrect RRF score')
    _require(candidates == sorted(candidates, key=lambda h: (-h['rrf_score'], h['chunk_id'])),
             'Non-deterministic fused ordering')
    # RRF with k>=1 and two branches is also in [0,1]; reuse evidence/date/rank checks.
    _check_hits(conn, [{**h, 'score': h['rrf_score']} for h in result['hits']],
                filters, expect_empty=empty)


def verify(conn, config):
    before = _statuses(conn)
    q = QdrantClient(url=config['dense']['url'], timeout=120)
    model = ModelClient.from_env()
    try:
        count = q.count(config['dense']['collection'], exact=True).count
        print(json.dumps({'phase': 'queries', 'inputs': len(QUERIES)}), flush=True)
        vectors = model.embed(QUERIES, input_type='query')
        mapping = dict(zip(QUERIES, vectors, strict=True))

        def embed(texts, *, input_type):
            _require(input_type == 'query', 'Document embedding is forbidden in retrieval smoke')
            return [mapping[text] for text in texts]

        cache = SimpleNamespace(config=model.config, embed=embed)
        lexical = BM25Index(config['bm25']['root'])
        retriever = hybrid.HybridRetriever(conn, config, bm25_index=lexical, qdrant=q, model=cache)
        cases = [(f'query-{i}', query, {}, False) for i, query in enumerate(QUERIES, 1)]
        cases.extend([
            ('source', QUERIES[0], {'source': 'VNEXPRESS'}, False),
            ('dates', QUERIES[2], {'date_from': '2026-09-01', 'date_to': '2026-09-19'}, False),
            ('combined', QUERIES[0], {'source': 'baochinhphu', 'date_from': '2026-09-01',
                                     'date_to': '2026-09-19'}, False),
            ('absent-source', QUERIES[0], {'source': '__no_such_source__'}, True),
            ('outside-corpus-date', QUERIES[0], {'date_from': '2100-01-01',
                                                'date_to': '2100-01-01'}, True),
        ])
        results = []
        repeated = False
        for name, query, filters, empty in cases:
            result = retriever.search(query, limit=5, **filters)
            _require(result['mode'] == 'hybrid' and not result['degraded'], 'Healthy query degraded')
            _check_result(conn, result, filters, empty=empty)
            results.append({'name': name, 'passed': True, 'result': result})
            print(json.dumps({'case': name, 'mode': result['mode'], 'hits': len(result['hits']),
                              'candidates': len(result['trace']['candidates']), 'passed': True}), flush=True)
            if name == 'query-1':
                again = retriever.search(query, limit=5)
                repeated = again['trace']['candidates'] == result['trace']['candidates']
                _require(repeated, 'Repeated query changed candidates/ranks/scores')
                anchor = result['hits'][0]
                day = anchor['published_at'][:10]
                cases.append(('exact-vn-day', query, {'source': anchor['source'],
                                                     'date_from': day, 'date_to': day}, False))

        class DownQdrant:
            def get_collection(self, *args):
                raise ConnectionError('Injected Qdrant outage')

        class DownBM25:
            manifest, path = lexical.manifest, lexical.path

            def search(self, *args, **kwargs):
                raise OSError('Injected BM25 outage')

        fallback_results = []
        for name, b, v, mode in [('dense-outage', lexical, DownQdrant(), 'bm25_only'),
                                  ('bm25-outage', DownBM25(), q, 'dense_only')]:
            failing = hybrid.HybridRetriever(conn, config, bm25_index=b, qdrant=v, model=cache)
            try:
                failing.search(QUERIES[0])
            except hybrid.HybridUnavailableError:
                strict_failed = True
            else:
                strict_failed = False
            _require(strict_failed, 'Strict query silently fell back')
            fallback = failing.search(QUERIES[0], allow_fallback=True)
            _require(fallback['mode'] == mode and fallback['degraded'], 'Fallback not disclosed')
            _check_result(conn, fallback, {})
            fallback_results.append({'name': name, 'strict_failed': strict_failed, 'result': fallback})
            print(json.dumps({'case': name, 'mode': mode, 'strict_failed': True, 'passed': True}), flush=True)
        after = _statuses(conn)
        _require(before == after, 'Retrieval changed DB status/error/timestamps')
        _require(q.count(config['dense']['collection'], exact=True).count == count, 'Point count changed')
        return {'passed': True, 'cases': results, 'fallback': fallback_results,
                'repeated_query_identical': repeated, 'point_count': count,
                'status_before': before, 'status_after': after,
                'query_embedding_requests': 1, 'query_inputs': len(QUERIES),
                'document_embedding_requests': 0, 'fault_injection': 'clients only; services unchanged',
                'scope': 'Technical smoke, not retrieval quality evaluation'}
    finally:
        model.close()
        q.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/rag.yaml')
    parser.add_argument('--report', required=True)
    args = parser.parse_args(argv)
    if Path(args.report).exists():
        parser.error('Report already exists; choose a new path')
    try:
        config = yaml.safe_load(Path(args.config).read_text('utf-8'))
        with db.connect() as conn:
            result = verify(conn, config)
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        _write_json(args.report, result)
        print(json.dumps({'passed': True, 'report': args.report}), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 -- sanitize infrastructure failures
        print(f'Hybrid verification failed ({type(exc).__name__})', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
